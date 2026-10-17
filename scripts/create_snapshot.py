from app.api.ingestion import build_services


def main() -> None:
    _, archive = build_services()
    print(archive.create_snapshot())


if __name__ == "__main__":
    main()
