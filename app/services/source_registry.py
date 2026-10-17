from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RSSSource:
    source_id: str
    name: str
    feed_url: str
    topic: str
    reliability_score: float
    is_paywalled: bool
    enabled: bool = True


# Reliability values are configurable starting estimates, not objective ratings.
RSS_SOURCES: tuple[RSSSource, ...] = (
    RSSSource(
        "bbc-technology", "BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "technology_ai", 0.85, False,
    ),
    RSSSource(
        "mit-technology-review", "MIT Technology Review", "https://www.technologyreview.com/feed/",
        "technology_ai", 0.9, False,
    ),
    RSSSource(
        "nasa-breaking-news", "NASA", "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "science_research", 0.9, False,
    ),
    RSSSource(
        "nature-news", "Nature News", "https://www.nature.com/nature.rss",
        "science_research", 0.92, False,
    ),
    RSSSource(
        "bbc-world", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml",
        "world", 0.85, False,
    ),
    RSSSource(
        "bbc-business", "BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml",
        "business_markets", 0.85, False,
    ),
    RSSSource(
        "bbc-sport", "BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml",
        "sports", 0.85, False,
    ),
    RSSSource(
        "bbc-health", "BBC Health", "https://feeds.bbci.co.uk/news/health/rss.xml",
        "health", 0.85, False,
    ),
)


def enabled_sources() -> list[RSSSource]:
    return [source for source in RSS_SOURCES if source.enabled]
