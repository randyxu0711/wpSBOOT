import pytest

from wpsboot.examples import EXAMPLE_FASTA
from wpsboot.fasta import FastaError, parse_fasta


def parse(text: str, max_sequences: int = 200, max_sequence_length: int = 10_000):  # type: ignore[no-untyped-def]
    return parse_fasta(text, max_sequences=max_sequences, max_sequence_length=max_sequence_length)


def errors_of(text: str, **limits: int) -> list[str]:
    with pytest.raises(FastaError) as exc:
        parse(text, **limits)
    return exc.value.errors


def test_example_parses_cleanly() -> None:
    parsed = parse(EXAMPLE_FASTA)
    assert [r.name for r in parsed.records] == [f"seq{i}" for i in range(11)]
    assert parsed.warnings == []
    # The space inside seq1 in the original sample is removed.
    assert " " not in parsed.records[1].sequence


def test_normalised_output_round_trips() -> None:
    parsed = parse(">a desc here\r\nacgt\r\nACGT\r\n\r\n>b\nTTTT\n")
    assert parsed.to_fasta() == ">a desc here\nACGTACGT\n>b\nTTTT\n"
    assert parsed.total_residues == 12
    assert parse(parsed.to_fasta()).records == parsed.records


def test_long_sequences_are_wrapped() -> None:
    parsed = parse(">a\n" + "A" * 130 + "\n>b\nC\n")
    assert parsed.to_fasta().splitlines()[1:4] == ["A" * 60, "A" * 60, "A" * 10]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", "No sequences found."),
        ("ACGT\n>a\nAC\n", "must start with a '>'"),
        (">a\nACGT\n", "At least 2 sequences"),
        (">a\nACGT\n>a\nAC\n", "Duplicate sequence name 'a'"),
        (">a\nACGT\n>\nAC\n", "#2 has no name"),
        (">a\nACGT\n>b\n\n", "'b' is empty"),
        (">a\nAC1GT\n>b\nAC\n", "invalid characters: 1"),
        (">a\x00(b\nACGT\n>c\nAC\n", "#1 contains control characters"),
        (">a\nACGT\n>b desc\x1b[31m\nAC\n", "#2 contains control characters"),
    ],
)
def test_invalid_input(text: str, expected: str) -> None:
    assert any(expected in e for e in errors_of(text))


def test_limits() -> None:
    three = ">a\nAC\n>b\nAC\n>c\nAC\n"
    assert any("limit 2" in e for e in errors_of(three, max_sequences=2))
    assert any("limit 3" in e for e in errors_of(">a\nACGT\n>b\nA\n", max_sequence_length=3))


def test_error_list_is_capped() -> None:
    text = "".join(f">s{i}\n1\n" for i in range(30))
    errors = errors_of(text)
    assert len(errors) == 11
    assert errors[-1].startswith("...and")


def test_gaps_are_removed_with_warning() -> None:
    parsed = parse(">a\nAC-G.T\n>b\nACGT\n")
    assert parsed.records[0].sequence == "ACGT"
    assert any("Gap characters" in w for w in parsed.warnings)


def test_names_colliding_after_phylip_truncation_are_rejected() -> None:
    errors = errors_of(">sequence_001\nAC\n>sequence_002\nAC\n")
    assert any("'sequence_0'" in e for e in errors)


def test_long_but_unique_names_warn() -> None:
    parsed = parse(">alpha_long_name\nAC\n>beta_long_name\nAC\n")
    assert any("truncated" in w for w in parsed.warnings)


def test_tab_in_description_is_allowed() -> None:
    parsed = parse(">a\tfrom species X\nAC\n>b\nAC\n")
    assert parsed.records[0].name == "a"


def test_risky_characters_warn() -> None:
    parsed = parse(">a:1\nAC\n>b(2)\nAC\n")
    assert any("break many tree programs" in w for w in parsed.warnings)
