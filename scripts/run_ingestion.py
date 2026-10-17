import asyncio

from app.api.ingestion import build_services


async def main() -> None:
    service, archive = build_services()
    summary = await service.ingest()
    print(summary.__dict__)
    if summary.feeds_failed == summary.feeds_attempted:
        raise SystemExit("All RSS feeds failed; no successful ingestion occurred.")
    print(archive.create_snapshot())


if __name__ == "__main__":
    asyncio.run(main())
