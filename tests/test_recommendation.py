from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    return database, user_id


def test_topics_embeddings_and_cosine_are_deterministic() -> None:
    assert len(assign_topics("Artificial intelligence software and computer chips", 0.1)) <= 2
    assert assign_topics("completely unrelated words", 0.5) == []
    vector = embed_text("technology software")
    assert cosine_similarity(vector, vector) > 0.99
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity(None, vector) == 0.0


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
    assert client.get(f"/api/users/{user_id}/preferences").status_code == 200
    assert client.put(f"/api/users/{user_id}/preferences", json={"muted_topics": ["sports"]}).status_code == 200
    assert client.get("/api/users/missing/preferences").status_code == 404
    assert client.post("/api/users/missing/recommendations/preview").status_code == 404
    assert client.get(f"/api/users/{user_id}/recommendations").status_code == 404
