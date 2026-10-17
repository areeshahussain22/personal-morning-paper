from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository

router = APIRouter(prefix="/api", tags=["events"])
EVENT_TYPES = {"impression_seen", "expand_summary", "save", "like", "dislike", "less_topic", "return", "pdf_download"}
SOURCES = {"web", "pdf", "onboarding"}


class EventInput(BaseModel):
    type: str
    article_id: str | None = Field(default=None, max_length=100)
    edition_id: str | None = Field(default=None, max_length=100)
    value: float | None = None
    position: int | None = Field(default=None, ge=1, le=1000)
    source: str = "web"
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError("unsupported event type")
        return value

    @field_validator("source")
    @classmethod
    def valid_source(cls, value: str) -> str:
        if value not in SOURCES:
            raise ValueError("unsupported event source")
        return value


def _repo() -> ProfileRepository:
    return ProfileRepository(Database(get_settings().database_path))


@router.post("/events", status_code=204)
async def record_events(request: Request) -> Response:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    body = await request.body()
    if len(body) > 32 * 1024:
        raise HTTPException(status_code=413, detail="Event payload too large")
    try:
        raw = json.loads(body)
        values = raw if isinstance(raw, list) else [raw]
        if not values or len(values) > 50:
            raise ValueError("too many events")
        events = [EventInput.model_validate(value) for value in values]
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Invalid event payload") from exc
    repo = _repo()
    settings = get_settings()
    if repo.event_count_since(user_id, 60) + len(events) > settings.event_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Event rate limit exceeded")
    for event in events:
        if not repo.event_allowed_for_edition(user_id, event.article_id, event.edition_id):
            raise HTTPException(status_code=403, detail="Event does not belong to this reader")
        repo.record_event(
            user_id, event.type, event.source, event.article_id, event.edition_id,
            event.value, event.position, event.extra,
        )
    return Response(status_code=204)
