from __future__ import annotations

import asyncio
from pathlib import Path

from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.editions import EditionService
from app.services.embeddings import HashedEmbedder
from app.services.recommendation import RecommendationService
from tests.test_recommendation import seed_database


def make_service(path: Path) -> tuple[EditionService, str, Database]:
    database, user_id = seed_database(path)
    recommender = RecommendationService(database, embedder=HashedEmbedder())
    return EditionService(database, recommender), user_id, database


def test_no_llm_edition_is_complete_and_positions_are_sequential(tmp_path: Path) -> None:
    service, user_id, database = make_service(tmp_path / "editions.db")
    result = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))

    assert result["layout_source"] == "code"
    assert [item["position"] for item in result["items"]] == list(range(1, len(result["items"]) + 1))
    assert result["items"][0]["position"] == 1
    assert result["items"][0]["article_id"] == result["lead_id"]
    assert all(item["summary"] for item in result["items"])
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM edition_items").fetchone()[0] == len(result["items"])


def test_generation_is_idempotent_and_force_replaces(tmp_path: Path) -> None:
    service, user_id, database = make_service(tmp_path / "editions.db")
    first = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))
    same = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))
    forced = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False, force=True))

    assert same["edition_id"] == first["edition_id"]
    assert forced["edition_id"] != first["edition_id"]
    assert len(ProfileRepository(database).list_editions(user_id)) == 1


def test_summary_cache_is_reused_for_existing_article(tmp_path: Path) -> None:
    service, user_id, database = make_service(tmp_path / "editions.db")
    first = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))
    with database.connect() as db:
        before = db.execute(
            "SELECT article_id, summary, summary_source FROM articles WHERE summary IS NOT NULL ORDER BY article_id LIMIT 1"
        ).fetchone()
        assert before is not None
        db.execute("DELETE FROM edition_articles WHERE edition_id = ?", (first["edition_id"],))
        db.execute("DELETE FROM edition_items WHERE edition_id = ?", (first["edition_id"],))
        db.execute("DELETE FROM editions WHERE edition_id = ?", (first["edition_id"],))
        db.execute("UPDATE users SET editions_read = 0 WHERE user_id = ?", (user_id,))
    second = asyncio.run(service.generate(user_id, "2026-10-18", use_llm=False))
    assert second["items"]
    with database.connect() as db:
        after = db.execute(
            "SELECT summary, summary_source FROM articles WHERE article_id = ?",
            (before["article_id"],),
        ).fetchone()
    assert after["summary"] == before["summary"]
    assert after["summary_source"] == before["summary_source"]
