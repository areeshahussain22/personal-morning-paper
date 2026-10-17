import json
from base64 import b64encode
from itsdangerous import TimestampSigner
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_new_reader_lands_on_onboarding_and_can_sign_out() -> None:
    fresh_client = TestClient(app)
    response = fresh_client.get("/")
    assert response.status_code == 200
    assert "Set up your paper" in response.text
    assert "Personalize my paper" in response.text

    fresh_client.cookies.set("morning_paper_session", "signed-in-placeholder")
    logout_response = fresh_client.get("/logout", follow_redirects=False)
    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/"


def test_unknown_session_is_cleared_for_new_reader(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "new-reader.db"))
    fresh_client = TestClient(app)
    session_middleware = next(
        middleware for middleware in app.user_middleware
        if middleware.cls.__name__ == "SessionMiddleware"
    )
    session = b64encode(json.dumps({"user_id": "missing-reader"}).encode("utf-8"))
    cookie = TimestampSigner(str(session_middleware.kwargs["secret_key"])).sign(session).decode("utf-8")
    fresh_client.cookies.set("morning_paper_session", cookie)
    response = fresh_client.get("/")
    assert response.status_code == 200
    assert "Set up your paper" in response.text
    assert "morning_paper_session=null" in response.headers["set-cookie"]


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
