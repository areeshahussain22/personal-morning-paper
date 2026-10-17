from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from dateutil import parser as date_parser

from app.models.article import Article
from app.repositories.database import Database, utc_now
from app.services.source_registry import RSSSource, enabled_sources

logger = logging.getLogger(__name__)
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def strip_html(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip() or None


def parse_publication_date(entry: Any) -> tuple[datetime | None, str | None]:
    raw = entry.get("published") or entry.get("updated") or entry.get("created")
    if not raw:
        return None, "missing_publication_date"
    try:
        parsed = date_parser.parse(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc), None
    except (TypeError, ValueError, OverflowError):
        return None, "invalid_publication_date"


def normalize_entry(entry: Any, source: RSSSource, now: datetime | None = None) -> Article | None:
    title = strip_html(entry.get("title"))
    original_url = str(entry.get("link") or "").strip()
    if not title or not original_url:
        return None
    canonical_url = canonicalize_url(original_url)
    if not urlsplit(canonical_url).scheme or not urlsplit(canonical_url).netloc:
        return None
    published_at, issue = parse_publication_date(entry)
    now = now or utc_now()
    image_url = None
    for enclosure in entry.get("enclosures", []):
        if str(enclosure.get("type", "")).startswith("image/"):
            image_url = enclosure.get("href") or enclosure.get("url")
            break
    if not image_url:
        media = entry.get("media_content", [])
        if media:
            image_url = media[0].get("url")
    article_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return Article(
        article_id=article_id, title=title, original_url=original_url,
        canonical_url=canonical_url, source_id=source.source_id, source_name=source.name,
        description=strip_html(entry.get("summary") or entry.get("description")),
        published_at=published_at, image_url=image_url, topic=source.topic,
        first_ingested_at=now, last_updated_at=now, publication_date_issue=issue,
    )


@dataclass
class FeedResult:
    source_id: str
    success: bool
    parsed_entries: int = 0
    rejected_entries: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    articles: list[Article] = field(default_factory=list)
    error: str | None = None


@dataclass
class IngestionSummary:
    feeds_attempted: int
    feeds_successful: int
    feeds_failed: int
    entries_parsed: int
    new_articles: int
    existing_articles: int
    entries_rejected: int
    rejection_reasons: dict[str, int]
    duration_seconds: float
    feed_errors: dict[str, str]


class RSSIngestionService:
    def __init__(
        self,
        database: Database,
        sources: list[RSSSource] | None = None,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        max_concurrent_feeds: int = 4,
    ):
        self.database = database
        self.sources = sources if sources is not None else enabled_sources()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_concurrent_feeds = max_concurrent_feeds
        self.database.initialize()
        for source in self.sources:
            self.database.upsert_source(source)

    async def fetch_feed(self, client: httpx.AsyncClient, source: RSSSource) -> FeedResult:
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(source.feed_url)
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError("malformed RSS or Atom document")
                result = FeedResult(source_id=source.source_id, success=True)
                for entry in parsed.entries:
                    result.parsed_entries += 1
                    article = normalize_entry(entry, source)
                    if article is None:
                        result.rejected_entries += 1
                        reason = "missing_title_or_url"
                        if not (entry.get("title") or "").strip():
                            reason = "missing_title"
                        elif not (entry.get("link") or "").strip():
                            reason = "missing_url"
                        result.rejection_reasons[reason] = result.rejection_reasons.get(reason, 0) + 1
                    else:
                        result.articles.append(article)
                        if article.published_at and article.published_at > utc_now() + timedelta(minutes=5):
                            logger.warning(
                                "RSS entry has suspicious future timestamp: source=%s title=%s",
                                source.source_id,
                                article.title,
                            )
                        if article.publication_date_issue:
                            result.rejection_reasons[article.publication_date_issue] = (
                                result.rejection_reasons.get(article.publication_date_issue, 0) + 1
                            )
                logger.info("RSS feed succeeded: source=%s entries=%d", source.source_id, result.parsed_entries)
                return result
            except (httpx.HTTPError, ValueError, TypeError, UnicodeError) as exc:
                if attempt >= self.max_retries:
                    logger.error("RSS feed failed: source=%s error=%s", source.source_id, exc)
                    return FeedResult(source.source_id, False, error=str(exc))
                await asyncio.sleep(0.25 * (2 ** attempt))
        return FeedResult(source.source_id, False, error="exhausted retries")

    async def ingest(self) -> IngestionSummary:
        started = utc_now()
        semaphore = asyncio.Semaphore(self.max_concurrent_feeds)

        async def run(source: RSSSource) -> FeedResult:
            async with semaphore:
                return await self.fetch_feed(client, source)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            headers={"User-Agent": "PersonalMorningPaper/0.1 RSS reader"},
            follow_redirects=True,
        ) as client:
            results = await asyncio.gather(*(run(source) for source in self.sources))
        counts: dict[str, int] = {}
        new_articles = existing_articles = 0
        for result in results:
            for key, value in result.rejection_reasons.items():
                counts[key] = counts.get(key, 0) + value
            if result.success:
                for article in result.articles:
                    if self.database.upsert_article(article):
                        new_articles += 1
                    else:
                        existing_articles += 1
        failed = [result for result in results if not result.success]
        if not results or len(failed) == len(results):
            logger.error("All RSS feeds failed")
        return IngestionSummary(
            feeds_attempted=len(results), feeds_successful=len(results) - len(failed),
            feeds_failed=len(failed), entries_parsed=sum(r.parsed_entries for r in results),
            new_articles=new_articles, existing_articles=existing_articles,
            entries_rejected=sum(r.rejected_entries for r in results),
            rejection_reasons=counts, duration_seconds=(utc_now() - started).total_seconds(),
            feed_errors={r.source_id: r.error for r in failed if r.error},
        )
