import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from .metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_IN_PROGRESS,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        skip = path == "/metrics"

        if not skip:
            HTTP_REQUESTS_IN_PROGRESS.inc()

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            if not skip:
                HTTP_REQUESTS_IN_PROGRESS.dec()
                HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(elapsed)
                HTTP_REQUESTS_TOTAL.labels(
                    method=method, path=path, status_code=str(status_code)
                ).inc()