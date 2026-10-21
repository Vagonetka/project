
from typing import Any
from prometheus_flask_exporter.multiprocess import GunicornInternalPrometheusMetrics


def child_exit(server: Any, worker: Any) -> None:
    GunicornInternalPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)
