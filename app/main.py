from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.ingestion import router as ingestion_router
from app.api.onboarding import router as onboarding_router
from app.api.recommendations import router as recommendations_router
from app.api.events import router as events_router
from app.api.profile import router as profile_router
from app.api.jobs import router as jobs_router
from app.api.demo import router as demo_router
from app.core.config import get_settings
from app.core.logging import configure_http_logging
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.pdf import build_pdf

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
app.include_router(events_router)
app.include_router(profile_router)
app.include_router(jobs_router)
app.include_router(demo_router)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.state.templates = templates


def _relative_time(value: str | None) -> str:
    if not value:
        return "recently"
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        minutes = max(0, int((datetime.now(timezone.utc) - published.astimezone(timezone.utc)).total_seconds() / 60))
        if minutes < 60:
            return f"{minutes}m ago"
        if minutes < 1440:
            return f"{minutes // 60}h ago"
        return f"{minutes // 1440}d ago"
    except ValueError:
        return "recently"


templates.env.filters["relative_time"] = _relative_time
templates.env.filters["from_json"] = lambda value: __import__("json").loads(value)


def _repo() -> ProfileRepository:
    return ProfileRepository(Database(settings.database_path))


def _edition_context(request: Request, edition_date: str) -> dict:
    user_id = request.session.get("user_id")
    repo = _repo()
    stored = repo.render_edition(user_id, edition_date) if user_id else None
    profile = repo.get_profile(user_id) if user_id else None
    if stored is None:
        stored = {"edition_date": edition_date, "items": [], "sections": [], "render_items": []}
    editions = repo.list_editions(user_id) if user_id else []
    number = next((index for index, item in enumerate(reversed(editions), 1)
                   if item["edition_date"] == edition_date), len(editions) + 1)
    return {"edition": stored, "reader_name": (profile or {}).get("settings", {}).get("display_name") or (profile or {}).get("name", "Reader"), "edition_number": number, "user_id": user_id}


@app.get("/")
def read_root(request: Request) -> Response:
    if request.session.get("user_id"):
        return RedirectResponse("/edition/today")
    return templates.TemplateResponse(request=request, name="onboarding.html", context={"topics": []})


@app.get("/preparing")
def preparing(request: Request) -> Response:
    if not request.session.get("user_id"):
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="preparing.html", context={})


@app.get("/edition/today")
def today_edition(request: Request) -> Response:
    if not request.session.get("user_id"):
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="edition.html", context=_edition_context(request, datetime.now(timezone.utc).date().isoformat()))


@app.get("/edition/{edition_date}/pdf")
def edition_pdf(request: Request, edition_date: str, background_tasks: BackgroundTasks) -> Response:
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")
    try:
        path = build_pdf(_repo(), user_id, edition_date, settings)
    except LookupError:
        return Response(status_code=404)
    metadata = _repo().edition_pdf_metadata(user_id, edition_date)
    if metadata:
        background_tasks.add_task(
            _repo().record_event, user_id, "pdf_download", "pdf",
            None, metadata["edition_id"], None, None, {},
        )
    return Response(
        content=path.read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="morning-paper-{edition_date}.pdf"'},
    )


@app.get("/edition/{edition_date}")
def edition_page(request: Request, edition_date: str) -> Response:
    if not request.session.get("user_id"):
        return RedirectResponse("/")
    return templates.TemplateResponse(request=request, name="edition.html", context=_edition_context(request, edition_date))


@app.get("/archive")
def archive_page(request: Request) -> Response:
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/")
    editions = _repo().list_editions(user_id)
    rows = []
    for item in editions:
        result = item["result"]
        rows.append({
            "edition_date": item["edition_date"],
            "layout_source": item["layout_source"],
            "story_count": len(result.get("items", [])),
            "lead_headline": result.get("items", [{}])[0].get("headline", "Morning paper"),
        })
    dates = [row["edition_date"] for row in rows]
    return templates.TemplateResponse(request=request, name="archive.html", context={
        "editions": rows,
        "previous_edition": dates[1] if len(dates) > 1 else None,
        "next_edition": None,
    })


@app.get("/out/{token}")
def outbound_link(request: Request, token: str, background_tasks: BackgroundTasks) -> Response:
    repo = _repo()
    details = repo.token_details(token)
    target = details["original_url"] if details else None
    parsed = urlparse(target or "")
    if not target or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return Response(status_code=404)
    user_agent = request.headers.get("user-agent", "").lower()
    prefetch = any(name in request.headers for name in ("purpose", "sec-purpose", "x-moz"))
    bot = any(name in user_agent for name in ("bot", "crawler", "spider", "prefetch", "preview"))
    if request.method != "HEAD" and not prefetch and not bot:
        def record_click() -> None:
            if not repo.click_recorded_recently(
                details["user_id"], token, settings.event_click_dedupe_seconds
            ):
                repo.record_event(
                    details["user_id"], "click", details["token_source"], details["article_id"],
                    details["edition_id"], None, details["position"], {"token": token},
                )
        background_tasks.add_task(record_click)
    return RedirectResponse(target, status_code=302)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
