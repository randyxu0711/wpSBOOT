"""HTML pages."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from wpsboot import services as svc
from wpsboot.api import job_to_out
from wpsboot.config import Settings
from wpsboot.db import get_session
from wpsboot.deps import get_app_settings
from wpsboot.examples import EXAMPLE_FASTA, HERO_ALIGNMENTS
from wpsboot.pipeline import ALIGNERS, MIN_ALIGNERS
from wpsboot.templating import templates

router = APIRouter(include_in_schema=False)

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def index(request: Request, settings: SettingsDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "aligners": list(ALIGNERS.values()),
            "min_aligners": MIN_ALIGNERS,
            "example_fasta": EXAMPLE_FASTA,
            "hero_segments": [
                {"id": a.id, "label": a.label, "rows": HERO_ALIGNMENTS.get(a.id, [])}
                for a in ALIGNERS.values()
            ],
            "settings": settings,
            "max_upload_mb": settings.max_upload_bytes / 1024 / 1024,
        },
    )


@router.api_route(
    "/jobs/{job_id}", methods=["GET", "HEAD"], response_class=HTMLResponse, name="job_page"
)
def job_page(
    job_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep
) -> HTMLResponse:
    job = svc.get_visible_job(session, job_id)
    if job is None:
        return templates.TemplateResponse(request, "error.html", {"status_code": 404}, 404)
    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "job": job_to_out(request, session, settings, job).model_dump(mode="json"),
            "settings": settings,
        },
    )


@router.api_route("/healthz", methods=["GET", "HEAD"])
def healthz(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
