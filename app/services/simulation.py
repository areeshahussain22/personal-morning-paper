from __future__ import annotations

import csv
import json
import random
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.repositories.database import Database, to_db_time
from app.repositories.profile_repository import ProfileRepository
from app.services.learning import LearningProcessor, position_factor
from app.services.source_registry import enabled_sources


@dataclass(frozen=True)
class Persona:
    name: str
    topics: list[str]
    sub_interests: list[str]
    tags: list[str]
    preferences: dict
    true_affinities: dict[str, float]
    llm_editor: bool
    seed: int


def load_personas(path: Path | str = "config/personas.yaml") -> list[Persona]:
    try:
        import yaml
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except ImportError:
        raise RuntimeError("PyYAML is required to load config/personas.yaml")
    return [
        Persona(
            name=item["name"], topics=item["onboarding"]["topics"],
            sub_interests=item["onboarding"].get("sub_interests", []),
            tags=item["onboarding"].get("tags", []),
            preferences=item["onboarding"].get("preferences", {}),
            true_affinities=item["true_affinities"], llm_editor=bool(item.get("llm_editor", False)),
            seed=int(item["seed"]),
        )
        for item in raw["personas"]
    ]


def metric_summary(db: Database, user_id: str, edition_id: str, affinities: dict[str, float]) -> dict:
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT e.type, e.position, a.topic FROM events e
               JOIN articles a ON a.article_id=e.article_id
               WHERE e.user_id=? AND e.edition_id=?""", (user_id, edition_id)
        )]
    seen = [row for row in rows if row["type"] == "impression_seen"]
    clicks = [row for row in rows if row["type"] == "click"]
    top_topics = {topic for topic, value in affinities.items() if value >= 0.6}
    clicked_positions = [row["position"] for row in clicks if row["position"] is not None]
    true_top = [row for row in seen if row["topic"] in top_topics]
    return {
        "seen": len(seen),
        "clicks": len(clicks),
        "click_through_rate": len(clicks) / len(seen) if seen else 0.0,
        "average_clicked_position": sum(clicked_positions) / len(clicked_positions) if clicked_positions else None,
        "top5_hit_rate": sum(1 for row in clicks if (row["position"] or 999) <= 5) / len(clicks) if clicks else 0.0,
        "true_top_topic_share": len(true_top) / len(seen) if seen else 0.0,
    }


class SimulationRunner:
    def __init__(self, source_database: Database, output_dir: Path | str = "out/sim"):
        self.source_database = source_database
        self.settings = get_settings()
        self.output_dir = Path(output_dir)

    def _isolated_database(self) -> Database:
        target = self.output_dir / "sim.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        database = Database(target)
        database.initialize()
        with self.source_database.connect() as source, database.connect() as dest:
            for table in ("sources", "articles", "article_topics", "article_embeddings", "article_clusters", "archive_snapshots"):
                columns = [row["name"] for row in source.execute(f"PRAGMA table_info({table})")]
                rows = source.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
                if rows:
                    placeholders = ",".join("?" for _ in columns)
                    dest.executemany(f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                                     [tuple(row) for row in rows])
        with database.connect() as connection:
            has_articles = connection.execute("SELECT 1 FROM articles LIMIT 1").fetchone()
        if not has_articles:
            self._seed_pool(database)
        return database

    @staticmethod
    def _seed_pool(db: Database) -> None:
        topics = ["technology_ai", "sports", "politics_government", "health", "science_research", "business_markets", "world"]
        now = datetime.now(timezone.utc)
        with db.connect() as connection:
            for topic in topics:
                source_id = f"sim-{topic}"
                connection.execute(
                    "INSERT OR IGNORE INTO sources(source_id,name,feed_url,topic,reliability_score,updated_at) VALUES(?,?,?,?,?,?)",
                    (source_id, f"Simulation {topic}", f"https://example.invalid/{topic}", topic, 0.8, to_db_time(now)),
                )
                for index in range(6):
                    article_id = f"{source_id}-{index}"
                    connection.execute(
                        """INSERT OR IGNORE INTO articles
                           (article_id,title,original_url,canonical_url,source_id,source_name,description,
                            published_at,image_url,topic,first_ingested_at,last_updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (article_id, f"{topic.replace('_', ' ').title()} story {index}",
                         f"https://example.invalid/{article_id}", f"https://example.invalid/{article_id}",
                         source_id, f"Simulation {topic}", f"About {topic}", to_db_time(now),
                         None, topic, to_db_time(now), to_db_time(now)),
                    )

    def _articles_for_day(self, db: Database, day: str, cycle: bool, rng: random.Random) -> list[dict]:
        with db.connect() as connection:
            snapshots = [dict(row) for row in connection.execute(
                "SELECT * FROM archive_snapshots ORDER BY as_of"
            )]
        selected = next((row for row in snapshots if row["as_of"][:10] == day), None)
        if selected is None and cycle and snapshots:
            selected = snapshots[rng.randrange(len(snapshots))]
        if selected:
            articles = json.loads(selected["articles_json"])
            if selected["as_of"][:10] != day:
                for article in articles:
                    article["article_id"] = f"{article['article_id']}-{day}"
                    article["canonical_url"] = f"{article['canonical_url']}#sim-{day}"
                    article["published_at"] = f"{day}T12:00:00+00:00"
                    with db.connect() as connection:
                        source = connection.execute(
                            "SELECT 1 FROM sources WHERE source_id=?", (article["source_id"],)
                        ).fetchone()
                        if source:
                            columns = [
                                "article_id", "title", "original_url", "canonical_url", "source_id",
                                "source_name", "description", "published_at", "image_url", "topic",
                                "first_ingested_at", "last_updated_at", "publication_date_issue",
                            ]
                            values = [article.get(column) for column in columns]
                            connection.execute(
                                f"INSERT OR REPLACE INTO articles ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                values,
                            )
            return articles
        with db.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM articles ORDER BY topic, article_id"
            )]

    def run(self, days: int, persona_name: str = "all", seed: int = 42, cycle: bool = False) -> dict:
        db = self._isolated_database()
        personas = [p for p in load_personas() if persona_name == "all" or p.name == persona_name]
        with db.connect() as connection:
            available = list(dict.fromkeys(row["as_of"][:10] for row in connection.execute(
                "SELECT as_of FROM archive_snapshots ORDER BY as_of"
            )))
        if not available:
            available = [(datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat() for i in range(days, 0, -1)]
        days_run = available[:days] if len(available) >= days else available
        if cycle and len(days_run) < days:
            days_run = [(available[i % len(available)]) for i in range(days)]
        repo = ProfileRepository(db)
        all_metrics: list[dict] = []
        for persona in personas:
            rng = random.Random(seed + persona.seed)
            weights = {topic: 3.0 for topic in persona.topics}
            user_id = repo.create_user(
                f"simulated-{persona.name}", weights, {}, [], [1.0] * 64, "hashed",
                persona.sub_interests, persona.tags, persona.preferences,
            )
            for day in days_run:
                articles = self._articles_for_day(db, day, cycle, rng)
                articles = [article for article in articles if article.get("topic") in persona.true_affinities or article.get("topic")]
                scored = sorted(
                    articles,
                    key=lambda article: (weights.get(article.get("topic"), 0) + rng.random() * 0.01),
                    reverse=True,
                )[:10]
                items = []
                result = {"edition_date": day, "layout_source": "code", "lead_id": scored[0]["article_id"] if scored else "", "sections": [], "items": []}
                for position, article in enumerate(scored, 1):
                    result["items"].append({
                        "article_id": article["article_id"], "position": position,
                        "selection_group": "regular", "headline": article["title"],
                        "summary": article.get("description") or article["title"],
                        "summary_source": "snippet", "reason_code": "simulation",
                        "reason_text": "Selected by simulated recommendation", "score": 0.0,
                        "score_components": {}, "section": article.get("topic", "news"),
                    })
                edition_id = repo.save_generated_edition(user_id, day, result, result["items"], "code", None, None, {})
                for position, article in enumerate(scored, 1):
                    examined = rng.random() < position_factor(position)
                    if not examined:
                        continue
                    repo.record_event(user_id, "impression_seen", "web", article["article_id"], edition_id, None, position)
                    affinity = persona.true_affinities.get(article.get("topic"), 0.05)
                    if rng.random() < affinity:
                        repo.record_event(user_id, "click", "web", article["article_id"], edition_id, None, position)
                        seconds = rng.randint(35, 120) if affinity >= 0.5 else rng.randint(1, 8)
                        repo.record_event(user_id, "return", "web", article["article_id"], edition_id, seconds, position,
                                         {"seconds_away": seconds})
                    elif affinity < 0.15 and rng.random() < 0.2:
                        repo.record_event(user_id, "dislike", "web", article["article_id"], edition_id, None, position)
                LearningProcessor(db).process_user(user_id)
                metrics = metric_summary(db, user_id, edition_id, persona.true_affinities)
                with db.connect() as connection:
                    connection.execute("UPDATE editions SET metrics_json=?, result_json=? WHERE edition_id=?",
                                       (json.dumps(metrics), json.dumps({**result, "metrics": metrics}), edition_id))
                state = repo.learning_state(user_id)
                with db.connect() as connection:
                    connection.execute("INSERT OR REPLACE INTO learning_snapshots VALUES (?,?,?,?,?)",
                                       (persona.name, day, json.dumps(state["topic_weights"]), json.dumps(state["topic_stats"]), json.dumps(metrics)))
                all_metrics.append({"persona": persona.name, "day": day, **metrics})
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "summary.json").write_text(json.dumps({"days": days_run, "cycle": cycle, "metrics": all_metrics}, indent=2), encoding="utf-8")
        with (self.output_dir / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["persona", "day", "seen", "clicks", "click_through_rate", "average_clicked_position", "top5_hit_rate", "true_top_topic_share"])
            writer.writeheader()
            writer.writerows(all_metrics)
        return {"days": days_run, "cycle": cycle, "metrics": all_metrics, "database": str(db.path), "llm_calls": 0}
