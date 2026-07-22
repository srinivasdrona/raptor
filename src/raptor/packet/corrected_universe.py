"""Corrected all-VUS expert-review packet track (D1/D5/D9/D11/D12/D13/D14/D15) --
`raptor.packet.corrected_universe`.

Assembles the FULL corrected all-VUS universe (all four census-selection
strata: `candidate_LP_review`, `candidate_LB_review`, `no_deterministic_resolution`,
`manual_review`), conserves it against the current-policy census oracle,
builds the deterministic 8-case discovery sample, and writes the run's
external-only artifacts. LP/LB reuse `build_candidate_universe` verbatim;
`no_deterministic_resolution`/`manual_review` are assembled here (never
scored, never given a `pattern_ref`, and BIAS rows that fired zero criteria
get the deterministic evidence-absent packet). Every packet -- in every
stratum -- keeps `candidate_direction=null` / `POLICY_BLOCKED`
(`configs/eval/bp4pp3_predictor_policy.json` remains `disabled_manual`);
this module never imports `raptor.eval.combine`/`harness`/`benchmark`/
`knowns` and never inspects a benchmark/KB label.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from raptor.census.strata import (
    ConservationError,
    ManifestEntry,
    STRENGTH_MAP,
    StratumEntry,
    _split_consequence_terms,
    _variant_class_for,
    reproduce_census_strata,
)
from raptor.eval.config import load_config as load_eval_config
from raptor.packet.build import bind_census_selection_metadata, build_packet
from raptor.packet.config import PacketConfig, RenderConfig
from raptor.packet.model import (
    CandidateEvidencePacket,
    CanonicalVariantIdentity,
    CensusSelectionMetadata,
    MissingEvidence,
    PacketInput,
    PacketValidationError,
    PacketView,
    RunMetadata,
    SourceSnapshotPins,
    redact_for_first_pass,
)
from raptor.packet.queue import build_queue_index
from raptor.packet.render import render_markdown
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.model import BiasRecord
from raptor.scorer.parse import parse_rationale

from scripts.build_tsc_calibration_batch import (
    RunPins,
    build_candidate_universe,
    build_packet_input,
    canonical_json,
    derive_quality_flags,
)

#: This file's fixed location is `<repo>/src/raptor/packet/corrected_universe.py`,
#: so the repo root is always this file's great-grandparent -- never the
#: caller's current working directory (output-boundary checks must hold
#: regardless of cwd).
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: The committed current-policy census oracle (fixed path, never a caller
#: parameter -- `conserve_current_policy` cross-checks actual computed
#: counts against exactly this file unless a caller-supplied override path
#: is given).
_CURRENT_POLICY_CENSUS_PATH = (
    _REPO_ROOT / "data" / "census" / "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"
)

#: Per-gene MANE `.5` transcript pin for the non-LP/LB strata assembled by
#: `build_full_vus_universe`. Includes NTHL1 (BIAS-misannotated TSC2 rows
#: pre-routed to `manual_review` by `reproduce_census_strata`, D2/D11).
_GENE_MANE_TRANSCRIPTS: Mapping[str, str] = {
    "TSC1": "NM_000368.5",
    "TSC2": "NM_000548.5",
    "NTHL1": "NM_002528.7",
}

_DISCOVERY_STRATA_ORDER: tuple[str, ...] = (
    "candidate_LP_review",
    "candidate_LB_review",
    "no_deterministic_resolution",
    "manual_review",
)
_DISCOVERY_SAMPLE_SIZE_PER_STRATUM = 2

_CANONICAL_MISSING_EVIDENCE = (
    MissingEvidence(
        category="criteria_absent",
        next_action="no fired BIAS criteria",
        supporting_field_paths=("criterion_inputs",),
    ),
)


class OutputBoundaryError(RuntimeError):
    """The corrected run's `--output-root` is missing, resolves inside the
    repository tree, or its `run_dir` already exists -- refused before any
    write."""


class DiscoverySampleError(RuntimeError):
    """A census-selection stratum has fewer than the two packets required
    by the deterministic 2+2+2+2 discovery sample."""


# --------------------------------------------------------------------------
# D5: current-policy conservation (real ManifestEntry/BiasRecord/StratumEntry
# / RunPins-derived counts against the committed census oracle)
# --------------------------------------------------------------------------


def _load_current_policy_census(census_stats_path: Optional[Path]) -> Mapping[str, Any]:
    path = Path(census_stats_path) if census_stats_path is not None else _CURRENT_POLICY_CENSUS_PATH
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return json.loads(raw.decode("utf-8"))


def conserve_current_policy(
    total_vus: int,
    lp_count: int,
    lb_count: int,
    unresolved_count: int,
    manual_count: int,
    lp_patterns: int,
    lb_patterns: int,
    *,
    census_stats_path: Optional[Path] = None,
) -> None:
    """Fail loud with `ConservationError` unless every actual, ALREADY
    computed count (never re-derived here) exactly matches the committed
    current-policy census oracle: the four strata counts, the two
    exact-strength pattern counts, and that the four strata counts sum to
    `total_vus`. Reads only `corpus.total_vus`,
    `raptor_current_policy_internal_direction.*`, and
    `candidate_pattern_compression.*.exact_strength_patterns` -- never
    `run_integrity.input_vcf_sha256`/`worker.*` (those belong to the
    unrelated, unmodified `assert_source_of_record_conservation`)."""
    census = _load_current_policy_census(census_stats_path)

    expected_total = census["corpus"]["total_vus"]
    if total_vus != expected_total:
        raise ConservationError(f"total_vus drift: expected {expected_total}, got {total_vus}")

    counts = census["raptor_current_policy_internal_direction"]
    checks = (
        ("candidate_LP_review", counts["candidate_LP_review"], lp_count),
        ("candidate_LB_review", counts["candidate_LB_review"], lb_count),
        ("no_deterministic_resolution", counts["no_deterministic_resolution"], unresolved_count),
        # D11: `annotation_manual_review` maps exactly once to `manual_count`.
        ("annotation_manual_review->manual_review", counts["annotation_manual_review"], manual_count),
    )
    for label, expected, actual in checks:
        if expected != actual:
            raise ConservationError(f"{label} count drift: expected {expected}, got {actual}")

    patterns = census["candidate_pattern_compression"]
    pattern_checks = (
        ("candidate_LP_review", patterns["candidate_LP_review"]["exact_strength_patterns"], lp_patterns),
        ("candidate_LB_review", patterns["candidate_LB_review"]["exact_strength_patterns"], lb_patterns),
    )
    for label, expected, actual in pattern_checks:
        if expected != actual:
            raise ConservationError(f"{label} exact-strength pattern count drift: expected {expected}, got {actual}")

    stratum_sum = lp_count + lb_count + unresolved_count + manual_count
    if stratum_sum != total_vus:
        raise ConservationError(
            f"stratum counts do not conserve total_vus: {lp_count}+{lb_count}+{unresolved_count}"
            f"+{manual_count}={stratum_sum} != {total_vus}"
        )


# --------------------------------------------------------------------------
# D12: deterministic evidence-absent packet for a zero-fired-criteria row
# --------------------------------------------------------------------------


def build_evidence_absent_packet(
    packet_input: PacketInput, config: Optional[PacketConfig]
) -> CandidateEvidencePacket:
    """A BIAS row that fired no criteria at all still needs a real,
    conservation-counted packet (D12). Overrides `missing_evidence` to
    exactly one canonical `criteria_absent` / `no fired BIAS criteria` entry
    regardless of `packet_input`'s own `missing_evidence`, forces
    `criterion_inputs=()`, and permits the otherwise-forbidden empty
    criteria set via `build_packet(..., allow_empty_criteria=True)`. The
    direction contract is untouched: the unapproved production predictor
    policy still resolves every packet to `candidate_direction=null` /
    `null_reason=production_policy_unapproved` / `review_state=POLICY_BLOCKED`."""
    absent_input = replace(
        packet_input, criterion_inputs=(), missing_evidence=_CANONICAL_MISSING_EVIDENCE
    )
    return build_packet(absent_input, config, allow_empty_criteria=True)


def _primary_consequence(consequence: str) -> str:
    terms = _split_consequence_terms(consequence)
    if not terms:
        raise PacketValidationError(f"BIAS row consequence is blank: {consequence!r}")
    return ",".join(terms)


def _hex64_of_obj(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _build_absent_packet_input(
    identity: CanonicalVariantIdentity,
    bias_row: BiasRecord,
    metadata: CensusSelectionMetadata,
    packet_config: PacketConfig,
    run_pins: RunPins,
) -> PacketInput:
    """Construct the zero-`criterion_inputs` `PacketInput` for a BIAS row
    that fired no criteria at all. Mirrors `build_packet_input`'s
    `RunMetadata`/`SourceSnapshotPins`/config-fingerprint construction
    exactly (same formula, same field values) -- `build_packet_input`
    itself is never called here because it unconditionally raises
    `PacketValidationError` on an empty parsed-criteria list."""
    quality_flags = derive_quality_flags(bias_row, identity, ())

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
    return PacketInput(
        identity=identity,
        criterion_inputs=(),
        run_metadata=run_metadata,
        source_snapshot=source_snapshot,
        quality_flags=quality_flags,
        missing_evidence=_CANONICAL_MISSING_EVIDENCE,
        pattern_ref=None,
        external_comparators=(),
        predecessor_packet_id=None,
        predecessor_envelope_hash=None,
        census_selection_stratum=metadata,
    )


# --------------------------------------------------------------------------
# D1/D9: full all-VUS universe assembly
# --------------------------------------------------------------------------


def build_full_vus_universe(
    manifest: Sequence[ManifestEntry],
    bias_records: Sequence[BiasRecord],
    run_pins: RunPins,
    packet_config: PacketConfig,
    *,
    expected_total: Optional[int] = None,
    expected_lp: Optional[int] = None,
    expected_lb: Optional[int] = None,
    expected_unresolved: Optional[int] = None,
    expected_manual: Optional[int] = None,
    expected_lp_patterns: Optional[int] = None,
    expected_lb_patterns: Optional[int] = None,
) -> tuple[CandidateEvidencePacket, ...]:
    """Assemble the FULL corrected all-VUS universe: `candidate_LP_review`/
    `candidate_LB_review` are built by reusing `build_candidate_universe`
    literally (then bound with `CensusSelectionMetadata` + rehashed);
    `no_deterministic_resolution`/`manual_review` are assembled per-row here
    (never scored, `pattern_ref=None`). `reproduce_census_strata` (reused
    unchanged) conserves the exact one-to-one manifest<->BIAS-row join --
    a duplicate, missing, or extra join raises `ConservationError` before
    any packet is built. Each optional `expected_*` is an independent
    self-consistency check against the counts this call itself computes
    (NOT the committed census oracle -- see `conserve_current_policy` for
    that); a given `expected_*` that disagrees with the actual computed
    count also raises `ConservationError`."""
    manifest = tuple(manifest)
    bias_records = tuple(bias_records)

    scorer_config = load_scorer_config("configs/acmg/tsc.yaml")
    eval_config = load_eval_config("configs/eval/tsc2.yaml")

    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest}
    strata = reproduce_census_strata(bias_records, manifest_by_vcf_key, scorer_config, eval_config)

    def _check(label: str, expected: Optional[int], actual: int) -> None:
        if expected is not None and expected != actual:
            raise ConservationError(f"{label} drift: expected {expected}, got {actual}")

    _check("manifest identities", expected_total, len(manifest))

    lp_count = sum(1 for entry in strata if entry.stratum == "candidate_LP_review")
    lb_count = sum(1 for entry in strata if entry.stratum == "candidate_LB_review")
    unresolved_count = sum(1 for entry in strata if entry.stratum == "no_deterministic_resolution")
    manual_count = sum(1 for entry in strata if entry.stratum == "manual_review")
    _check("candidate_LP_review", expected_lp, lp_count)
    _check("candidate_LB_review", expected_lb, lb_count)
    _check("no_deterministic_resolution", expected_unresolved, unresolved_count)
    _check("manual_review", expected_manual, manual_count)

    lp_patterns = len({entry.pattern_id for entry in strata if entry.stratum == "candidate_LP_review" and entry.pattern_id})
    lb_patterns = len({entry.pattern_id for entry in strata if entry.stratum == "candidate_LB_review" and entry.pattern_id})
    _check("candidate_LP_review exact-strength pattern count", expected_lp_patterns, lp_patterns)
    _check("candidate_LB_review exact-strength pattern count", expected_lb_patterns, lb_patterns)

    candidate_packets = build_candidate_universe(strata, bias_records, manifest, packet_config, run_pins)
    bound_candidates = [
        bind_census_selection_metadata(
            packet,
            CensusSelectionMetadata(census_selection_stratum=packet.pattern_ref.census_selection_stratum),
        )
        for packet in candidate_packets
    ]

    manifest_by_variant_id = {entry.variant_id: entry for entry in manifest}
    bias_by_vcf_key = {row.variant_id: row for row in bias_records}

    other_packets: list[CandidateEvidencePacket] = []
    for stratum_entry in strata:
        if stratum_entry.stratum not in ("no_deterministic_resolution", "manual_review"):
            continue

        manifest_entry = manifest_by_variant_id[stratum_entry.variant_id]
        bias_row = bias_by_vcf_key[manifest_entry.vcf_key]

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
        metadata = CensusSelectionMetadata(census_selection_stratum=stratum_entry.stratum)

        calls = parse_rationale(bias_row.criteria, STRENGTH_MAP)
        if calls:
            packet_input = build_packet_input(identity, bias_row, stratum_entry, packet_config, run_pins)
            packet_input = replace(packet_input, census_selection_stratum=metadata)
            packet = build_packet(packet_input, packet_config)
        else:
            absent_input = _build_absent_packet_input(identity, bias_row, metadata, packet_config, run_pins)
            packet = build_evidence_absent_packet(absent_input, packet_config)
        other_packets.append(packet)

    all_packets = sorted(list(bound_candidates) + other_packets, key=lambda packet: packet.packet_id)
    return tuple(all_packets)


# --------------------------------------------------------------------------
# D14: deterministic 8-case discovery sample
# --------------------------------------------------------------------------


def select_discovery_sample(packets: Sequence[Any]) -> list[Any]:
    """Deterministic, stable 2+2+2+2 discovery sample across the four
    census-selection strata, in `_DISCOVERY_STRATA_ORDER`. Within each
    stratum, sorts by `identity.canonical_spdi` (plain Python string/byte
    order) and takes the first two; fails closed (`DiscoverySampleError`)
    if any stratum has fewer than two members. Reads ONLY `packet_id`,
    `identity.canonical_spdi`, and `census_selection_stratum` -- never
    `candidate_direction`/`external_comparators` (permutation-invariant:
    input order never affects the result)."""
    buckets: dict[str, list[Any]] = {stratum: [] for stratum in _DISCOVERY_STRATA_ORDER}
    for packet in packets:
        stratum = packet.census_selection_stratum.census_selection_stratum
        if stratum in buckets:
            buckets[stratum].append(packet)

    selected: list[Any] = []
    for stratum in _DISCOVERY_STRATA_ORDER:
        members = sorted(buckets[stratum], key=lambda packet: packet.identity.canonical_spdi)
        if len(members) < _DISCOVERY_SAMPLE_SIZE_PER_STRATUM:
            raise DiscoverySampleError(
                f"stratum {stratum!r} has only {len(members)} packet(s); at least "
                f"{_DISCOVERY_SAMPLE_SIZE_PER_STRATUM} are required for the deterministic "
                "discovery sample"
            )
        selected.extend(members[:_DISCOVERY_SAMPLE_SIZE_PER_STRATUM])
    return selected


# --------------------------------------------------------------------------
# D15: external-only, atomic, canonical-bytes writer
# --------------------------------------------------------------------------


def _assert_corrected_output_boundary(output_root: Path) -> Path:
    resolved = output_root.resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise OutputBoundaryError(
            f"--output-root must be outside the repository tree ({_REPO_ROOT}); got {resolved}"
        )
    return resolved


def _write_canonical_bytes(path: Path, text: str) -> None:
    """Binary write of already-LF-only `text` -- never a text-mode write,
    which on Windows would translate `\\n` to `\\r\\n`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    if not encoded.endswith(b"\n"):
        encoded += b"\n"
    path.write_bytes(encoded)


def _write_canonical_json(path: Path, obj: Any) -> None:
    _write_canonical_bytes(path, canonical_json(obj))


def _stratum_of(packet: Any) -> Optional[str]:
    metadata = getattr(packet, "census_selection_stratum", None)
    return getattr(metadata, "census_selection_stratum", None) if metadata is not None else None


def write_corrected_run_outputs(
    *,
    output_root: str | Path,
    run_name: str,
    packets: Sequence[Any],
    aggregate_manifest: Optional[Mapping[str, Any]] = None,
    render_config: Optional[RenderConfig] = None,
    discovery_sample: Optional[Sequence[Any]] = None,
) -> Path:
    """Write every corrected-run artifact under a brand-new
    `output_root/run_name` directory: refuses an in-repo `output_root`
    (`OutputBoundaryError`) and refuses an already-existing `run_dir`
    (`OutputBoundaryError`, never overwritten). All bytes are canonical
    UTF-8 JSON with LF-only line endings and exactly one terminal newline,
    written via binary writes. Publication is atomic: every artifact is
    first written under a sibling staging directory, which is renamed onto
    `run_dir` only once every write has succeeded (any failure removes the
    staging directory -- no partial/leftover `run_dir`, no `.tmp`/
    `.staging` files survive under the published tree).

    `aggregate_manifest`, `render_config`, and `discovery_sample` are all
    optional: the minimal 3-kwarg call (`output_root`, `run_name`,
    `packets`) still produces a valid, non-empty, canonical
    `aggregate_manifest.json` even for packets that carry no
    `census_selection_stratum` at all (e.g. a pre-existing, non-corrected
    packet)."""
    output_root = Path(output_root)
    resolved_root = _assert_corrected_output_boundary(output_root)
    run_dir = resolved_root / run_name
    if run_dir.exists():
        raise OutputBoundaryError(f"run directory already exists, refusing to overwrite: {run_dir}")

    packets = tuple(sorted(packets, key=lambda packet: packet.packet_id))

    staging_dir = resolved_root / f".{run_name}.staging-{uuid.uuid4().hex}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    try:
        packets_dir = staging_dir / "packets"
        first_pass_dir = staging_dir / "first_pass"
        for packet in packets:
            _write_canonical_json(packets_dir / f"{packet.packet_id}.json", packet)
            view = redact_for_first_pass(packet)
            _write_canonical_json(first_pass_dir / f"{packet.packet_id}.json", view)
            if render_config is not None:
                markdown = render_markdown(packet, render_config, view=PacketView.FIRST_PASS)
                _write_canonical_bytes(first_pass_dir / f"{packet.packet_id}.md", markdown)

        strata_groups: dict[str, list[str]] = defaultdict(list)
        for packet in packets:
            stratum = _stratum_of(packet) or "unclassified"
            strata_groups[stratum].append(packet.packet_id)
        queues_dir = staging_dir / "queues"
        for stratum, packet_ids in strata_groups.items():
            _write_canonical_json(queues_dir / f"{stratum}.json", {"packet_ids": sorted(packet_ids)})

        candidate_priority_ids = sorted(
            packet.packet_id for packet in packets
            if _stratum_of(packet) in ("candidate_LP_review", "candidate_LB_review")
        )
        _write_canonical_json(
            staging_dir / "candidate_priority_queue.json", {"packet_ids": candidate_priority_ids}
        )

        if render_config is not None:
            queue_index = build_queue_index(list(packets), render_config)
            _write_canonical_bytes(staging_dir / "review_queue.csv", queue_index.to_csv())
            _write_canonical_bytes(staging_dir / "review_queue.jsonl", queue_index.to_jsonl())

        if discovery_sample is not None:
            sample_payload = [
                {
                    "packet_id": packet.packet_id,
                    "canonical_spdi": packet.identity.canonical_spdi,
                    "census_selection_stratum": _stratum_of(packet),
                }
                for packet in discovery_sample
            ]
            _write_canonical_json(staging_dir / "discovery_sample.json", sample_payload)

        manifest_payload: Mapping[str, Any]
        if aggregate_manifest is not None:
            manifest_payload = aggregate_manifest
        else:
            manifest_payload = {
                "universe_size": len(packets),
                "packet_ids": [packet.packet_id for packet in packets],
            }
        _write_canonical_json(staging_dir / "aggregate_manifest.json", manifest_payload)

        summary_payload = {
            "run_name": run_name,
            "universe_size": len(packets),
            "strata": {stratum: len(ids) for stratum, ids in sorted(strata_groups.items())},
        }
        _write_canonical_json(staging_dir / "summary.json", summary_payload)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    staging_dir.rename(run_dir)
    return run_dir
