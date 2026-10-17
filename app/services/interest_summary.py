from __future__ import annotations

import json

from app.models.llm import InterestSummary
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.llm import LLMClient, LLMUnavailable, LLMValidationError


def fallback_summary(profile: dict, clicked: list[str], disliked: list[str]) -> str:
    topics = sorted(profile["topic_weights"], key=profile["topic_weights"].get, reverse=True)[:3]
    topic_text = ", ".join(topics) or "a broad mix of current events"
    if clicked:
        return f"You are most interested in {topic_text}. Recent reading suggests you value stories like {clicked[0]}."
    if disliked:
        return f"You are most interested in {topic_text}. You have recently shown less interest in {disliked[0]}."
    return f"You are most interested in {topic_text}. Your paper is learning from your reading choices."


async def generate_interest_summary(
    database: Database, user_id: str, client: LLMClient | None = None, force: bool = False
) -> str | None:
    repo = ProfileRepository(database)
    profile = repo.get_profile(user_id)
    if profile is None:
        return None
    if profile.get("interest_summary_source") == "user" and not force:
        return profile.get("interest_summary")
    with database.connect() as db:
        clicked = [row["title"] for row in db.execute(
            """SELECT a.title FROM events e JOIN articles a ON a.article_id=e.article_id
               WHERE e.user_id=? AND e.type='click' ORDER BY e.created_at DESC LIMIT 10""", (user_id,)
        )]
        disliked = [row["title"] for row in db.execute(
            """SELECT a.title FROM events e JOIN articles a ON a.article_id=e.article_id
               WHERE e.user_id=? AND e.type IN ('dislike','less_topic')
               ORDER BY e.created_at DESC LIMIT 10""", (user_id,)
        )]
    prompt_data = {
        "top_topics": sorted(profile["topic_weights"], key=profile["topic_weights"].get, reverse=True)[:8],
        "clicked_headlines": clicked,
        "disliked_headlines": disliked,
        "onboarding_tags": json.loads(profile["settings"].get("onboarding_baseline_json", "{}")).get("interest_tags", []),
    }
    text = None
    if client is not None:
        try:
            result = await client.generate_structured(
                "interest_summary",
                "Write a concise, neutral reader-interest summary from these topics and headlines. Do not mention names, ids, or identifiers.",
                [{"text": str(prompt_data)}],
                "Return a 2 to 3 sentence InterestSummary.",
                InterestSummary,
            )
            text = result.value.text
        except (LLMUnavailable, LLMValidationError, ValueError):
            text = None
    text = text or fallback_summary(profile, clicked, disliked)
    repo.save_interest_summary(user_id, text, "auto")
    return text
