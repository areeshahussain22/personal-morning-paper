from __future__ import annotations

import re
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.topics import TOPICS

ModelT = TypeVar("ModelT", bound=BaseModel)


def reject_markup_or_url(value: str) -> str:
    if re.search(r"<[^>]+>|https?://|www\.", value, re.IGNORECASE):
        raise ValueError("text must not contain HTML or URLs")
    return value


class ArticleTopic(str, Enum):
    technology_ai = "technology_ai"
    science_research = "science_research"
    world = "world"
    business_markets = "business_markets"
    sports = "sports"
    health = "health"


class ArticleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=120)
    headline: str = Field(min_length=1, max_length=90)
    summary: str = Field(min_length=1, max_length=240)
    topic: ArticleTopic

    _safe_headline = field_validator("headline")(reject_markup_or_url)
    _safe_summary = field_validator("summary")(reject_markup_or_url)


class EditorSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    article_ids: list[str] = Field(max_length=20)
    headlines: dict[str, str] = Field(max_length=20)
    why_lines: dict[str, str] = Field(max_length=20)

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        return reject_markup_or_url(value)

    @field_validator("headlines", "why_lines")
    @classmethod
    def safe_text_maps(cls, values: dict[str, str]) -> dict[str, str]:
        return {key: reject_markup_or_url(value) for key, value in values.items()}


class EditorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: str = Field(min_length=1, max_length=120)
    sections: list[EditorSection] = Field(min_length=1, max_length=10)


class InterestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=400)

    @field_validator("text")
    @classmethod
    def max_words_and_safe_text(cls, value: str) -> str:
        if len(value.split()) > 60:
            raise ValueError("text must contain at most 60 words")
        return reject_markup_or_url(value)


class OnboardingTags(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(max_length=10)

    @field_validator("tags")
    @classmethod
    def safe_tags(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) > 40:
                raise ValueError("tag must contain at most 40 characters")
            reject_markup_or_url(value)
        return values


class LLMMetadata(BaseModel):
    provider: str
    model: str
    latency_ms: int
    attempts: int


class LLMResult(Generic[ModelT]):
    def __init__(self, value: ModelT, metadata: LLMMetadata):
        self.value = value
        self.metadata = metadata


def allowed_topics() -> list[str]:
    return [topic.name for topic in TOPICS]
