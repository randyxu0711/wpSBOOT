"""Parse, validate and normalise user-submitted FASTA before it reaches the aligners."""

import re
import unicodedata
from dataclasses import dataclass, field

# BioPerl's PHYLIP writer truncates sequence names to this many characters.
PHYLIP_NAME_LENGTH = 10
# Characters that break PHYLIP/Newick parsing in common downstream tree software.
RISKY_NAME_CHARS = frozenset(":,()[];'\"")
RESIDUE_RE = re.compile(r"[A-Za-z*]+")
GAP_CHARS = "-."
MAX_REPORTED_ERRORS = 10


@dataclass(frozen=True)
class Record:
    name: str
    header: str
    sequence: str


@dataclass
class ParsedFasta:
    records: list[Record]
    warnings: list[str] = field(default_factory=list)

    @property
    def total_residues(self) -> int:
        return sum(len(r.sequence) for r in self.records)

    def to_fasta(self, width: int = 60) -> str:
        lines: list[str] = []
        for record in self.records:
            lines.append(f">{record.header}")
            seq = record.sequence
            lines.extend(seq[i : i + width] for i in range(0, len(seq), width))
        return "\n".join(lines) + "\n"


class FastaError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_fasta(text: str, *, max_sequences: int, max_sequence_length: int) -> ParsedFasta:
    """Parse FASTA text. Raises FastaError listing every problem found (capped)."""
    errors: list[str] = []
    warnings: list[str] = []
    raw = _split_records(text.lstrip("﻿"), errors)

    records: list[Record] = []
    seen: set[str] = set()
    gaps_removed = False
    for index, (header, seq_lines) in enumerate(raw, start=1):
        if any(unicodedata.category(c) == "Cc" and c != "\t" for c in header):
            errors.append(f"Sequence #{index} contains control characters in its header line.")
            header = "".join(c for c in header if unicodedata.category(c) != "Cc" or c == "\t")
        name = header.split()[0] if header.split() else ""
        label = f"'{name}'" if name else f"#{index}"
        if not name:
            errors.append(f"Sequence #{index} has no name after '>'.")
        elif name in seen:
            errors.append(f"Duplicate sequence name {label}.")
        seen.add(name)

        sequence = "".join("".join(seq_lines).split())
        if any(c in GAP_CHARS for c in sequence):
            gaps_removed = True
            sequence = sequence.translate(str.maketrans("", "", GAP_CHARS))
        if not sequence:
            errors.append(f"Sequence {label} is empty.")
        elif not RESIDUE_RE.fullmatch(sequence):
            bad = sorted({c for c in sequence if not RESIDUE_RE.fullmatch(c)})
            errors.append(f"Sequence {label} contains invalid characters: {' '.join(bad)}")
        elif len(sequence) > max_sequence_length:
            errors.append(
                f"Sequence {label} is {len(sequence)} residues long (limit {max_sequence_length})."
            )
        records.append(Record(name=name, header=header, sequence=sequence.upper()))

    if raw and len(records) < 2:
        errors.append("At least 2 sequences are required.")
    if len(records) > max_sequences:
        errors.append(f"{len(records)} sequences submitted (limit {max_sequences}).")

    if not errors:
        errors.extend(_name_errors(records, warnings))
    if gaps_removed:
        warnings.append("Gap characters ('-' or '.') were removed; input should be unaligned.")
    if errors:
        if len(errors) > MAX_REPORTED_ERRORS:
            hidden = len(errors) - MAX_REPORTED_ERRORS
            errors = [*errors[:MAX_REPORTED_ERRORS], f"...and {hidden} more problems."]
        raise FastaError(errors)
    return ParsedFasta(records=records, warnings=warnings)


def _split_records(text: str, errors: list[str]) -> list[tuple[str, list[str]]]:
    records: list[tuple[str, list[str]]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith(">"):
            records.append((stripped[1:].strip(), []))
        elif not records:
            errors.append(f"Line {line_no}: FASTA must start with a '>' header line.")
            return []
        else:
            records[-1][1].append(stripped)
    if not records and not errors:
        errors.append("No sequences found.")
    return records


def _name_errors(records: list[Record], warnings: list[str]) -> list[str]:
    errors: list[str] = []
    by_short: dict[str, list[str]] = {}
    for record in records:
        by_short.setdefault(record.name[:PHYLIP_NAME_LENGTH], []).append(record.name)
    for short, names in by_short.items():
        if len(names) > 1:
            errors.append(
                f"Names {', '.join(names)} all become '{short}' in the PHYLIP output "
                f"(names are cut to {PHYLIP_NAME_LENGTH} characters). Please rename them."
            )
    long_names = [r.name for r in records if len(r.name) > PHYLIP_NAME_LENGTH]
    if long_names and not errors:
        warnings.append(
            f"{len(long_names)} sequence name(s) are longer than {PHYLIP_NAME_LENGTH} characters "
            "and will be truncated in superMSA.phylip."
        )
    risky = [r.name for r in records if RISKY_NAME_CHARS.intersection(r.name)]
    if risky:
        warnings.append(
            "Some names contain characters that break many tree programs "
            f"(: , ( ) [ ] ; quotes): {', '.join(risky[:5])}" + ("..." if len(risky) > 5 else "")
        )
    return errors
