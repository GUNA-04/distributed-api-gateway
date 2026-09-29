"""
Prometheus metrics for the API gateway.

Exposed in Prometheus text exposition format at GET /metrics and scraped by
Prometheus/AWS CloudWatch Container Insights for dashboards and alerting.
"""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter(
    "gateway_http_requests_total",
    "Total HTTP requests processed by the gateway",
    ["method", "path", "status"],
)

REQUEST_LATENCY = Histogram(
    "gateway_http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ORDERS_CREATED = Counter(
    "gateway_orders_created_total",
    "Orders accepted by the gateway and queued for processing",
)

ORDERS_QUEUED_FAILED = Counter(
    "gateway_orders_queue_failed_total",
    "Orders stored in Postgres but NOT queued to Kafka (broker unavailable)",
)

RATE_LIMITED = Counter(
    "gateway_rate_limited_total",
    "Requests rejected with HTTP 429 by the rate limiter",
)

IN_FLIGHT = Gauge(
    "gateway_requests_in_flight",
    "HTTP requests currently being served",
)


def route_path(request) -> str:
    """Return the route template (e.g. /api/v1/orders/{order_id}) to keep
    metric label cardinality bounded; falls back to the raw path."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)
