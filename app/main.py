from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.ingestion import router as ingestion_router
from app.api.onboarding import router as onboarding_router
from app.api.recommendations import router as recommendations_router
from app.core.config import get_settings
from app.core.logging import configure_http_logging

settings = get_settings()
configure_http_logging()
if settings.environment != "development" and not settings.session_secret:
    raise RuntimeError("SESSION_SECRET is required outside development")

app = FastAPI(
    title="Personal Morning Paper",
    description="AI-powered personalized digital newspaper.",
    version="0.1.0",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or "development-only-session-secret",
    same_site="lax",
    https_only=settings.environment != "development",
    session_cookie="morning_paper_session",
)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(ingestion_router)
app.include_router(recommendations_router)
app.include_router(onboarding_router)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/")
def read_root(request: Request) -> Response:
    if request.session.get("user_id"):
        return RedirectResponse("/preparing")
    return templates.TemplateResponse(request=request, name="onboarding.html", context={"topics": []})


@app.get("/preparing")
def preparing(request: Request) -> Response:
    if not request.session.get("user_id"):
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="preparing.html", context={})


@app.get("/edition/{edition_date}")
def edition_page(request: Request, edition_date: str) -> Response:
    if not request.session.get("user_id"):
        return RedirectResponse("/")
    return templates.TemplateResponse(
        request=request, name="edition.html", context={"edition_date": edition_date}
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
