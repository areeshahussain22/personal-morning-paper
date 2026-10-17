from __future__ import annotations

import asyncio
import json
from datetime import date

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.scheduler import JobRunner

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/users/{user_id}/editions/{edition_date}/stream")
async def edition_stream(user_id: str, edition_date: date, request: Request):
    repo = ProfileRepository(Database(get_settings().database_path))
    if repo.get_profile(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if request.session.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Edition not found")

    async def events():
        last = None
        for _ in range(120):
            if await request.is_disconnected():
                return
            current = repo.generation_status(user_id, edition_date.isoformat())
            if current and current != last:
                last = current
                payload = {"stage": current["stage"], "status": current["status"]}
                if current.get("error"):
                    payload["error"] = current["error"]
                yield f"event: {current['status']}\ndata: {json.dumps(payload)}\n\n"
                if current["status"] in {"ready", "failed"}:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/admin/jobs")
def admin_jobs(request: Request, x_admin_token: str | None = Header(default=None)) -> list[dict]:
    settings = get_settings()
    if settings.environment != "development" or not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=404, detail="Not found")
    return ProfileRepository(Database(settings.database_path)).job_runs()
