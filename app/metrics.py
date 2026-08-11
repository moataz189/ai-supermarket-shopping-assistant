from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

router = APIRouter()

# Metric names/shapes deliberately mirror polyaifursa's agent_chat_requests_total /
# agent_chat_request_duration_seconds / agent_input_tokens_total / agent_output_tokens_total
# (same PromQL, same Grafana panels, same PrometheusRule alerting pattern carry over
# unchanged) — everything below that isn't one of those four is new, instrumenting this
# project's own MCP-call/clarification/retailer-choice/cart-preparation surface, which the
# reference has no equivalent of.

agent_chat_requests_total = Counter(
    "agent_chat_requests_total",
    "Total /chat requests handled, by outcome",
    ["status"],
)

agent_chat_request_duration_seconds = Histogram(
    "agent_chat_request_duration_seconds",
    "Wall-clock duration of /chat requests, in seconds",
)

agent_input_tokens_total = Counter(
    "agent_input_tokens_total",
    "Bedrock input tokens consumed by the request-classification LLM call",
)

agent_output_tokens_total = Counter(
    "agent_output_tokens_total",
    "Bedrock output tokens produced by the request-classification LLM call",
)

agent_request_type_total = Counter(
    "agent_request_type_total",
    "Chat requests classified by type",
    ["request_type"],
)

mcp_call_total = Counter(
    "mcp_call_total",
    "Backend calls to an MCP server, by service and outcome",
    ["mcp_service", "status"],
)

retailer_choice_total = Counter(
    "retailer_choice_total",
    "Retailer chosen by the user for a finalized cart",
    ["retailer"],
)

cart_preparation_total = Counter(
    "cart_preparation_total",
    "Retailer-cart preparation outcomes",
    ["status"],
)


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
