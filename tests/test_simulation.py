import json

from app.repositories.database import Database
from app.services.simulation import SimulationRunner, load_personas, metric_summary


def test_simulation_is_deterministic_and_isolated(tmp_path):
    real = Database(tmp_path / "real.db")
    real.initialize()
    first = SimulationRunner(real, tmp_path / "one").run(3, "featured", 42)
    second = SimulationRunner(real, tmp_path / "two").run(3, "featured", 42)
    assert first["metrics"] == second["metrics"]
    assert real.read_job_runs() == []
    assert (tmp_path / "one" / "metrics.csv").exists()


def test_simulation_cycle_is_labelled_when_reusing_days(tmp_path):
    database = Database(tmp_path / "real.db")
    database.initialize()
    result = SimulationRunner(database, tmp_path / "cycle").run(3, "health_science", 7, cycle=True)
    assert result["cycle"] is True
    assert len(result["days"]) == 3


def test_metric_summary_uses_stored_events(tmp_path):
    database = Database(tmp_path / "metrics.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            ("s", "S", "https://example.invalid/feed", "health", .8, 0, 1, "now"),
        )
        for index in range(2):
            connection.execute(
                """INSERT INTO articles(article_id,title,original_url,canonical_url,source_id,source_name,
                   topic,first_ingested_at,last_updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (f"a{index}", "title", f"https://example.invalid/{index}", f"https://example.invalid/{index}",
                 "s", "S", "health", "now", "now"),
            )
        connection.execute(
            "INSERT INTO users(user_id,name,created_at) VALUES(?,?,?)", ("u", "u", "now")
        )
        connection.execute(
            "INSERT INTO editions(edition_id,user_id,created_at,result_json,edition_date) VALUES(?,?,?,?,?)",
            ("e", "u", "now", "{}", "2026-01-01"),
        )
        connection.execute(
            "INSERT INTO events(user_id,article_id,edition_id,type,position,source,extra_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("u", "a0", "e", "impression_seen", 1, "web", "{}", "now"),
        )
        connection.execute(
            "INSERT INTO events(user_id,article_id,edition_id,type,position,source,extra_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("u", "a0", "e", "click", 1, "web", "{}", "now"),
        )
    metrics = metric_summary(database, "u", "e", {"health": .8})
    assert metrics["click_through_rate"] == 1.0
    assert metrics["top5_hit_rate"] == 1.0


def test_personas_use_existing_topics():
    names = {topic for persona in load_personas() for topic in persona.topics}
    assert "politics_government" not in names
    assert "technology_ai" in names
