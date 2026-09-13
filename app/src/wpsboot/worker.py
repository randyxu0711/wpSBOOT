"""Background worker: claims queued jobs from Postgres and runs the pipeline."""

import json
import logging
import os
import signal
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import Any

from wpsboot import __version__
from wpsboot import services as svc
from wpsboot.config import Settings, get_settings
from wpsboot.db import session_scope
from wpsboot.logconfig import configure_logging
from wpsboot.mail import notify_job_finished
from wpsboot.models import Job, JobStatus
from wpsboot.pipeline import (
    ALIGNERS,
    CONCATENATE_STEP,
    INPUT_FILE,
    MIN_ALIGNERS,
    Hooks,
    StepResult,
    StepStatus,
    prepare_job_dir,
    remove_work_dir,
    run_aligners,
    run_concatenate,
)

log = logging.getLogger(__name__)

LIVENESS_FILE = Path("/tmp/wpsboot-worker-alive")  # noqa: S108  # read by the container healthcheck
TRACKED_PACKAGES = ("mafft", "muscle", "clustalw", "t-coffee", "perl-bioperl", "perl")


def load_tool_versions(settings: Settings) -> dict[str, Any]:
    versions: dict[str, Any] = {"wpsboot": __version__}
    try:
        packages = json.loads(settings.tools_packages_file.read_text())
    except (OSError, ValueError):
        log.warning("tool versions file %s not readable", settings.tools_packages_file)
        return versions
    for package in packages:
        if package.get("name") in TRACKED_PACKAGES:
            versions[package["name"]] = package.get("version")
    return versions


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.tool_versions = load_tool_versions(settings)
        self.shutdown = threading.Event()
        self.interrupt: threading.Event | None = None  # set to stop the current job's processes
        self._next_maintenance = 0.0

    # --- main loop -------------------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        log.info("worker %s started, tools=%s", self.worker_id, self.tool_versions)
        while not self.shutdown.is_set():
            self.touch_liveness()
            if time.monotonic() >= self._next_maintenance:
                self.maintenance()
                self._next_maintenance = (
                    time.monotonic() + self.settings.maintenance_interval_seconds
                )
            if not self.run_once():
                self.shutdown.wait(self.settings.worker_poll_seconds)
        log.info("worker %s stopped", self.worker_id)

    def run_once(self) -> bool:
        """Claim and process one job. Returns False when the queue was empty."""
        with session_scope() as session:
            job_id = svc.claim_next_job(session, self.worker_id)
        if job_id is None:
            return False
        try:
            self.process(job_id)
        except Exception:
            log.exception("job %s crashed the worker loop", job_id)
            self._fail(job_id, "An internal error occurred while running the job.")
        return True

    def maintenance(self) -> None:
        try:
            with session_scope() as session:
                if svc.try_maintenance_lock(session):
                    svc.recover_stale_jobs(session, self.settings)
                    svc.expire_jobs(session, self.settings)
        except Exception:
            log.exception("maintenance failed")

    def touch_liveness(self) -> None:
        LIVENESS_FILE.touch()

    def _on_signal(self, signum: int, frame: FrameType | None) -> None:
        log.info("received signal %d, shutting down", signum)
        self.shutdown.set()
        if self.interrupt is not None:
            self.interrupt.set()

    # --- one job ---------------------------------------------------------------------------

    def process(self, job_id: uuid.UUID) -> None:
        with session_scope() as session:
            job = session.get_one(Job, job_id)
            aligners = list(job.aligners)
            job.tool_versions = self.tool_versions
        directory = svc.job_dir(self.settings, job_id)
        log.info("job %s started (aligners=%s)", job_id, aligners)
        if not (directory / INPUT_FILE).is_file():
            self._fail(job_id, "The input file for this job is missing.")
            return
        prepare_job_dir(directory)

        self.interrupt = interrupt = threading.Event()
        cancel_requested = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat, args=(job_id, interrupt, cancel_requested), daemon=True
        )
        beat.start()
        try:
            hooks = self._hooks(job_id)
            deadline = time.monotonic() + self.settings.job_timeout_seconds
            results = run_aligners(
                directory, aligners, deadline=deadline, cancel=interrupt, hooks=hooks
            )
            succeeded = [a for a in aligners if results[a].status is StepStatus.SUCCEEDED]

            order: list[str] = []
            error: str | None = None
            if interrupt.is_set():
                pass
            elif len(succeeded) < MIN_ALIGNERS:
                self._set_step(job_id, CONCATENATE_STEP, status=StepStatus.SKIPPED)
                error = _not_enough_aligners_message(results, aligners)
            else:
                concat, order = run_concatenate(
                    directory,
                    succeeded,
                    script=self.settings.concatenate_script,
                    deadline=deadline,
                    cancel=interrupt,
                    hooks=hooks,
                )
                if concat.status is StepStatus.TIMED_OUT:
                    error = "Building the Super-MSA exceeded the time limit."
                elif concat.status is StepStatus.FAILED:
                    error = "Building the Super-MSA failed."
        finally:
            interrupt.set()  # stops the heartbeat thread
            beat.join()
            self.interrupt = None
            remove_work_dir(directory)

        self._complete(job_id, error=error, order=order, cancel_requested=cancel_requested)

    def _complete(
        self,
        job_id: uuid.UUID,
        *,
        error: str | None,
        order: list[str],
        cancel_requested: threading.Event,
    ) -> None:
        with session_scope() as session:
            job = session.get_one(Job, job_id, with_for_update=True)
            if job.locked_by != self.worker_id or job.status is not JobStatus.RUNNING:
                log.warning("job %s is no longer owned by this worker; dropping result", job_id)
                return
            if job.cancel_action is not None:
                svc.finalize_stop(self.settings, job, job.cancel_action)
                return
            if self.shutdown.is_set() and not cancel_requested.is_set():
                svc.release_job(session, job_id, self.worker_id)
                return
            finished = svc.now()
            job.status = JobStatus.FAILED if error else JobStatus.SUCCEEDED
            job.error_message = error
            job.concat_order = order or None
            job.finished_at = finished
            job.expires_at = finished + timedelta(days=self.settings.retention_days)
            job.locked_by = None
            log.info("job %s %s", job_id, job.status)
        self._notify(job_id)

    def _notify(self, job_id: uuid.UUID) -> None:
        with session_scope() as session:
            job = session.get_one(Job, job_id)
            if not job.email:
                return
            sent = notify_job_finished(self.settings, job)
            # The address is only kept until we have tried to use it.
            job.email = None
            if sent:
                job.notified_at = svc.now()

    def _fail(self, job_id: uuid.UUID, message: str) -> None:
        with session_scope() as session:
            job = session.get_one(Job, job_id, with_for_update=True)
            if job.status is not JobStatus.RUNNING:
                return
            job.status = JobStatus.FAILED
            job.error_message = message
            job.finished_at = svc.now()
            job.locked_by = None
            for step in job.steps:
                if step.status in (StepStatus.PENDING, StepStatus.RUNNING):
                    step.status = StepStatus.SKIPPED
        self._notify(job_id)

    def _heartbeat(
        self, job_id: uuid.UUID, stop: threading.Event, cancel_requested: threading.Event
    ) -> None:
        while not stop.wait(self.settings.heartbeat_seconds):
            try:
                with session_scope() as session:
                    owned, cancelled = svc.heartbeat(session, job_id, self.worker_id)
            except Exception:
                log.exception("heartbeat for job %s failed", job_id)
                continue
            if cancelled or not owned:
                log.info("job %s: %s", job_id, "cancel requested" if owned else "ownership lost")
                cancel_requested.set()
                stop.set()

    def _hooks(self, job_id: uuid.UUID) -> Hooks:
        def on_start(name: str, at: datetime) -> None:
            self._set_step(job_id, name, status=StepStatus.RUNNING, started_at=at)

        def on_finish(result: StepResult) -> None:
            self._set_step(
                job_id,
                result.name,
                status=result.status,
                started_at=result.started_at,
                finished_at=result.finished_at,
                exit_code=result.exit_code,
                stderr_tail=result.stderr_tail,
            )

        return Hooks(on_start=on_start, on_finish=on_finish, on_tick=self.touch_liveness)

    def _set_step(self, job_id: uuid.UUID, name: str, **values: Any) -> None:
        with session_scope() as session:
            step = session.get_one(Job, job_id).step(name)
            for key, value in values.items():
                setattr(step, key, value)


def _not_enough_aligners_message(results: dict[str, StepResult], aligners: list[str]) -> str:
    reasons = {
        StepStatus.FAILED: "failed",
        StepStatus.TIMED_OUT: "exceeded the time limit",
        StepStatus.CANCELLED: "was stopped",
    }
    failed = [
        f"{ALIGNERS[a].label} {reasons.get(results[a].status, results[a].status)}"
        for a in aligners
        if results[a].status is not StepStatus.SUCCEEDED
    ]
    return (
        f"At least {MIN_ALIGNERS} aligners must succeed to build a Super-MSA. "
        + "; ".join(failed)
        + "."
    )


def main() -> None:
    configure_logging()
    Worker(get_settings()).run()


if __name__ == "__main__":
    main()
