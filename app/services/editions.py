from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date
from typing import Any

from app.models.llm import ArticleSummaryBatch, EditorOutput
from app.models.recommendation import RecommendationResult, ScoredArticle
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.llm import LLMClient, LLMUnavailable, LLMValidationError
from app.services.recommendation import RecommendationService


def _clean_snippet(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:2])[:240].strip()


def _all_items(result: RecommendationResult) -> list[tuple[str, ScoredArticle]]:
    return [
        (group, item)
        for group, values in (
            ("must_know", result.must_know),
            ("exploration", result.exploration),
            ("regular", result.regular),
        )
        for item in values
    ]


class EditionService:
    def __init__(
        self,
        database: Database,
        recommendation: RecommendationService,
        llm_client: LLMClient | None = None,
    ):
        self.database = database
        self.database.initialize()
        self.recommendation = recommendation
        self.llm_client = llm_client
        self.profiles = ProfileRepository(database)

    def _summary_rows(self, article_ids: set[str]) -> dict[str, dict[str, Any]]:
        if not article_ids:
            return {}
        marks = ",".join("?" for _ in article_ids)
        with self.database.connect() as db:
            rows = db.execute(
                f"SELECT * FROM articles WHERE article_id IN ({marks})", tuple(article_ids)
            ).fetchall()
        return {row["article_id"]: dict(row) for row in rows}

    async def ensure_summaries(
        self, selected: list[ScoredArticle], batch_size: int = 20
    ) -> tuple[dict[str, dict[str, Any]], str | None, str | None]:
        rows = self._summary_rows({item.article["article_id"] for item in selected})
        pending = [row for row in rows.values() if not row.get("summary")]
        provider = model = None
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
            generated: dict[str, ArticleSummary] = {}
            if self.llm_client is not None:
                try:
                    result = await self.llm_client.generate_structured(
                        "article_summaries",
                        "Summarize each supplied article. Article ids must be preserved exactly.",
                        [
                            {
                                "id": row["article_id"],
                                "text": f"Headline: {row['title']}\nSnippet: {row.get('description') or ''}",
                            }
                            for row in batch
                        ],
                        "Return one ArticleSummary for each supplied article as a JSON array.",
                        ArticleSummaryBatch,
                        supplied_ids={row["article_id"] for row in batch},
                    )
                    generated = {item.id: item for item in result.value.items}
                    provider, model = result.metadata.provider, result.metadata.model
                except (LLMUnavailable, ValueError):
                    generated = {}
            with self.database.connect() as db:
                for row in batch:
                    item = generated.get(row["article_id"])
                    if item is None:
                        summary, source = _clean_snippet(row.get("description")) or row["title"][:240], "snippet"
                        item_topic, item_provider, item_model = row["topic"], None, None
                    else:
                        summary, source = item.summary, "llm"
                        item_topic, item_provider, item_model = item.topic.value, provider, model
                    db.execute(
                        """UPDATE articles SET summary = ?, summary_source = ?,
                           summary_provider = ?, summary_model = ? WHERE article_id = ?""",
                        (summary, source, item_provider, item_model, row["article_id"]),
                    )
                    row.update(
                        {
                            "summary": summary,
                            "summary_source": source,
                            "summary_provider": item_provider,
                            "summary_model": item_model,
                            "topic": item_topic,
                        }
                    )
        return self._summary_rows(set(rows)), provider, model

    def _code_layout(self, selected: list[tuple[str, ScoredArticle]], rows: dict[str, dict]) -> dict:
        ordered = sorted(selected, key=lambda pair: pair[1].score, reverse=True)
        groups: dict[str, list[tuple[str, ScoredArticle]]] = defaultdict(list)
        for group, item in ordered:
            topic = item.topics[0] if item.topics else item.article.get("topic", "general")
            groups[topic].append((group, item))
        sections = []
        for topic, values in sorted(groups.items(), key=lambda pair: -sum(i.score for _, i in pair[1])):
            sections.append(
                {
                    "name": topic,
                    "article_ids": [i.article["article_id"] for _, i in values],
                    "headlines": {i.article["article_id"]: i.article["title"].strip() for _, i in values},
                    "why_lines": {i.article["article_id"]: i.reason_text for _, i in values},
                }
            )
        return {"lead_id": ordered[0][1].article["article_id"] if ordered else "", "sections": sections}

    def _validate_editor(
        self, output: EditorOutput, selected: list[tuple[str, ScoredArticle]]
    ) -> None:
        ids = {item.article["article_id"] for _, item in selected}
        output_ids = [article_id for section in output.sections for article_id in section.article_ids]
        if set(output_ids) != ids or len(output_ids) != len(ids):
            raise ValueError("editor output must contain every selected article exactly once")
        top_ids = {item.article["article_id"] for _, item in sorted(selected, key=lambda pair: -pair[1].score)[:5]}
        if output.lead_id not in top_ids:
            raise ValueError("editor lead must be among the five highest-scoring stories")
        for section in output.sections:
            if set(section.headlines) != set(section.article_ids) or set(section.why_lines) != set(section.article_ids):
                raise ValueError("editor maps must match section article ids")

    async def generate(
        self, user_id: str, edition_date: str | date, force: bool = False, use_llm: bool = True
    ) -> dict:
        edition_date = edition_date.isoformat() if isinstance(edition_date, date) else edition_date
        existing = self.profiles.edition_for_date(user_id, edition_date)
        if existing and not force:
            return existing
        started = time.perf_counter()
        profile = self.profiles.get_preferences(user_id)
        if profile is None:
            raise LookupError("User not found")
        recommendation = self.recommendation.preview(user_id, profile)
        selected = _all_items(recommendation)
        rows, _, _ = await self.ensure_summaries([item for _, item in selected])
        selected_ids = {item.article["article_id"] for _, item in selected}
        selected = [(group, item) for group, item in selected if item.article["article_id"] in selected_ids]
        layout = self._code_layout(selected, rows)
        layout_source, layout_provider, layout_model = "code", None, None
        if use_llm and self.llm_client is not None and selected:
            blocks = [
                {
                    "id": item.article["article_id"],
                    "text": f"Headline: {item.article['title']}\nSummary: {rows[item.article['article_id']].get('summary') or ''}\n"
                    f"Score: {item.score}\nReason code: {item.reason_code}\nGroup: {group}",
                }
                for group, item in selected
            ]
            try:
                result = await self.llm_client.generate_structured(
                    "edition_editor",
                    "Arrange the supplied stories without adding, dropping, or changing their meaning.",
                    blocks,
                    "Return EditorOutput. Use every supplied id exactly once. Why-lines may only rephrase supplied reason codes.",
                    EditorOutput,
                    supplied_ids=selected_ids,
                )
                self._validate_editor(result.value, selected)
                layout = result.value.model_dump()
                layout_source = "llm"
                layout_provider, layout_model = result.metadata.provider, result.metadata.model
            except (LLMUnavailable, LLMValidationError, ValueError):
                pass
        selected_by_id = {item.article["article_id"]: (group, item) for group, item in selected}
        ordered_ids = [
            article_id
            for section in layout["sections"]
            for article_id in section["article_ids"]
        ]
        if layout["lead_id"] in ordered_ids:
            ordered_ids.remove(layout["lead_id"])
            ordered_ids.insert(0, layout["lead_id"])
        items = []
        position = 0
        section_by_id = {
            article_id: section["name"]
            for section in layout["sections"]
            for article_id in section["article_ids"]
        }
        for article_id in ordered_ids:
            group, item = selected_by_id[article_id]
            position += 1
            row = rows[article_id]
            items.append(
                {
                    "article_id": article_id,
                    "position": position,
                    "selection_group": group,
                    "headline": next(
                        section["headlines"][article_id]
                        for section in layout["sections"]
                        if article_id in section["article_ids"]
                    ),
                    "summary": row.get("summary") or _clean_snippet(row.get("description")),
                    "summary_source": row.get("summary_source") or "snippet",
                    "summary_provider": row.get("summary_provider"),
                    "summary_model": row.get("summary_model"),
                    "reason_code": item.reason_code,
                    "reason_text": next(
                        section["why_lines"][article_id]
                        for section in layout["sections"]
                        if article_id in section["article_ids"]
                    ),
                    "score": item.score,
                    "score_components": item.components,
                    "section": section_by_id[article_id],
                }
            )
        result = {
            "edition_date": edition_date,
            "layout_source": layout_source,
            "layout_provider": layout_provider,
            "layout_model": layout_model,
            "lead_id": layout["lead_id"],
            "sections": layout["sections"],
            "items": items,
        }
        timings = {"total": int((time.perf_counter() - started) * 1000)}
        result["stage_timings"] = timings
        edition_id = self.profiles.save_generated_edition(
            user_id, edition_date, result, items, layout_source, layout_provider, layout_model, timings, force
        )
        result["edition_id"] = edition_id
        return result
