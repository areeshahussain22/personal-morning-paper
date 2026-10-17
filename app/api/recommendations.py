from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.embeddings import create_embedder
from app.services.recommendation import RecommendationService, build_profile_vector
from app.services.pdf import build_pdf
from app.services.topics import TOPICS
from app.services.editions import EditionService
from app.cli import build_client
from datetime import date

router = APIRouter(prefix="/api", tags=["recommendations"])


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    selected_topics: list[str] = Field(default_factory=list)
    selected_sub_interests: list[str] = Field(default_factory=list)
    interest_tags: list[str] = Field(default_factory=list)
    source_weights: dict[str, float] = Field(default_factory=dict)
    muted_topics: list[str] = Field(default_factory=list)


class PreferencesUpdate(BaseModel):
    topic_weights: dict[str, float] | None = None
    source_weights: dict[str, float] | None = None
    muted_topics: list[str] | None = None


def repository() -> ProfileRepository:
    return ProfileRepository(Database(get_settings().database_path))


def topic_preferences(payload: UserCreate) -> dict[str, float]:
    result = {topic: 3.0 for topic in payload.selected_topics}
    result.update({topic: 2.0 for topic in payload.selected_sub_interests})
    for tag in payload.interest_tags:
        result[tag] = 2.0
    return result


@router.get("/topics")
def topics() -> list[dict[str, str]]:
    return [{"name": topic.name, "description": topic.description} for topic in TOPICS]


@router.post("/users")
def create_user(payload: UserCreate) -> dict[str, str]:
    repo = repository()
    settings = get_settings()
    embedder = create_embedder(
        settings.embedding_backend, settings.embedding_dimensions, settings.embedding_allow_fallback
    )
    weights = topic_preferences(payload)
    vector = build_profile_vector(embedder, weights, payload.selected_sub_interests, payload.interest_tags)
    user_id = repo.create_user(
        payload.name, weights, payload.source_weights, payload.muted_topics, vector, embedder.name
    )
    return {"user_id": user_id}


@router.get("/users/{user_id}/preferences")
def get_preferences(user_id: str) -> dict:
    profile = repository().get_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


@router.put("/users/{user_id}/preferences")
def update_preferences(user_id: str, payload: PreferencesUpdate) -> dict:
    repo = repository()
    current = repo.get_profile(user_id)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not repo.update_preferences(
        user_id,
        payload.topic_weights if payload.topic_weights is not None else current["topic_weights"],
        payload.source_weights if payload.source_weights is not None else current["source_weights"],
        payload.muted_topics if payload.muted_topics is not None else current["muted_topics"],
    ):
        raise HTTPException(status_code=404, detail="User not found")
    settings = get_settings()
    embedder = create_embedder(
        settings.embedding_backend, settings.embedding_dimensions, settings.embedding_allow_fallback
    )
    vector = build_profile_vector(embedder, payload.topic_weights or current["topic_weights"])
    repo.set_vectors(user_id, vector, embedder.name)
    return repo.get_profile(user_id)


@router.post("/users/{user_id}/recommendations/preview")
def recommendation_preview(user_id: str, edition_size: int = 10) -> dict:
    settings = get_settings()
    repo = repository()
    profile = repo.get_preferences(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="User not found")
    service = RecommendationService(
        Database(settings.database_path),
        freshness_hours=settings.freshness_hours,
        topic_threshold=(
            settings.real_topic_match_threshold
            if settings.embedding_backend == "sentence_transformer"
            else settings.topic_match_threshold
        ),
        dimensions=settings.embedding_dimensions,
    )
    result = service.preview(user_id, profile, max(1, min(edition_size, 100)))
    serialized = result.as_dict()
    edition_id = repo.save_edition(user_id, serialized)
    serialized["edition_id"] = edition_id
    return serialized


@router.get("/users/{user_id}/recommendations")
def latest_recommendations(user_id: str) -> dict:
    repo = repository()
    if repo.get_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    result = repo.latest_edition(user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No recommendation edition found")
    return result


def edition_service(use_llm: bool) -> tuple[EditionService, object | None]:
    settings = get_settings()
    database = Database(settings.database_path)
    profile_service = RecommendationService(
        database,
        freshness_hours=settings.freshness_hours,
        topic_threshold=settings.real_topic_match_threshold
        if settings.embedding_backend == "sentence_transformer"
        else settings.topic_match_threshold,
        dimensions=settings.embedding_dimensions,
    )
    client = build_client() if use_llm else None
    return EditionService(database, profile_service, client), client


@router.post("/users/{user_id}/editions/generate")
async def generate_edition(
    user_id: str,
    background_tasks: BackgroundTasks,
    edition_date: date | None = None,
    force: bool = False,
    use_llm: bool = True,
) -> dict:
    service, client = edition_service(use_llm)
    try:
        if client is not None:
            async with client:
                result = await service.generate(user_id, edition_date or date.today(), force, use_llm)
        else:
            result = await service.generate(user_id, edition_date or date.today(), force, use_llm)
        background_tasks.add_task(
            build_pdf, repository(), user_id, (edition_date or date.today()).isoformat(), get_settings()
        )
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/users/{user_id}/editions")
def list_editions(user_id: str) -> list[dict]:
    repo = repository()
    if repo.get_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return repo.list_editions(user_id)


@router.get("/users/{user_id}/editions/{edition_date}")
def get_edition(user_id: str, edition_date: date) -> dict:
    repo = repository()
    if repo.get_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    result = repo.edition_for_date(user_id, edition_date.isoformat())
    if result is None:
        raise HTTPException(status_code=404, detail="Edition not found")
    return result
