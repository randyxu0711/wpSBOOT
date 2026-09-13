"""End-to-end pipeline with the real aligners and the lab's concatenate.pl (worker image only)."""

import threading
import time
from pathlib import Path

import pytest

from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.fasta import PHYLIP_NAME_LENGTH, parse_fasta
from wpsboot.pipeline import (
    ALIGNERS,
    INPUT_FILE,
    SUPER_MSA_FILE,
    Hooks,
    StepStatus,
    run_aligners,
    run_concatenate,
)

pytestmark = pytest.mark.tools

REAL_CONCATENATE = Path("/opt/wpsboot/tools/concatenate.pl")


def run_pipeline(job_dir: Path, fasta: str) -> tuple[list[str], str]:
    (job_dir / INPUT_FILE).write_text(
        parse_fasta(fasta, max_sequences=200, max_sequence_length=10_000).to_fasta()
    )
    deadline = time.monotonic() + 300
    results = run_aligners(
        job_dir, list(ALIGNERS), deadline=deadline, cancel=threading.Event(), hooks=Hooks()
    )
    for name, result in results.items():
        assert result.status is StepStatus.SUCCEEDED, f"{name}: {result.stderr_tail}"
    concat, order = run_concatenate(
        job_dir,
        list(ALIGNERS),
        script=REAL_CONCATENATE,
        deadline=deadline,
        cancel=threading.Event(),
        hooks=Hooks(),
    )
    assert concat.status is StepStatus.SUCCEEDED, concat.stderr_tail
    return order, (job_dir / SUPER_MSA_FILE).read_text()


def test_all_aligners_and_concatenate(tmp_path: Path) -> None:
    order, phylip = run_pipeline(tmp_path, EXAMPLE_FASTA)
    assert sorted(order) == sorted(ALIGNERS)
    for aligner in ALIGNERS.values():
        alignment = (tmp_path / aligner.output_file).read_text()
        assert alignment.count(">") == 11, aligner.id

    header = phylip.splitlines()[0].split()
    assert header[0] == "11"
    # The Super-MSA is every alignment laid end to end.
    assert int(header[1]) == sum(
        alignment_length(tmp_path / a.output_file) for a in ALIGNERS.values()
    )


def alignment_length(path: Path) -> int:
    first_record = path.read_text().split(">")[1]
    return sum(len(line.strip()) for line in first_record.splitlines()[1:])


def test_phylip_truncates_names_to_ten_characters(tmp_path: Path) -> None:
    """Pins the BioPerl behaviour that the FASTA name-collision check relies on."""
    fasta = (
        ">sequence_alpha\nFQTWEEFSRAAEKLYLADPMKVRVVLKYRHVDGNLCIKVTDDLVCLVYRTDQAQDVKKIEKF\n"
        ">sequence_beta\nEEYQTWEEFARAAEKLYLTDPMKVRVVLKYRHCDGNLCMKVTDDAVCLQYKTDQAQDVKKVEKLHGK\n"
        ">short\nMYQVWEEFSRAVEKLYLTDPMKVRVVLKYRHCDGNLCIKVTDNSVCLQYKTDQAQDVK\n"
    )
    _, phylip = run_pipeline(tmp_path, fasta)
    names = {line.split()[0] for line in phylip.splitlines()[1:4]}
    assert names == {"sequence_a", "sequence_b", "short"}
    assert all(len(n) <= PHYLIP_NAME_LENGTH for n in names)
