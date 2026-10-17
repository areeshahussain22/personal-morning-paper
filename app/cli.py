from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.models.llm import InterestSummary
from app.repositories.database import Database
from app.services.llm import LLMClient, ProviderConfig, LLMUnavailable
from app.services.editions import EditionService, _all_items
from app.services.recommendation import RecommendationService
from app.services.learning import LearningProcessor
from app.services.interest_summary import generate_interest_summary
from app.services.simulation import SimulationRunner
from app.services.demo import seed_demo, demo_database_path, export_demo


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


async def generate_all(use_llm: bool, force: bool, edition_date: str | None = None) -> int:
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
        await generate_edition(user_id, edition_date or date.today().isoformat(), use_llm, force)
    return 0


async def generate_summary(user_id: str, force: bool) -> int:
    client = build_client()
    async with client:
        result = await generate_interest_summary(
            Database(get_settings().database_path), user_id, client, force
        )
    print(result or "user not found")
    return 0 if result else 1


def simulate(days: int, persona: str, seed: int, cycle: bool, llm_featured: bool) -> int:
    settings = get_settings()
    result = SimulationRunner(Database(settings.database_path), Path("out/sim")).run(
        days, persona, seed, cycle
    )
    print(f"days={len(result['days'])}")
    print(f"cycle={result['cycle']}")
    print(f"llm_calls={result['llm_calls'] if llm_featured else 0}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["llm-check", "generate-edition", "generate-all", "process-events", "generate-summary", "scheduler", "run-once", "status", "simulate", "seed-demo", "export-demo"])
    parser.add_argument("--user-id")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--provider", choices=["gemini", "groq", "openrouter", "ollama"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--persona", default="all")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cycle", action="store_true")
    parser.add_argument("--llm-featured", action="store_true")
    parser.add_argument("--output-dir", default="out/demo")
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
    elif args.command == "generate-summary":
        if not args.user_id:
            parser.error("--user-id is required for generate-summary")
        code = asyncio.run(generate_summary(args.user_id, args.force))
    elif args.command == "scheduler":
        from app.services.scheduler import scheduler_main
        scheduler_main()
        code = 0
    elif args.command == "run-once":
        from app.services.scheduler import JobRunner
        runner = JobRunner(Database(get_settings().database_path))
        asyncio.run(runner.ingest_and_enrich())
        asyncio.run(runner.generate_due())
        runner.nightly_archive()
        code = 0
    elif args.command == "status":
        from app.services.scheduler import JobRunner
        runner = JobRunner(Database(get_settings().database_path))
        for run in runner.database.read_job_runs():
            print(json.dumps(run))
        code = 0
    elif args.command == "simulate":
        code = simulate(args.days, args.persona, args.seed, args.cycle, args.llm_featured)
    elif args.command == "seed-demo":
        result = seed_demo(Database(get_settings().database_path), args.output_dir)
        print(f"database={demo_database_path(args.output_dir)}")
        print(f"days={len(result['days'])}")
        code = 0
    elif args.command == "export-demo":
        database = Database(args.output_dir + "/sim.db")
        print(json.dumps(export_demo(database, args.output_dir)))
        code = 0
    else:
        code = asyncio.run(generate_all(not args.no_llm, args.force, args.date))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
