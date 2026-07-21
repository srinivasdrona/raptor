"""Assemble the real, deterministic, provisional TSC calibration batch (prd04-calibration slot 2).

Reproduces the already-recorded `clinvar_2026-07-07` VUS-run census selection
strata + exact-strength pattern catalog from the pinned manifest + BIAS
output TSV, conserves the source of record (fail-loud, before any output),
emits PRD-04-schema-conformant, provenance-complete, direction-null /
`POLICY_BLOCKED` packets, and selects a calibration batch
(`raptor.packet.queue.select_calibration_batch`) that covers every observed
pattern / gene / variant-class / edge-flag atom. Selection / evidence review
only -- never a classification.

`raptor.eval.combine.implied_direction` is imported and called **only** at
this script's module scope (never from `src/raptor/packet`) to reproduce the
census selection stratum; the basis token `eval_only_census_selection_metadata`
records that non-authoritative provenance. The packet path never imports the
eval combiner and every packet keeps `candidate_direction=null`.

ADR-0012 census extraction (D1): the pure census-selection core
(`ManifestEntry`, `StratumEntry`, `STRENGTH_MAP`, `ManifestError`,
`ConservationError`, `load_manifest`, `reproduce_census_strata`,
`_split_consequence_terms`, `_variant_class_for`) now lives in the
packet-free `raptor.census.strata` and is imported back here VERBATIM
(pure move + import) so this script's behavior is unchanged byte-for-byte.

Reused frozen public APIs only: `raptor.census.strata.*` (packet-free),
`raptor.scorer.bias_source.BiasTsvSource`,
`raptor.scorer.config.load_config`, `raptor.scorer.parse.parse_rationale`,
`raptor.eval.config.load_config`, `raptor.eval.combine.implied_direction`,
`raptor.eval.lineage_policy.load_lineage_policy` (via `load_packet_config`),
`raptor.packet.config.*`, `raptor.packet.model.*`, `raptor.packet.build.build_packet`,
`raptor.packet.queue.*`, `raptor.packet.render.render_markdown`. No KB/benchmark/
labels/knowns file is opened; no network call is made; no submission or public
worklist is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from raptor.census.strata import (
    BASIS,
    ConservationError,
    ManifestEntry,
    ManifestError,
    STRENGTH_MAP,
    StratumEntry,
    _split_consequence_terms,
    _variant_class_for,
    load_manifest,
    reproduce_census_strata,
)
from raptor.eval.combine import implied_direction
from raptor.eval.config import EvalConfig
from raptor.eval.config import load_config as load_eval_config
from raptor.packet.config import (
    PacketConfig,
    RenderConfig,
    SelectionConfig,
    load_narrative_catalog,
    load_packet_config,
    load_render_config,
    load_selection_config,
)
from raptor.packet.build import build_packet
from raptor.packet.model import (
    CandidateEvidencePacket,
    CanonicalVariantIdentity,
    MissingEvidence,
    PacketCriterionInput,
    PacketInput,
    PacketValidationError,
    PatternRef,
    PrimaryGrounding,
    RunMetadata,
    ScorerProvenance,
    SourceSnapshotPins,
)
from raptor.packet.queue import Batch, build_queue_index, select_calibration_batch
from raptor.packet.render import render_markdown
from raptor.packet.model import PacketView
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import ScorerConfig
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.model import BiasRecord, CriterionCall
from raptor.scorer.parse import parse_rationale

# --------------------------------------------------------------------------
# Pinned constants (slot 2)
# --------------------------------------------------------------------------
#
# `BASIS`, `STRENGTH_MAP`, `ManifestEntry`, `StratumEntry`, `ManifestError`,
# `ConservationError`, `load_manifest`, and `reproduce_census_strata` moved
# to `raptor.census.strata` (ADR-0012 D1) and are imported above -- this
# script no longer defines them locally.

#: Pinned batch + census-manifest limitations (CAL-AC5), fixed order.
LIMITATIONS: tuple[str, ...] = (
    "bias_bp4_pp3_aggregation_defect",
    "aavc_comparator_omitted",
    "candidate_direction_null_policy_blocked",
    "primary_grounding_absent",
    "transcript_version_drift",
    "nthl1_misannotation",
)

#: Per-gene production MANE `.5` transcript identity (independent of the raw
#: `.4` BIAS transcript -- see `transcript_version_drift`).
_GENE_MANE_TRANSCRIPTS: Mapping[str, str] = {
    "TSC1": "NM_000368.5",
    "TSC2": "NM_000548.5",
}

_PRIMARY_REQUIRED_REASON = "no_primary_literature_or_ps3_assay"
_NOT_REQUIRED_REASON = "primary_not_required_by_policy"

_HEX64_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
_HEX40_RE = __import__("re").compile(r"^[0-9a-f]{40}$")


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _is_hex40(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX40_RE.fullmatch(value))


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------
# Typed failures
# --------------------------------------------------------------------------


class OutputBoundaryError(RuntimeError):
    """`--output-dir` is missing or resolves inside the repository tree
    (CAL-AC8) -- refused before any write."""


# --------------------------------------------------------------------------
# 0. Exact input value objects
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunPins:
    """Real-run identity + worker-version pins, cross-checked against the
    census/audit pins by `assert_source_of_record_conservation`."""

    input_sha256: str
    output_sha256: str
    manifest_sha256: str
    source_snapshot: str
    bias_version: str
    bias_commit: str
    nirvana_version: str
    code_commit: str

    def __post_init__(self) -> None:
        for name in ("input_sha256", "output_sha256", "manifest_sha256"):
            if not _is_hex64(getattr(self, name)):
                raise ValueError(f"RunPins.{name} must be lowercase hex-64")
        if not _is_hex40(self.bias_commit):
            raise ValueError("RunPins.bias_commit must be lowercase hex-40")
        for name in ("source_snapshot", "bias_version", "nirvana_version", "code_commit"):
            if not _non_blank(getattr(self, name)):
                raise ValueError(f"RunPins.{name} must be non-blank")


# --------------------------------------------------------------------------
# 1. Census-stratum reproduction (eval-only, outside the packet path)
# --------------------------------------------------------------------------
#
# `StratumEntry`, `load_manifest`, and `reproduce_census_strata` moved to
# `raptor.census.strata` (ADR-0012 D1) and are imported above -- this script
# no longer defines them locally, and reuses them verbatim.


# --------------------------------------------------------------------------
# 2. Fail-loud source-of-record conservation
# --------------------------------------------------------------------------


def assert_source_of_record_conservation(
    manifest: Sequence[ManifestEntry],
    bias_rows: Sequence[BiasRecord],
    strata: Sequence[StratumEntry],
    census_stats: Mapping[str, Any],
    provenance: RunPins,
) -> None:
    """Raise `ConservationError` (naming expected vs actual) unless the
    manifest/BIAS-row/strata counts and source hashes/versions exactly match
    the pinned census (CAL-AC1). Runs before any output is written."""
    manifest = tuple(manifest)
    bias_rows = tuple(bias_rows)
    strata = tuple(strata)

    expected_identities = census_stats["corpus"]["total_vus"]
    if len(manifest) != expected_identities:
        raise ConservationError(
            f"manifest identity count drift: expected {expected_identities}, got {len(manifest)}"
        )
    unique_variant_ids = {entry.variant_id for entry in manifest}
    if len(unique_variant_ids) != expected_identities:
        raise ConservationError(
            f"manifest variant_id duplicates: expected {expected_identities} unique ids, "
            f"got {len(unique_variant_ids)}"
        )

    expected_bias_rows = census_stats["run_integrity"]["bias_rows"]
    if len(bias_rows) != expected_bias_rows:
        raise ConservationError(
            f"BIAS row count drift: expected {expected_bias_rows}, got {len(bias_rows)}"
        )
    unique_raw_keys = {row.variant_id for row in bias_rows}
    expected_unique_keys = census_stats["run_integrity"]["unique_raw_keys"]
    if len(unique_raw_keys) != expected_unique_keys:
        raise ConservationError(
            f"BIAS raw row key duplicates: expected {expected_unique_keys} unique keys, "
            f"got {len(unique_raw_keys)}"
        )

    manifest_vcf_keys = {entry.vcf_key for entry in manifest}
    if manifest_vcf_keys != unique_raw_keys:
        missing_from_manifest = sorted(unique_raw_keys - manifest_vcf_keys)
        missing_from_bias = sorted(manifest_vcf_keys - unique_raw_keys)
        raise ConservationError(
            "manifest vcf_key set does not exactly match the BIAS-row locus set (SPDI join): "
            f"{len(missing_from_manifest)} BIAS loci missing a manifest entry "
            f"(e.g. {missing_from_manifest[:5]!r}); {len(missing_from_bias)} manifest entries with "
            f"no matching BIAS row (e.g. {missing_from_bias[:5]!r})"
        )

    lp_count = sum(1 for entry in strata if entry.stratum == "candidate_LP_review")
    expected_lp = census_stats["raptor_current_policy_internal_direction"]["candidate_LP_review"]
    if lp_count != expected_lp:
        raise ConservationError(f"candidate_LP_review count drift: expected {expected_lp}, got {lp_count}")

    lb_count = sum(1 for entry in strata if entry.stratum == "candidate_LB_review")
    expected_lb = census_stats["raptor_current_policy_internal_direction"]["candidate_LB_review"]
    if lb_count != expected_lb:
        raise ConservationError(f"candidate_LB_review count drift: expected {expected_lb}, got {lb_count}")

    lp_patterns = {entry.pattern_id for entry in strata if entry.stratum == "candidate_LP_review"}
    expected_lp_patterns = census_stats["candidate_pattern_compression"]["candidate_LP_review"][
        "exact_strength_patterns"
    ]
    if len(lp_patterns) != expected_lp_patterns:
        raise ConservationError(
            f"candidate_LP_review exact-strength pattern count drift: expected "
            f"{expected_lp_patterns}, got {len(lp_patterns)}"
        )

    lb_patterns = {entry.pattern_id for entry in strata if entry.stratum == "candidate_LB_review"}
    expected_lb_patterns = census_stats["candidate_pattern_compression"]["candidate_LB_review"][
        "exact_strength_patterns"
    ]
    if len(lb_patterns) != expected_lb_patterns:
        raise ConservationError(
            f"candidate_LB_review exact-strength pattern count drift: expected "
            f"{expected_lb_patterns}, got {len(lb_patterns)}"
        )

    expected_input_sha = census_stats["run_integrity"]["input_vcf_sha256"]
    if provenance.input_sha256 != expected_input_sha:
        raise ConservationError(
            f"input VCF sha256 drift: expected {expected_input_sha}, got {provenance.input_sha256}"
        )
    expected_output_sha = census_stats["run_integrity"]["bias_tsv_sha256"]
    if provenance.output_sha256 != expected_output_sha:
        raise ConservationError(
            f"BIAS output TSV sha256 drift: expected {expected_output_sha}, got {provenance.output_sha256}"
        )

    expected_bias_version = census_stats["worker"]["bias"]
    if provenance.bias_version != expected_bias_version:
        raise ConservationError(
            f"BIAS worker version drift: expected {expected_bias_version}, got {provenance.bias_version}"
        )
    expected_bias_commit = census_stats["worker"]["bias_commit"]
    if provenance.bias_commit != expected_bias_commit:
        raise ConservationError(
            f"BIAS worker commit drift: expected {expected_bias_commit}, got {provenance.bias_commit}"
        )
    expected_nirvana = census_stats["worker"]["nirvana"]
    if provenance.nirvana_version != expected_nirvana:
        raise ConservationError(
            f"Nirvana worker version drift: expected {expected_nirvana}, got {provenance.nirvana_version}"
        )


# --------------------------------------------------------------------------
# 3. Real scorer provenance + edge flags
# --------------------------------------------------------------------------


def build_scorer_provenance(bias_row: BiasRecord, run_pins: RunPins) -> ScorerProvenance:
    """One real `ScorerProvenance` for `bias_row` -- never a `PrimaryEvidenceRef`.
    `transcript` is the RAW BIAS transcript, recorded verbatim."""
    raw_row = bias_row.provenance["raw_row"]
    return ScorerProvenance(
        bias_row_key=bias_row.variant_id,
        chromosome=bias_row.chromosome,
        position=bias_row.position,
        ref=bias_row.ref_allele,
        alt=bias_row.alt_allele,
        scorer_run_id=f"{run_pins.source_snapshot}:{run_pins.code_commit}",
        input_sha256=run_pins.input_sha256,
        output_sha256=run_pins.output_sha256,
        raw_row_sha256=hashlib.sha256(str(raw_row).encode("utf-8")).hexdigest(),
        bias_version=run_pins.bias_version,
        bias_commit=run_pins.bias_commit,
        nirvana_version=run_pins.nirvana_version,
        transcript=bias_row.transcript,
    )


def derive_quality_flags(
    bias_row: BiasRecord,
    identity: CanonicalVariantIdentity,
    calls: Sequence[CriterionCall],
) -> tuple[str, ...]:
    """Observed edge flags (sorted, deduped) -- BP4/PP3 aggregation and any
    other real contradiction are preserved, never silently corrected."""
    flags: set[str] = set()
    if bias_row.gene_name == "NTHL1":
        flags.add("nthl1_misannotation")
    if bias_row.transcript != identity.transcript:
        flags.add("transcript_version_drift")

    directions = {call.direction for call in calls}
    if "pathogenic" in directions and "benign" in directions:
        flags.add("contradiction")

    criteria = {call.criterion for call in calls}
    if "BP4" in criteria and "PP3" in criteria:
        flags.add("bp4_pp3_computational_aggregation")

    for call in calls:
        if call.criterion == "BS2" and not call.rationale.strip():
            flags.add("bs2_no_rationale")

    return tuple(sorted(flags))


# --------------------------------------------------------------------------
# 4. Packet assembly (direction-null, POLICY_BLOCKED)
# --------------------------------------------------------------------------


# `_split_consequence_terms` and `_variant_class_for` moved to
# `raptor.census.strata` (ADR-0012 D1) and are imported above; only
# `_primary_consequence` (packet-only, raises `PacketValidationError`) stays.


def _primary_consequence(consequence: str) -> str:
    terms = _split_consequence_terms(consequence)
    if not terms:
        raise PacketValidationError(f"BIAS row consequence is blank: {consequence!r}")
    return ",".join(terms)


def _hex64_of_obj(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def build_packet_input(
    identity: CanonicalVariantIdentity,
    bias_row: BiasRecord,
    stratum_entry: StratumEntry,
    packet_config: PacketConfig,
    run_pins: RunPins,
) -> PacketInput:
    """Every fired BIAS criterion becomes exactly one `PacketCriterionInput`
    (not just the direction-contributing/automatable subset), each carrying
    exactly one real `ScorerProvenance`. PS3/literature is the only
    primary-required criterion in this batch (`primary_grounding=ABSENT`);
    every other fired criterion is `primary_grounding=NOT_REQUIRED`."""
    if stratum_entry.variant_id != identity.canonical_spdi:
        raise PacketValidationError(
            "build_packet_input: stratum_entry.variant_id "
            f"{stratum_entry.variant_id!r} does not match identity.canonical_spdi "
            f"{identity.canonical_spdi!r}"
        )

    calls = parse_rationale(bias_row.criteria, STRENGTH_MAP)
    if not calls:
        raise PacketValidationError(
            f"BIAS row {bias_row.variant_id!r} fired no criteria -- cannot build a packet"
        )

    quality_flags = derive_quality_flags(bias_row, identity, calls)
    scorer_provenance = build_scorer_provenance(bias_row, run_pins)

    criterion_inputs = []
    for call in calls:
        if call.criterion in packet_config.primary_required_criteria:
            grounding = PrimaryGrounding.ABSENT
            reason = _PRIMARY_REQUIRED_REASON
        else:
            grounding = PrimaryGrounding.NOT_REQUIRED
            reason = _NOT_REQUIRED_REASON
        criterion_inputs.append(
            PacketCriterionInput(
                criterion=call.criterion,
                strength=call.strength,
                direction=call.direction,
                rationale=call.rationale,
                scorer_provenance=scorer_provenance,
                primary_evidence_refs=(),
                primary_grounding=grounding,
                primary_grounding_reason=reason,
            )
        )
    criterion_inputs.sort(key=lambda item: item.criterion)

    packet_config_fingerprint = _hex64_of_obj({
        "packet_schema_version": packet_config.packet_schema_version,
        "config_version": packet_config.config_version,
        "lineage_policy_sha256": packet_config.lineage_policy_sha256,
        "candidate_policy_sha256": packet_config.candidate_policy_sha256,
    })
    run_metadata = RunMetadata(
        run_id=f"tsc-calibration-batch:{run_pins.source_snapshot}",
        generated_at="1970-01-01T00:00:00Z",
        code_commit=run_pins.code_commit,
        packet_config_sha256=packet_config_fingerprint,
        lineage_policy_sha256=packet_config.lineage_policy_sha256,
        candidate_policy_sha256=packet_config.candidate_policy_sha256,
    )

    snapshot_date = (
        run_pins.source_snapshot.rsplit("_", 1)[-1]
        if "_" in run_pins.source_snapshot
        else run_pins.source_snapshot
    )
    source_snapshot = SourceSnapshotPins(
        snapshot_id=run_pins.source_snapshot,
        snapshot_date=snapshot_date,
        clinvar_sha256=run_pins.input_sha256,
        bias_output_sha256=run_pins.output_sha256,
        manifest_sha256=run_pins.manifest_sha256,
    )

    missing_evidence = (
        MissingEvidence(
            category="functional_validation",
            next_action=(
                "obtain a PS3 functional-assay or primary-literature source before "
                "external readiness"
            ),
            supporting_field_paths=("entries.primary_grounding",),
        ),
    )

    pattern_ref = None
    if stratum_entry.pattern_id:
        pattern_ref = PatternRef(
            census_snapshot_id=run_pins.source_snapshot,
            pattern_id=stratum_entry.pattern_id,
            census_selection_stratum=stratum_entry.stratum,
            pattern_signature=stratum_entry.pattern_signature,
            member_count=1,
        )

    return PacketInput(
        identity=identity,
        criterion_inputs=tuple(criterion_inputs),
        run_metadata=run_metadata,
        source_snapshot=source_snapshot,
        quality_flags=quality_flags,
        missing_evidence=missing_evidence,
        pattern_ref=pattern_ref,
        external_comparators=(),
        predecessor_packet_id=None,
        predecessor_envelope_hash=None,
    )


def build_candidate_universe(
    strata: Sequence[StratumEntry],
    bias_rows: Sequence[BiasRecord],
    manifest: Sequence[ManifestEntry],
    packet_config: PacketConfig,
    run_pins: RunPins,
) -> tuple[CandidateEvidencePacket, ...]:
    """Build exactly the LP+LB candidate universe via `build_packet`; NTHL1
    manual_review + no_deterministic_resolution variants never enter it. The
    result is sorted by `packet_id`, so re-running with any input-sequence
    permutation is byte-identical (CAL-AC6)."""
    manifest_by_variant_id = {entry.variant_id: entry for entry in manifest}
    bias_by_vcf_key = {row.variant_id: row for row in bias_rows}
    pattern_member_counts = Counter(entry.pattern_id for entry in strata if entry.pattern_id)

    packets: list[CandidateEvidencePacket] = []
    for stratum_entry in strata:
        if stratum_entry.stratum not in ("candidate_LP_review", "candidate_LB_review"):
            continue

        manifest_entry = manifest_by_variant_id.get(stratum_entry.variant_id)
        if manifest_entry is None:
            raise ConservationError(
                f"stratum variant_id {stratum_entry.variant_id!r} has no manifest entry"
            )
        bias_row = bias_by_vcf_key.get(manifest_entry.vcf_key)
        if bias_row is None:
            raise ConservationError(
                f"manifest vcf_key {manifest_entry.vcf_key!r} has no matching BIAS row"
            )

        gene = bias_row.gene_name
        transcript = _GENE_MANE_TRANSCRIPTS.get(gene)
        if transcript is None:
            raise PacketValidationError(f"no MANE transcript pin configured for gene {gene!r}")

        identity = CanonicalVariantIdentity(
            canonical_spdi=manifest_entry.variant_id,
            gene=gene,
            transcript=transcript,
            consequence=_primary_consequence(bias_row.consequence),
            variant_class=_variant_class_for(bias_row.consequence),
        )

        packet_input = build_packet_input(identity, bias_row, stratum_entry, packet_config, run_pins)
        if packet_input.pattern_ref is not None:
            packet_input = replace(
                packet_input,
                pattern_ref=replace(
                    packet_input.pattern_ref,
                    member_count=pattern_member_counts[stratum_entry.pattern_id],
                ),
            )

        packets.append(build_packet(packet_input, packet_config))

    packets.sort(key=lambda packet: packet.packet_id)
    return tuple(packets)


# --------------------------------------------------------------------------
# 5. Selection + coverage assertion
# --------------------------------------------------------------------------


def select_batch(
    universe: Sequence[CandidateEvidencePacket], selection_config: SelectionConfig
) -> Batch:
    """PRD-04 FR17 deterministic set-cover selection (seed pinned by config)."""
    return select_calibration_batch(universe, selection_config)


def assert_batch_coverage(batch: Batch, strata: Sequence[StratumEntry]) -> None:
    """Fail loud unless the batch coverage proves every populated atom (per
    independent dimension) is covered, `missing` is empty on every dimension,
    and no impossible/unpopulated cell was declared covered/selected."""
    for dimension, atoms in batch.coverage.missing.items():
        if atoms:
            raise ConservationError(
                f"batch coverage is missing populated atom(s) for dimension {dimension!r}: {atoms}"
            )
    for dimension, atoms in batch.coverage.impossible_unpopulated.items():
        if atoms:
            raise ConservationError(
                f"selection declared impossible/unpopulated atom(s) for dimension {dimension!r} "
                f"that were never actually observed: {atoms}"
            )

    observed_patterns = {entry.pattern_id for entry in strata if entry.pattern_id}
    covered_patterns = set(batch.coverage.covered.get("pattern", ()))
    uncovered = observed_patterns - covered_patterns
    if uncovered:
        raise ConservationError(
            f"pattern(s) observed in the reproduced strata are not covered by the batch: {sorted(uncovered)}"
        )


# --------------------------------------------------------------------------
# 6. Output writers (outside repo) + in-repo aggregate
# --------------------------------------------------------------------------


def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _normalize_for_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_normalize_for_json(item) for item in value]
    return value


def canonical_json(obj: Any) -> str:
    """Deterministic canonical JSON: `sort_keys=True`, compact separators,
    UTF-8, trailing newline (CAL-AC6)."""
    normalized = _normalize_for_json(obj)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


#: This script's fixed location is `<repo>/scripts/build_tsc_calibration_batch.py`,
#: so the repo root is always this file's grandparent -- never the caller's
#: current working directory (CAL-AC8 boundary checks must hold regardless
#: of cwd).
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _assert_output_boundary(output_dir: Path) -> Path:
    repo_root = _REPO_ROOT
    resolved = output_dir.resolve()
    if resolved == repo_root or repo_root in resolved.parents:
        raise OutputBoundaryError(
            f"--output-dir must be outside the repository tree ({repo_root}); got {resolved}"
        )
    return resolved


def assert_census_record_boundary(path: str | Path) -> Path:
    """Refuse any `--emit-census-record` path except a direct `.json` child
    of `<repo>/data/census` (never nested, never another extension, never
    another in-repo directory, never outside the repo) -- raised before any
    aggregate write (CAL-AC8)."""
    census_dir = (_REPO_ROOT / "data" / "census").resolve()
    resolved = Path(path).resolve()
    if resolved.parent != census_dir or resolved.suffix != ".json":
        raise OutputBoundaryError(
            f"--emit-census-record must be a direct .json child of {census_dir}; got {resolved}"
        )
    return resolved


def write_outputs(
    output_dir: str | Path,
    batch: Batch,
    render_config: RenderConfig,
    batch_manifest: Mapping[str, Any],
) -> None:
    """Write the operator packet JSONs, `FIRST_PASS` Markdown, reviewer
    queue, coverage report, and batch manifest under `output_dir` (must be
    outside the repo tree, CAL-AC8). All writes are byte-deterministic;
    packet ordering is by `packet_id`."""
    resolved = _assert_output_boundary(Path(output_dir))

    packet_by_id = {packet.packet_id: packet for packet in batch.packets}
    selected_ids = tuple(sorted(batch.selected_packet_ids))
    selected_packets = [packet_by_id[packet_id] for packet_id in selected_ids]

    packets_dir = resolved / "packets"
    first_pass_dir = resolved / "first_pass"
    queue_dir = resolved / "queue"
    coverage_dir = resolved / "coverage"
    for directory in (resolved, packets_dir, first_pass_dir, queue_dir, coverage_dir):
        directory.mkdir(parents=True, exist_ok=True)

    for packet_id, packet in zip(selected_ids, selected_packets):
        (packets_dir / f"{packet_id}.json").write_text(canonical_json(packet), encoding="utf-8")
        markdown = render_markdown(packet, render_config, view=PacketView.FIRST_PASS)
        (first_pass_dir / f"{packet_id}.md").write_text(markdown, encoding="utf-8")

    queue_index = build_queue_index(selected_packets, render_config)
    (queue_dir / "tsc_calibration_queue.csv").write_text(queue_index.to_csv(), encoding="utf-8")
    (queue_dir / "tsc_calibration_queue.jsonl").write_text(queue_index.to_jsonl(), encoding="utf-8")

    (coverage_dir / "coverage_report.json").write_text(canonical_json(batch.coverage), encoding="utf-8")
    (resolved / "batch_manifest.json").write_text(canonical_json(batch_manifest), encoding="utf-8")


def build_batch_manifest(
    universe: Sequence[CandidateEvidencePacket],
    batch: Batch,
    packet_config: PacketConfig,
    selection_config: SelectionConfig,
    render_config: RenderConfig,
    run_pins: RunPins,
    census_stats: Mapping[str, Any],
    lineage_audit: Mapping[str, Any],
) -> dict:
    """Source/config hashes, code_commit, run pins, the conservation record,
    `selected_packet_ids`, a coverage summary, and the pinned `limitations`."""
    conservation = {
        "manifest_identities": census_stats["corpus"]["total_vus"],
        "bias_rows": census_stats["run_integrity"]["bias_rows"],
        "candidate_LP_review": census_stats["raptor_current_policy_internal_direction"][
            "candidate_LP_review"
        ],
        "candidate_LB_review": census_stats["raptor_current_policy_internal_direction"][
            "candidate_LB_review"
        ],
        "lp_patterns": census_stats["candidate_pattern_compression"]["candidate_LP_review"][
            "exact_strength_patterns"
        ],
        "lb_patterns": census_stats["candidate_pattern_compression"]["candidate_LB_review"][
            "exact_strength_patterns"
        ],
    }
    coverage = {
        "populated": {k: list(v) for k, v in batch.coverage.populated.items()},
        "covered": {k: list(v) for k, v in batch.coverage.covered.items()},
        "impossible_unpopulated": {k: list(v) for k, v in batch.coverage.impossible_unpopulated.items()},
        "missing": {k: list(v) for k, v in batch.coverage.missing.items()},
    }
    return {
        "schema_version": "1",
        "code_commit": run_pins.code_commit,
        "run_pins": {
            "bias_version": run_pins.bias_version,
            "bias_commit": run_pins.bias_commit,
            "nirvana_version": run_pins.nirvana_version,
            "source_snapshot": run_pins.source_snapshot,
        },
        "source_hashes": {
            "input_vcf_sha256": run_pins.input_sha256,
            "bias_tsv_sha256": run_pins.output_sha256,
            "manifest_sha256": run_pins.manifest_sha256,
        },
        "config_hashes": {
            "packet_config_lineage_policy_sha256": packet_config.lineage_policy_sha256,
            "packet_config_candidate_policy_sha256": packet_config.candidate_policy_sha256,
            "selection_config_sha256": _hex64_of_obj({
                "config_version": selection_config.config_version,
                "census_snapshot_id": selection_config.census_snapshot_id,
                "seed": selection_config.seed,
                "required_dimensions": list(selection_config.required_dimensions),
            }),
            "render_config_sha256": _hex64_of_obj({
                "config_version": render_config.config_version,
                "non_authoritative_marker": render_config.non_authoritative_marker,
                "first_pass_heading": render_config.first_pass_heading,
                "operator_heading": render_config.operator_heading,
                "reconciliation_heading": render_config.reconciliation_heading,
            }),
        },
        "universe_size": len(universe),
        "conservation": conservation,
        "selected_packet_ids": list(selected_ids_sorted := sorted(batch.selected_packet_ids)),
        "coverage": coverage,
        "lineage_audit": dict(lineage_audit),
        "limitations": list(LIMITATIONS),
    }


def build_census_source_of_record(batch_manifest: Mapping[str, Any]) -> dict:
    """AGGREGATE, NON-IDENTIFYING projection of `batch_manifest`: counts,
    pattern-catalog sizes, selected-batch SIZE (never the per-packet id
    list), source/config hashes, and limitations. No per-variant SPDI."""
    census = {key: value for key, value in batch_manifest.items() if key != "selected_packet_ids"}
    census["selected_batch_size"] = len(batch_manifest.get("selected_packet_ids", ()))
    return census


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _resolve_code_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if commit else "unknown"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the real, deterministic, provisional TSC calibration batch"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bias-tsv", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--census-stats", required=True)
    parser.add_argument("--lineage-audit", required=True)
    parser.add_argument("--packet-config", required=True)
    parser.add_argument("--selection-config", required=True)
    parser.add_argument("--render-config", required=True)
    parser.add_argument("--narrative-catalog", required=True)
    parser.add_argument("--scorer-config", required=True)
    parser.add_argument("--eval-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--aavc-comparator", default=None)
    parser.add_argument("--emit-census-record", default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    output_dir = Path(args.output_dir)
    try:
        _assert_output_boundary(output_dir)
    except OutputBoundaryError as exc:
        print(f"calibration batch build aborted: {exc}", file=sys.stderr)
        return 1

    emit_census_path: Path | None = None
    if args.emit_census_record:
        try:
            emit_census_path = assert_census_record_boundary(args.emit_census_record)
        except OutputBoundaryError as exc:
            print(f"calibration batch build aborted: {exc}", file=sys.stderr)
            return 1

    manifest = load_manifest(args.manifest)
    bias_rows = tuple(BiasTsvSource(args.bias_tsv).records())
    provenance_raw = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
    census_stats = json.loads(Path(args.census_stats).read_text(encoding="utf-8"))
    lineage_audit = json.loads(Path(args.lineage_audit).read_text(encoding="utf-8"))

    scorer_config = load_scorer_config(args.scorer_config)
    eval_config = load_eval_config(args.eval_config)
    packet_config = load_packet_config(args.packet_config)
    selection_config = load_selection_config(args.selection_config)
    render_config = load_render_config(args.render_config)
    load_narrative_catalog(args.narrative_catalog)

    run_pins = RunPins(
        input_sha256=str(provenance_raw["vcf_hash"]),
        output_sha256=hashlib.sha256(Path(args.bias_tsv).read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest(),
        source_snapshot=str(provenance_raw["source_snapshot"]),
        bias_version=str(census_stats["worker"]["bias"]),
        bias_commit=str(census_stats["worker"]["bias_commit"]),
        nirvana_version=str(census_stats["worker"]["nirvana"]),
        code_commit=_resolve_code_commit(),
    )

    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest}
    strata = reproduce_census_strata(bias_rows, manifest_by_vcf_key, scorer_config, eval_config)

    try:
        assert_source_of_record_conservation(manifest, bias_rows, strata, census_stats, run_pins)
    except ConservationError as exc:
        print(f"calibration batch build aborted: {exc}", file=sys.stderr)
        return 1

    universe = build_candidate_universe(strata, bias_rows, manifest, packet_config, run_pins)
    batch = select_batch(universe, selection_config)

    try:
        assert_batch_coverage(batch, strata)
    except ConservationError as exc:
        print(f"calibration batch build aborted: {exc}", file=sys.stderr)
        return 1

    batch_manifest = build_batch_manifest(
        universe, batch, packet_config, selection_config, render_config,
        run_pins, census_stats, lineage_audit,
    )

    try:
        write_outputs(output_dir, batch, render_config, batch_manifest)
    except OutputBoundaryError as exc:
        print(f"calibration batch build aborted: {exc}", file=sys.stderr)
        return 1

    if emit_census_path is not None:
        census_record = build_census_source_of_record(batch_manifest)
        emit_census_path.parent.mkdir(parents=True, exist_ok=True)
        emit_census_path.write_text(canonical_json(census_record), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
