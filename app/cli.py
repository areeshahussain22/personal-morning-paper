from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.models.llm import InterestSummary
from app.repositories.database import Database
from app.services.llm import LLMClient, ProviderConfig, LLMUnavailable


def build_client() -> LLMClient:
    settings = get_settings()
    providers = {
        "gemini": ProviderConfig("gemini", settings.gemini_model, settings.gemini_api_key, "https://generativelanguage.googleapis.com"),
        "groq": ProviderConfig("groq", settings.groq_model, settings.groq_api_key, "https://api.groq.com/openai/v1"),
        "openrouter": ProviderConfig("openrouter", settings.openrouter_model, settings.openrouter_api_key, "https://openrouter.ai/api/v1"),
        "ollama": ProviderConfig("ollama", settings.ollama_model, None, "http://localhost:11434"),
    }
    return LLMClient(
        Database(settings.database_path), list(settings.llm_provider_order), providers,
        timeout_seconds=settings.llm_timeout_seconds, max_retries=settings.llm_max_retries,
        concurrency_limit=settings.llm_concurrency_limit,
        min_provider_interval=settings.llm_min_provider_interval,
    )


async def llm_check() -> int:
    try:
        async with build_client() as client:
            result = await client.generate_structured(
                "diagnostic",
                "Return a short diagnostic response.",
                [],
                "Return exactly one short sentence confirming the structured LLM client works.",
                InterestSummary,
            )
        print(f"provider={result.metadata.provider}")
        print(f"model={result.metadata.model}")
        print(f"latency_ms={result.metadata.latency_ms}")
        print(f"attempts={result.metadata.attempts}")
        return 0
    except LLMUnavailable as exc:
        print(f"LLM unavailable: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["llm-check"])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(llm_check()))


if __name__ == "__main__":
    main()
