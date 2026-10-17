from __future__ import annotations

import re
from collections import Counter

from app.models.llm import OnboardingTags
from app.services.llm import LLMClient, LLMUnavailable, LLMValidationError

STOP_WORDS = {
    "about", "also", "and", "for", "from", "have", "into", "that", "the",
    "this", "with", "your", "want", "follow", "specific",
}


def fallback_tags(text: str) -> list[str]:
    words = [word.lower() for word in re.findall(r"[A-Za-z0-9]+", text)]
    candidates = [word for word in words if word not in STOP_WORDS and len(word) > 2]
    phrases = [
        f"{words[index]} {words[index + 1]}"
        for index in range(len(words) - 1)
        if words[index] not in STOP_WORDS
        and words[index + 1] not in STOP_WORDS
        and len(words[index]) > 2
        and len(words[index + 1]) > 2
    ]
    candidates.extend(phrases)
    return list(dict.fromkeys(candidates))[:10]


async def make_tags(text: str, client: LLMClient | None = None) -> list[str]:
    if not text.strip() or client is None:
        return fallback_tags(text)
    try:
        result = await client.generate_structured(
            "onboarding_tags",
            "Extract concise interest tags from the supplied text.",
            [{"id": "interest-text", "text": text}],
            "Return at most 10 useful tags. Do not include URLs or HTML.",
            OnboardingTags,
        )
        return result.value.tags
    except (LLMUnavailable, LLMValidationError, ValueError):
        return fallback_tags(text)
