from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import ingestion
from app.main import app
from app.models.article import Article
from app.repositories.database import Database
from app.services.archive import ArticleArchive
from app.services.rss_ingestion import RSSIngestionService, canonicalize_url, normalize_entry
from app.services.source_registry import RSSSource

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Useful story</title><link>https://example.com/story?utm_source=test&amp;page=2</link>
<description><![CDATA[<p>A useful snippet.</p>]]></description>
<pubDate>Sat, 17 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://example.com/no-title</link></item>
<item><title>No URL</title></item>
</channel></rss>"""

SOURCE = RSSSource("test", "Test Source", "https://example.com/feed", "technology_ai", 0.8, False)


def test_canonical_url_removes_tracking_but_preserves_meaningful_query() -> None:
    assert canonicalize_url(
        "HTTPS://Example.COM/story/?utm_campaign=x&page=2&fbclid=abc"
    ) == "https://example.com/story/?page=2"


def test_normalize_entry_handles_valid_and_invalid_dates() -> None:
    valid = normalize_entry(
        {"title": "Story", "link": "https://example.com/story", "published": "not a date"},
        SOURCE,
    )
    assert valid is not None
    assert valid.published_at is None
    assert valid.publication_date_issue == "invalid_publication_date"
    assert normalize_entry({"title": "", "link": "https://example.com"}, SOURCE) is None
    assert normalize_entry({"title": "Missing URL"}, SOURCE) is None


def test_database_prevents_duplicate_canonical_urls(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    service = RSSIngestionService(database, [SOURCE])
    now = datetime.now(timezone.utc)
    first = normalize_entry(
        {
            "title": "One",
            "link": "https://example.com/a?utm_source=x",
            "published": now.isoformat(),
        },
        SOURCE,
        now,
    )
    second = normalize_entry(
        {"title": "Updated", "link": "https://example.com/a", "published": now.isoformat()},
        SOURCE,
        now,
    )
    assert first and second
    assert database.upsert_article(first) is True
    assert database.upsert_article(second) is False
    assert len(database.list_articles(10, 0, now - timedelta(days=1))) == 1


def test_successful_and_failed_feeds_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database(tmp_path / "test.db")
    good = SOURCE
    bad = RSSSource("bad", "Bad Source", "https://bad.example/feed", "world", 0.5, False)
    service = RSSIngestionService(database, [good, bad], max_retries=0)

    async def fake_get(self: httpx.AsyncClient, url: str) -> httpx.Response:
        if url == good.feed_url:
            return httpx.Response(200, content=RSS.encode(), request=httpx.Request("GET", url))
        return httpx.Response(503, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    summary = asyncio.run(service.ingest())
    assert summary.feeds_successful == 1
    assert summary.feeds_failed == 1
    assert summary.entries_parsed == 3
    assert summary.new_articles == 1
    assert summary.entries_rejected == 2


def test_malformed_feed_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database(tmp_path / "test.db")
    service = RSSIngestionService(database, [SOURCE], max_retries=0)

    async def fake_get(self: httpx.AsyncClient, url: str) -> httpx.Response:
        return httpx.Response(200, content=b"<not-rss", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    summary = asyncio.run(service.ingest())
    assert summary.feeds_failed == 1
    assert "malformed" in summary.feed_errors["test"]


def test_freshness_and_snapshot_replay(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    service = RSSIngestionService(database, [SOURCE])
    now = datetime.now(timezone.utc)
    article = normalize_entry(
        {"title": "Recent", "link": "https://example.com/recent", "published": now.isoformat()},
        SOURCE,
        now,
    )
    assert article
    database.upsert_article(article)
    archive = ArticleArchive(database, freshness_hours=48)
    snapshot = archive.create_snapshot(now)
    replayed = archive.replay_snapshot(snapshot["snapshot_id"])
    assert replayed is not None
    assert replayed["article_count"] == 1
    assert replayed["articles"][0]["title"] == "Recent"


def test_ingestion_api_response_and_snapshot_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    client = TestClient(app)
    response = client.get("/api/ingestion/articles")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert client.get("/api/ingestion/snapshots/missing").status_code == 404


def test_repeated_ingestion_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database(tmp_path / "test.db")
    service = RSSIngestionService(database, [SOURCE], max_retries=0)

    async def fake_get(self: httpx.AsyncClient, url: str) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode(), request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    first = asyncio.run(service.ingest())
    second = asyncio.run(service.ingest())
    assert first.new_articles == 1
    assert second.new_articles == 0
    assert second.existing_articles == 1


def test_ingestion_api_reports_all_feed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedService:
        async def ingest(self) -> object:
            return type(
                "Summary",
                (),
                {
                    "feeds_attempted": 1,
                    "feeds_successful": 0,
                    "feeds_failed": 1,
                    "entries_parsed": 0,
                    "new_articles": 0,
                    "existing_articles": 0,
                    "entries_rejected": 0,
                    "rejection_reasons": {},
                    "duration_seconds": 0.1,
                    "feed_errors": {"test": "offline"},
                },
            )()

    monkeypatch.setattr(ingestion, "build_services", lambda: (FailedService(), None))
    response = TestClient(app).post("/api/ingestion/run")
    assert response.status_code == 502
    assert response.json()["detail"]["message"] == "All RSS feeds failed"
