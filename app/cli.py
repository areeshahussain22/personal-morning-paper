from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from app.core.config import get_settings
from app.models.llm import InterestSummary
from app.repositories.database import Database
from app.services.llm import LLMClient, ProviderConfig, LLMUnavailable
from app.services.editions import EditionService, _all_items
from app.services.recommendation import RecommendationService
from app.services.learning import LearningProcessor


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


async def llm_check(provider_name: str | None = None) -> int:
    settings = get_settings()
    if provider_name:
        configured = {
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
            "openrouter": settings.openrouter_api_key,
            "ollama": None,
        }.get(provider_name)
        model = {
            "gemini": settings.gemini_model,
            "groq": settings.groq_model,
            "openrouter": settings.openrouter_model,
            "ollama": settings.ollama_model,
        }.get(provider_name)
        if provider_name not in {"gemini", "groq", "openrouter", "ollama"}:
            print(f"unknown provider={provider_name}", file=sys.stderr)
            return 2
        print(f"provider={provider_name}")
        print(f"key_configured={'yes' if configured else 'no'}")
        print(f"model={model}")
        if provider_name != "ollama" and not configured:
            print("status=skipped")
            return 0
        order = [provider_name]
    else:
        order = None
    try:
        client_config = build_client()
        if order is not None:
            client_config.provider_order = order
        async with client_config as client:
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
        print("status=unavailable")
        print(f"http_status={exc.status if exc.status is not None else 'none'}")
        print(f"error={exc.error_message[:200]}")
        return 1


async def generate_edition(user_id: str, edition_date: str, use_llm: bool, force: bool) -> int:
    settings = get_settings()
    database = Database(settings.database_path)
    recommender = RecommendationService(
        database,
        freshness_hours=settings.freshness_hours,
        topic_threshold=settings.real_topic_match_threshold
        if settings.embedding_backend == "sentence_transformer"
        else settings.topic_match_threshold,
        dimensions=settings.embedding_dimensions,
    )
    client = build_client() if use_llm else None
    service = EditionService(database, recommender, client)
    if client is not None:
        async with client:
            result = await service.generate(user_id, edition_date, force, use_llm)
    else:
        result = await service.generate(user_id, edition_date, force, use_llm)
    print(f"edition_id={result['edition_id']}")
    print(f"layout_source={result['layout_source']}")
    print(f"items={len(result['items'])}")
    return 0


async def generate_all(use_llm: bool, force: bool) -> int:
    settings = get_settings()
    database = Database(settings.database_path)
    with database.connect() as db:
        user_ids = [row["user_id"] for row in db.execute("SELECT user_id FROM users")]
    service = EditionService(
        database,
        RecommendationService(
            database,
            freshness_hours=settings.freshness_hours,
            topic_threshold=settings.real_topic_match_threshold
            if settings.embedding_backend == "sentence_transformer"
            else settings.topic_match_threshold,
            dimensions=settings.embedding_dimensions,
        ),
        build_client() if use_llm else None,
    )
    selected = []
    for user_id in user_ids:
        profile = service.profiles.get_preferences(user_id)
        if profile is not None:
            selected.extend(item for _, item in _all_items(service.recommendation.preview(user_id, profile)))
    if selected:
        if service.llm_client is not None:
            async with service.llm_client:
                await service.ensure_summaries(selected)
        else:
            await service.ensure_summaries(selected)
    for user_id in user_ids:
        await generate_edition(user_id, date.today().isoformat(), use_llm, force)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["llm-check", "generate-edition", "generate-all", "process-events"])
    parser.add_argument("--user-id")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--provider", choices=["gemini", "groq", "openrouter", "ollama"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "llm-check":
        code = asyncio.run(llm_check(args.provider))
    elif args.command == "generate-edition":
        if not args.user_id:
            parser.error("--user-id is required for generate-edition")
        code = asyncio.run(generate_edition(args.user_id, args.date, not args.no_llm, args.force))
    elif args.command == "process-events":
        if not args.user_id:
            parser.error("--user-id is required for process-events")
        result = LearningProcessor(Database(get_settings().database_path)).process_user(args.user_id, args.dry_run)
        print(f"processed={result['processed']}")
        print(f"before={result['before']}")
        print(f"after={result['after']}")
        code = 0
    else:
        code = asyncio.run(generate_all(not args.no_llm, args.force))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
