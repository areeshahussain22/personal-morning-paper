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
    RSSSource("npr-news", "NPR News", "https://feeds.npr.org/1001/rss.xml", "world", 0.86, False),
    RSSSource("npr-world", "NPR World", "https://feeds.npr.org/1004/rss.xml", "world", 0.86, False),
    RSSSource("npr-science", "NPR Science", "https://feeds.npr.org/1007/rss.xml", "science_research", 0.86, False),
    RSSSource("npr-health", "NPR Health", "https://feeds.npr.org/1128/rss.xml", "health", 0.86, False),
    RSSSource("npr-business", "NPR Business", "https://feeds.npr.org/1019/rss.xml", "business_markets", 0.86, False),
    RSSSource("npr-technology", "NPR Technology", "https://feeds.npr.org/1014/rss.xml", "technology_ai", 0.86, False),
    RSSSource("guardian-world", "The Guardian World", "https://www.theguardian.com/world/rss", "world", 0.82, False),
    RSSSource("guardian-business", "The Guardian Business", "https://www.theguardian.com/business/rss", "business_markets", 0.82, False),
    RSSSource("guardian-tech", "The Guardian Technology", "https://www.theguardian.com/technology/rss", "technology_ai", 0.82, False),
    RSSSource("guardian-science", "The Guardian Science", "https://www.theguardian.com/science/rss", "science_research", 0.82, False),
    RSSSource("guardian-sport", "The Guardian Sport", "https://www.theguardian.com/sport/rss", "sports", 0.82, False),
    RSSSource("guardian-health", "The Guardian Health", "https://www.theguardian.com/society/health/rss", "health", 0.82, False),
    RSSSource("nyt-world", "The New York Times World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "world", 0.9, True),
    RSSSource("nyt-business", "The New York Times Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "business_markets", 0.9, True),
    RSSSource("nyt-technology", "The New York Times Technology", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml", "technology_ai", 0.9, True),
    RSSSource("nyt-science", "The New York Times Science", "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "science_research", 0.9, True),
    RSSSource("nyt-health", "The New York Times Health", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "health", 0.9, True),
    RSSSource("techcrunch", "TechCrunch", "https://techcrunch.com/feed/", "technology_ai", 0.83, False),
    RSSSource("ars-technica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "technology_ai", 0.84, False),
    RSSSource("the-verge", "The Verge", "https://www.theverge.com/rss/index.xml", "technology_ai", 0.8, False),
    RSSSource("wired", "WIRED", "https://www.wired.com/feed/rss", "technology_ai", 0.82, False),
    RSSSource("space-com", "Space.com", "https://www.space.com/feeds/all", "science_research", 0.78, False),
    RSSSource("science-daily", "ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml", "science_research", 0.76, False),
    RSSSource("espn-news", "ESPN News", "https://www.espn.com/espn/rss/news", "sports", 0.78, False),
    RSSSource("formula1", "Formula 1", "https://www.formula1.com/en/latest/all.xml", "sports", 0.86, False),
    RSSSource("cnbc", "CNBC Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "business_markets", 0.8, False),
    RSSSource("marketwatch", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "business_markets", 0.8, False),
    RSSSource("economist", "The Economist", "https://www.economist.com/the-world-this-week/rss.xml", "world", 0.9, True),
)


def enabled_sources() -> list[RSSSource]:
    return [source for source in RSS_SOURCES if source.enabled]
