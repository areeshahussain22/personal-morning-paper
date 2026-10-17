from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
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
                "source_weights": source_weights,
                "selected_sub_interests": selected_sub_interests or [],
                "interest_tags": interest_tags or [],
                "long_vector": vector,
                "short_vector": vector,
                "embedder_name": embedder_name,
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
        db.executemany("INSERT INTO user_topic_preferences (user_id, topic, weight, updated_at) VALUES (?, ?, ?, ?)",
                       [(user_id, key, float(value), to_db_time(utc_now())) for key, value in topics.items()])
        db.executemany("INSERT INTO user_source_preferences (user_id, source_id, weight, updated_at) VALUES (?, ?, ?, ?)",
                       [(user_id, key, float(value), to_db_time(utc_now())) for key, value in sources.items()])
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
            topics = db.execute("SELECT topic, weight, updated_at FROM user_topic_preferences WHERE user_id = ?", (user_id,)).fetchall()
            sources = db.execute("SELECT source_id, weight, updated_at FROM user_source_preferences WHERE user_id = ?", (user_id,)).fetchall()
            muted = db.execute("SELECT topic FROM user_muted_topics WHERE user_id = ?", (user_id,)).fetchall()
            settings = db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
            return {
                **dict(user),
                "topic_weights": {row["topic"]: row["weight"] for row in topics},
                "source_weights": {row["source_id"]: row["weight"] for row in sources},
                "topic_updated_at": {row["topic"]: row["updated_at"] for row in topics},
                "source_updated_at": {row["source_id"]: row["updated_at"] for row in sources},
                "muted_topics": [row["topic"] for row in muted],
                "vector_embedder": user["vector_embedder"],
                "vector_dimension": user["vector_dimension"],
                "settings": dict(settings) if settings else {},
            }

    def save_interest_summary(self, user_id: str, text: str, source: str) -> bool:
        with self.database.connect() as db:
            cursor = db.execute(
                "UPDATE users SET interest_summary=?, interest_summary_source=?, interest_summary_updated_at=? WHERE user_id=?",
                (text, source, to_db_time(utc_now()), user_id),
            )
        return cursor.rowcount > 0

    def reset_profile(self, user_id: str) -> bool:
        profile = self.get_profile(user_id)
        if profile is None:
            return False
        baseline = json.loads(profile["settings"].get("onboarding_baseline_json", "{}"))
        with self.database.connect() as db:
            self._replace_preferences(
                db, user_id, baseline.get("topic_weights", {}),
                baseline.get("source_weights", {}), [],
            )
            db.execute(
                "UPDATE users SET long_vector=?, short_vector=?, interest_summary=NULL, interest_summary_source=NULL WHERE user_id=?",
                (json.dumps(baseline.get("long_vector")) if baseline.get("long_vector") else None,
                 json.dumps(baseline.get("short_vector")) if baseline.get("short_vector") else None, user_id),
            )
            db.execute("DELETE FROM user_topic_stats WHERE user_id=?", (user_id,))
            db.execute("UPDATE events SET processed_at=NULL WHERE user_id=?", (user_id,))
        return True

    def delete_user(self, user_id: str) -> bool:
        with self.database.connect() as db:
            exists = db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not exists:
                return False
            db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        return True

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

    def render_edition(self, user_id: str, edition_date: str) -> dict | None:
        result = self.edition_for_date(user_id, edition_date)
        if result is None:
            return None
        ids = [item["article_id"] for item in result.get("items", [])]
        if not ids:
            result["render_items"] = []
            return result
        marks = ",".join("?" for _ in ids)
        with self.database.connect() as db:
            rows = db.execute(
                f"""SELECT a.article_id, a.source_id, a.source_name, a.original_url,
                           a.image_url, a.published_at, a.topic, s.reliability_score, s.is_paywalled
                    FROM articles a JOIN sources s ON s.source_id=a.source_id
                    WHERE a.article_id IN ({marks})""", ids
            ).fetchall()
            covered = db.execute(
                f"""SELECT c1.article_id, a2.source_name
                    FROM article_clusters c1
                    JOIN article_clusters c2 ON c1.cluster_id=c2.cluster_id
                    JOIN articles a2 ON a2.article_id=c2.article_id
                    WHERE c1.article_id IN ({marks}) AND c2.article_id != c1.article_id""", ids
            ).fetchall()
        details = {row["article_id"]: dict(row) for row in rows}
        outlets: dict[str, list[str]] = {}
        for row in covered:
            outlets.setdefault(row["article_id"], []).append(row["source_name"])
        render_items = []
        for item in result["items"]:
            detail = details.get(item["article_id"], {})
            enriched = {**item, **detail}
            enriched["edition_id"] = result["edition_id"]
            enriched["other_outlets"] = sorted(set(outlets.get(item["article_id"], [])))
            score = detail.get("reliability_score", 0)
            enriched["reliability_label"] = "high" if score >= 0.85 else "medium" if score >= 0.65 else "lower"
            enriched["out_token"] = self.get_or_create_token(
                user_id, item["article_id"], result["edition_id"], item["position"], detail.get("source_id", ""), "web"
            )
            render_items.append(enriched)
        result["render_items"] = render_items
        return result

    def get_or_create_token(
        self, user_id: str, article_id: str, edition_id: str, position: int,
        source_id: str, token_source: str = "web",
    ) -> str:
        lookup_source_id = source_id if token_source == "web" else f"{source_id}:{token_source}"
        with self.database.connect() as db:
            row = db.execute(
                """SELECT token FROM link_tokens
                   WHERE user_id=? AND article_id=? AND edition_id=? AND position=?
                     AND source_id=? AND token_source=?""",
                (user_id, article_id, edition_id, position, lookup_source_id, token_source),
            ).fetchone()
            if row:
                return row["token"]
            token = secrets.token_urlsafe(32)
            db.execute(
                """INSERT INTO link_tokens
                   (token,user_id,article_id,edition_id,position,source_id,token_source,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (token, user_id, article_id, edition_id, position, lookup_source_id, token_source, to_db_time(utc_now())),
            )
            return token

    def link_target(self, token: str) -> str | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT a.original_url FROM link_tokens t JOIN articles a ON a.article_id=t.article_id WHERE t.token=?",
                (token,),
            ).fetchone()
        return row["original_url"] if row else None

    def token_details(self, token: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                """SELECT token, user_id, article_id, edition_id, position, source_id, token_source,
                          a.original_url
                   FROM link_tokens t JOIN articles a ON a.article_id=t.article_id
                   WHERE t.token=?""", (token,)
            ).fetchone()
        return dict(row) if row else None

    def record_event(
        self, user_id: str, event_type: str, source: str, article_id: str | None = None,
        edition_id: str | None = None, value: float | None = None,
        position: int | None = None, extra: dict | None = None,
    ) -> bool:
        with self.database.connect() as db:
            if event_type == "impression_seen":
                existing = db.execute(
                    """SELECT 1 FROM events WHERE user_id=? AND edition_id=? AND article_id=?
                       AND type=? LIMIT 1""",
                    (user_id, edition_id, article_id, event_type),
                ).fetchone()
                if existing:
                    return False
            db.execute(
                """INSERT INTO events
                   (user_id, article_id, edition_id, type, value, position, source, extra_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, article_id, edition_id, event_type, value, position, source,
                 json.dumps(extra or {}), to_db_time(utc_now())),
            )
        return True

    def event_allowed_for_edition(
        self, user_id: str, article_id: str | None, edition_id: str | None
    ) -> bool:
        if article_id is None and edition_id is None:
            return True
        with self.database.connect() as db:
            if edition_id is None:
                return db.execute(
                    "SELECT 1 FROM editions e JOIN edition_items i ON i.edition_id=e.edition_id "
                    "WHERE e.user_id=? AND i.article_id=? LIMIT 1", (user_id, article_id)
                ).fetchone() is not None
            if article_id is None:
                return db.execute(
                    "SELECT 1 FROM editions WHERE user_id=? AND edition_id=?", (user_id, edition_id)
                ).fetchone() is not None
            return db.execute(
                "SELECT 1 FROM editions e JOIN edition_items i ON i.edition_id=e.edition_id "
                "WHERE e.user_id=? AND e.edition_id=? AND i.article_id=?",
                (user_id, edition_id, article_id),
            ).fetchone() is not None

    def event_count_since(self, user_id: str, seconds: int) -> int:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS count FROM events WHERE user_id=? AND created_at >= ?",
                (user_id, to_db_time(utc_now() - timedelta(seconds=seconds))),
            ).fetchone()
        return int(row["count"])

    def click_recorded_recently(self, user_id: str, token: str, seconds: int) -> bool:
        with self.database.connect() as db:
            return db.execute(
                """SELECT 1 FROM events WHERE user_id=? AND type='click'
                   AND extra_json LIKE ? AND created_at >= ? LIMIT 1""",
                (user_id, f'%"token": "{token}"%', to_db_time(utc_now() - timedelta(seconds=seconds))),
            ).fetchone() is not None

    def set_pdf_status(self, edition_id: str, status: str, path: str | None = None) -> None:
        with self.database.connect() as db:
            db.execute(
                "UPDATE editions SET pdf_status=?, pdf_path=?, pdf_rendered_at=? WHERE edition_id=?",
                (status, path, to_db_time(utc_now()) if status == "ready" else None, edition_id),
            )

    def edition_pdf_metadata(self, user_id: str, edition_date: str) -> dict | None:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT edition_id, pdf_status, pdf_path, pdf_rendered_at FROM editions "
                "WHERE user_id=? AND edition_date=?", (user_id, edition_date)
            ).fetchone()
        return dict(row) if row else None

    def learning_state(self, user_id: str) -> dict | None:
        profile = self.get_profile(user_id)
        if profile is None:
            return None
        with self.database.connect() as db:
            stats = db.execute(
                "SELECT topic, views, clicks, updated_at FROM user_topic_stats WHERE user_id=?",
                (user_id,),
            ).fetchall()
        long_vector = json.loads(profile["long_vector"]) if profile["long_vector"] else []
        short_vector = json.loads(profile["short_vector"]) if profile["short_vector"] else []
        norm = lambda values: sum(float(value) ** 2 for value in values) ** 0.5
        return {
            "user_id": user_id,
            "topic_weights": profile["topic_weights"],
            "source_weights": profile["source_weights"],
            "topic_stats": {row["topic"]: dict(row) for row in stats},
            "vector_norms": {"long": norm(long_vector), "short": norm(short_vector)},
            "last_update": max(
                [v for v in profile["topic_updated_at"].values() if v]
                + [v for v in profile["source_updated_at"].values() if v]
                or [None]
            ),
        }

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
                old_pdf = db.execute("SELECT pdf_path FROM editions WHERE edition_id=?", (existing["edition_id"],)).fetchone()
                if old_pdf and old_pdf["pdf_path"]:
                    Path(old_pdf["pdf_path"]).unlink(missing_ok=True)
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
