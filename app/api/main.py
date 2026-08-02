from fastapi import FastAPI

from app.api.routes.chat import router as chat_router

app = FastAPI(title="AI Supermarket Shopping Assistant")
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
