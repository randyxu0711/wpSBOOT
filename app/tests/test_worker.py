"""Queue and worker behaviour against a real database, with fake aligners."""

import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from wpsboot import services as svc
from wpsboot.config import Settings
from wpsboot.db import get_sessionmaker
from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.fasta import parse_fasta
from wpsboot.models import CancelAction, Job, JobStatus
from wpsboot.pipeline import StepStatus
from wpsboot.worker import Worker

pytestmark = pytest.mark.db


def create(
    db: Session, settings: Settings, aligners: list[str] | None = None, email: str | None = None
) -> uuid.UUID:
    parsed = parse_fasta(EXAMPLE_FASTA, max_sequences=200, max_sequence_length=10_000)
    job = svc.create_job(
        db,
        settings,
        parsed=parsed,
        aligners=aligners or ["mafft", "muscle", "tcoffee"],
        email=email,
        client_ip="203.0.113.7",
        warnings=[],
    )
    return job.id


def reload(job_id: uuid.UUID) -> Job:
    with get_sessionmaker()() as session:
        return session.get_one(Job, job_id)


@pytest.fixture
def worker(
    settings: Settings, fake_tools: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Worker:
    monkeypatch.setattr("wpsboot.worker.LIVENESS_FILE", tmp_path / "alive")
    return Worker(settings)


def test_claim_is_fifo_and_exclusive(db: Session, settings: Settings) -> None:
    first = create(db, settings)
    second = create(db, settings)
    with get_sessionmaker()() as a, get_sessionmaker()() as b:
        assert svc.claim_next_job(a, "worker-a") == first
        assert svc.claim_next_job(b, "worker-b") == second
        assert svc.claim_next_job(a, "worker-a") is None
    job = reload(first)
    assert job.status is JobStatus.RUNNING
    assert job.locked_by == "worker-a"
    assert job.attempts == 1


def test_successful_job(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    sent: list[dict[str, str]] = []
    monkeypatch.setattr("wpsboot.mail.send_mail", lambda settings, **kw: sent.append(kw))
    job_id = create(db, settings, email="user@example.org")

    assert worker.run_once() is True
    job = reload(job_id)
    assert job.status is JobStatus.SUCCEEDED, job.error_message
    assert {s.name: s.status for s in job.steps} == {
        "mafft": StepStatus.SUCCEEDED,
        "muscle": StepStatus.SUCCEEDED,
        "tcoffee": StepStatus.SUCCEEDED,
        "concatenate": StepStatus.SUCCEEDED,
    }
    assert sorted(job.concat_order or []) == ["mafft", "muscle", "tcoffee"]
    assert job.locked_by is None
    assert job.tool_versions is not None and "wpsboot" in job.tool_versions
    assert job.expires_at > job.finished_at + timedelta(days=settings.retention_days - 1)  # type: ignore[operator]
    directory = settings.data_dir / str(job_id)
    assert sorted(p.name for p in directory.iterdir()) == [
        "input.fasta",
        "mafft.fasta",
        "muscle.fasta",
        "superMSA.phylip",
        "tcoffee.fasta",
    ]
    # Notified once, then the address is forgotten.
    assert len(sent) == 1 and sent[0]["to"] == "user@example.org"
    assert f"/jobs/{job_id}" in sent[0]["body"]
    assert job.email is None and job.notified_at is not None
    assert worker.run_once() is False


def test_not_enough_aligners(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MUSCLE", "fail")
    monkeypatch.setenv("FAKE_T_COFFEE", "empty")
    job_id = create(db, settings)
    worker.run_once()
    job = reload(job_id)
    assert job.status is JobStatus.FAILED
    assert "At least 2 aligners must succeed" in (job.error_message or "")
    assert "MUSCLE failed" in (job.error_message or "")
    assert job.step("concatenate").status is StepStatus.SKIPPED
    assert job.step("muscle").exit_code == 3


def test_one_failure_still_builds_super_msa(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MUSCLE", "fail")
    job_id = create(db, settings)
    worker.run_once()
    job = reload(job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert sorted(job.concat_order or []) == ["mafft", "tcoffee"]


def test_timeout(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_T_COFFEE", "hang")
    monkeypatch.setenv("FAKE_MUSCLE", "hang")
    monkeypatch.setattr(settings, "job_timeout_seconds", 2)
    job_id = create(db, settings)
    worker.run_once()
    job = reload(job_id)
    assert job.status is JobStatus.FAILED
    assert job.step("tcoffee").status is StepStatus.TIMED_OUT
    assert "exceeded the time limit" in (job.error_message or "")


def test_user_delete_stops_running_job(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAFFT", "hang")
    monkeypatch.setattr(settings, "heartbeat_seconds", 0.2)
    job_id = create(db, settings)

    def delete_soon() -> None:
        time.sleep(1)
        with get_sessionmaker()() as session:
            svc.request_stop(session, settings, job_id, CancelAction.DELETE)

    threading.Thread(target=delete_soon).start()
    started = time.monotonic()
    worker.run_once()
    assert time.monotonic() - started < 15
    job = reload(job_id)
    assert job.status is JobStatus.DELETED
    assert job.step("mafft").status is StepStatus.CANCELLED
    assert not (settings.data_dir / str(job_id)).exists()


def test_graceful_shutdown_releases_job(
    db: Session, settings: Settings, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAFFT", "hang")
    job_id = create(db, settings)
    threading.Timer(1, lambda: worker._on_signal(15, None)).start()
    worker.run_once()
    job = reload(job_id)
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0
    assert all(s.status is StepStatus.PENDING for s in job.steps)


def test_stale_job_is_recovered_then_failed(db: Session, settings: Settings) -> None:
    job_id = create(db, settings)
    svc.claim_next_job(db, "dead-worker")

    def age_heartbeat() -> None:
        job = db.get_one(Job, job_id)
        db.refresh(job)
        job.heartbeat_at = svc.now() - timedelta(seconds=settings.stale_after_seconds + 5)
        db.commit()

    age_heartbeat()
    assert svc.recover_stale_jobs(db, settings) == 1
    db.commit()
    assert reload(job_id).status is JobStatus.QUEUED

    svc.claim_next_job(db, "dead-worker")  # attempt 2 of max 2
    age_heartbeat()
    svc.recover_stale_jobs(db, settings)
    db.commit()
    job = reload(job_id)
    assert job.status is JobStatus.FAILED
    assert "interrupted repeatedly" in (job.error_message or "")


def test_maintenance_lock_is_exclusive(db: Session) -> None:
    with get_sessionmaker()() as other:
        assert svc.try_maintenance_lock(db) is True
        assert svc.try_maintenance_lock(other) is False
        db.rollback()
        assert svc.try_maintenance_lock(other) is True
        other.rollback()


def test_missing_input_fails(db: Session, settings: Settings, worker: Worker) -> None:
    job_id = create(db, settings)
    (settings.data_dir / str(job_id) / "input.fasta").unlink()
    worker.run_once()
    job = reload(job_id)
    assert job.status is JobStatus.FAILED
    assert "input file" in (job.error_message or "")
