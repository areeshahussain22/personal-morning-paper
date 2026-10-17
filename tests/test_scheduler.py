from datetime import datetime, timezone

from app.repositories.database import Database
from app.services.scheduler import JobRunner, due_edition_date


def test_due_edition_uses_reader_local_date_and_lead_time():
    now = datetime(2026, 3, 8, 13, 30, tzinfo=timezone.utc)
    assert due_edition_date(now, "America/New_York", "09:00", 60) == "2026-03-08"
    assert due_edition_date(now, "Asia/Kolkata", "23:00", 60) is None


def test_generation_job_key_is_idempotent(tmp_path):
    database = Database(tmp_path / "jobs.db")
    runner = JobRunner(database)
    first = runner.start("generate_edition", "reader:2026-10-17")
    second = runner.start("generate_edition", "reader:2026-10-17")
    assert first is not None
    assert second is None


def test_failed_generation_job_can_be_retried(tmp_path):
    database = Database(tmp_path / "jobs.db")
    runner = JobRunner(database)
    first = runner.start("generate_edition", "reader:2026-10-17")
    assert first is not None

    runner.finish(first, "failed", error="No fresh articles")

    retry = runner.start("generate_edition", "reader:2026-10-17")
    assert retry == first
    assert runner.start("generate_edition", "reader:2026-10-17") is None
