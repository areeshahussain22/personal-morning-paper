from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.cli import build_client
from app.core.config import get_settings
from app.repositories.database import Database, to_db_time, utc_now
from app.repositories.profile_repository import ProfileRepository
from app.services.archive import ArticleArchive
from app.services.embeddings import create_embedder
from app.services.editions import EditionService
from app.services.learning import LearningProcessor
from app.services.recommendation import RecommendationService
from app.services.rss_ingestion import RSSIngestionService

logger = logging.getLogger(__name__)


def due_edition_date(now: datetime, timezone_name: str, delivery_time: str, lead_minutes: int = 60) -> str | None:
    local = now.astimezone(ZoneInfo(timezone_name))
    hour, minute = (int(value) for value in delivery_time.split(":"))
    delivery = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < delivery - timedelta(minutes=lead_minutes):
        return None
    return local.date().isoformat()


class JobRunner:
    def __init__(self, database: Database):
        self.database = database
        self.settings = get_settings()
        self.database.initialize()

    def start(self, job: str, key: str) -> int | None:
        with self.database.connect() as db:
            existing = db.execute(
                "SELECT id, status FROM job_runs WHERE job=? AND run_key=?", (job, key)
            ).fetchone()
            if existing is not None:
                retryable = existing["status"] not in {"running", "success"}
                if job == "generate_edition" and existing["status"] == "success":
                    user_id, edition_date = key.rsplit(":", 1)
                    edition = db.execute(
                        "SELECT result_json FROM editions WHERE user_id=? AND edition_date=?",
                        (user_id, edition_date),
                    ).fetchone()
                    retryable = (
                        edition is None or not json.loads(edition["result_json"]).get("items")
                    )
                if not retryable:
                    return None
                db.execute(
                    "UPDATE job_runs SET status='running', started_at=?, finished_at=NULL, "
                    "error=NULL, stats_json='{}' WHERE id=?",
                    (to_db_time(utc_now()), existing["id"]),
                )
                return existing["id"]
            try:
                cursor = db.execute(
                    "INSERT INTO job_runs(job,run_key,status,started_at) VALUES(?,?,?,?)",
                    (job, key, "running", to_db_time(utc_now())),
                )
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                return None

    def finish(self, run_id: int, status: str, stats: dict | None = None, error: str | None = None) -> None:
        with self.database.connect() as db:
            db.execute(
                "UPDATE job_runs SET status=?, finished_at=?, error=?, stats_json=? WHERE id=?",
                (status, to_db_time(utc_now()), error[:500] if error else None,
                 json.dumps(stats or {}), run_id),
            )

    async def ingest_and_enrich(self) -> dict:
        current = utc_now()
        interval_minutes = self.settings.scheduler_interval_hours * 60
        now = current.replace(
            minute=(current.hour * 60 + current.minute) // interval_minutes * interval_minutes % 60,
            hour=(current.hour * 60 + current.minute) // interval_minutes,
            second=0,
            microsecond=0,
        )
        run_id = self.start("ingest_enrich", now.isoformat())
        if run_id is None:
            return {"status": "skipped", "reason": "already running"}
        try:
            service = RSSIngestionService(
                self.database, timeout_seconds=self.settings.request_timeout_seconds,
                max_retries=self.settings.max_retries, max_concurrent_feeds=self.settings.max_concurrent_feeds,
            )
            summary = await service.ingest()
            embedder = create_embedder(
                self.settings.embedding_backend, self.settings.embedding_dimensions,
                self.settings.embedding_allow_fallback,
            )
            recommender = RecommendationService(
                self.database, freshness_hours=self.settings.freshness_hours,
                topic_threshold=self.settings.real_topic_match_threshold,
                dimensions=self.settings.embedding_dimensions, embedder=embedder,
            )
            embedded = recommender.embed_all_articles()
            stats = {"feeds_failed": summary.feeds_failed, "new_articles": summary.new_articles, "embedded": embedded}
            status = "warning" if summary.feeds_failed == summary.feeds_attempted else "success"
            self.finish(run_id, status, stats)
            return stats
        except Exception as exc:
            self.finish(run_id, "failed", error=str(exc))
            raise

    async def generate_due(self) -> dict:
        with self.database.connect() as db:
            users = [dict(row) for row in db.execute(
                "SELECT u.user_id, s.timezone, s.delivery_time FROM users u JOIN user_settings s ON s.user_id=u.user_id"
            )]
        now = utc_now()
        due = [(row["user_id"], due_edition_date(now, row["timezone"], row["delivery_time"], self.settings.scheduler_lead_minutes)) for row in users]
        due = [(user_id, edition_date) for user_id, edition_date in due if edition_date]
        async def one(user_id: str, edition_date: str) -> dict:
            key = f"{user_id}:{edition_date}"
            run_id = self.start("generate_edition", key)
            if run_id is None:
                return {"user_id": user_id, "status": "skipped"}
            repo = ProfileRepository(self.database)
            repo.set_generation_status(user_id, edition_date, "running", "selecting")
            for attempt in range(3):
                try:
                    LearningProcessor(self.database).process_user(user_id)
                    recommender = RecommendationService(self.database, freshness_hours=self.settings.freshness_hours,
                        topic_threshold=self.settings.real_topic_match_threshold, dimensions=self.settings.embedding_dimensions)
                    client = build_client()
                    async with client:
                        result = await EditionService(self.database, recommender, client).generate(user_id, edition_date)
                    if not result.get("items"):
                        raise LookupError("No eligible articles are available for this edition yet")
                    self.finish(run_id, "success", {"edition_id": result["edition_id"], "attempt": attempt + 1})
                    repo.set_generation_status(user_id, edition_date, "ready", "ready")
                    return {"user_id": user_id, "status": "success"}
                except Exception as exc:
                    if attempt == 2:
                        self.finish(run_id, "failed", error=str(exc))
                        repo.set_generation_status(
                            user_id, edition_date, "failed", "failed", str(exc)[:500]
                        )
                        logger.exception("edition generation failed user=%s", user_id)
                        return {"user_id": user_id, "status": "failed"}
                    await asyncio.sleep(2 ** attempt)
        return {"results": await asyncio.gather(*(one(*item) for item in due))}

    async def weekly_summary(self) -> dict:
        from app.services.interest_summary import generate_interest_summary
        with self.database.connect() as db:
            user_ids = [row["user_id"] for row in db.execute("SELECT user_id FROM users")]
        client = build_client()
        async with client:
            results = [await generate_interest_summary(self.database, user_id, client) for user_id in user_ids]
        return {"refreshed": sum(result is not None for result in results)}

    def nightly_archive(self) -> dict:
        return ArticleArchive(self.database, self.settings.freshness_hours).create_snapshot()


def scheduler_main() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    runner = JobRunner(database)
    scheduler = BlockingScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": settings.scheduler_misfire_grace_seconds},
        executors={"default": {"type": "threadpool", "max_workers": settings.scheduler_max_workers}},
    )
    scheduler.add_job(lambda: asyncio.run(runner.ingest_and_enrich()), IntervalTrigger(hours=settings.scheduler_interval_hours), id="ingest_enrich", replace_existing=True)
    scheduler.add_job(lambda: asyncio.run(runner.generate_due()), IntervalTrigger(minutes=5), id="generate_due", replace_existing=True)
    scheduler.add_job(lambda: asyncio.run(runner.weekly_summary()), "cron", day_of_week="sun", hour=2, id="weekly_summary", replace_existing=True)
    scheduler.add_job(runner.nightly_archive, "cron", hour=1, id="nightly_archive", replace_existing=True)
    scheduler.add_job(lambda: asyncio.run(runner.generate_due()), "date", run_date=datetime.now(timezone.utc), id="catch_up")
    logger.info("scheduler started interval_hours=%d", settings.scheduler_interval_hours)
    scheduler.start()
