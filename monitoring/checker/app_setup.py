import os
import yaml
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List
from flask import Flask, has_request_context, request
from redis import Redis, ConnectionPool
from api_tester import ApiTester
from flask.logging import default_handler
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics
from pythonjsonlogger.json import JsonFormatter as BaseJsonFormatter
from constants import (
    DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT,
    DEFAULT_REDIS_DB,
    DEFAULT_REDIS_SOCKET_TIMEOUT,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_SECRETS_DIR,
    DEFAULT_SCHEDULER_SECONDS,
    CONFIG_DIRECTORY,
    DATA_DIRECTORY,
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_FORMAT,
)


prom_metrics = GunicornInternalPrometheusMetrics.for_app_factory()


class JsonFormatter(BaseJsonFormatter):

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super(JsonFormatter, self).add_fields(log_record, record, message_dict)

        log_record["timestamp"] = self.formatTime(record, self.datefmt)
        log_record["level"] = record.levelname

        if has_request_context():
            log_record["url"] = request.url
            log_record["remote_addr"] = request.remote_addr
            log_record["method"] = request.method
            log_record["path"] = request.path


def get_logger() -> logging.Logger:

    level = logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO

    formatter = JsonFormatter(
        DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_LOG_DATE_FORMAT,
        json_ensure_ascii=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    app_logger = logging.getLogger()
    app_logger.setLevel(level)

    return app_logger


logger = get_logger()


def create_app() -> Flask:
    formatter = JsonFormatter(
        DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_LOG_DATE_FORMAT,
        json_ensure_ascii=False,
    )
    default_handler.setFormatter(formatter)

    app = Flask(__name__)
    app.logger.addHandler(default_handler)
    app.logger.setLevel(logging.WARNING)
    prom_metrics.init_app(app)
    return app


def create_redis_client() -> Redis:
    pool = ConnectionPool(
        host=os.getenv("REDIS_HOST", DEFAULT_REDIS_HOST),
        port=int(os.getenv("REDIS_PORT", DEFAULT_REDIS_PORT)),
        db=DEFAULT_REDIS_DB,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=DEFAULT_REDIS_SOCKET_TIMEOUT,
        max_connections=DEFAULT_MAX_CONNECTIONS,
    )
    return Redis(connection_pool=pool)


def load_pipelines() -> List[Dict[str, Any]]:
    config_dir = Path(CONFIG_DIRECTORY)

    if not config_dir.exists():
        raise FileNotFoundError(
            f"Configuration directory not found: {CONFIG_DIRECTORY}"
        )

    config_files = list(config_dir.glob("*.yaml"))
    pipelines = []

    for config_path in config_files:
        try:
            config = yaml.safe_load(config_path.read_text())
            while len(config) > 0:
                _, pipeline = config.popitem()
                pipelines.append(pipeline)
                logger.info(
                    f"Loaded pipeline: {pipeline.get('name', 'unnamed')} from {config_path.name}"
                )

        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in {config_path.name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to load {config_path.name}: {e}")
            raise

    if len(pipelines) == 0:
        raise ValueError(f"No valid pipelines found in {CONFIG_DIRECTORY}")

    logger.info(f"Loaded {len(pipelines)} pipeline(s) total")
    return pipelines


def create_api_testers() -> List[ApiTester]:
    redis = create_redis_client()

    try:
        pipelines = load_pipelines()
    except Exception as e:
        logger.critical(f"Failed to load configurations: {e}")
        raise

    secrets_dir = os.getenv("SECRETS_DIR", DEFAULT_SECRETS_DIR)

    api_testers = []
    for pipeline in pipelines:
        product_name = pipeline.get("name", "unknown")
        period_seconds = pipeline.get("period_seconds", DEFAULT_SCHEDULER_SECONDS)
        job_id = f"{product_name}-job"
        job_name = f"api-tester-{product_name}"
        logger.info(
            f"Creating ApiTester for pipeline '{product_name}' with job_id='{job_id}'"
        )

        api_tester = ApiTester(
            pipeline=pipeline,
            logger=logger,
            redis=redis,
            secrets_dir=secrets_dir,
            data_dir=DATA_DIRECTORY,
            period_seconds=period_seconds,
            job_id=job_id,
            job_name=job_name,
        )
        api_testers.append(api_tester)

    return api_testers
