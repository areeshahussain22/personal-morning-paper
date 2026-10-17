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
    embedding_backend: str = "sentence_transformer"
    embedding_allow_fallback: bool = False
    cluster_window_hours: int = 36
    cluster_similarity_threshold: float = 0.72
    hashed_cluster_similarity_threshold: float = 0.45
    real_topic_match_threshold: float = 0.45


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
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "sentence_transformer"),
        embedding_allow_fallback=os.getenv("EMBEDDING_ALLOW_FALLBACK", "false").lower() == "true",
        cluster_window_hours=int(os.getenv("CLUSTER_WINDOW_HOURS", "36")),
        cluster_similarity_threshold=float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.72")),
        hashed_cluster_similarity_threshold=float(os.getenv("HASHED_CLUSTER_SIMILARITY_THRESHOLD", "0.45")),
        real_topic_match_threshold=float(os.getenv("REAL_TOPIC_MATCH_THRESHOLD", "0.45")),
    )
