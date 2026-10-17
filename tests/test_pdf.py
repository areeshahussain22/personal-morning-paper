from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services import pdf
from app.services.editions import EditionService
from app.services.embeddings import HashedEmbedder
from app.services.recommendation import RecommendationService
from tests.test_recommendation import seed_database


def test_ssrf_guard_rejects_private_and_unsupported_urls(monkeypatch) -> None:
    assert pdf._public_ip("localhost") is False
    assert pdf._public_ip("169.254.169.254") is False
    assert pdf.fetch_image("file:///secret", Settings(Path("db")), object()) is None


def test_pdf_renderer_writes_pdf_and_uses_pdf_tokens(tmp_path: Path, monkeypatch) -> None:
    database, user_id = seed_database(tmp_path / "pdf.db")
    service = EditionService(database, RecommendationService(database, embedder=HashedEmbedder()))
    result = asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))

    class FakeRenderer:
        def render(self, html, output_path, base_url):
            output_path.write_bytes(b"%PDF-1.7\nfixture")

    monkeypatch.setattr(pdf, "choose_renderer", lambda settings: FakeRenderer())
    monkeypatch.chdir(tmp_path)
    path = pdf.build_pdf(
        ProfileRepository(database), user_id, "2026-10-17", Settings(tmp_path / "pdf.db")
    )
    assert path.read_bytes().startswith(b"%PDF")
    with database.connect() as db:
        token = db.execute(
            "SELECT token_source FROM link_tokens WHERE edition_id=? AND token_source='pdf'",
            (result["edition_id"],),
        ).fetchone()
    assert token["token_source"] == "pdf"


def test_pdf_cache_and_force_invalidation(tmp_path: Path, monkeypatch) -> None:
    database, user_id = seed_database(tmp_path / "cache.db")
    service = EditionService(database, RecommendationService(database, embedder=HashedEmbedder()))
    asyncio.run(service.generate(user_id, "2026-10-17", use_llm=False))

    class FakeRenderer:
        calls = 0

        def render(self, html, output_path, base_url):
            self.calls += 1
            output_path.write_bytes(b"%PDF-1.7\nfixture")

    renderer = FakeRenderer()
    monkeypatch.setattr(pdf, "choose_renderer", lambda settings: renderer)
    monkeypatch.chdir(tmp_path)
    repo = ProfileRepository(database)
    settings = Settings(tmp_path / "cache.db")
    pdf.build_pdf(repo, user_id, "2026-10-17", settings)
    pdf.build_pdf(repo, user_id, "2026-10-17", settings)
    assert renderer.calls == 1
    with database.connect() as db:
        edition_id = db.execute("SELECT edition_id FROM editions").fetchone()["edition_id"]
        db.execute("UPDATE editions SET pdf_path=NULL WHERE edition_id=?", (edition_id,))
    pdf.build_pdf(repo, user_id, "2026-10-17", settings, force=True)
    assert renderer.calls == 2
