from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "api_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "api_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "api_http_requests_in_progress",
    "HTTP requests currently in progress",
    registry=REGISTRY,
)

RESOURCE_VIEWS_TOTAL = Counter(
    "api_resource_views_total",
    "Resource views",
    ["resource"],
    registry=REGISTRY,
)

ORDERS_CREATED_TOTAL = Counter(
    "api_orders_created_total",
    "Orders created",
    registry=REGISTRY,
)

USERS_COUNT = Gauge(
    "api_users_count",
    "Current number of users",
    registry=REGISTRY,
)

ORDERS_COUNT = Gauge(
    "api_orders_count",
    "Current number of orders",
    registry=REGISTRY,
)