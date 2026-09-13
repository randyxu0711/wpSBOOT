"""Password-protected admin panel for job management (/admin)."""

import secrets
import uuid
from collections.abc import Callable
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from wpsboot import services as svc
from wpsboot.config import Settings
from wpsboot.db import get_session
from wpsboot.deps import get_app_settings
from wpsboot.models import CancelAction, Job, JobStatus
from wpsboot.templating import STEP_LABELS, templates

PAGE_SIZE = 50

basic = HTTPBasic(realm="wpSBOOT admin")
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


def require_admin(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic)], settings: SettingsDep
) -> str:
    user_ok = secrets.compare_digest(
        credentials.username.encode(), settings.admin_username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.encode()
    )
    if not (user_ok and password_ok):
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def require_same_origin(request: Request) -> None:
    """Browsers resend Basic credentials automatically, so POSTs need a CSRF check."""
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source or urlsplit(source).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin request rejected")


router = APIRouter(prefix="/admin", include_in_schema=False, dependencies=[Depends(require_admin)])


@router.get("", response_class=HTMLResponse, name="admin_jobs")
def list_jobs(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    status: Annotated[JobStatus | None, Query()] = None,
    q: Annotated[str, Query(max_length=36)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> HTMLResponse:
    query = select(Job)
    if status is not None:
        query = query.where(Job.status == status)
    if q.strip():
        query = query.where(cast(Job.id, String).startswith(q.strip().lower()))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    jobs = session.scalars(
        query.order_by(Job.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    return templates.TemplateResponse(
        request,
        "admin/jobs.html",
        {
            "jobs": jobs,
            "stats": svc.stats(session),
            "statuses": list(JobStatus),
            "status": status,
            "q": q,
            "page": page,
            "pages": max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
            "total": total,
            "labels": STEP_LABELS,
            "settings": settings,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse, name="admin_job")
def job_detail(
    job_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep
) -> HTMLResponse:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "admin/job.html",
        {
            "job": job,
            "labels": STEP_LABELS,
            "queue_position": svc.queue_position(session, job),
            "settings": settings,
        },
    )


def _action(
    apply: Callable[[Session, Settings, uuid.UUID], object],
) -> Callable[[uuid.UUID, Request, Session, Settings], RedirectResponse]:
    def endpoint(
        job_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep
    ) -> RedirectResponse:
        require_same_origin(request)
        try:
            apply(session, settings, job_id)
        except LookupError as exc:
            raise HTTPException(404) from exc
        except svc.InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(request.url_for("admin_job", job_id=job_id), status_code=303)

    return endpoint


router.add_api_route(
    "/jobs/{job_id}/cancel",
    _action(lambda s, st, jid: svc.request_stop(s, st, jid, CancelAction.CANCEL)),
    methods=["POST"],
    name="admin_cancel",
)
router.add_api_route(
    "/jobs/{job_id}/delete",
    _action(lambda s, st, jid: svc.request_stop(s, st, jid, CancelAction.DELETE)),
    methods=["POST"],
    name="admin_delete",
)
router.add_api_route(
    "/jobs/{job_id}/requeue",
    _action(lambda s, st, jid: svc.requeue(s, jid)),
    methods=["POST"],
    name="admin_requeue",
)
