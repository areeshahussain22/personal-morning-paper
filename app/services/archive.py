from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.repositories.database import Database


class ArticleArchive:
    def __init__(self, database: Database, freshness_hours: int = 48):
        self.database = database
        self.freshness_hours = freshness_hours

    def recent_articles(self, limit: int = 50, offset: int = 0) -> list[dict]:
        limit = min(max(limit, 1), 100)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.freshness_hours)
        return [dict(row) for row in self.database.list_articles(limit, offset, cutoff)]

    def create_snapshot(self, as_of: datetime | None = None) -> dict:
        as_of = as_of or datetime.now(timezone.utc)
        cutoff = as_of - timedelta(hours=self.freshness_hours)
        rows = self.database.list_articles(10000, 0, cutoff)
        snapshot_id = uuid4().hex
        self.database.create_snapshot(snapshot_id, as_of, rows)
        return {"snapshot_id": snapshot_id, "as_of": as_of.isoformat(), "article_count": len(rows)}

    def replay_snapshot(self, snapshot_id: str) -> dict | None:
        return self.database.read_snapshot(snapshot_id)
