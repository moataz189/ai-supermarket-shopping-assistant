import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes.chat import router as chat_router
from app.metrics import router as metrics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("BEDROCK_MODEL_ID"):
        raise RuntimeError(
            "BEDROCK_MODEL_ID environment variable is required (Bedrock model used by the "
            "LangGraph agent) — set it in .env or docker-compose before starting the backend."
        )
    yield


app = FastAPI(title="AI Supermarket Shopping Assistant", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(metrics_router)

# Generic per-route HTTP request count/duration/status metrics (http_requests_total,
# http_request_duration_seconds_*) — complements the business-logic counters in
# app/metrics.py. .expose(app) is deliberately not called: app/metrics.py's own /metrics
# route already serves prometheus_client's whole default registry, which this instrumentator
# registers into, so a second /metrics route would just be a duplicate.
Instrumentator().instrument(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
