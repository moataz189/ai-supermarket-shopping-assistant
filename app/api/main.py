from fastapi import FastAPI

app = FastAPI(title="AI Supermarket Shopping Assistant")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
