from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable


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
    tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
    matches = []
    for topic in TOPICS:
        overlap = len(tokens.intersection(topic.keywords))
        confidence = overlap / max(1, len(topic.keywords))
        if confidence >= threshold:
            matches.append((topic.name, min(1.0, confidence)))
    return sorted(matches, key=lambda item: (-item[1], item[0]))[:limit]


def embed_text(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine_similarity(left: Iterable[float] | None, right: Iterable[float] | None) -> float:
    if left is None or right is None:
        return 0.0
    left_values, right_values = list(left), list(right)
    if not left_values or len(left_values) != len(right_values):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left_values, right_values)) / (left_norm * right_norm)
