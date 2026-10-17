from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.recommendation import ProfilePreferences
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.recommendation import (
    RecommendationService,
    exploration_share,
    score_article,
    title_similarity,
)
from app.services.embeddings import (
    EmbeddingBackendError,
    HashedEmbedder,
    cosine_similarity as embedding_cosine,
    create_embedder,
)
from app.services.recommendation import build_profile_vector
from app.services.source_registry import RSSSource
from app.services.topics import assign_topics, cosine_similarity, embed_text


SOURCE = RSSSource("test-source", "Test Source", "https://example.com/feed", "technology_ai", 0.9, False)


def seed_database(path: Path) -> tuple[Database, str]:
    database = Database(path)
    database.initialize()
    database.upsert_source(SOURCE)
    now = datetime.now(timezone.utc)
    from app.models.article import Article
    articles = [
        Article("a1", "AI software breakthrough", "https://example.com/a1", "https://example.com/a1",
                SOURCE.source_id, SOURCE.name, "New artificial intelligence software", now - timedelta(hours=2),
                None, "technology_ai", now, now),
        Article("a2", "AI software related update", "https://example.com/a2", "https://example.com/a2",
                SOURCE.source_id, SOURCE.name, "Another technology story", now - timedelta(hours=3),
                None, "technology_ai", now, now),
        Article("a3", "Global football championship", "https://example.com/a3", "https://example.com/a3",
                SOURCE.source_id, SOURCE.name, "International sports team", now - timedelta(hours=4),
                None, "sports", now, now),
        Article("old", "Old technology story", "https://example.com/old", "https://example.com/old",
                SOURCE.source_id, SOURCE.name, "Technology", now - timedelta(hours=60),
                None, "technology_ai", now, now),
    ]
    for article in articles:
        database.upsert_article(article)
    user_id = ProfileRepository(database).create_user("Demo", {"technology_ai": 3}, {}, [])
    RecommendationService(database, embedder=HashedEmbedder()).embed_all_articles()
    return database, user_id


def test_topics_embeddings_and_cosine_are_deterministic() -> None:
    assert len(assign_topics("Artificial intelligence software and computer chips", 0.1)) <= 2
    assert assign_topics("completely unrelated words", 0.5) == []
    vector = embed_text("technology software")
    assert cosine_similarity(vector, vector) > 0.99
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity(None, vector) == 0.0


def test_embedder_interface_backend_selection_and_mixed_vectors() -> None:
    embedder = create_embedder("hashed", 16)
    assert embedder.name == "hashed"
    assert embedder.dimension == 16
    assert len(embedder.embed_texts(["hello"])[0]) == 16
    try:
        embedding_cosine([1.0], [1.0], "hashed", "sentence_transformer")
    except ValueError as exc:
        assert "Cannot compare" in str(exc)
    else:
        raise AssertionError("mixed embedder comparison was not rejected")


def test_sentence_backend_does_not_silently_fallback(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_ALLOW_FALLBACK", raising=False)
    embedder = create_embedder("sentence_transformer")
    monkeypatch.setattr(embedder, "_load", lambda: (_ for _ in ()).throw(EmbeddingBackendError("missing")))
    try:
        embedder.embed_texts(["test"])
    except EmbeddingBackendError:
        pass
    else:
        raise AssertionError("sentence backend silently fell back")


def test_initial_profile_vector_uses_weighted_preferences() -> None:
    embedder = HashedEmbedder(8)
    vector = build_profile_vector(embedder, {"technology_ai": 3}, ["science"], ["robotics"])
    assert len(vector) == 8
    assert sum(value * value for value in vector) > 0.99


def test_scoring_formula_components_and_exploration() -> None:
    profile = ProfilePreferences({"technology_ai": 3}, {"test-source": 2}, set(), [1.0, 0.0], [0.0, 1.0])
    score, parts = score_article(
        {"source_id": "test-source"}, profile, [1.0, 0.0], 4, 0.9, 2, ["technology_ai"]
    )
    assert score > 0
    assert set(parts) == {"T", "E", "S", "C", "F", "reliability"}
    assert exploration_share(0) == 0.4
    assert exploration_share(10) == 0.15


def test_filters_selection_and_snapshot_result(tmp_path: Path) -> None:
    database, user_id = seed_database(tmp_path / "recommendations.db")
    profile = ProfileRepository(database).get_preferences(user_id)
    assert profile is not None
    result = RecommendationService(database).preview(user_id, profile, edition_size=4)
    ids = [item.article["article_id"] for group in (result.must_know, result.exploration, result.regular) for item in group]
    assert "old" not in ids
    assert ids
    assert all(item.reason_code for item in result.must_know + result.exploration + result.regular)
    assert title_similarity("AI software breakthrough", "AI software related update") > 0.3


def test_preview_uses_profile_edition_size_by_default(tmp_path: Path) -> None:
    database, user_id = seed_database(tmp_path / "recommendations.db")
    repo = ProfileRepository(database)
    assert repo.update_settings(
        user_id,
        {
            "depth": "standard",
            "edition_size": 2,
            "surprise_level": "medium",
            "exploration_floor": 0.15,
            "timezone": "UTC",
            "delivery_time": "07:00",
            "display_name": "Demo",
        },
    )
    profile = repo.get_preferences(user_id)
    assert profile is not None
    result = RecommendationService(database).preview(user_id, profile)
    assert len(result.must_know + result.exploration + result.regular) == 2


def test_muted_topics_and_previous_editions_are_excluded(tmp_path: Path) -> None:
    database, user_id = seed_database(tmp_path / "recommendations.db")
    repo = ProfileRepository(database)
    assert repo.update_preferences(user_id, {"technology_ai": 3}, {}, ["sports"])
    profile = repo.get_preferences(user_id)
    assert profile is not None
    first = RecommendationService(database).preview(user_id, profile, edition_size=5)
    repo.save_edition(user_id, first.as_dict())
    second = RecommendationService(database).preview(user_id, profile, edition_size=5)
    ids = {item.article["article_id"] for group in (second.must_know, second.exploration, second.regular) for item in group}
    assert "a3" not in ids
    assert not ids.intersection({"a1", "a2"})


def test_low_reliability_and_empty_pool_are_safe(tmp_path: Path) -> None:
    database, user_id = seed_database(tmp_path / "recommendations.db")
    with database.connect() as db:
        db.execute("UPDATE sources SET reliability_score = 0.2")
    profile = ProfileRepository(database).get_preferences(user_id)
    assert profile is not None
    result = RecommendationService(database).preview(user_id, profile)
    assert result.must_know == result.exploration == result.regular == []


def test_profile_and_recommendation_api_validation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    client = TestClient(app)
    response = client.post("/api/users", json={"name": "Demo", "selected_topics": ["technology_ai"]})
    assert response.status_code == 200
    user_id = response.json()["user_id"]
    preferences = client.get(f"/api/users/{user_id}/preferences")
    assert preferences.status_code == 200
    assert preferences.json()["vector_embedder"] == "hashed"
    assert preferences.json()["vector_dimension"] > 0
    assert client.put(f"/api/users/{user_id}/preferences", json={"muted_topics": ["sports"]}).status_code == 200
    assert client.get("/api/users/missing/preferences").status_code == 404
    assert client.post("/api/users/missing/recommendations/preview").status_code == 404
    assert client.get(f"/api/users/{user_id}/recommendations").status_code == 404


@pytest.mark.slow
def test_real_model_semantic_similarity() -> None:
    pytest.importorskip("sentence_transformers")
    embedder = create_embedder("sentence_transformer")
    related = embedder.embed_text("startup funding")
    venture = embedder.embed_text("venture capital")
    unrelated = embedder.embed_text("football match")
    assert embedding_cosine(related, venture, embedder.name, embedder.name) > embedding_cosine(
        related, unrelated, embedder.name, embedder.name
    )
