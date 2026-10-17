from fastapi import FastAPI

from app.api.ingestion import router as ingestion_router
from app.api.recommendations import router as recommendations_router

app = FastAPI(
    title="Personal Morning Paper",
    description="AI-powered personalized digital newspaper.",
    version="0.1.0",
)
app.include_router(ingestion_router)
app.include_router(recommendations_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Welcome to Personal Morning Paper"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
