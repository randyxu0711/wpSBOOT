"""Public JSON API (/api/v1). The web frontend uses the same endpoints."""

import tempfile
import uuid
import zipfile
import math
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from wpsboot import services as svc
from wpsboot.config import Settings
from wpsboot.db import get_session
from wpsboot.deps import get_app_settings
from wpsboot.errors import ApiError, ErrorBody
from wpsboot.fasta import FastaError, parse_fasta
from wpsboot.models import FINISHED_STATUSES, CancelAction, Job
from wpsboot.pipeline import ALIGNERS, INPUT_FILE, MIN_ALIGNERS, SUPER_MSA_FILE
from wpsboot.templating import STEP_LABELS

router = APIRouter(prefix="/api/v1", tags=["jobs"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorBody},
    422: {"model": ErrorBody},
}


class StepOut(BaseModel):
    name: str
    label: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None


class FileOut(BaseModel):
    name: str
    label: str
    size_bytes: int
    url: str


class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime
    queue_position: int | None
    aligners: list[str]
    sequence_count: int
    total_residues: int
    warnings: list[str]
    error: str | None
    steps: list[StepOut]
    files: list[FileOut]
    archive_url: str | None
    concatenation_order: list[str] | None
    tool_versions: dict[str, Any] | None
    result_url: str


class JobCreated(BaseModel):
    id: uuid.UUID
    status: str
    status_url: str
    result_url: str
    warnings: list[str]


@router.post(
    "/jobs",
    status_code=201,
    response_model=JobCreated,
    responses={**ERROR_RESPONSES, 413: {"model": ErrorBody}, 429: {"model": ErrorBody}},
    summary="Submit sequences to build a Super-MSA",
)
def submit_job(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    sequences: Annotated[
        str | None, Form(description="FASTA text (at most 1 MB; send larger input as `file`)")
    ] = None,
    file: Annotated[UploadFile | None, File(description="FASTA file")] = None,
    aligners: Annotated[
        list[str] | None,
        Form(description=f"Repeat for each aligner; default all. Choices: {', '.join(ALIGNERS)}"),
    ] = None,
    email: Annotated[str | None, Form(description="Optional notification address")] = None,
) -> JobCreated:
    text = _read_input(settings, sequences, file)
    chosen = _validate_aligners(aligners)
    try:
        parsed = parse_fasta(
            text,
            max_sequences=settings.max_sequences,
            max_sequence_length=settings.max_sequence_length,
        )
    except FastaError as exc:
        raise ApiError(422, exc.errors) from exc

    warnings: list[str] = []
    address = _validate_email(email)
    if address and not settings.mail_enabled:
        warnings.append(
            "Email notifications are not enabled on this server; bookmark the result page instead."
        )
        address = None

    client_ip = request.client.host if request.client else "unknown"
    try:
        job = svc.create_job(
            session,
            settings,
            parsed=parsed,
            aligners=chosen,
            email=address,
            client_ip=client_ip,
            warnings=warnings,
        )
    except svc.RateLimitedError as exc:
        minutes = math.ceil(exc.retry_after_seconds / 60)
        raise ApiError(
            429,
            [f"Too many jobs from your address. Try again in {minutes} min."],
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except svc.TooManyActiveJobsError as exc:
        raise ApiError(
            429,
            [
                f"You already have {exc.limit} jobs queued or running. "
                "Submit again when one of them has finished."
            ],
        ) from exc

    status_url = str(request.url_for("get_job", job_id=job.id))
    response.headers["Location"] = status_url
    return JobCreated(
        id=job.id,
        status=job.status,
        status_url=status_url,
        result_url=str(request.url_for("job_page", job_id=job.id)),
        warnings=job.warnings,
    )


@router.get("/jobs/{job_id}", response_model=JobOut, responses=ERROR_RESPONSES)
def get_job(
    job_id: uuid.UUID, request: Request, session: SessionDep, settings: SettingsDep
) -> JobOut:
    job = _visible_job(session, job_id)
    return job_to_out(request, session, settings, job)


@router.delete("/jobs/{job_id}", status_code=204, responses=ERROR_RESPONSES)
def delete_job(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> Response:
    try:
        svc.request_stop(session, settings, job_id, CancelAction.DELETE)
    except LookupError as exc:
        raise ApiError(404, ["Job not found."]) from exc
    return Response(status_code=204)


@router.get(
    "/jobs/{job_id}/files/{name}",
    response_class=FileResponse,
    responses=ERROR_RESPONSES,
    summary="Download one result file",
)
def download_file(
    job_id: uuid.UUID, name: str, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    job = _visible_job(session, job_id)
    # Only names from the fixed set of result files are served, so paths cannot escape the job dir.
    available = {path.name: path for path in _result_paths(settings, job)}
    if name not in available:
        raise ApiError(404, ["File not found."])
    return FileResponse(available[name], media_type="text/plain", filename=name)


@router.get(
    "/jobs/{job_id}/archive",
    response_class=FileResponse,
    responses=ERROR_RESPONSES,
    summary="Download all result files as a zip archive",
)
def download_archive(job_id: uuid.UUID, session: SessionDep, settings: SettingsDep) -> FileResponse:
    job = _visible_job(session, job_id)
    paths = _result_paths(settings, job)
    if not paths:
        raise ApiError(404, ["No files are available for this job."])
    with (
        tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp,
        zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        for path in paths:
            archive.write(path, arcname=f"wpsboot-{job.id}/{path.name}")
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"wpsboot-{str(job.id)[:8]}.zip",
        background=BackgroundTask(Path(tmp.name).unlink),
    )


# --- helpers --------------------------------------------------------------------------------


def job_to_out(request: Request, session: Session, settings: Settings, job: Job) -> JobOut:
    files = [
        FileOut(
            name=path.name,
            label=_file_label(path.name),
            size_bytes=path.stat().st_size,
            url=str(request.url_for("download_file", job_id=job.id, name=path.name)),
        )
        for path in _result_paths(settings, job)
    ]
    return JobOut(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        expires_at=job.expires_at,
        queue_position=svc.queue_position(session, job),
        aligners=job.aligners,
        sequence_count=job.seq_count,
        total_residues=job.total_residues,
        warnings=job.warnings,
        error=job.error_message,
        steps=[
            StepOut(
                name=s.name,
                label=STEP_LABELS.get(s.name, s.name),
                status=s.status,
                started_at=s.started_at,
                finished_at=s.finished_at,
                duration_seconds=s.duration_seconds,
            )
            for s in job.steps
        ],
        files=files,
        archive_url=str(request.url_for("download_archive", job_id=job.id)) if files else None,
        concatenation_order=job.concat_order,
        tool_versions=job.tool_versions,
        result_url=str(request.url_for("job_page", job_id=job.id)),
    )


def _visible_job(session: Session, job_id: uuid.UUID) -> Job:
    job = svc.get_visible_job(session, job_id)
    if job is None:
        raise ApiError(404, ["Job not found."])
    return job


def _result_paths(settings: Settings, job: Job) -> list[Path]:
    if job.status not in FINISHED_STATUSES:
        return []
    directory = svc.job_dir(settings, job.id)
    names = [INPUT_FILE, *(ALIGNERS[a].output_file for a in job.aligners), SUPER_MSA_FILE]
    return [directory / n for n in names if (directory / n).is_file()]


def _file_label(name: str) -> str:
    if name == INPUT_FILE:
        return "Input sequences"
    if name == SUPER_MSA_FILE:
        return "Super-MSA (PHYLIP)"
    aligner = ALIGNERS.get(Path(name).stem)
    return f"{aligner.label} alignment" if aligner else name


def _read_input(settings: Settings, sequences: str | None, file: UploadFile | None) -> str:
    text = sequences if sequences and sequences.strip() else None
    upload = file if file is not None and file.filename else None
    if text is not None and upload is not None:
        raise ApiError(422, ["Provide either pasted sequences or a file, not both."])
    if upload is not None:
        data = upload.file.read(settings.max_upload_bytes + 1)
    elif text is not None:
        data = text.encode()
    else:
        raise ApiError(422, ["Paste sequences or upload a FASTA file."])
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / 1024 / 1024
        raise ApiError(413, [f"Input is larger than the {limit_mb:g} MB limit."])
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ApiError(422, ["The file is not a plain-text FASTA file."]) from exc


def _validate_aligners(aligners: list[str] | None) -> list[str]:
    if not aligners:
        return list(ALIGNERS)
    unknown = sorted(set(aligners) - set(ALIGNERS))
    if unknown:
        raise ApiError(
            422, [f"Unknown aligner(s): {', '.join(unknown)}. Choose from {', '.join(ALIGNERS)}."]
        )
    chosen = [a for a in ALIGNERS if a in aligners]
    if len(chosen) < MIN_ALIGNERS:
        raise ApiError(422, [f"Select at least {MIN_ALIGNERS} aligners."])
    return chosen


def _validate_email(email: str | None) -> str | None:
    if not email or not email.strip():
        return None
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ApiError(422, [f"Email address is not valid: {exc}"]) from exc
