from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app.cli import build_client
from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.embeddings import create_embedder
from app.services.interest_summary import generate_interest_summary
from app.services.learning import LearningProcessor
from app.services.recommendation import build_profile_vector

router = APIRouter(tags=["profile"])


def _repo() -> ProfileRepository:
    return ProfileRepository(Database(get_settings().database_path))


def _user(request: Request) -> str:
    user_id = request.session.get("user_id")
    if not user_id or _repo().get_profile(user_id) is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user_id


@router.get("/profile")
def profile_page(request: Request):
    user_id = _user(request)
    return request.app.state.templates.TemplateResponse(
        request=request, name="profile.html", context={"profile": _repo().get_profile(user_id)}
    )


class SummaryUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=400)


class TopicEdit(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    action: str


@router.post("/api/profile/topic")
def edit_topic(payload: TopicEdit, request: Request) -> dict:
    user_id = _user(request)
    repo = _repo()
    profile = repo.get_profile(user_id)
    if payload.action not in {"boost", "mute"}:
        raise HTTPException(status_code=422, detail="Invalid topic action")
    weights = dict(profile["topic_weights"])
    weights[payload.topic] = 6.0 if payload.action == "boost" else -5.0
    repo.update_preferences(user_id, weights, profile["source_weights"], profile["muted_topics"])
    repo.record_event(user_id, "profile_edit", "web", extra={"topic": payload.topic, "action": payload.action})
    return {"status": "ok"}


@router.put("/api/profile/summary")
def update_summary(payload: SummaryUpdate, request: Request) -> dict:
    user_id = _user(request)
    settings = get_settings()
    repo = _repo()
    profile = repo.get_profile(user_id)
    embedder = create_embedder(settings.embedding_backend, settings.embedding_dimensions, settings.embedding_allow_fallback)
    vector = embedder.embed_text(payload.text)
    current = json.loads(profile["long_vector"]) if profile["long_vector"] else vector
    nudged = [0.85 * old + 0.15 * new for old, new in zip(current, vector)]
    repo.set_vectors(user_id, nudged, embedder.name)
    repo.save_interest_summary(user_id, payload.text, "user")
    repo.record_event(user_id, "profile_edit", "web", extra={"field": "interest_summary"})
    return {"summary": payload.text}


@router.post("/api/profile/summary/regenerate")
async def regenerate_summary(request: Request) -> dict:
    user_id = _user(request)
    client = build_client()
    async with client:
        text = await generate_interest_summary(Database(get_settings().database_path), user_id, client, True)
    return {"summary": text}


@router.post("/api/profile/reset")
def reset_profile(request: Request) -> dict:
    user_id = _user(request)
    LearningProcessor(Database(get_settings().database_path)).recompute_profile(user_id)
    return {"status": "ok"}


@router.delete("/api/profile")
def delete_profile(request: Request) -> dict:
    user_id = _user(request)
    if _repo().delete_user(user_id):
        request.session.clear()
    return {"status": "deleted"}


@router.post("/api/onboarding/reactions")
def onboarding_reactions(payload: list[dict], request: Request, background_tasks: BackgroundTasks) -> dict:
    user_id = _user(request)
    repo = _repo()
    for reaction in payload[:8]:
        event_type = reaction.get("type")
        if event_type not in {"like", "dislike"}:
            continue
        article_id = reaction.get("article_id")
        if repo.event_allowed_for_edition(user_id, article_id, None):
            repo.record_event(user_id, event_type, "onboarding", article_id=article_id)
    background_tasks.add_task(LearningProcessor(Database(get_settings().database_path)).process_user, user_id)
    return {"status": "accepted"}
