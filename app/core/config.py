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
    real_topic_match_threshold: float = 0.10
    topic_secondary_margin: float = 0.04
    llm_provider_order: tuple[str, ...] = ("gemini", "groq", "openrouter", "ollama")
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_concurrency_limit: int = 2
    llm_min_provider_interval: float = 0.0
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.1-8b-instant"
    openrouter_model: str = "meta-llama/llama-3.3-8b-instruct:free"
    ollama_model: str = "llama3.2"
    environment: str = "development"
    session_secret: str | None = None
    pdf_renderer: str = "auto"
    public_base_url: str = "http://localhost:8000"
    pdf_image_timeout_seconds: float = 8.0
    pdf_image_max_bytes: int = 2 * 1024 * 1024
    event_click_dedupe_seconds: int = 30
    event_rate_limit_per_minute: int = 60


def _load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_settings() -> Settings:
    _load_local_env()
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
        real_topic_match_threshold=float(os.getenv("REAL_TOPIC_MATCH_THRESHOLD", "0.10")),
        topic_secondary_margin=float(os.getenv("TOPIC_SECONDARY_MARGIN", "0.04")),
        llm_provider_order=tuple(
            item.strip() for item in os.getenv(
                "LLM_PROVIDER_ORDER", "gemini,groq,openrouter,ollama"
            ).split(",") if item.strip()
        ),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "30")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        llm_concurrency_limit=int(os.getenv("LLM_CONCURRENCY_LIMIT", "2")),
        llm_min_provider_interval=float(os.getenv("LLM_MIN_PROVIDER_INTERVAL", "0")),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-8b-instruct:free"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        environment=os.getenv("ENVIRONMENT", "development"),
        session_secret=os.getenv("SESSION_SECRET"),
        pdf_renderer=os.getenv("PDF_RENDERER", "auto").lower(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        pdf_image_timeout_seconds=float(os.getenv("PDF_IMAGE_TIMEOUT_SECONDS", "8")),
        pdf_image_max_bytes=int(os.getenv("PDF_IMAGE_MAX_BYTES", str(2 * 1024 * 1024))),
        event_click_dedupe_seconds=int(os.getenv("EVENT_CLICK_DEDUPE_SECONDS", "30")),
        event_rate_limit_per_minute=int(os.getenv("EVENT_RATE_LIMIT_PER_MINUTE", "60")),
    )
