from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from app.repositories.database import Database
from app.services.simulation import SimulationRunner
from app.repositories.profile_repository import ProfileRepository
from app.core.config import get_settings
from app.services.pdf import build_pdf


def demo_database_path(output_dir: Path | str = "out/demo") -> Path:
    return Path(output_dir) / "sim.db"


def seed_demo(source_database: Database, output_dir: Path | str = "out/demo") -> dict:
    output = Path(output_dir)
    summary = output / "summary.json"
    if summary.exists() and demo_database_path(output).exists():
        return json.loads(summary.read_text(encoding="utf-8"))
    result = SimulationRunner(source_database, output).run(14, "all", 42, cycle=True)
    database = Database(demo_database_path(output))
    pdf_errors = []
    with database.connect() as connection:
        users = [row["user_id"] for row in connection.execute("SELECT user_id FROM users")]
    key_days = [result["days"][0], result["days"][-1]]
    pdf_root = output / "pdfs"
    for user_id in users:
        for day in key_days:
            try:
                generated = build_pdf(ProfileRepository(database), user_id, day, get_settings())
                target = pdf_root / user_id
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(generated, target / f"{day}.pdf")
            except Exception as exc:
                pdf_errors.append(f"{user_id}:{day}:{type(exc).__name__}")
    result["pdf_errors"] = pdf_errors
    return result


def demo_rows(database: Database) -> list[dict]:
    with database.connect() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT persona, day, metrics_json, topic_weights_json FROM learning_snapshots ORDER BY persona, day"
        )]


def demo_front_pages(database: Database) -> dict[str, list[dict]]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT u.name, e.edition_date, a.title AS headline FROM editions e "
            "JOIN users u ON u.user_id=e.user_id "
            "JOIN edition_items ei ON ei.edition_id=e.edition_id "
            "JOIN articles a ON a.article_id=ei.article_id "
            "WHERE u.name LIKE 'simulated-%' ORDER BY u.name, e.edition_date, ei.position"
        )
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["name"].removeprefix("simulated-"), []).append(dict(row))
        return {
            persona: [item for item in items if item["edition_date"] in {
                items[0]["edition_date"], items[-1]["edition_date"]
            }]
            for persona, items in grouped.items()
        }


def demo_stats(database: Database) -> dict:
    with database.connect() as connection:
        llm = [dict(row) for row in connection.execute(
            "SELECT COALESCE(provider, 'none') provider, purpose, COUNT(*) count FROM llm_calls GROUP BY provider, purpose"
        )]
        articles = connection.execute("SELECT COUNT(*) count FROM articles").fetchone()["count"]
        clusters = connection.execute("SELECT COUNT(DISTINCT cluster_id) count FROM article_clusters").fetchone()["count"]
        feeds = [row["source_name"] for row in connection.execute("SELECT DISTINCT source_name FROM articles ORDER BY source_name")]
        generation = [row["total"] for row in connection.execute(
            "SELECT AVG(json_extract(result_json, '$.stage_timings.total')) total FROM editions"
        ) if row["total"] is not None]
        cache_hits = connection.execute(
            "SELECT COUNT(*) count FROM llm_calls WHERE provider='cache'"
        ).fetchone()["count"]
    return {
        "llm_calls": llm, "articles": articles, "clusters": clusters, "feeds": feeds,
        "average_generation_ms": generation[0] if generation else 0,
        "summary_cache_hits": cache_hits,
    }


def export_demo(database: Database, output_dir: Path | str = "out/demo") -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows = demo_rows(database)
    with (output / "learning.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["persona", "day", "metrics_json", "topic_weights_json"])
        writer.writeheader()
        writer.writerows(rows)
    charts = []
    for persona in sorted({row["persona"] for row in rows}):
        points = [row for row in rows if row["persona"] == persona]
        for metric, label in (("click_through_rate", "CTR"), ("top5_hit_rate", "Top 5 hit rate")):
            line = " ".join(
                f"{40 + index * 55},{230 - int(json.loads(row['metrics_json']).get(metric, 0) * 180)}"
                for index, row in enumerate(points)
            )
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="260"><polyline fill="none" stroke="#0b7285" stroke-width="3" points="{line}"/><text x="20" y="25">{persona} {label}</text></svg>'
            path = output / f"{persona}-{metric}.svg"
            path.write_text(svg, encoding="utf-8")
            charts.append(str(path))
    return {"csv": str(output / "learning.csv"), "charts": charts}
