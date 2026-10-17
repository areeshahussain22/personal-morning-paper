import json
import pytest
from fastapi import HTTPException

from app.api.demo import require_demo
from app.repositories.database import Database
from app.services.demo import demo_rows, export_demo, seed_demo


def test_demo_seed_is_idempotent_and_exports(tmp_path):
    real = Database(tmp_path / "real.db")
    real.initialize()
    output = tmp_path / "demo"
    first = seed_demo(real, output)
    second = seed_demo(real, output)
    assert first["days"] == second["days"]
    exported = export_demo(Database(output / "sim.db"), output)
    assert (output / "learning.csv").exists()
    assert exported["charts"]
    assert all((output / "sim.db").exists() for _ in [0])


def test_demo_chart_rows_have_expected_shape(tmp_path):
    real = Database(tmp_path / "real.db")
    real.initialize()
    output = tmp_path / "demo"
    seed_demo(real, output)
    rows = demo_rows(Database(output / "sim.db"))
    assert rows
    assert {"persona", "day", "metrics_json", "topic_weights_json"} <= rows[0].keys()
    assert "click_through_rate" in json.loads(rows[0]["metrics_json"])


def test_demo_routes_are_gated(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    with pytest.raises(HTTPException) as exc_info:
        require_demo()
    assert exc_info.value.status_code == 404
