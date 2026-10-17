from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.repositories.database import Database
from app.repositories.profile_repository import ProfileRepository
from app.services.demo import demo_database_path, demo_rows, demo_stats, demo_front_pages

router = APIRouter(prefix="/demo", tags=["demo"])


def demo_db() -> Database:
    return Database(Path(os.getenv("DATABASE_URL", str(demo_database_path()))))


def require_demo() -> None:
    if not get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/login/{persona}")
def demo_login(persona: str, request: Request):
    require_demo()
    database = demo_db()
    ProfileRepository(database)
    with database.connect() as connection:
        row = connection.execute("SELECT user_id FROM users WHERE name=?", (f"simulated-{persona}",)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    request.session["user_id"] = row["user_id"]
    return {"persona": persona, "redirect": "/edition/today"}


@router.get("/charts")
def charts(request: Request):
    require_demo()
    return request.app.state.templates.TemplateResponse(
        request=request, name="demo_charts.html", context={
            "rows": demo_rows(demo_db()), "front_pages": demo_front_pages(demo_db()), "simulated": True
        }
    )


@router.get("/stats")
def stats(request: Request):
    require_demo()
    return request.app.state.templates.TemplateResponse(
        request=request, name="demo_stats.html", context={"stats": demo_stats(demo_db()), "simulated": True}
    )
