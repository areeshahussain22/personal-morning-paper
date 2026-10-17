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
            return {
                **dict(user),
                "topic_weights": {row["topic"]: row["weight"] for row in topics},
                "source_weights": {row["source_id"]: row["weight"] for row in sources},
                "muted_topics": [row["topic"] for row in muted],
                "vector_embedder": user["vector_embedder"],
                "vector_dimension": user["vector_dimension"],
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
        )

    def save_edition(self, user_id: str, result: dict) -> str:
        edition_id = uuid4().hex
        with self.database.connect() as db:
            db.execute("INSERT INTO editions VALUES (?, ?, ?, ?)", (edition_id, user_id, to_db_time(utc_now()), json.dumps(result)))
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
