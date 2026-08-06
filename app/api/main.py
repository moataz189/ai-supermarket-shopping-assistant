import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.chat import router as chat_router


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
