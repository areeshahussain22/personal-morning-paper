import asyncio
import argparse

from app.api.ingestion import build_services


async def main(create_snapshot: bool = True) -> None:
    service, archive = build_services()
    summary = await service.ingest()
    print(summary.__dict__)
    if summary.feeds_failed == summary.feeds_attempted:
        raise SystemExit("All RSS feeds failed; no successful ingestion occurred.")
    if create_snapshot:
        print(archive.create_snapshot())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-snapshot", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(not args.no_snapshot))
