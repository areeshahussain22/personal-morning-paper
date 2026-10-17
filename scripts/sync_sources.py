from app.core.config import get_settings
from app.repositories.database import Database
from app.services.source_registry import enabled_sources


def main() -> None:
    database = Database(get_settings().database_path)
    for source in enabled_sources():
        database.upsert_source(source)
    print(f"Synced {len(enabled_sources())} enabled sources.")


if __name__ == "__main__":
    main()
