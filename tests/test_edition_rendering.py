from __future__ import annotations

import json
import asyncio
import re
from base64 import b64encode
from pathlib import Path

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.editions import EditionService
from app.services.embeddings import HashedEmbedder
from app.services.recommendation import RecommendationService
from tests.test_recommendation import seed_database


def test_edition_page_renders_story_sections(tmp_path: Path, monkeypatch) -> None:
    database, user_id = seed_database(tmp_path / "edition-page.db")
    service = EditionService(
        database,
        RecommendationService(database, embedder=HashedEmbedder()),
    )
    edition = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))
    repository = ProfileRepository(database)
    monkeypatch.setattr(main, "_repo", lambda: repository)

    session_middleware = next(
        middleware for middleware in main.app.user_middleware
        if middleware.cls.__name__ == "SessionMiddleware"
    )
    session = b64encode(json.dumps({"user_id": user_id}).encode("utf-8"))
    cookie = TimestampSigner(str(session_middleware.kwargs["secret_key"])).sign(session).decode("utf-8")
    client = TestClient(main.app)
    client.cookies.set("morning_paper_session", cookie)

    response = client.get(f"/edition/{edition['edition_date']}")

    assert response.status_code == 200
    assert "Lead story" in response.text
    assert edition["items"][0]["headline"] in response.text
    assert "Previous papers" in response.text
    assert "Static sample previews only" in response.text
    pdf = tmp_path / "issue.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(main, "build_pdf", lambda *_args: pdf)
    token_match = re.search(r'href="/edition/2026-10-17/pdf\?token=([^"]+)"', response.text)
    assert token_match is not None

    download = TestClient(main.app).get(
        f"/edition/2026-10-17/pdf?token={token_match.group(1)}"
    )

    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")


def test_pdf_link_token_cannot_be_reused_for_another_edition(tmp_path: Path, monkeypatch) -> None:
    database, user_id = seed_database(tmp_path / "edition-page.db")
    service = EditionService(
        database,
        RecommendationService(database, embedder=HashedEmbedder()),
    )
    edition = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))
    repository = ProfileRepository(database)
    monkeypatch.setattr(main, "_repo", lambda: repository)
    session_middleware = next(
        middleware for middleware in main.app.user_middleware
        if middleware.cls.__name__ == "SessionMiddleware"
    )
    session = b64encode(json.dumps({"user_id": user_id}).encode("utf-8"))
    cookie = TimestampSigner(str(session_middleware.kwargs["secret_key"])).sign(session).decode("utf-8")
    client = TestClient(main.app)
    client.cookies.set("morning_paper_session", cookie)
    response = client.get(f"/edition/{edition['edition_date']}")
    token_match = re.search(r'href="/edition/2026-10-17/pdf\?token=([^"]+)"', response.text)
    assert token_match is not None

    rejected = TestClient(main.app).get(
        f"/edition/2026-10-18/pdf?token={token_match.group(1)}"
    )

    assert rejected.status_code == 401
