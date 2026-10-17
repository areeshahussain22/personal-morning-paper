from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    freshness_hours: int = 48
    request_timeout_seconds: float = 15.0
    max_retries: int = 2
    max_concurrent_feeds: int = 4
    recommendation_edition_size: int = 10
    topic_match_threshold: float = 0.12
    embedding_dimensions: int = 64


def get_settings() -> Settings:
    return Settings(
        database_path=Path(
            os.getenv("DATABASE_PATH", "data/personal_morning_paper.db")
        ),
        freshness_hours=int(os.getenv("FRESHNESS_HOURS", "48")),
        request_timeout_seconds=float(os.getenv("RSS_TIMEOUT_SECONDS", "15")),
        max_retries=int(os.getenv("RSS_MAX_RETRIES", "2")),
        max_concurrent_feeds=int(os.getenv("RSS_MAX_CONCURRENT_FEEDS", "4")),
        recommendation_edition_size=int(os.getenv("RECOMMENDATION_EDITION_SIZE", "10")),
        topic_match_threshold=float(os.getenv("TOPIC_MATCH_THRESHOLD", "0.12")),
        embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "64")),
    )
