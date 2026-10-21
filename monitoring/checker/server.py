import os
from typing import Dict, Any, List
from datetime import datetime

from flask import jsonify, Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

from app_setup import create_app, create_api_testers, logger, prom_metrics
from constants import (
    DEFAULT_SCHEDULER_SECONDS,
    DEFAULT_THREAD_POOL_SIZE,
    DEFAULT_PROCESS_POOL_SIZE,
    DEFAULT_MAX_INSTANCES,
    SCHEDULER_TIMEZONE,
    MISFIRE_GRACE_TIME,
)


app = create_app()
api_testers = create_api_testers()

executors = {
    "default": ThreadPoolExecutor(DEFAULT_THREAD_POOL_SIZE),
    "processpool": ProcessPoolExecutor(DEFAULT_PROCESS_POOL_SIZE),
}

scheduler = BackgroundScheduler(
    daemon=True, executors=executors, timezone=SCHEDULER_TIMEZONE
)

for api_tester in api_testers:
    scheduler.add_job(
        id=api_tester.job_id,
        name=api_tester.job_name,
        func=api_tester.run,
        trigger="interval",
        seconds=api_tester.period_seconds,
        max_instances=DEFAULT_MAX_INSTANCES,
        misfire_grace_time=MISFIRE_GRACE_TIME,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(),
    )
    logger.info(f"Added scheduler job: id='{api_tester.job_id}', period: {api_tester.period_seconds} seconds")

scheduler.start()
logger.info(
    f"Scheduler started with {len(api_testers)} job(s)"
)


@app.route("/", endpoint="main")
@prom_metrics.do_not_track()
def print_status() -> Response:
    redis_keys: Dict[str, Any] = dict()

    if os.getenv("DEBUG", "").lower() != "true":
        return jsonify(**redis_keys)

    try:
        redis_client = api_testers[0].redis
        for key in redis_client.scan_iter("*"):
            value = redis_client.get(key)
            redis_keys[key] = value
    except Exception as e:
        logger.warning(f"Failed to retrieve Redis keys: {e}")

    return jsonify(**redis_keys)


@app.route("/favicon.ico", endpoint="favicon")
@prom_metrics.do_not_track()
def favicon() -> Response:
    return Response(status=204)


@app.route("/flask-health-check", endpoint="health-check")
@prom_metrics.do_not_track()
def flask_health_check() -> Response:
    try:
        if not scheduler.running:
            logger.error("Health check failed: scheduler not running")
            return Response(status=503, response="Scheduler not running")

        for api_tester in api_testers:
            job = scheduler.get_job(job_id=api_tester.job_id)
            if job is None:
                logger.error(
                    f"Health check failed: job '{api_tester.job_id}' not found"
                )
                return Response(
                    status=503, response=f"Job '{api_tester.job_id}' not found"
                )

        return Response(status=200, response="OK")
    except Exception as e:
        logger.error(f"Health check failed: {e}", exc_info=True)
        return Response(status=503, response="Health check failed")


if __name__ == "__main__":
    app.run(debug=False, port=8080)
