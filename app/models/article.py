from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Article:
    article_id: str
    title: str
    original_url: str
    canonical_url: str
    source_id: str
    source_name: str
    description: str | None
    published_at: datetime | None
    image_url: str | None
    topic: str
    first_ingested_at: datetime
    last_updated_at: datetime
    publication_date_issue: str | None = None
