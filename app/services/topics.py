from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.embeddings import Embedder, HashedEmbedder, cosine_similarity


@dataclass(frozen=True)
class Topic:
    name: str
    description: str
    keywords: tuple[str, ...]


TOPICS: tuple[Topic, ...] = (
    Topic("technology_ai", "Artificial intelligence, software, and technology", ("technology", "software", "ai", "artificial", "computer", "chip", "robot")),
    Topic("science_research", "Scientific discoveries and research", ("science", "research", "study", "space", "nasa", "climate", "health")),
    Topic("world", "International affairs, politics, and global events", ("world", "global", "international", "government", "war", "election", "president")),
    Topic("business_markets", "Business, finance, markets, and the economy", ("business", "market", "finance", "economy", "company", "stock", "trade")),
    Topic("sports", "Sport competitions, teams, and athletes", ("sport", "football", "soccer", "basketball", "tennis", "olympic", "team")),
    Topic("health", "Medicine, health, and wellbeing", ("health", "medical", "medicine", "doctor", "disease", "wellbeing", "fitness")),
)


def assign_topics(text: str, threshold: float = 0.12, limit: int = 2) -> list[tuple[str, float]]:
    return assign_topics_with_embedder(text, threshold, limit, HashedEmbedder())


def assign_topics_with_embedder(
    text: str,
    threshold: float = 0.12,
    limit: int = 2,
    embedder: Embedder | None = None,
) -> list[tuple[str, float]]:
    if embedder is not None and embedder.name != "hashed":
        article_vector = embedder.embed_text(text)
        topic_vectors = embedder.embed_texts([topic.description for topic in TOPICS])
        matches = [
            (topic.name, cosine_similarity(article_vector, vector, embedder.name, embedder.name))
            for topic, vector in zip(TOPICS, topic_vectors)
        ]
        return sorted(
            [(name, confidence) for name, confidence in matches if confidence >= threshold],
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    matches = []
    for topic in TOPICS:
        overlap = len(tokens.intersection(topic.keywords))
        confidence = overlap / max(1, len(topic.keywords))
        if confidence >= threshold:
            matches.append((topic.name, min(1.0, confidence)))
    return sorted(matches, key=lambda item: (-item[1], item[0]))[:limit]


def embed_text(text: str, dimensions: int = 64) -> list[float]:
    return HashedEmbedder(dimensions).embed_text(text)
