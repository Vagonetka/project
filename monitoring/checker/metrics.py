from prometheus_client import Gauge, Summary

api_tester_stage_status = Gauge(
    name="api_tester_stage_status",
    documentation="Pipeline stage status: 0 - FAIL, 1 - OK",
    labelnames=["product_name", "stage_name"],
    multiprocess_mode="mostrecent",
)

api_tester_job_status = Gauge(
    name="api_tester_job_status",
    documentation="Pipeline job status: 0 - FAIL, 1 - OK",
    labelnames=["product_name"],
    multiprocess_mode="mostrecent",
)

api_tester_job_seconds = Summary(
    name="api_tester_job_seconds",
    documentation="Completion time of the job",
    labelnames=["product_name"],
)

def create_dynamic_metric(name, labels=[], documentation='', multiprocess_mode=''):
    return Gauge(
    name=name,
    documentation=documentation,
    labelnames=labels,
    multiprocess_mode=multiprocess_mode,
)