from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_db_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def from_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    feed_url TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    reliability_score REAL NOT NULL CHECK (reliability_score >= 0 AND reliability_score <= 1),
                    is_paywalled INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS articles (
                    article_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    original_url TEXT NOT NULL,
                    canonical_url TEXT NOT NULL UNIQUE,
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    source_name TEXT NOT NULL,
                    description TEXT,
                    published_at TEXT,
                    image_url TEXT,
                    topic TEXT NOT NULL,
                    first_ingested_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL,
                    publication_date_issue TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_articles_canonical_url ON articles(canonical_url);
                CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
                CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(topic);
                CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);
                CREATE TABLE IF NOT EXISTS archive_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    article_count INTEGER NOT NULL,
                    articles_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    editions_read INTEGER NOT NULL DEFAULT 0,
                    long_vector TEXT,
                    short_vector TEXT
                );
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                    depth TEXT NOT NULL DEFAULT 'standard',
                    edition_size INTEGER NOT NULL DEFAULT 10,
                    surprise_level TEXT NOT NULL DEFAULT 'medium',
                    exploration_floor REAL NOT NULL DEFAULT 0.15,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    delivery_time TEXT NOT NULL DEFAULT '07:00',
                    display_name TEXT,
                    onboarding_baseline_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS edition_generation_status (
                    user_id TEXT NOT NULL,
                    edition_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, edition_date)
                );
                CREATE TABLE IF NOT EXISTS user_topic_preferences (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    topic TEXT NOT NULL,
                    weight REAL NOT NULL,
                    PRIMARY KEY (user_id, topic)
                );
                CREATE TABLE IF NOT EXISTS user_source_preferences (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    source_id TEXT NOT NULL,
                    weight REAL NOT NULL,
                    PRIMARY KEY (user_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS user_muted_topics (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    topic TEXT NOT NULL,
                    PRIMARY KEY (user_id, topic)
                );
                CREATE TABLE IF NOT EXISTS article_topics (
                    article_id TEXT NOT NULL REFERENCES articles(article_id) ON DELETE CASCADE,
                    topic TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    PRIMARY KEY (article_id, topic)
                );
                CREATE TABLE IF NOT EXISTS article_embeddings (
                    article_id TEXT PRIMARY KEY REFERENCES articles(article_id) ON DELETE CASCADE,
                    dimensions INTEGER NOT NULL,
                    vector_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS article_clusters (
                    article_id TEXT PRIMARY KEY REFERENCES articles(article_id) ON DELETE CASCADE,
                    cluster_id TEXT NOT NULL,
                    cluster_size INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS editions (
                    edition_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edition_items (
                    edition_id TEXT NOT NULL REFERENCES editions(edition_id) ON DELETE CASCADE,
                    article_id TEXT NOT NULL REFERENCES articles(article_id),
                    position INTEGER NOT NULL,
                    is_lead INTEGER NOT NULL DEFAULT 0,
                    selection_group TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    reason_text TEXT NOT NULL,
                    score REAL NOT NULL,
                    score_components_json TEXT NOT NULL,
                    PRIMARY KEY (edition_id, article_id)
                );
                CREATE TABLE IF NOT EXISTS edition_articles (
                    edition_id TEXT NOT NULL REFERENCES editions(edition_id) ON DELETE CASCADE,
                    article_id TEXT NOT NULL REFERENCES articles(article_id),
                    selection_group TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    PRIMARY KEY (edition_id, article_id)
                );
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    article_id TEXT NOT NULL REFERENCES articles(article_id),
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_edition_user_created ON editions(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_article_topics_topic ON article_topics(topic);
                CREATE TABLE IF NOT EXISTS llm_calls (
                    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error_type TEXT,
                    error_status INTEGER,
                    error_message TEXT,
                    latency_ms INTEGER NOT NULL,
                    input_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_calls_created ON llm_calls(created_at);
                CREATE INDEX IF NOT EXISTS idx_llm_calls_purpose_provider ON llm_calls(purpose, provider);
                CREATE TABLE IF NOT EXISTS llm_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._add_column_if_missing(connection, "users", "vector_embedder", "TEXT")
            self._add_column_if_missing(connection, "users", "vector_dimension", "INTEGER")
            self._add_column_if_missing(connection, "article_embeddings", "embedder_name", "TEXT")
            self._add_column_if_missing(connection, "articles", "summary", "TEXT")
            self._add_column_if_missing(connection, "articles", "summary_source", "TEXT")
            self._add_column_if_missing(connection, "articles", "summary_provider", "TEXT")
            self._add_column_if_missing(connection, "articles", "summary_model", "TEXT")
            self._add_column_if_missing(connection, "llm_calls", "error_status", "INTEGER")
            self._add_column_if_missing(connection, "llm_calls", "error_message", "TEXT")
            self._add_column_if_missing(connection, "editions", "edition_date", "TEXT")
            self._add_column_if_missing(connection, "editions", "layout_source", "TEXT")
            self._add_column_if_missing(connection, "editions", "layout_provider", "TEXT")
            self._add_column_if_missing(connection, "editions", "layout_model", "TEXT")
            self._add_column_if_missing(connection, "editions", "stage_timings_json", "TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_editions_user_date ON editions(user_id, edition_date)"
            )

    @staticmethod
    def _add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def log_llm_call(
        self, provider: str, model: str, purpose: str, success: bool,
        error_type: str | None, latency_ms: int, input_size: int,
        error_status: int | None = None, error_message: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO llm_calls
                   (provider, model, purpose, success, error_type, error_status,
                    error_message, latency_ms, input_size, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider, model, purpose, int(success), error_type, error_status,
                    error_message, latency_ms, input_size, to_db_time(utc_now()),
                ),
            )

    def llm_calls_per_day(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(
                """SELECT substr(created_at, 1, 10) AS day, purpose, provider,
                   COUNT(*) AS calls, SUM(success) AS successes
                   FROM llm_calls GROUP BY day, purpose, provider ORDER BY day DESC"""
            ))

    def read_llm_cache(self, cache_key: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return json.loads(row["response_json"]) if row else None

    def write_llm_cache(self, cache_key: str, response: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, response_json, created_at) VALUES (?, ?, ?)",
                (cache_key, json.dumps(response), to_db_time(utc_now())),
            )

    def upsert_source(self, source: Any) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO sources
                    (source_id, name, feed_url, topic, reliability_score, is_paywalled, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    name=excluded.name, feed_url=excluded.feed_url, topic=excluded.topic,
                    reliability_score=excluded.reliability_score, is_paywalled=excluded.is_paywalled,
                    enabled=excluded.enabled, updated_at=excluded.updated_at
                """,
                (
                    source.source_id, source.name, source.feed_url, source.topic,
                    source.reliability_score, int(source.is_paywalled), int(source.enabled),
                    to_db_time(utc_now()),
                ),
            )

    def upsert_article(self, article: Any) -> bool:
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT article_id FROM articles WHERE canonical_url = ?",
                (article.canonical_url,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO articles (
                    article_id, title, original_url, canonical_url, source_id, source_name,
                    description, published_at, image_url, topic, first_ingested_at,
                    last_updated_at, publication_date_issue
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    title=excluded.title, original_url=excluded.original_url,
                    source_id=excluded.source_id, source_name=excluded.source_name,
                    description=excluded.description, published_at=excluded.published_at,
                    image_url=excluded.image_url, topic=excluded.topic,
                    last_updated_at=excluded.last_updated_at,
                    publication_date_issue=excluded.publication_date_issue
                """,
                (
                    article.article_id, article.title, article.original_url,
                    article.canonical_url, article.source_id, article.source_name,
                    article.description,
                    to_db_time(article.published_at) if article.published_at else None,
                    article.image_url, article.topic, to_db_time(article.first_ingested_at),
                    to_db_time(article.last_updated_at), article.publication_date_issue,
                ),
            )
            return existing is None

    def list_articles(self, limit: int, offset: int, cutoff: datetime) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(
                """
                SELECT * FROM articles
                WHERE published_at IS NOT NULL AND published_at >= ? AND published_at <= ?
                ORDER BY published_at DESC LIMIT ? OFFSET ?
                """,
                (to_db_time(cutoff), to_db_time(utc_now()), limit, offset),
            ))

    def create_snapshot(self, snapshot_id: str, as_of: datetime, rows: list[sqlite3.Row]) -> None:
        payload = [dict(row) for row in rows]
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO archive_snapshots VALUES (?, ?, ?, ?, ?)",
                (snapshot_id, to_db_time(utc_now()), to_db_time(as_of), len(payload), json.dumps(payload)),
            )

    def snapshot_for_date(self, calendar_date: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM archive_snapshots WHERE substr(as_of, 1, 10) = ? "
                "ORDER BY as_of DESC LIMIT 1",
                (calendar_date,),
            ).fetchone()
        return dict(row) if row else None

    def read_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM archive_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["articles"] = json.loads(result.pop("articles_json"))
        return result

    def close(self) -> Iterator[None]:
        return iter(())
