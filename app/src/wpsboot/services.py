"""Job operations shared by the API, the admin panel and the worker."""

import hashlib
import hmac
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from wpsboot.config import Settings
from wpsboot.fasta import ParsedFasta
from wpsboot.models import FINISHED_STATUSES, CancelAction, Job, JobStatus, JobStep
from wpsboot.pipeline import CONCATENATE_STEP, INPUT_FILE, StepStatus

log = logging.getLogger(__name__)

MAINTENANCE_LOCK_KEY = 0x77_70_53_42  # "wpSB"


class RateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limited")
        self.retry_after_seconds = retry_after_seconds


class InvalidTransitionError(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def job_dir(settings: Settings, job_id: uuid.UUID) -> Path:
    return settings.data_dir / str(job_id)


def hash_ip(settings: Settings, ip: str) -> str:
    return hmac.new(settings.secret_key.encode(), ip.encode(), hashlib.sha256).hexdigest()


# --- creation -------------------------------------------------------------------------------


def check_rate_limit(session: Session, settings: Settings, ip_hash: str) -> None:
    window_start = now() - timedelta(hours=1)
    created = session.scalars(
        select(Job.created_at)
        .where(Job.client_ip_hash == ip_hash, Job.created_at > window_start)
        .order_by(Job.created_at)
    ).all()
    if len(created) >= settings.rate_limit_per_hour:
        oldest = created[len(created) - settings.rate_limit_per_hour]
        retry_after = int((oldest + timedelta(hours=1) - now()).total_seconds()) + 1
        raise RateLimitedError(max(retry_after, 1))


def create_job(
    session: Session,
    settings: Settings,
    *,
    parsed: ParsedFasta,
    aligners: list[str],
    email: str | None,
    client_ip: str,
    warnings: list[str],
) -> Job:
    ip_hash = hash_ip(settings, client_ip)
    check_rate_limit(session, settings, ip_hash)

    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.QUEUED,
        aligners=aligners,
        seq_count=len(parsed.records),
        total_residues=parsed.total_residues,
        warnings=[*parsed.warnings, *warnings],
        email=email,
        client_ip_hash=ip_hash,
        expires_at=now() + timedelta(days=settings.retention_days),
        steps=[JobStep(name=name) for name in [*aligners, CONCATENATE_STEP]],
    )
    directory = job_dir(settings, job.id)
    directory.mkdir(parents=True)
    try:
        (directory / INPUT_FILE).write_text(parsed.to_fasta())
        session.add(job)
        session.commit()
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    log.info("job %s created: %d sequences, aligners=%s", job.id, job.seq_count, aligners)
    return job


# --- reading --------------------------------------------------------------------------------


def get_visible_job(session: Session, job_id: uuid.UUID) -> Job | None:
    job = session.get(Job, job_id)
    if job is None or job.status is JobStatus.DELETED:
        return None
    return job


def queue_position(session: Session, job: Job) -> int | None:
    if job.status is not JobStatus.QUEUED:
        return None
    ahead = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.QUEUED, Job.created_at < job.created_at)
    )
    return (ahead or 0) + 1


# --- stopping -------------------------------------------------------------------------------


def request_stop(
    session: Session, settings: Settings, job_id: uuid.UUID, action: CancelAction
) -> Job:
    """Delete or cancel a job. Running jobs are stopped by their worker via the heartbeat."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None or job.status is JobStatus.DELETED:
        raise LookupError(job_id)
    if job.status is JobStatus.RUNNING:
        job.cancel_requested_at = now()
        job.cancel_action = action
    elif job.status is JobStatus.QUEUED or action is CancelAction.DELETE:
        finalize_stop(settings, job, action)
    else:
        raise InvalidTransitionError(f"Cannot cancel a job that is {job.status}.")
    session.commit()
    return job


def finalize_stop(settings: Settings, job: Job, action: CancelAction) -> None:
    """Apply a delete/cancel to a job row that the caller holds locked."""
    job.locked_by = None
    job.cancel_requested_at = None
    job.cancel_action = None
    job.finished_at = job.finished_at or now()
    for step in job.steps:
        if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
            step.status = StepStatus.CANCELLED
    if action is CancelAction.DELETE:
        job.status = JobStatus.DELETED
        job.email = None
        shutil.rmtree(job_dir(settings, job.id), ignore_errors=True)
        log.info("job %s deleted", job.id)
    else:
        job.status = JobStatus.FAILED
        job.error_message = "Cancelled by an administrator."
        log.info("job %s cancelled", job.id)


def requeue(session: Session, job_id: uuid.UUID) -> Job:
    """Admin action: run a failed job again from its stored input."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None or job.status is not JobStatus.FAILED:
        raise InvalidTransitionError("Only failed jobs can be re-queued.")
    _reset_for_queue(job)
    job.attempts = 0
    job.error_message = None
    job.started_at = None
    job.finished_at = None
    session.commit()
    return job


def _reset_for_queue(job: Job) -> None:
    job.status = JobStatus.QUEUED
    job.locked_by = None
    job.heartbeat_at = None
    for step in job.steps:
        step.reset()


# --- worker-side transitions ----------------------------------------------------------------


def claim_next_job(session: Session, worker_id: str) -> uuid.UUID | None:
    job_id: uuid.UUID | None = session.scalar(
        text(
            """
            UPDATE jobs
               SET status = 'running', locked_by = :worker, attempts = attempts + 1,
                   started_at = COALESCE(started_at, now()), heartbeat_at = now()
             WHERE id = (SELECT id FROM jobs WHERE status = 'queued'
                          ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id
            """
        ),
        {"worker": worker_id},
    )
    session.commit()
    return job_id


def heartbeat(session: Session, job_id: uuid.UUID, worker_id: str) -> tuple[bool, bool]:
    """Returns (still_owned, cancel_requested)."""
    row = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == JobStatus.RUNNING)
        .values(heartbeat_at=func.now())
        .returning(Job.cancel_requested_at)
    ).first()
    session.commit()
    if row is None:
        return False, False
    return True, row.cancel_requested_at is not None


def release_job(session: Session, job_id: uuid.UUID, worker_id: str) -> None:
    """Hand a job back to the queue on graceful worker shutdown (not counted as an attempt)."""
    job = session.get(Job, job_id, with_for_update=True)
    if job is None or job.locked_by != worker_id or job.status is not JobStatus.RUNNING:
        return
    _reset_for_queue(job)
    job.attempts = max(job.attempts - 1, 0)
    log.info("job %s released back to the queue", job.id)


# --- maintenance ----------------------------------------------------------------------------


def try_maintenance_lock(session: Session) -> bool:
    return bool(session.scalar(select(func.pg_try_advisory_xact_lock(MAINTENANCE_LOCK_KEY))))


def recover_stale_jobs(session: Session, settings: Settings) -> int:
    cutoff = now() - timedelta(seconds=settings.stale_after_seconds)
    stale = session.scalars(
        select(Job)
        .where(Job.status == JobStatus.RUNNING, Job.heartbeat_at < cutoff)
        .with_for_update(skip_locked=True)
    ).all()
    for job in stale:
        if job.cancel_action is not None:
            finalize_stop(settings, job, job.cancel_action)
        elif job.attempts >= settings.max_attempts:
            job.status = JobStatus.FAILED
            job.locked_by = None
            job.finished_at = now()
            job.error_message = "The job was interrupted repeatedly and has been stopped."
            log.warning("job %s failed after %d interrupted attempts", job.id, job.attempts)
        else:
            log.warning("job %s lost its worker %s; re-queued", job.id, job.locked_by)
            _reset_for_queue(job)
    return len(stale)


def expire_jobs(session: Session, settings: Settings) -> int:
    expired = session.scalars(
        select(Job)
        .where(Job.status.in_(FINISHED_STATUSES), Job.expires_at < now())
        .with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        shutil.rmtree(job_dir(settings, job.id), ignore_errors=True)
        job.status = JobStatus.EXPIRED
        job.email = None
    if expired:
        log.info("expired %d jobs", len(expired))
    return len(expired)


# --- statistics (admin) ---------------------------------------------------------------------


@dataclass
class Stats:
    by_status: dict[str, int]
    created_24h: int
    created_7d: int
    created_30d: int
    step_stats: list[dict[str, Any]]


def stats(session: Session) -> Stats:
    by_status = {
        str(status): count
        for status, count in session.execute(
            select(Job.status, func.count()).group_by(Job.status)
        ).tuples()
    }

    def created_since(delta: timedelta) -> int:
        return (
            session.scalar(
                select(func.count()).select_from(Job).where(Job.created_at > now() - delta)
            )
            or 0
        )

    duration = func.extract("epoch", JobStep.finished_at - JobStep.started_at)
    rows = session.execute(
        select(
            JobStep.name,
            func.count().label("runs"),
            func.count().filter(JobStep.status == StepStatus.SUCCEEDED).label("succeeded"),
            func.count()
            .filter(JobStep.status.in_([StepStatus.FAILED, StepStatus.TIMED_OUT]))
            .label("failed"),
            func.avg(duration).filter(JobStep.status == StepStatus.SUCCEEDED).label("avg_seconds"),
        )
        .where(JobStep.started_at.is_not(None))
        .group_by(JobStep.name)
        .order_by(JobStep.name)
    ).all()
    return Stats(
        by_status=by_status,
        created_24h=created_since(timedelta(days=1)),
        created_7d=created_since(timedelta(days=7)),
        created_30d=created_since(timedelta(days=30)),
        step_stats=[row._asdict() for row in rows],
    )
