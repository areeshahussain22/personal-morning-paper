from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.repositories.database import Database
from app.services.archive import ArticleArchive
from app.services.rss_ingestion import RSSIngestionService

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


def build_services() -> tuple[RSSIngestionService, ArticleArchive]:
    settings = get_settings()
    database = Database(settings.database_path)
    return (
        RSSIngestionService(
            database,
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
            max_concurrent_feeds=settings.max_concurrent_feeds,
        ),
        ArticleArchive(database, settings.freshness_hours),
    )


@router.post("/run")
async def run_ingestion() -> dict:
    service, _ = build_services()
    summary = await service.ingest()
    if summary.feeds_failed == summary.feeds_attempted:
        raise HTTPException(status_code=502, detail={
            "message": "All RSS feeds failed",
            "summary": summary.__dict__,
        })
    return summary.__dict__


@router.get("/articles")
def recent_articles(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    _, archive = build_services()
    return {"items": archive.recent_articles(limit, offset), "limit": limit, "offset": offset}


@router.post("/snapshots")
def create_snapshot() -> dict:
    _, archive = build_services()
    return archive.create_snapshot()


@router.get("/snapshots/{snapshot_id}")
def replay_snapshot(snapshot_id: str) -> dict:
    _, archive = build_services()
    snapshot = archive.replay_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot
