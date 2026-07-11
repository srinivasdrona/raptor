"""PRD-04 Task B `queue.py` — CSV/JSONL queue index + calibration-batch
selection (FR11/FR13/FR17).

`build_queue_index` is built **only** from the `FIRST_PASS` projection
(`redact_for_first_pass`) — the queue/reviewer-delivery surface never
consumes `packet.candidate_direction` / `packet.pattern_ref` /
`packet.external_comparators` (FR14.1/AC20); `QueueRow` has no candidate
direction, points, policy id, pattern stratum, or comparator field at all.

`select_calibration_batch` / `coverage_report` implement FR17: deterministic
set coverage over the **populated observed atoms** of four independent
dimensions (`pattern`, `gene`, `variant_class`, `edge_flag`) — never a
Cartesian product of empty cells. The selector first covers every populated
`pattern_id`, then any remaining gene/variant-class/edge-flag atoms not
already covered as a side effect, breaking ties by
`sha256(f"{seed}:{packet_id}")`; it never reads `candidate_direction` or
`census_selection_stratum` to decide inclusion, so a re-run over the same
universe/config (in any input order) is byte-identical.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from typing import Mapping, Sequence, Tuple

from .config import RenderConfig, SelectionConfig
from .model import CandidateEvidencePacket, PacketValidationError, redact_for_first_pass

_QUEUE_FIELDS: Tuple[str, ...] = (
    "packet_id",
    "evidence_core_hash",
    "canonical_spdi",
    "gene",
    "review_state",
    "gate_status",
    "quality_flags",
    "contradiction",
)

# Joins multiple quality flags into one CSV/JSONL-safe cell; JSONL always
# carries the flags as a proper JSON array, so this only matters for CSV.
_FLAG_JOIN = "|"

# FR17: the exact, fixed set of independent coverage dimensions.
_DIMENSIONS: Tuple[str, ...] = ("pattern", "gene", "variant_class", "edge_flag")


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class QueueRow:
    """One reviewer-delivery queue row (FR11), built only from the
    `FIRST_PASS` projection. Deliberately carries **no** candidate
    direction, signed points, policy id, pattern stratum, or comparator."""

    packet_id: str
    evidence_core_hash: str
    canonical_spdi: str
    gene: str
    review_state: str
    gate_status: str
    quality_flags: Tuple[str, ...]
    contradiction: bool

    def __post_init__(self) -> None:
        for name in (
            "packet_id", "evidence_core_hash", "canonical_spdi", "gene",
            "review_state", "gate_status",
        ):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"QueueRow.{name} must be non-blank")
        if not isinstance(self.quality_flags, (list, tuple)):
            raise PacketValidationError(
                f"QueueRow.quality_flags must be a list/tuple, got {type(self.quality_flags).__name__}"
            )
        for flag in self.quality_flags:
            if not _non_blank(flag):
                raise PacketValidationError(
                    f"QueueRow.quality_flags entries must be non-blank strings, got {flag!r}"
                )
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        if not isinstance(self.contradiction, bool):
            raise PacketValidationError("QueueRow.contradiction must be a bool")


@dataclass(frozen=True)
class QueueIndex:
    """Deterministic CSV/JSONL queue index (FR11/FR13). `rows` sort by
    `(gene, canonical_spdi, packet_id)`."""

    rows: Tuple[QueueRow, ...]

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, QueueRow):
                raise PacketValidationError("QueueIndex.rows must contain only QueueRow")
        # Deterministic ordering is an invariant of the type itself, not just
        # of `build_queue_index` -- direct construction (e.g. `QueueIndex(rows=...)`)
        # must serialize identically regardless of input row order.
        rows = tuple(sorted(rows, key=lambda row: (row.gene, row.canonical_spdi, row.packet_id)))
        object.__setattr__(self, "rows", rows)

    def _row_payload(self, row: QueueRow) -> dict:
        return {
            "packet_id": row.packet_id,
            "evidence_core_hash": row.evidence_core_hash,
            "canonical_spdi": row.canonical_spdi,
            "gene": row.gene,
            "review_state": row.review_state,
            "gate_status": row.gate_status,
            "quality_flags": list(row.quality_flags),
            "contradiction": row.contradiction,
        }

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(_QUEUE_FIELDS), lineterminator="\n")
        writer.writeheader()
        for row in self.rows:
            payload = self._row_payload(row)
            payload["quality_flags"] = _FLAG_JOIN.join(row.quality_flags)
            payload["contradiction"] = "true" if row.contradiction else "false"
            writer.writerow(payload)
        return buffer.getvalue()

    def to_jsonl(self) -> str:
        lines = [
            json.dumps(self._row_payload(row), sort_keys=True, separators=(",", ":"))
            for row in self.rows
        ]
        return "".join(line + "\n" for line in lines)


def build_queue_index(
    packets: Sequence[CandidateEvidencePacket], config: RenderConfig
) -> QueueIndex:
    """Build the reviewer-delivery queue index (FR11) from **only** the
    `FIRST_PASS` projection of each packet (FR14.1/AC20)."""
    if config is None:
        raise PacketValidationError("build_queue_index requires a RenderConfig")

    rows = []
    for packet in packets:
        view = redact_for_first_pass(packet)
        rows.append(
            QueueRow(
                packet_id=view.packet_id,
                evidence_core_hash=view.evidence_core_hash,
                canonical_spdi=view.identity.canonical_spdi,
                gene=view.identity.gene,
                review_state=view.review_state.value,
                gate_status=view.gate_status.value,
                quality_flags=view.quality_flags,
                contradiction=view.contradiction,
            )
        )
    rows.sort(key=lambda row: (row.gene, row.canonical_spdi, row.packet_id))
    return QueueIndex(rows=tuple(rows))


@dataclass(frozen=True)
class CoverageReport:
    """Distinguishes `populated` (an atom observed in the corpus), `covered`
    (a populated atom included in the batch), `impossible_unpopulated` (a
    declared-but-never-observed atom -- reported, never selected), and
    `missing` (a populated atom the batch failed to cover). All four maps
    have exactly the four dimension keys; values are sorted tuples."""

    populated: Mapping[str, Tuple[str, ...]]
    covered: Mapping[str, Tuple[str, ...]]
    impossible_unpopulated: Mapping[str, Tuple[str, ...]]
    missing: Mapping[str, Tuple[str, ...]]

    def __post_init__(self) -> None:
        for name in ("populated", "covered", "impossible_unpopulated", "missing"):
            mapping = dict(getattr(self, name))
            normalized = {
                dimension: tuple(sorted(str(atom) for atom in mapping.get(dimension, ())))
                for dimension in _DIMENSIONS
            }
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True)
class Batch:
    """A calibration batch (FR13/FR17): the complete input packet universe,
    the deterministically selected packet ids, and the coverage report."""

    packets: Tuple[CandidateEvidencePacket, ...]
    selected_packet_ids: Tuple[str, ...]
    coverage: CoverageReport

    def __post_init__(self) -> None:
        object.__setattr__(self, "packets", tuple(self.packets))
        object.__setattr__(self, "selected_packet_ids", tuple(self.selected_packet_ids))
        if not isinstance(self.coverage, CoverageReport):
            raise PacketValidationError("Batch.coverage must be a CoverageReport")


def _atom_values(packet: CandidateEvidencePacket, dimension: str) -> Tuple[str, ...]:
    """The observed atom(s) `packet` contributes to `dimension`. Never reads
    `candidate_direction` or `pattern_ref.census_selection_stratum` -- only
    `pattern_id` (selection metadata, not a cutoff), `identity.gene`,
    `identity.variant_class`, and `quality_flags` (observed edge flags)."""
    if dimension == "pattern":
        return (packet.pattern_ref.pattern_id,) if packet.pattern_ref is not None else ()
    if dimension == "gene":
        return (packet.identity.gene,)
    if dimension == "variant_class":
        return (packet.identity.variant_class,)
    if dimension == "edge_flag":
        return tuple(packet.quality_flags)
    raise PacketValidationError(f"unknown coverage dimension {dimension!r}")


def _populated_atoms(
    packets: Sequence[CandidateEvidencePacket],
) -> Mapping[str, Tuple[str, ...]]:
    populated = {dimension: set() for dimension in _DIMENSIONS}
    for packet in packets:
        for dimension in _DIMENSIONS:
            populated[dimension].update(_atom_values(packet, dimension))
    return {dimension: tuple(sorted(atoms)) for dimension, atoms in populated.items()}


def coverage_report(
    all_packets: Sequence[CandidateEvidencePacket],
    selected_packets: Sequence[CandidateEvidencePacket],
    selection_config: SelectionConfig,
) -> CoverageReport:
    """Independent per-dimension coverage over populated observed atoms only
    (FR17) -- never a cross-product of empty cells."""
    if selection_config is None:
        raise PacketValidationError("coverage_report requires a SelectionConfig")

    populated = _populated_atoms(all_packets)
    covered_sets = {dimension: set() for dimension in _DIMENSIONS}
    for packet in selected_packets:
        for dimension in _DIMENSIONS:
            covered_sets[dimension].update(_atom_values(packet, dimension))

    covered = {
        dimension: tuple(sorted(covered_sets[dimension] & set(populated[dimension])))
        for dimension in _DIMENSIONS
    }
    missing = {
        dimension: tuple(sorted(set(populated[dimension]) - covered_sets[dimension]))
        for dimension in _DIMENSIONS
    }
    impossible_unpopulated = {
        dimension: tuple(
            sorted(set(selection_config.expected_atoms.get(dimension, ())) - set(populated[dimension]))
        )
        for dimension in _DIMENSIONS
    }

    return CoverageReport(
        populated=populated,
        covered=covered,
        impossible_unpopulated=impossible_unpopulated,
        missing=missing,
    )


def _tie_break_hash(seed: int, packet_id: str) -> str:
    return hashlib.sha256(f"{seed}:{packet_id}".encode("utf-8")).hexdigest()


def select_calibration_batch(
    packets: Sequence[CandidateEvidencePacket], selection_config: SelectionConfig
) -> Batch:
    """Deterministic greedy set-cover (FR17): the universe is the complete
    input packet collection. First covers every populated `pattern_id`, then
    any remaining gene/variant-class/edge-flag atoms not already covered as
    a side effect of the pattern picks, breaking ties by
    `sha256(f"{seed}:{packet_id}")`. Never uses candidate direction or
    census stratum as a cutoff; re-running with the same universe/config (in
    any order) is byte-identical."""
    if selection_config is None:
        raise PacketValidationError("select_calibration_batch requires a SelectionConfig")

    universe = tuple(packets)

    atom_candidates: dict[str, dict[str, list]] = {dimension: {} for dimension in _DIMENSIONS}
    for packet in universe:
        for dimension in _DIMENSIONS:
            for atom in _atom_values(packet, dimension):
                atom_candidates[dimension].setdefault(atom, []).append(packet)

    selected_by_id: dict[str, CandidateEvidencePacket] = {}

    def _already_covered(dimension: str, atom: str) -> bool:
        return any(atom in _atom_values(p, dimension) for p in selected_by_id.values())

    def _select_for_atom(dimension: str, atom: str) -> None:
        if _already_covered(dimension, atom):
            return
        candidates = atom_candidates[dimension][atom]
        winner = min(
            candidates,
            key=lambda p: (_tie_break_hash(selection_config.seed, p.packet_id), p.packet_id),
        )
        selected_by_id[winner.packet_id] = winner

    for atom in sorted(atom_candidates["pattern"].keys()):
        _select_for_atom("pattern", atom)
    for dimension in ("gene", "variant_class", "edge_flag"):
        for atom in sorted(atom_candidates[dimension].keys()):
            _select_for_atom(dimension, atom)

    selected_packets = tuple(sorted(selected_by_id.values(), key=lambda p: p.packet_id))
    selected_packet_ids = tuple(p.packet_id for p in selected_packets)

    coverage = coverage_report(universe, selected_packets, selection_config)

    return Batch(packets=universe, selected_packet_ids=selected_packet_ids, coverage=coverage)
