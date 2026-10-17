from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

from app.models.recommendation import ProfilePreferences, RecommendationResult, ScoredArticle
from app.repositories.database import Database, from_db_time, to_db_time, utc_now
from app.services.embeddings import Embedder, cosine_similarity
from app.services.topics import TOPICS, assign_topics_with_embedder


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_article(
    article: dict,
    profile: ProfilePreferences,
    embedding: list[float] | None,
    cluster_size: int,
    reliability: float,
    age_hours: float,
    topics: Iterable[str],
    article_embedder: str | None = None,
) -> tuple[float, dict[str, float]]:
    topic_list = list(topics)
    topic_weight = max((profile.topic_weights.get(topic, 0.0) for topic in topic_list), default=0.0)
    T = math.tanh(topic_weight / 4)
    E = 0.6 * cosine_similarity(
        profile.long_vector, embedding, profile.embedder_name, article_embedder
    ) + 0.4 * cosine_similarity(
        profile.short_vector, embedding, profile.embedder_name, article_embedder
    )
    source_weight = profile.source_weights.get(article.get("source_id"), 0.0)
    S = clamp(math.tanh(source_weight / 4), -0.3, 0.3)
    C = min(1.0, math.log2(max(1, cluster_size)) / 3)
    F = math.exp(-max(0.0, age_hours) / 18)
    reliability = clamp(reliability, 0.0, 1.0)
    score = (0.40 * T + 0.35 * E + 0.10 * S + 0.15 * C) * F * (0.5 + 0.5 * reliability)
    return score, {"T": T, "E": E, "S": S, "C": C, "F": F, "reliability": reliability}


def exploration_share(editions_read: int, floor: float = 0.15) -> float:
    return max(floor, 0.40 - 0.05 * max(0, editions_read))


def title_similarity(left: str, right: str) -> float:
    a = set(re.findall(r"[a-z0-9]+", left.lower()))
    b = set(re.findall(r"[a-z0-9]+", right.lower()))
    return len(a & b) / max(1, len(a | b))


class RecommendationService:
    def __init__(
        self, database: Database, freshness_hours: int = 48, topic_threshold: float = 0.12,
        dimensions: int = 64, embedder: Embedder | None = None,
        cluster_similarity_threshold: float = 0.72, cluster_window_hours: int = 36,
        topic_secondary_margin: float = 0.04,
    ):
        self.database = database
        self.freshness_hours = freshness_hours
        self.topic_threshold = topic_threshold
        self.dimensions = dimensions
        self.embedder = embedder
        self.cluster_similarity_threshold = cluster_similarity_threshold
        self.cluster_window_hours = cluster_window_hours
        self.topic_secondary_margin = topic_secondary_margin
        self.database.initialize()

    def _prepare_article(self, row: dict) -> tuple[dict, list[str], list[float]]:
        article = dict(row)
        with self.database.connect() as db:
            cached = db.execute(
                "SELECT vector_json, embedder_name, dimensions FROM article_embeddings WHERE article_id = ?",
                (article["article_id"],),
            ).fetchone()
            cached_topics = db.execute(
                "SELECT topic, confidence FROM article_topics WHERE article_id = ? ORDER BY confidence DESC",
                (article["article_id"],),
            ).fetchall()
        if cached is not None and (
            self.embedder is None or (
                cached["embedder_name"] == self.embedder.name
                and cached["dimensions"] == self.embedder.dimension
            )
        ):
            article["_embedder_name"] = cached["embedder_name"]
            topics = [item["topic"] for item in cached_topics[:2]] or [article["topic"]]
            return article, topics, json.loads(cached["vector_json"])
        if self.embedder is None:
            return article, [], []
        text = f"{article['title']} {article.get('description') or ''}"
        embedding = self.embedder.embed_text(text)
        assigned = assign_topics_with_embedder(
            text, self.topic_threshold, 2, self.embedder, self.topic_secondary_margin
        )
        topics = [topic for topic, _ in assigned]
        with self.database.connect() as db:
            db.execute("DELETE FROM article_topics WHERE article_id = ?", (article["article_id"],))
            db.executemany("INSERT INTO article_topics VALUES (?, ?, ?)",
                           [(article["article_id"], topic, confidence) for topic, confidence in assigned])
            db.execute(
                """INSERT INTO article_embeddings
                   (article_id, dimensions, vector_json, updated_at, embedder_name)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(article_id) DO UPDATE SET dimensions=excluded.dimensions,
                   vector_json=excluded.vector_json, updated_at=excluded.updated_at,
                   embedder_name=excluded.embedder_name""",
                (article["article_id"], len(embedding), json.dumps(embedding), to_db_time(utc_now()), self.embedder.name),
            )
        article["_embedder_name"] = self.embedder.name
        return article, topics, embedding

    def _eligible_rows(self, profile: ProfilePreferences, user_id: str) -> list[dict]:
        cutoff = utc_now() - timedelta(hours=self.freshness_hours)
        displayed = self._displayed_ids(user_id)
        with self.database.connect() as db:
            rows = db.execute(
                """SELECT a.*, s.reliability_score FROM articles a JOIN sources s ON s.source_id = a.source_id
                   WHERE a.published_at IS NOT NULL AND a.published_at >= ? AND a.published_at <= ?
                   AND s.reliability_score >= 0.3""",
                (to_db_time(cutoff), to_db_time(utc_now())),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if item["article_id"] not in displayed:
                result.append(item)
        return result

    def _displayed_ids(self, user_id: str) -> set[str]:
        with self.database.connect() as db:
            return {row["article_id"] for row in db.execute(
                """SELECT ea.article_id FROM edition_articles ea JOIN editions e ON e.edition_id = ea.edition_id
                   WHERE e.user_id = ? ORDER BY e.created_at DESC LIMIT 7""", (user_id,)
            )}

    def preview(self, user_id: str, profile: ProfilePreferences, edition_size: int = 10) -> RecommendationResult:
        candidates: list[ScoredArticle] = []
        now = utc_now()
        for raw in self._eligible_rows(profile, user_id):
            article, topics, embedding = self._prepare_article(raw)
            if not embedding or (
                profile.embedder_name
                and article.get("_embedder_name") != profile.embedder_name
            ):
                continue
            if set(topics) & profile.muted_topics:
                continue
            cluster_size = self._cluster_size(article, topics)
            published = from_db_time(article["published_at"])
            age_hours = (now - published).total_seconds() / 3600 if published else 999
            score, components = score_article(
                article, profile, embedding, cluster_size, raw["reliability_score"],
                age_hours, topics, article.get("_embedder_name"),
            )
            topic = topics[0] if topics else article["topic"]
            code = "topic_interest" if profile.topic_weights.get(topic, 0) else "top_story"
            text = f"Because you read about {topic}" if code == "topic_interest" else "Top story today"
            candidates.append(ScoredArticle(article, score, components, tuple(topics), code, text))
        candidates.sort(key=lambda item: item.score, reverse=True)
        must_know = self._must_know(candidates)
        selected_ids = {item.article["article_id"] for item in must_know}
        remaining = [item for item in candidates if item.article["article_id"] not in selected_ids]
        edition_size = min(edition_size, profile.edition_size)
        exploration_count = min(
            len(remaining), round(edition_size * exploration_share(profile.editions_read, profile.exploration_floor))
        )
        outside = [item for item in remaining if not set(item.topics) & set(sorted(profile.topic_weights, key=profile.topic_weights.get, reverse=True)[:3])]
        exploration = [self._with_reason(item, "exploration", f"Something new: {item.topics[0] if item.topics else item.article['topic']}") for item in outside[:exploration_count]]
        selected_ids.update(item.article["article_id"] for item in exploration)
        regular = self._mmr([item for item in remaining if item.article["article_id"] not in selected_ids], edition_size - len(must_know) - len(exploration), selected_ids)
        return RecommendationResult(must_know, exploration, regular)

    def embed_all_articles(self, reembed: bool = False) -> int:
        if self.embedder is None:
            raise ValueError("An embedder is required for article enrichment")
        with self.database.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM articles")]
        pending = []
        for row in rows:
            with self.database.connect() as db:
                existing = db.execute(
                    "SELECT embedder_name, dimensions FROM article_embeddings WHERE article_id = ?",
                    (row["article_id"],),
                ).fetchone()
            if not reembed and existing and existing["embedder_name"] == self.embedder.name and existing["dimensions"] == self.embedder.dimension:
                continue
            pending.append(row)
        for row in pending:
            self._prepare_article(row)
        self.cluster_articles()
        return len(pending)

    def cluster_articles(self) -> None:
        if self.embedder is None:
            raise ValueError("An embedder is required for clustering")
        threshold = self.cluster_similarity_threshold
        with self.database.connect() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT a.*, e.vector_json, e.embedder_name FROM articles a JOIN article_embeddings e ON e.article_id = a.article_id"
            )]
        for article in rows:
            published = from_db_time(article["published_at"])
            if not published:
                continue
            cluster_members = []
            for other in rows:
                other_published = from_db_time(other["published_at"])
                if other["article_id"] == article["article_id"] or not other_published:
                    continue
                if abs((published - other_published).total_seconds()) > self.cluster_window_hours * 3600:
                    continue
                similarity = cosine_similarity(
                    json.loads(article["vector_json"]), json.loads(other["vector_json"]),
                    article["embedder_name"], other["embedder_name"],
                )
                if similarity >= threshold or title_similarity(article["title"], other["title"]) >= 0.45:
                    cluster_members.append(other)
            members = [article, *cluster_members]
            cluster_id = min(item["article_id"] for item in members)
            source_count = len({item["source_id"] for item in members})
            with self.database.connect() as db:
                for member in members:
                    db.execute(
                        """INSERT INTO article_clusters (article_id, cluster_id, cluster_size)
                           VALUES (?, ?, ?) ON CONFLICT(article_id) DO UPDATE SET
                           cluster_id=excluded.cluster_id, cluster_size=excluded.cluster_size""",
                        (member["article_id"], cluster_id, source_count),
                    )

    def _cluster_size(self, article: dict, topics: list[str]) -> int:
        with self.database.connect() as db:
            row = db.execute(
                "SELECT cluster_size FROM article_clusters WHERE article_id = ?",
                (article["article_id"],),
            ).fetchone()
        return int(row["cluster_size"]) if row else 1

    def _must_know(self, candidates: list[ScoredArticle]) -> list[ScoredArticle]:
        ordered = sorted(candidates, key=lambda item: item.components["C"], reverse=True)
        chosen = []
        for candidate in ordered:
            if all(title_similarity(candidate.article["title"], other.article["title"]) < 0.45 for other in chosen):
                chosen.append(self._with_reason(candidate, "must_know", "Top story today"))
            if len(chosen) == min(2, len(candidates)):
                break
        return chosen

    def _mmr(self, candidates: list[ScoredArticle], count: int, selected_ids: set[str]) -> list[ScoredArticle]:
        selected: list[ScoredArticle] = []
        topic_counts: dict[str, int] = {}
        while candidates and len(selected) < max(0, count):
            best = max(candidates, key=lambda item: item.score - 0.3 * max(
                [title_similarity(item.article["title"], other.article["title"]) for other in selected] or [0.0]
            ))
            topic = best.topics[0] if best.topics else best.article["topic"]
            cap = max(1, math.ceil((len(selected) + count) * 0.4))
            under_cap = [
                item for item in candidates
                if topic_counts.get(item.topics[0] if item.topics else item.article["topic"], 0) < cap
            ]
            if under_cap:
                best = max(under_cap, key=lambda item: item.score - 0.3 * max(
                    [title_similarity(item.article["title"], other.article["title"]) for other in selected] or [0.0]
                ))
            selected.append(best)
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            candidates.remove(best)
        return selected

    @staticmethod
    def _with_reason(item: ScoredArticle, code: str, text: str) -> ScoredArticle:
        return ScoredArticle(item.article, item.score, item.components, item.topics, code, text)


def build_profile_vector(
    embedder: Embedder,
    topic_weights: dict[str, float],
    selected_sub_interests: list[str] | None = None,
    interest_tags: list[str] | None = None,
) -> list[float]:
    texts: list[str] = []
    weights: list[float] = []
    descriptions = {topic.name: topic.description for topic in TOPICS}
    for topic, weight in topic_weights.items():
        texts.append(descriptions.get(topic, topic))
        weights.append(float(weight))
    for value in selected_sub_interests or []:
        texts.append(value)
        weights.append(2.0)
    for value in interest_tags or []:
        texts.append(value)
        weights.append(2.0)
    if not texts:
        return [0.0] * embedder.dimension
    vectors = embedder.embed_texts(texts)
    average = [sum(weight * vector[index] for weight, vector in zip(weights, vectors))
               for index in range(len(vectors[0]))]
    norm = math.sqrt(sum(value * value for value in average))
    return [value / norm for value in average] if norm else average
