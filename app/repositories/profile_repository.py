from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.repositories.database import Database, from_db_time, to_db_time, utc_now


class ProfileRepository:
    def __init__(self, database: Database):
        self.database = database
        self.database.initialize()

    def create_user(
        self, name: str, topic_weights: dict, source_weights: dict, muted_topics: list[str],
        vector: list[float] | None = None, embedder_name: str | None = None,
        selected_sub_interests: list[str] | None = None, interest_tags: list[str] | None = None,
        settings: dict | None = None,
    ) -> str:
        user_id = uuid4().hex
        with self.database.connect() as db:
            db.execute(
                """INSERT INTO users
                   (user_id, name, created_at, editions_read, long_vector, short_vector, vector_embedder, vector_dimension)
                   VALUES (?, ?, ?, 0, ?, ?, ?, ?)""",
                (user_id, name, to_db_time(utc_now()), json.dumps(vector) if vector else None,
                 json.dumps(vector) if vector else None, embedder_name, len(vector) if vector else None),
            )
            self._replace_preferences(db, user_id, topic_weights, source_weights, muted_topics)
            profile_settings = settings or {}
            baseline = {
                "topic_weights": topic_weights,
                "selected_sub_interests": selected_sub_interests or [],
                "interest_tags": interest_tags or [],
            }
            db.execute(
                """INSERT INTO user_settings
                   (user_id, depth, edition_size, surprise_level, exploration_floor, timezone,
                    delivery_time, display_name, onboarding_baseline_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    profile_settings.get("depth", "standard"),
                    profile_settings.get("edition_size", 10),
                    profile_settings.get("surprise_level", "medium"),
                    profile_settings.get("exploration_floor", 0.15),
                    profile_settings.get("timezone", "UTC"),
                    profile_settings.get("delivery_time", "07:00"),
                    profile_settings.get("display_name") or name,
                    json.dumps(baseline),
                ),
            )
        return user_id

    def _replace_preferences(self, db: Any, user_id: str, topics: dict, sources: dict, muted: list[str]) -> None:
        db.execute("DELETE FROM user_topic_preferences WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM user_source_preferences WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM user_muted_topics WHERE user_id = ?", (user_id,))
        db.executemany("INSERT INTO user_topic_preferences VALUES (?, ?, ?)",
                       [(user_id, key, float(value)) for key, value in topics.items()])
        db.executemany("INSERT INTO user_source_preferences VALUES (?, ?, ?)",
                       [(user_id, key, float(value)) for key, value in sources.items()])
        db.executemany("INSERT INTO user_muted_topics VALUES (?, ?)", [(user_id, topic) for topic in muted])

    def update_preferences(self, user_id: str, topics: dict, sources: dict, muted: list[str]) -> bool:
        with self.database.connect() as db:
            if db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
                return False
            self._replace_preferences(db, user_id, topics, sources, muted)
        return True

    def set_vectors(self, user_id: str, vector: list[float], embedder_name: str) -> bool:
        with self.database.connect() as db:
            cursor = db.execute(
                """UPDATE users SET long_vector = ?, short_vector = ?, vector_embedder = ?,
                   vector_dimension = ? WHERE user_id = ?""",
                (json.dumps(vector), json.dumps(vector), embedder_name, len(vector), user_id),
            )
        return cursor.rowcount > 0

    def get_profile(self, user_id: str) -> dict | None:
        with self.database.connect() as db:
            user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user is None:
                return None
            topics = db.execute("SELECT topic, weight FROM user_topic_preferences WHERE user_id = ?", (user_id,)).fetchall()
            sources = db.execute("SELECT source_id, weight FROM user_source_preferences WHERE user_id = ?", (user_id,)).fetchall()
            muted = db.execute("SELECT topic FROM user_muted_topics WHERE user_id = ?", (user_id,)).fetchall()
            settings = db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return {
                **dict(user),
                "topic_weights": {row["topic"]: row["weight"] for row in topics},
                "source_weights": {row["source_id"]: row["weight"] for row in sources},
                "muted_topics": [row["topic"] for row in muted],
                "vector_embedder": user["vector_embedder"],
                "vector_dimension": user["vector_dimension"],
                "settings": dict(settings) if settings else {},
            }

    def get_preferences(self, user_id: str):
        profile = self.get_profile(user_id)
        if profile is None:
            return None
        from app.models.recommendation import ProfilePreferences
        return ProfilePreferences(
            topic_weights=profile["topic_weights"],
            source_weights=profile["source_weights"],
            muted_topics=set(profile["muted_topics"]),
            editions_read=profile["editions_read"],
            long_vector=json.loads(profile["long_vector"]) if profile["long_vector"] else None,
            short_vector=json.loads(profile["short_vector"]) if profile["short_vector"] else None,
            embedder_name=profile["vector_embedder"],
            vector_dimension=profile["vector_dimension"],
            edition_size=profile["settings"].get("edition_size", 10),
            exploration_floor=profile["settings"].get("exploration_floor", 0.15),
        )

    def update_settings(self, user_id: str, settings: dict) -> bool:
        with self.database.connect() as db:
            cursor = db.execute(
                """UPDATE user_settings SET depth=?, edition_size=?, surprise_level=?,
                   exploration_floor=?, timezone=?, delivery_time=?, display_name=?
                   WHERE user_id=?""",
                (
                    settings["depth"], settings["edition_size"], settings["surprise_level"],
                    settings["exploration_floor"], settings["timezone"], settings["delivery_time"],
                    settings.get("display_name"), user_id,
                ),
            )
        return cursor.rowcount > 0

    def set_generation_status(
        self, user_id: str, edition_date: str, status: str, stage: str, error: str | None = None
    ) -> None:
        with self.database.connect() as db:
            db.execute(
                """INSERT INTO edition_generation_status
                   (user_id, edition_date, status, stage, error, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, edition_date) DO UPDATE SET status=excluded.status,
                   stage=excluded.stage, error=excluded.error, updated_at=excluded.updated_at""",
                (user_id, edition_date, status, stage, error, to_db_time(utc_now())),
            )

    def generation_status(self, user_id: str, edition_date: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT * FROM edition_generation_status WHERE user_id=? AND edition_date=?",
                (user_id, edition_date),
            ).fetchone()
        return dict(row) if row else None

    def save_edition(self, user_id: str, result: dict) -> str:
        edition_id = uuid4().hex
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO editions (edition_id, user_id, created_at, result_json) VALUES (?, ?, ?, ?)",
                (edition_id, user_id, to_db_time(utc_now()), json.dumps(result)),
            )
            for group in ("must_know", "exploration", "regular"):
                for item in result[group]:
                    db.execute("INSERT INTO edition_articles VALUES (?, ?, ?, ?)",
                               (edition_id, item["article"]["article_id"], group, item["reason_code"]))
            db.execute("UPDATE users SET editions_read = editions_read + 1 WHERE user_id = ?", (user_id,))
        return edition_id

    def displayed_article_ids(self, user_id: str, editions: int = 7) -> set[str]:
        with self.database.connect() as db:
            rows = db.execute(
                """SELECT ea.article_id FROM edition_articles ea JOIN editions e ON e.edition_id = ea.edition_id
                   WHERE e.user_id = ? ORDER BY e.created_at DESC LIMIT ?""", (user_id, editions)
            ).fetchall()
            return {row["article_id"] for row in rows}

    def latest_edition(self, user_id: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT edition_id, result_json, created_at FROM editions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        result["edition_id"] = row["edition_id"]
        result["created_at"] = row["created_at"]
        return result

    def edition_for_date(self, user_id: str, edition_date: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT edition_id, result_json, created_at, edition_date FROM editions "
                "WHERE user_id = ? AND edition_date = ?",
                (user_id, edition_date),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        result.update(
            {
                "edition_id": row["edition_id"],
                "created_at": row["created_at"],
                "edition_date": row["edition_date"],
            }
        )
        return result

    def list_editions(self, user_id: str) -> list[dict]:
        with self.database.connect() as db:
            rows = db.execute(
                "SELECT edition_id, edition_date, created_at, layout_source, result_json "
                "FROM editions WHERE user_id = ? ORDER BY COALESCE(edition_date, created_at) DESC",
                (user_id,),
            ).fetchall()
        return [
            {
                "edition_id": row["edition_id"],
                "edition_date": row["edition_date"],
                "created_at": row["created_at"],
                "layout_source": row["layout_source"],
                "result": json.loads(row["result_json"]),
            }
            for row in rows
        ]

    def save_generated_edition(
        self,
        user_id: str,
        edition_date: str,
        result: dict,
        items: list[dict],
        layout_source: str,
        layout_provider: str | None,
        layout_model: str | None,
        stage_timings: dict[str, int],
        force: bool = False,
    ) -> str:
        edition_id = uuid4().hex
        with self.database.connect() as db:
            existing = db.execute(
                "SELECT edition_id FROM editions WHERE user_id = ? AND edition_date = ?",
                (user_id, edition_date),
            ).fetchone()
            if existing and not force:
                return existing["edition_id"]
            if existing:
                db.execute("DELETE FROM editions WHERE edition_id = ?", (existing["edition_id"],))
                db.execute("UPDATE users SET editions_read = MAX(0, editions_read - 1) WHERE user_id = ?", (user_id,))
            db.execute(
                """INSERT INTO editions
                   (edition_id, user_id, created_at, result_json, edition_date, layout_source,
                    layout_provider, layout_model, stage_timings_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edition_id,
                    user_id,
                    to_db_time(utc_now()),
                    json.dumps(result),
                    edition_date,
                    layout_source,
                    layout_provider,
                    layout_model,
                    json.dumps(stage_timings),
                ),
            )
            for item in items:
                db.execute(
                    """INSERT INTO edition_items
                       (edition_id, article_id, position, is_lead, selection_group, headline,
                        summary, reason_code, reason_text, score, score_components_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        edition_id,
                        item["article_id"],
                        item["position"],
                        int(item["position"] == 1),
                        item["selection_group"],
                        item["headline"],
                        item["summary"],
                        item["reason_code"],
                        item["reason_text"],
                        item["score"],
                        json.dumps(item["score_components"]),
                    ),
                )
                db.execute(
                    "INSERT INTO edition_articles VALUES (?, ?, ?, ?)",
                    (edition_id, item["article_id"], item["selection_group"], item["reason_code"]),
                )
            db.execute("UPDATE users SET editions_read = editions_read + 1 WHERE user_id = ?", (user_id,))
        return edition_id
