from typing import Optional, Callable, Dict, List, Any
from logging import Logger, LoggerAdapter
from string import Template
from pathlib import Path
import requests
import re
import time
import json
import os
from keycloak import KeycloakOpenID
from redis import Redis
import uuid

from constants import (
    STAGE_STATUS_FAIL,
    STAGE_STATUS_SUCCESS,
    DEFAULT_TIMEOUT,
    DEFAULT_FAILURE_THRESHOLD,
    DEFAULT_PERIOD_SECONDS,
)
from metrics import (
    api_tester_stage_status,
    api_tester_job_status,
    api_tester_job_seconds,
    create_dynamic_metric
)
from http_client import HttpClient


class ApiTester:
    def __init__(
        self,
        pipeline: Dict[str, Any],
        logger: Logger,
        redis: Redis,
        secrets_dir: str,
        data_dir: str,
        period_seconds: int,
        job_id: str = "default",
        job_name: Optional[str] = None,
    ) -> None:

        if "name" not in pipeline or "jobs" not in pipeline:
            raise ValueError("pipeline must contain 'name' and 'jobs' keys")

        self.product_name = pipeline["name"]
        self.jobs = pipeline["jobs"]
        self.job_id = job_id
        self.job_name = job_name

        self.logger = LoggerAdapter(logger, {"app": job_id})

        self.redis = redis
        self.secrets_dir = secrets_dir
        self.data_dir = data_dir
        self.period_seconds = period_seconds
        self.redis_ttl = period_seconds * 2
        self.metric = None

    def run(self) -> None:
        pipe_status = STAGE_STATUS_SUCCESS
        last_failed_stage = None
        task_id = "N/A"
        stage_uuid = str(uuid.uuid4())
        
        self.logger.info(f"Starting pipeline '{self.product_name}' | UUID={stage_uuid}")
        
        with api_tester_job_seconds.labels(product_name=self.product_name).time():
            for stage in self.jobs:
                stage_name = stage.get("name", "unknown")
                
                if pipe_status != STAGE_STATUS_SUCCESS:
                    fail_stage = last_failed_stage or stage_name
                    self.logger.error(f"Pipeline Failed on '{fail_stage}' | TASK_ID={task_id}")
                    api_tester_stage_status.labels(product_name=self.product_name, stage_name=stage_name).set(STAGE_STATUS_FAIL)
                    continue

                params = self._prepare_stage_params(stage, stage_uuid)
                task_id = params.get('envs', {}).get('taskId', 'N/A')
                
                try:
                    status = self._execute_stage(stage, stage_uuid)
                except Exception as e:
                    self.logger.error(f"Error executing stage '{stage_name}': {e}", exc_info=True)
                    status = STAGE_STATUS_FAIL

                api_tester_stage_status.labels(product_name=self.product_name, stage_name=stage_name).set(status)

                if status != STAGE_STATUS_SUCCESS:
                    last_failed_stage = stage_name
                    pipe_status = STAGE_STATUS_FAIL
                    continue

        api_tester_job_status.labels(product_name=self.product_name).set(pipe_status)
        
        if pipe_status == STAGE_STATUS_SUCCESS:
            self.logger.info(f"Pipeline '{self.product_name}' COMPLETED SUCCESSFULLY | TASK_ID={task_id} | All stages OK") 

    def _execute_stage(self, stage: Dict[str, Any], stage_uuid: str) -> int:
        stage_name = stage["name"]
        stage_type = stage["type"]

        self.logger.info(f"Executing stage: {stage_name}")

        params = self._prepare_stage_params(stage, stage_uuid)
        task_id = params.get('envs', {}).get('taskId', 'N/A')
        self.logger.info(f"Stage '{stage_name}' with TASK_ID={task_id}")
        if not hasattr(self, stage_type):
            raise AttributeError(f"Unknown stage type: {stage_type}")
        run_func = getattr(self, stage_type)
        return run_func(**params)

    def _prepare_stage_params(
        self, stage: Dict[str, Any], stage_uuid: str
    ) -> Dict[str, Any]:
        params = self._load_params(stage.get("params", {}))
        params["stage_uuid"] = stage_uuid
        envs = self._load_envs(stage.get("envs"), stage_uuid)
        params.update(
            {
                "stage_name": stage["name"],
                "envs": envs,
                "check": stage.get("check"),
                "output": stage.get("output"),
                "metrics": stage.get("metrics")
            }
        )

        params.update(stage.get("base", {}))

        if stage.get("json_file"):
            file_path = Path(self.data_dir) / stage["json_file"]
            with open(file_path, "r", encoding="utf-8") as f:
                params["json_file"] = f.read().strip()

        if stage.get("headers"):
            params["headers"] = stage["headers"]

        if stage.get("sub_type"):
            if not hasattr(self, stage["sub_type"]):
                raise AttributeError(f"Unknown sub_type: {stage['sub_type']}")
            params["func"] = getattr(self, stage["sub_type"])

        return params

    def _load_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("secret:"):
                secret_name = value[7:] 
                secret_path = Path(self.secrets_dir) / secret_name
                try:
                    result[key] = secret_path.read_text(encoding="utf-8").strip()
                except Exception as e:
                    self.logger.error(f"Can't load secret {key}: {e}", exc_info=True)
            elif isinstance(value, str) and value.startswith("env:"):
                result[key] = os.getenv(value[4:], "")
            else:
                result[key] = value
        return result

    def substitute(self, base: str, envs: Optional[Dict[str, str]]) -> str:
        if not envs:
            return base

        try:
            template = Template(base)
            return template.substitute(envs)
        except KeyError as e:
            #self.logger.warning(f"Missing variable in template substitution: {e}")
            return template.safe_substitute(envs)

    def _load_envs(
        self, envs: Optional[List[Dict[str, Any]]], stage_uuid: str
    ) -> Dict[str, str]:
        prepared: Dict[str, str] = {}

        if not envs:
            return prepared

        for sub in envs:
            if "name" not in sub:
                self.logger.warning(f"Environment variable missing 'name': {sub}")
                continue

            var_name = sub["name"]

            if sub.get("from"):
                value = self.redis.get(f"{var_name}-{stage_uuid}")
                if value is not None:
                    prepared[var_name] = str(value)
                else:
                    self.logger.warning(f"Redis key '{var_name}' not found")
            elif "value" in sub:
                prepared[var_name] = sub["value"]
            else:
                self.logger.warning(
                    f"Environment variable '{var_name}' has no 'value' or 'from'"
                )

        return prepared

    def auth_keycloak(
        self,
        stage_name: str,
        server_url: str,
        realm_name: str,
        client_id: str,
        client_secret_key: str,
        username: str,
        password: str,
        stage_uuid: str,
        output: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 60,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        period_seconds: int = DEFAULT_PERIOD_SECONDS,
        **kwargs,
    ) -> int:
        response = None
        status = STAGE_STATUS_FAIL

        try:
            keycloak_openid = KeycloakOpenID(
                server_url=server_url,
                realm_name=realm_name,
                client_id=client_id,
                client_secret_key=client_secret_key,
                timeout=timeout,
                max_retries=failure_threshold,
            )
            response = keycloak_openid.token(username, password)
            status = STAGE_STATUS_SUCCESS
            self.logger.info(f"{stage_name} - Token obtained successfully")
        except Exception as e:
            self.logger.error(
                f"{stage_name} - Keycloak authentication error: {e}",
                exc_info=True,
            )
            return status

        if status and response:
            try:
                self.save_output(response, output, stage_uuid)
            except Exception as e:
                self.logger.error(
                    f"{stage_name} - Failed to save Keycloak token: {e}",
                    exc_info=True,
                )
                status = STAGE_STATUS_FAIL

        return status

    def handle_body(
        self,
        stage_name: str,
        url: str,
        func: Callable,
        stage_uuid: str,
        headers: Optional[str] = None,
        json_file: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        check: Optional[Dict[str, Any]] = None,
        output: Optional[List[Dict[str, Any]]] = None,
        metrics: Optional[Dict[str, str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        period_seconds: int = DEFAULT_PERIOD_SECONDS,
        **kwargs,
    ) -> int:
        
        status = STAGE_STATUS_FAIL
        response = None
        try:
            url = self.substitute(url, envs)
            parsed_headers = (
                json.loads(self.substitute(headers, envs)) if headers else None
            )
            parsed_json = (
                json.loads(self.substitute(json_file, envs)) if json_file else None
            )
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"{stage_name} - Failed to parse request parameters: {e}")
            return status

        try:
            response = func(url, parsed_json, parsed_headers, timeout)
            self.check_result(response,check)
            path_metric = None 

            for data in check:
                is_metric = data.get('value_metric','')
                if is_metric == True:
                    path_metric = data.get('path') 
                    break

            metric_value = 0
            metric_value = self._extract_by_path(response,path_metric, 0)

            labels_dict = {}
            label_names = []
            for label in (metrics or {}).get("labels", []):
                name = label.get("name")
                path = label.get("value", [])                
                if not name:
                    continue

                label_names.append(name)
                value = self._extract_by_path(response, path, "unknown")
                labels_dict[name] = str(value) if value else "unknown"
            if self.metric is None:
                self.metric = create_dynamic_metric(
                    metrics.get('name'),
                    label_names,  
                    metrics.get('documentation',''),
                    metrics.get('multiprocess_mode','')
                )
            if label_names:
                self.metric.labels(**labels_dict,).set(float(metric_value))
            else:
                self.metric.set(float(metric_value))
            
            self.logger.info(f'Metric successed {stage_name} - {response}')
            status = STAGE_STATUS_SUCCESS
        except AssertionError as e:
            self.logger.error(f"{stage_name} - Validation response: {e} {response}")
        except Exception as e:
            self.logger.exception(f"{stage_name} - Failed to process metrics: {e}")
        return status

    def handle_request(
        self,
        stage_name: str,
        url: str,
        func: Callable,
        stage_uuid: str,
        headers: Optional[str] = None,
        json_file: Optional[str] = None,
        envs: Optional[Dict[str, str]] = None,
        check: Optional[Dict[str, Any]] = None,
        output: Optional[List[Dict[str, Any]]] = None,
        timeout: int = DEFAULT_TIMEOUT,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        period_seconds: int = DEFAULT_PERIOD_SECONDS,
        **kwargs,
    ) -> int:

        status = STAGE_STATUS_FAIL
        response = None

        try:
            url = self.substitute(url, envs)
            parsed_headers = (
                json.loads(self.substitute(headers, envs)) if headers else None
            )
            parsed_json = (
                json.loads(self.substitute(json_file, envs)) if json_file else None
            )
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"{stage_name} - Failed to parse request parameters: {e}")
            return status
        for attempt in range(failure_threshold):
            try:
                response = func(url, parsed_json, parsed_headers, timeout)
                self.check_result(response, check)
                status = STAGE_STATUS_SUCCESS
                self.logger.debug(f"{stage_name} - API request completed successfully")
                break
            except requests.exceptions.RequestException as e:
                if attempt == failure_threshold - 1:
                    self.logger.error(
                        f"{stage_name} - API request failed after {failure_threshold} attempts: {e}"
                    )
                else:
                    self.logger.warning(
                        f"{stage_name} - API request attempt {attempt + 1} failed, retrying..."
                    )
                time.sleep(period_seconds)
            except AssertionError as e:
                self.logger.error(f"{stage_name} - Validation response: {e} {response}")
                time.sleep(period_seconds)
            except Exception as e:
                time.sleep(period_seconds)

        if status and response:
            try:
                self.save_output(response, output, stage_uuid)
            except Exception as e:
                self.logger.error(
                    f"{stage_name} - Failed to save API response: {e}",
                    exc_info=True,
                )
                status = STAGE_STATUS_FAIL

        return status

    def post_request(
        self,
        url: str,
        json_file: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
        timeout: int,
    ) -> Dict[str, Any]:
        return HttpClient.post(url, json_file, headers, timeout)

    def get_request(
        self,
        url: str,
        json_file: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
        timeout: int,
    ) -> Dict[str, Any]:
        return HttpClient.get(url, json_file, headers, timeout)

    def save_output(
        self,
        response: Dict[str, Any],
        output: Optional[List[Dict[str, Any]]],
        stage_uuid: str,
    ) -> None:
        if not output:
            return

        for out in output:
            if "name" not in out or "path" not in out:
                self.logger.warning(f"Invalid output mapping: {out}")
                continue

            try:
                value = response
                for path in out["path"]:
                    if isinstance(value, dict):
                        value = value.get(path)
                    elif isinstance(value, list):
                        value = value[int(path)]
                    else:
                        raise TypeError(f"Cannot navigate path in {type(value)}")

                if value is not None:

                    self.redis.setex(
                        name=f"{out['name']}-{stage_uuid}",
                        time=self.redis_ttl,
                        value=str(value),
                    )
                    if out.get("log") is not None:
                        self.logger.info(
                            f"Output variable '{out['name']}' has value: {value}"
                        )
                    self.logger.debug(f"Saved '{out['name']}' to Redis")
                else:
                    self.logger.warning(f"Path {out['path']} resulted in None value")
            except (KeyError, IndexError, TypeError, ValueError) as e:
                self.logger.error(
                    f"Failed to extract value for '{out.get('name')}': {e}"
                )

    def check_result(
        self, response: Dict[str, Any], check: Optional[Dict[str, Any]]
    ) -> None:
        if not check:
            return
        for data_check in check:
            if "path" not in data_check or "result" not in data_check:
                raise ValueError("Check must contain 'path' and 'result' keys")

            value = response
            for path in data_check["path"]:
                if isinstance(value, dict):
                    value = value.get(path)
                elif isinstance(value, list):
                    value = value[int(path)]
                else:
                    raise TypeError(f"Cannot navigate path in {type(value)}")

            if value is None:
                raise AssertionError(f"Path {data_check['path']} resulted in None")

            pattern = data_check["result"]
            str_value = str(value)
            match = re.match(pattern, str_value)

            if not match or match.group(0) != str_value:
                raise AssertionError(
                    f"Value '{str_value}' does not match pattern '{pattern}'"
                )
        
    def _extract_by_path(self, data: Any, path: List[str], default: Any):
        current = data
        for key in path:
            if isinstance(current, dict):
                current = current.get(key, default)
            else:
                return default
        return current if current is not None else default