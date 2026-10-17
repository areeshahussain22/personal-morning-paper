from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProfilePreferences:
    topic_weights: dict[str, float] = field(default_factory=dict)
    source_weights: dict[str, float] = field(default_factory=dict)
    muted_topics: set[str] = field(default_factory=set)
    long_vector: list[float] | None = None
    short_vector: list[float] | None = None
    editions_read: int = 0


@dataclass(frozen=True)
class ScoredArticle:
    article: dict
    score: float
    components: dict[str, float]
    topics: tuple[str, ...]
    reason_code: str
    reason_text: str


@dataclass
class RecommendationResult:
    must_know: list[ScoredArticle] = field(default_factory=list)
    exploration: list[ScoredArticle] = field(default_factory=list)
    regular: list[ScoredArticle] = field(default_factory=list)

    def as_dict(self) -> dict:
        def serialize(item: ScoredArticle) -> dict:
            return {
                "article": item.article,
                "score": item.score,
                "score_components": item.components,
                "topics": item.topics,
                "reason_code": item.reason_code,
                "reason_text": item.reason_text,
            }
        return {
            "must_know": [serialize(item) for item in self.must_know],
            "exploration": [serialize(item) for item in self.exploration],
            "regular": [serialize(item) for item in self.regular],
        }
