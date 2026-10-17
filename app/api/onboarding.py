from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.cli import build_client
from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.editions import EditionService
from app.services.embeddings import create_embedder
from app.services.onboarding import make_tags
from app.services.learning import LearningProcessor
from app.services.recommendation import RecommendationService, build_profile_vector
from app.services.topics import TOPICS
from app.services.source_registry import enabled_sources

router = APIRouter(prefix="/api", tags=["onboarding"])
TOPIC_NAMES = {topic.name for topic in TOPICS}


class TagRequest(BaseModel):
    text: str = Field(default="", max_length=1000)


class OnboardingRequest(BaseModel):
    selected_topics: list[str] = Field(default_factory=list, max_length=6)
    muted_topics: list[str] = Field(default_factory=list, max_length=6)
    selected_sub_interests: list[str] = Field(default_factory=list, max_length=20)
    interest_tags: list[str] = Field(default_factory=list, max_length=10)
    source_weights: dict[str, float] = Field(default_factory=dict, max_length=12)
    depth: str = "standard"
    stories_per_edition: int = Field(default=10, ge=10, le=20)
    surprise_level: str = "medium"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    delivery_time: str = Field(default="07:00", pattern=r"^\d{2}:\d{2}$")
    display_name: str | None = Field(default=None, max_length=120)
    reactions: list[dict] = Field(default_factory=list, max_length=8)

    @field_validator("selected_topics")
    @classmethod
    def valid_topics(cls, values: list[str]) -> list[str]:
        if any(value not in TOPIC_NAMES for value in values):
            raise ValueError("selected_topics contains an unknown topic")
        return list(dict.fromkeys(values))

    @field_validator("muted_topics")
    @classmethod
    def valid_muted_topics(cls, values: list[str]) -> list[str]:
        if any(value not in TOPIC_NAMES for value in values):
            raise ValueError("muted_topics contains an unknown topic")
        return list(dict.fromkeys(values))

    @field_validator("source_weights")
    @classmethod
    def valid_source_weights(cls, values: dict[str, float]) -> dict[str, float]:
        source_ids = {source.source_id for source in enabled_sources()}
        if any(source_id not in source_ids for source_id in values):
            raise ValueError("source_weights contains an unknown source")
        if any(not 0 <= weight <= 5 for weight in values.values()):
            raise ValueError("source weights must be between 0 and 5")
        return values

    @field_validator("depth")
    @classmethod
    def valid_depth(cls, value: str) -> str:
        if value not in {"brief", "standard", "long"}:
            raise ValueError("depth must be brief, standard, or long")
        return value

    @field_validator("surprise_level")
    @classmethod
    def valid_surprise(cls, value: str) -> str:
        if value not in {"low", "medium", "high"}:
            raise ValueError("surprise_level must be low, medium, or high")
        return value


def _create_profile(payload: OnboardingRequest) -> str:
    settings = get_settings()
    database = Database(settings.database_path)
    repo = ProfileRepository(database)
    embedder = create_embedder(
        settings.embedding_backend, settings.embedding_dimensions, settings.embedding_allow_fallback
    )
    weights = {topic: 3.0 for topic in payload.selected_topics}
    weights.update({interest: 2.0 for interest in payload.selected_sub_interests})
    weights.update({tag: 2.0 for tag in payload.interest_tags})
    vector = build_profile_vector(
        embedder, weights, payload.selected_sub_interests, payload.interest_tags
    )
    floor = {"low": 0.10, "medium": 0.15, "high": 0.25}[payload.surprise_level]
    return repo.create_user(
        payload.display_name or "Reader",
        weights,
        payload.source_weights,
        payload.muted_topics,
        vector,
        embedder.name,
        payload.selected_sub_interests,
        payload.interest_tags,
        {
            "depth": payload.depth,
            "edition_size": payload.stories_per_edition,
            "surprise_level": payload.surprise_level,
            "exploration_floor": floor,
            "timezone": payload.timezone,
            "delivery_time": payload.delivery_time,
            "display_name": payload.display_name,
        },
    )


def _generate_background(user_id: str, edition_date: str) -> None:
    async def run() -> None:
        settings = get_settings()
        database = Database(settings.database_path)
        repo = ProfileRepository(database)
        repo.set_generation_status(user_id, edition_date, "running", "selecting")
        recommender = RecommendationService(
            database,
            freshness_hours=settings.freshness_hours,
            topic_threshold=settings.real_topic_match_threshold
            if settings.embedding_backend == "sentence_transformer"
            else settings.topic_match_threshold,
            dimensions=settings.embedding_dimensions,
            embedder=create_embedder(
                settings.embedding_backend,
                settings.embedding_dimensions,
                settings.embedding_allow_fallback,
            ),
        )
        client = build_client()
        try:
            async with client:
                service = EditionService(database, recommender, client)
                repo.set_generation_status(user_id, edition_date, "running", "summarizing")
                repo.set_generation_status(user_id, edition_date, "running", "arranging")
                await service.generate(user_id, edition_date)
                repo.set_generation_status(user_id, edition_date, "running", "saving")
            repo.set_generation_status(user_id, edition_date, "ready", "ready")
        except Exception as exc:
            repo.set_generation_status(user_id, edition_date, "failed", "failed", str(exc)[:500])
    asyncio.run(run())


@router.post("/onboarding/tags")
async def onboarding_tags(payload: TagRequest) -> dict[str, list[str]]:
    client = build_client()
    async with client:
        return {"tags": await make_tags(payload.text, client)}


@router.get("/onboarding/sources")
def onboarding_sources() -> list[dict[str, str]]:
        return [{"source_id": source.source_id, "name": source.name} for source in enabled_sources()]


@router.post("/onboarding")
async def create_onboarding(
    payload: OnboardingRequest, request: Request, background_tasks: BackgroundTasks
) -> dict[str, str]:
    user_id = _create_profile(payload)
    request.session["user_id"] = user_id
    edition_date = date.today().isoformat()
    repo = ProfileRepository(Database(get_settings().database_path))
    for reaction in payload.reactions:
        article_id = reaction.get("article_id")
        with Database(get_settings().database_path).connect() as db:
            exists = article_id and db.execute(
                "SELECT 1 FROM articles WHERE article_id=?", (article_id,)
            ).fetchone()
        if reaction.get("type") in {"like", "dislike"} and exists:
            repo.record_event(user_id, reaction["type"], "onboarding", article_id=article_id)
    LearningProcessor(Database(get_settings().database_path)).process_user(user_id)
    repo.set_generation_status(user_id, edition_date, "queued", "queued")
    background_tasks.add_task(_generate_background, user_id, edition_date)
    return {"user_id": user_id, "edition_date": edition_date}


@router.get("/me")
def me(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    profile = ProfileRepository(Database(get_settings().database_path)).get_profile(user_id)
    if profile is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not signed in")
    return {"user_id": user_id, "display_name": profile["settings"].get("display_name"), "settings": profile["settings"]}


@router.get("/users/{user_id}/editions/{edition_date}/status")
def generation_status(user_id: str, edition_date: date) -> dict:
    repo = ProfileRepository(Database(get_settings().database_path))
    if repo.get_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    status = repo.generation_status(user_id, edition_date.isoformat())
    if status is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return status
