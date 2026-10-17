from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.core.config import Settings, get_settings
from app.repositories.database import Database, from_db_time, to_db_time, utc_now
from app.repositories.profile_repository import ProfileRepository
from app.services.embeddings import cosine_similarity


@dataclass(frozen=True)
class LearningConstants:
    decay: float = 0.97
    click: float = 1.0
    long_read: float = 0.5
    bounce: float = -0.4
    expand_summary: float = 0.3
    save: float = 2.0
    like: float = 2.0
    dislike: float = -2.0
    less_topic: float = -3.0
    seen_penalty: float = -0.1
    vector_long_rate: float = 0.04
    vector_short_rate: float = 0.20


def position_factor(position: int) -> float:
    return 1.0 / (1.0 + 0.25 * max(0, position - 1))


def normalize(values: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in values))
    return [value / length for value in values] if length else values


class LearningProcessor:
    def __init__(self, database: Database, settings: Settings | None = None,
                 constants: LearningConstants | None = None):
        self.database = database
        self.settings = settings or get_settings()
        self.constants = constants or LearningConstants(
            decay=self.settings.learning_decay,
        )
        self.database.initialize()

    def _decay(self, weight: float, updated_at: str | None, now: datetime) -> float:
        if not updated_at:
            return weight
        previous = from_db_time(updated_at)
        days = max(0.0, (now - previous).total_seconds() / 86400) if previous else 0
        return weight * self.constants.decay ** days

    def _signal(self, event: dict, has_click: bool) -> float | None:
        event_type = event["type"]
        if event_type == "return":
            seconds = float((json.loads(event["extra_json"]) or {}).get("seconds_away", event["value"] or 0))
            if seconds >= self.settings.learning_min_long_read_seconds and has_click:
                return self.constants.long_read
            if seconds <= self.settings.learning_bounce_seconds and has_click:
                return self.constants.bounce
            return None
        return {
            "click": self.constants.click,
            "expand_summary": self.constants.expand_summary,
            "save": self.constants.save,
            "like": self.constants.like,
            "dislike": self.constants.dislike,
            "less_topic": self.constants.less_topic,
        }.get(event_type)

    def _article_context(self, article_id: str) -> tuple[list[str], str | None, list[float] | None]:
        with self.database.connect() as db:
            article = db.execute("SELECT topic, source_id FROM articles WHERE article_id=?", (article_id,)).fetchone()
            topics = db.execute(
                "SELECT topic FROM article_topics WHERE article_id=? ORDER BY confidence DESC LIMIT 2", (article_id,)
            ).fetchall()
            embedding = db.execute(
                "SELECT vector_json, embedder_name FROM article_embeddings WHERE article_id=?", (article_id,)
            ).fetchone()
        if not article:
            return [], None, None
        return ([row["topic"] for row in topics] or [article["topic"]], article["source_id"],
                (json.loads(embedding["vector_json"]), embedding["embedder_name"]) if embedding else None)

    def _apply(self, user_id: str, event: dict, now: datetime) -> bool:
        if not event["article_id"]:
            return True
        topics, source_id, embedding_info = self._article_context(event["article_id"])
        if not topics or not source_id:
            return True
        with self.database.connect() as db:
            click = db.execute(
                "SELECT 1 FROM events WHERE user_id=? AND article_id=? AND type='click' AND created_at <= ?",
                (user_id, event["article_id"], event["created_at"]),
            ).fetchone() is not None
            signal = self._signal(event, click)
            if event["type"] == "impression_seen":
                edition = db.execute(
                    "SELECT edition_date, created_at FROM editions WHERE edition_id=? AND user_id=?",
                    (event["edition_id"], user_id),
                ).fetchone()
                if not edition:
                    return False
                edition_end = from_db_time(edition["created_at"])
                if edition["edition_date"] >= now.date().isoformat() and (
                    not edition_end
                    or now < edition_end + timedelta(hours=self.settings.learning_cutoff_hours)
                ):
                    return False
                clicked = db.execute(
                    "SELECT 1 FROM events WHERE user_id=? AND edition_id=? AND article_id=? AND type='click'",
                    (user_id, event["edition_id"], event["article_id"]),
                ).fetchone()
                if clicked:
                    return True
                signal = self.constants.seen_penalty
            if signal is None:
                return True
            position = event["position"] or 1
            adjusted = signal
            if signal > 0 and event["type"] in {"click", "save", "like", "expand_summary"}:
                adjusted = min(2.5, signal / position_factor(position))
            elif event["type"] == "less_topic":
                adjusted = signal
            elif event["type"] == "impression_seen":
                adjusted = signal * position_factor(position)
            for index, topic in enumerate(topics):
                factor = 0.5 if index else 1.0
                row = db.execute(
                    "SELECT weight, updated_at FROM user_topic_preferences WHERE user_id=? AND topic=?",
                    (user_id, topic),
                ).fetchone()
                weight = self._decay(row["weight"], row["updated_at"], now) if row else 0.0
                db.execute(
                    """INSERT INTO user_topic_preferences(user_id,topic,weight,updated_at) VALUES(?,?,?,?)
                       ON CONFLICT(user_id,topic) DO UPDATE SET weight=excluded.weight,updated_at=excluded.updated_at""",
                    (user_id, topic, max(-5, min(10, weight + factor * adjusted)), to_db_time(now)),
                )
            row = db.execute(
                "SELECT weight, updated_at FROM user_source_preferences WHERE user_id=? AND source_id=?",
                (user_id, source_id),
            ).fetchone()
            source_weight = self._decay(row["weight"], row["updated_at"], now) if row else 0.0
            db.execute(
                """INSERT INTO user_source_preferences(user_id,source_id,weight,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(user_id,source_id) DO UPDATE SET weight=excluded.weight,updated_at=excluded.updated_at""",
                (user_id, source_id, max(-5, min(10, source_weight + 0.3 * adjusted)), to_db_time(now)),
            )
            if embedding_info:
                self._update_vector(db, user_id, embedding_info, adjusted)
            topic = topics[0]
            stat = db.execute(
                "SELECT views, clicks, updated_at FROM user_topic_stats WHERE user_id=? AND topic=?",
                (user_id, topic),
            ).fetchone()
            old_views = self._decay(stat["views"], stat["updated_at"], now) if stat else 0.0
            old_clicks = self._decay(stat["clicks"], stat["updated_at"], now) if stat else 0.0
            db.execute(
                """INSERT INTO user_topic_stats(user_id,topic,views,clicks,updated_at) VALUES(?,?,?, ?,?)
                   ON CONFLICT(user_id,topic) DO UPDATE SET
                   views=views+excluded.views, clicks=clicks+excluded.clicks, updated_at=excluded.updated_at""",
                (user_id, topic, old_views + int(event["type"] == "impression_seen"),
                 old_clicks + int(event["type"] == "click"), to_db_time(now)),
            )
        return True

    def _update_vector(self, db, user_id: str, embedding_info, signal: float) -> None:
        if signal <= 0:
            return
        row = db.execute("SELECT long_vector,short_vector,vector_embedder FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row["long_vector"] or row["vector_embedder"] != embedding_info[1]:
            return
        article = embedding_info[0]
        long = json.loads(row["long_vector"])
        short = json.loads(row["short_vector"])
        amount = min(2.0, signal)
        def update(vector, rate):
            return normalize([(1 - rate * amount) * old + rate * amount * new for old, new in zip(vector, article)])
        db.execute("UPDATE users SET long_vector=?, short_vector=? WHERE user_id=?",
                   (json.dumps(update(long, self.constants.vector_long_rate)),
                    json.dumps(update(short, self.constants.vector_short_rate)), user_id))

    def process_user(self, user_id: str, dry_run: bool = False) -> dict:
        with self.database.connect() as db:
            events = [dict(row) for row in db.execute(
                "SELECT * FROM events WHERE user_id=? AND processed_at IS NULL ORDER BY created_at,id", (user_id,)
            )]
        before = ProfileRepository(self.database).get_profile(user_id)
        for event in events:
            ready = self._apply(user_id, event, utc_now())
            if not dry_run and ready:
                with self.database.connect() as db:
                    db.execute("UPDATE events SET processed_at=? WHERE id=?", (to_db_time(utc_now()), event["id"]))
        after = ProfileRepository(self.database).get_profile(user_id)
        return {"processed": len(events), "before": before["topic_weights"] if before else {}, "after": after["topic_weights"] if after else {}}

    def recompute_profile(self, user_id: str) -> dict:
        repo = ProfileRepository(self.database)
        profile = repo.get_profile(user_id)
        if not profile:
            raise LookupError("User not found")
        baseline = profile["settings"].get("onboarding_baseline_json", "{}")
        baseline = json.loads(baseline)
        with self.database.connect() as db:
            db.execute("DELETE FROM user_topic_preferences WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM user_source_preferences WHERE user_id=?", (user_id,))
            db.executemany("INSERT INTO user_topic_preferences(user_id,topic,weight,updated_at) VALUES(?,?,?,NULL)",
                           [(user_id, topic, weight) for topic, weight in baseline.get("topic_weights", {}).items()])
            db.executemany("INSERT INTO user_source_preferences(user_id,source_id,weight,updated_at) VALUES(?,?,?,NULL)",
                           [(user_id, source, weight) for source, weight in baseline.get("source_weights", {}).items()])
            db.execute("UPDATE events SET processed_at=NULL WHERE user_id=?", (user_id,))
            if baseline.get("long_vector"):
                db.execute("UPDATE users SET long_vector=?,short_vector=? WHERE user_id=?",
                           (json.dumps(baseline["long_vector"]), json.dumps(baseline["short_vector"]), user_id))
        return self.process_user(user_id)
