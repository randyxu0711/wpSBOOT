"""Pipeline tests using fake aligner executables (no bioinformatics tools needed)."""

import threading
import time
from pathlib import Path

import pytest

from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.pipeline import (
    INPUT_FILE,
    SUPER_MSA_FILE,
    Hooks,
    StepResult,
    StepStatus,
    parse_concatenation_order,
    prepare_job_dir,
    run_aligners,
    run_concatenate,
)


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    path = tmp_path / "job"
    path.mkdir()
    (path / INPUT_FILE).write_text(EXAMPLE_FASTA)
    return path


class Recorder(Hooks):
    def __init__(self) -> None:
        super().__init__()
        self.started: list[str] = []
        self.finished: list[StepResult] = []
        self.on_start = lambda name, at: self.started.append(name)
        self.on_finish = self.finished.append


def run(job_dir: Path, aligners: list[str], *, timeout: float = 10, cancel=None):  # type: ignore[no-untyped-def]
    return run_aligners(
        job_dir,
        aligners,
        deadline=time.monotonic() + timeout,
        cancel=cancel or threading.Event(),
        hooks=Recorder(),
    )


def test_all_aligners_succeed(fake_tools: Path, job_dir: Path) -> None:
    hooks = Recorder()
    results = run_aligners(
        job_dir,
        ["mafft", "muscle", "clustalw", "tcoffee"],
        deadline=time.monotonic() + 10,
        cancel=threading.Event(),
        hooks=hooks,
    )
    assert {n: r.status for n, r in results.items()} == dict.fromkeys(
        ["mafft", "muscle", "clustalw", "tcoffee"], StepStatus.SUCCEEDED
    )
    assert sorted(hooks.started) == ["clustalw", "mafft", "muscle", "tcoffee"]
    assert len(hooks.finished) == 4
    for name in ("mafft", "muscle", "clustalw", "tcoffee"):
        assert (job_dir / f"{name}.fasta").read_text() == EXAMPLE_FASTA
    assert not (job_dir / "work").exists() or not any((job_dir / "work").iterdir())
    assert "fake" in results["muscle"].stderr_tail


def test_failures_and_empty_output(
    fake_tools: Path, job_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MUSCLE", "fail")
    monkeypatch.setenv("FAKE_CLUSTALW", "empty")
    results = run(job_dir, ["mafft", "muscle", "clustalw"])
    assert results["mafft"].status is StepStatus.SUCCEEDED
    assert results["muscle"].status is StepStatus.FAILED
    assert results["muscle"].exit_code == 3
    assert results["clustalw"].status is StepStatus.FAILED
    assert not (job_dir / "muscle.fasta").exists()


def test_deadline_kills_only_slow_aligners(
    fake_tools: Path, job_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_T_COFFEE", "hang")
    started = time.monotonic()
    results = run(job_dir, ["mafft", "tcoffee"], timeout=1.5)
    assert time.monotonic() - started < 10
    assert results["mafft"].status is StepStatus.SUCCEEDED
    assert results["tcoffee"].status is StepStatus.TIMED_OUT


def test_cancel_stops_running_aligners(
    fake_tools: Path, job_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MAFFT", "hang")
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    results = run(job_dir, ["mafft"], timeout=30, cancel=cancel)
    assert results["mafft"].status is StepStatus.CANCELLED


def test_concatenate_reports_order(job_dir: Path) -> None:
    script = Path(__file__).parent / "fakes" / "concatenate.pl"
    for name in ("mafft", "tcoffee"):
        (job_dir / f"{name}.fasta").write_text(EXAMPLE_FASTA)
    result, order = run_concatenate(
        job_dir,
        ["tcoffee", "mafft"],
        script=script,
        deadline=time.monotonic() + 10,
        cancel=threading.Event(),
        hooks=Hooks(),
    )
    assert result.status is StepStatus.SUCCEEDED
    assert order == ["tcoffee", "mafft"]
    assert (job_dir / SUPER_MSA_FILE).read_text() == "phylip\n"


def test_parse_concatenation_order_real_output() -> None:
    stdout = (
        "\nHow to concatenate:\n\torder: random\n\tsize: 2 alignments\n\talignments:"
        "\n\t\t../../muscle.fasta\n\t\t../../mafft.fasta\n\toutput: superMSA.phylip \n"
    )
    assert parse_concatenation_order(stdout) == ["muscle", "mafft"]


def test_prepare_job_dir_keeps_only_input(job_dir: Path) -> None:
    (job_dir / "mafft.fasta").write_text("x")
    (job_dir / "work" / "mafft").mkdir(parents=True)
    prepare_job_dir(job_dir)
    assert [p.name for p in job_dir.iterdir()] == [INPUT_FILE]
