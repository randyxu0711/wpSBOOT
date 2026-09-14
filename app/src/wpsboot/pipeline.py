"""Run the aligners and the lab's concatenate.pl for one job directory.

This module knows nothing about the database: the worker passes callbacks and a
cancel event, and gets StepResults back.

Job directory layout:
    input.fasta              normalised user input
    <aligner>.fasta          one MSA per successful aligner
    superMSA.phylip          concatenate.pl output
    work/<step>/             per-step scratch dir (cwd + HOME), removed afterwards
"""

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import IO

log = logging.getLogger(__name__)

INPUT_FILE = "input.fasta"
SUPER_MSA_FILE = "superMSA.phylip"
CONCATENATE_STEP = "concatenate"
WORK_DIR = "work"
STDERR_TAIL_BYTES = 4096
KILL_GRACE_SECONDS = 5.0
POLL_SECONDS = 0.2
# The only worker environment variables the tools see; the rest (database URL, passwords) stays out.
INHERITED_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


@dataclass(frozen=True)
class Aligner:
    id: str
    label: str
    # Arguments mirror the original wpSBOOT.sh so results stay comparable.
    args: tuple[str, ...]
    stdout_is_output: bool = False

    @property
    def output_file(self) -> str:
        return f"{self.id}.fasta"

    def command(self) -> list[str]:
        return [a.format(input=INPUT_FILE, output=self.output_file) for a in self.args]


ALIGNERS: dict[str, Aligner] = {
    a.id: a
    for a in (
        Aligner("mafft", "MAFFT", ("mafft", "{input}"), stdout_is_output=True),
        Aligner("muscle", "MUSCLE", ("muscle", "-in", "{input}", "-out", "{output}")),
        Aligner(
            "clustalw",
            "ClustalW",
            ("clustalw", "-infile={input}", "-outfile={output}", "-output=fasta"),
        ),
        Aligner(
            "tcoffee",
            "T-Coffee",
            ("t_coffee", "-infile={input}", "-outfile={output}", "-output=fasta"),
        ),
    )
}
MIN_ALIGNERS = 2


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    name: str
    status: StepStatus
    started_at: datetime
    finished_at: datetime
    exit_code: int | None = None
    stderr_tail: str = ""


@dataclass
class Hooks:
    on_start: Callable[[str, datetime], None] = lambda name, at: None
    on_finish: Callable[[StepResult], None] = lambda result: None
    # Called every poll iteration while processes run (worker liveness).
    on_tick: Callable[[], None] = lambda: None


@dataclass
class _Proc:
    name: str
    popen: "subprocess.Popen[bytes]"
    started_at: datetime
    work_dir: Path
    stdout: IO[bytes]
    stderr: IO[bytes]
    output: Path


def prepare_job_dir(job_dir: Path) -> None:
    """Remove leftovers of a previous attempt, keeping only the input."""
    for entry in job_dir.iterdir():
        if entry.name == INPUT_FILE:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def remove_work_dir(job_dir: Path) -> None:
    shutil.rmtree(job_dir / WORK_DIR, ignore_errors=True)


def run_aligners(
    job_dir: Path,
    aligner_ids: list[str],
    *,
    deadline: float,
    cancel: threading.Event,
    hooks: Hooks,
) -> dict[str, StepResult]:
    """Run aligners in parallel until all finish, the deadline passes or cancel is set."""
    procs = []
    for aligner_id in aligner_ids:
        aligner = ALIGNERS[aligner_id]
        work_dir = _make_work_dir(job_dir, aligner.id)
        shutil.copyfile(job_dir / INPUT_FILE, work_dir / INPUT_FILE)
        stdout_path = work_dir / (aligner.output_file if aligner.stdout_is_output else "stdout.log")
        procs.append(
            _spawn(
                aligner.id,
                aligner.command(),
                work_dir,
                stdout_path,
                output=work_dir / aligner.output_file,
                hooks=hooks,
            )
        )

    results = _supervise(procs, deadline=deadline, cancel=cancel, hooks=hooks)
    for proc in procs:
        result = results[proc.name]
        if result.status is StepStatus.SUCCEEDED:
            shutil.move(proc.output, job_dir / proc.output.name)
        shutil.rmtree(proc.work_dir, ignore_errors=True)
    return results


def run_concatenate(
    job_dir: Path,
    aligner_ids: list[str],
    *,
    script: Path,
    deadline: float,
    cancel: threading.Event,
    hooks: Hooks,
) -> tuple[StepResult, list[str]]:
    """Run the lab's concatenate.pl unmodified, exactly as the original server did.

    Returns the step result and the concatenation order (aligner ids) that the
    script chose at random, parsed from its stdout.
    """
    work_dir = _make_work_dir(job_dir, CONCATENATE_STEP)
    alignments = [f"../../{ALIGNERS[a].output_file}" for a in sorted(aligner_ids)]
    command = ["perl", str(script), "--random", "--aln", *alignments, "--out", SUPER_MSA_FILE]
    proc = _spawn(
        CONCATENATE_STEP,
        command,
        work_dir,
        work_dir / "stdout.log",
        output=work_dir / SUPER_MSA_FILE,
        hooks=hooks,
    )
    result = _supervise([proc], deadline=deadline, cancel=cancel, hooks=hooks)[CONCATENATE_STEP]
    order: list[str] = []
    if result.status is StepStatus.SUCCEEDED:
        order = parse_concatenation_order((work_dir / "stdout.log").read_text(errors="replace"))
        shutil.move(proc.output, job_dir / SUPER_MSA_FILE)
    shutil.rmtree(work_dir, ignore_errors=True)
    return result, order


def parse_concatenation_order(stdout: str) -> list[str]:
    """Extract alignment order from concatenate.pl's 'How to concatenate' report."""
    order: list[str] = []
    in_list = False
    for line in stdout.splitlines():
        if line.strip() == "alignments:":
            in_list = True
        elif in_list and line.startswith("\t\t"):
            order.append(Path(line.strip()).stem)
        elif in_list:
            break
    return order


def _make_work_dir(job_dir: Path, name: str) -> Path:
    work_dir = job_dir / WORK_DIR / name
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _spawn(
    name: str,
    command: list[str],
    work_dir: Path,
    stdout_path: Path,
    *,
    output: Path,
    hooks: Hooks,
) -> _Proc:
    # HOME and the T-Coffee dirs point at the scratch dir so concurrent runs never share state.
    inherited = {key: os.environ[key] for key in INHERITED_ENV if key in os.environ}
    env = inherited | {
        "HOME": str(work_dir),
        "HOME_4_TCOFFEE": str(work_dir),
        "TMP_4_TCOFFEE": str(work_dir),
        "CACHE_4_TCOFFEE": str(work_dir),
        "LOCKDIR_4_TCOFFEE": str(work_dir),
    }
    stdout = stdout_path.open("wb")
    stderr = (work_dir / "stderr.log").open("wb")
    started_at = datetime.now(UTC)
    log.info("starting step %s: %s", name, command)
    popen = subprocess.Popen(
        command,
        cwd=work_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,  # own process group, so we can kill the whole tree
    )
    hooks.on_start(name, started_at)
    return _Proc(name, popen, started_at, work_dir, stdout, stderr, output)


def _supervise(
    procs: list[_Proc], *, deadline: float, cancel: threading.Event, hooks: Hooks
) -> dict[str, StepResult]:
    results: dict[str, StepResult] = {}
    running = list(procs)
    while running:
        for proc in list(running):
            exit_code = proc.popen.poll()
            if exit_code is None:
                continue
            running.remove(proc)
            ok = exit_code == 0 and _has_alignment(proc.output)
            status = StepStatus.SUCCEEDED if ok else StepStatus.FAILED
            results[proc.name] = _finish(proc, status, exit_code, hooks)

        if running and (cancel.is_set() or time.monotonic() >= deadline):
            status = StepStatus.CANCELLED if cancel.is_set() else StepStatus.TIMED_OUT
            for proc in running:
                _kill(proc.popen)
                results[proc.name] = _finish(proc, status, proc.popen.returncode, hooks)
            running.clear()

        if running:
            hooks.on_tick()
            time.sleep(POLL_SECONDS)
    return results


def _finish(proc: _Proc, status: StepStatus, exit_code: int | None, hooks: Hooks) -> StepResult:
    proc.stdout.close()
    proc.stderr.close()
    result = StepResult(
        name=proc.name,
        status=status,
        started_at=proc.started_at,
        finished_at=datetime.now(UTC),
        exit_code=exit_code,
        stderr_tail=_tail(proc.work_dir / "stderr.log"),
    )
    log.info("step %s finished: %s (exit %s)", proc.name, status, exit_code)
    hooks.on_finish(result)
    return result


def _kill(popen: "subprocess.Popen[bytes]") -> None:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE_SECONDS), (signal.SIGKILL, None)):
        try:
            os.killpg(popen.pid, sig)
        except ProcessLookupError:
            break
        try:
            popen.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    popen.wait()


def _has_alignment(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _tail(path: Path) -> str:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - STDERR_TAIL_BYTES))
        return f.read().decode(errors="replace")
