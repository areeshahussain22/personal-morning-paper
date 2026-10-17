from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.onboarding import fallback_tags


def test_tag_fallback_is_deterministic_and_bounded() -> None:
    tags = fallback_tags("Follow the New York team, climate research, and robotics!")
    assert "new york" in tags
    assert len(tags) <= 10
    assert all(tag == tag.lower() for tag in tags)


def test_onboarding_creates_settings_vectors_cookie_and_status(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "onboarding.db"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "hashed")
    client = TestClient(app)
    response = client.post(
        "/api/onboarding",
        json={
            "selected_topics": ["technology_ai"],
            "selected_sub_interests": ["robotics"],
            "interest_tags": ["women's football"],
            "depth": "long",
            "stories_per_edition": 18,
            "surprise_level": "high",
            "timezone": "Asia/Karachi",
            "delivery_time": "06:30",
            "display_name": "<Reader>",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    user_id = payload["user_id"]
    assert client.get("/api/me").json()["user_id"] == user_id
    profile = ProfileRepository(Database(tmp_path / "onboarding.db")).get_profile(user_id)
    assert profile is not None
    assert profile["topic_weights"] == {"technology_ai": 3.0, "robotics": 2.0, "women's football": 2.0}
    assert profile["vector_dimension"] == 64
    assert profile["settings"]["edition_size"] == 18
    assert profile["settings"]["exploration_floor"] == 0.25
    status = client.get(f"/api/users/{user_id}/editions/{date.today().isoformat()}/status")
    assert status.status_code == 200
    assert status.json()["status"] in {"queued", "running", "ready", "failed"}
    page = client.get("/")
    assert page.status_code == 200
    assert "<Reader>" not in page.text
    assert "&lt;Reader&gt;" not in page.text


def test_tampered_session_cookie_is_rejected() -> None:
    client = TestClient(app)
    client.cookies.set("morning_paper_session", "tampered")
    assert client.get("/api/me").status_code == 401


def test_onboarding_validation_errors(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "invalid.db"))
    response = TestClient(app).post(
        "/api/onboarding",
        json={"selected_topics": ["not-a-topic"], "stories_per_edition": 9},
    )
    assert response.status_code == 422
