#!/usr/bin/env python
"""Build the corrected all-VUS expert-review packet universe (all four
census-selection strata: `candidate_LP_review`, `candidate_LB_review`,
`no_deterministic_resolution`, `manual_review`).

Standalone entrypoint: runs both as
`python <repo>/scripts/build_corrected_review_packets.py ...` from ANY
current working directory, and as
`python -m scripts.build_corrected_review_packets ...` (module form, which
additionally requires the repository root to already be on
`sys.path`/`PYTHONPATH` -- e.g. because it is the caller's own cwd -- so
Python can locate the `scripts` package before running any of this
module's code at all; that one precondition is the caller's, not this
module's, to satisfy). Every repository-relative default path (the eight
`--*-config`/`--predictor-policy` flags' defaults, and the two fixed
subordinate lineage/candidate-direction config paths) is resolved against
this file's own fixed on-disk location, never the caller's cwd; an
explicit value for any of those flags is resolved normally (as given, or
relative to the caller's own cwd, like any ordinary CLI path).

Verifies the approved predictor-policy artifact (canonical Git/LF blob) and
asserts `{schema, status, mode}` BEFORE parsing; verifies the four
subordinate configs (scorer/eval/lineage/candidate-direction) by RAW
on-disk byte SHA-256 against the pins recorded INSIDE that approved policy
(`raptor.census.cli._verify_bound_hashes`, reused unchanged); verifies the
five packet render/selection/narrative/comparator/schema configs by RAW
on-disk byte SHA-256 against this module's own pins; verifies the
current-policy census oracle by canonical Git/LF blob (loading its JSON
once); verifies the `--provenance` artifact's own raw on-disk byte SHA-256
(`immutable_external_inputs.provenance.sha256`, `raw_path_bytes_external`)
BEFORE its JSON is ever parsed, then its recorded
`vcf_hash`/`source_snapshot` (`raptor.census.cli._validate_provenance`,
reused unchanged) and its recorded `manifest_hash` (when present) against
the actual `--manifest` bytes; then cross-verifies the raw `--manifest`/
`--bias-tsv` bytes and the provenance artifact's `vcf_hash`/
`source_snapshot` against the verified census oracle's OWN recorded
`source_hashes`/`snapshot` (never a hardcoded/test-side pin). Every
verification runs BEFORE any output is written.

Reproduces the exact-join current-policy census strata
(`raptor.census.strata.reproduce_census_strata`, reused unchanged),
conserves the derived counts against the committed census oracle
(`raptor.packet.corrected_universe.conserve_current_policy`), assembles the
full four-stratum universe (`build_full_vus_universe`), selects the
deterministic eight-case discovery sample (`select_discovery_sample`), and
-- unless `--dry-run` -- writes every artifact under a brand-new external
run directory (`write_corrected_run_outputs`). Every packet keeps
`candidate_direction=null` / `POLICY_BLOCKED`
(`configs/eval/bp4pp3_predictor_policy.json` stays `disabled_manual`); this
script never imports `raptor.eval.combine`/`harness`/`benchmark`/`knowns`
and never opens a benchmark/KB label file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

# --------------------------------------------------------------------------
# Standalone-execution bootstrap -- MUST run before any `raptor.*`/
# `scripts.*` import below. Resolved once from this file's own fixed
# location (never the caller's cwd), so both `python <path-to-this-file>`
# (direct execution from any cwd) and `python -m
# scripts.build_corrected_review_packets` (module execution, from a cwd
# that already has the repo root on `sys.path`) see an identical `raptor`
# package under `src/` and the sibling `scripts` package (needed because
# `raptor.packet.corrected_universe` itself imports
# `scripts.build_tsc_calibration_batch` to reuse its calibration helpers
# unchanged, per spec, rather than duplicating that behavior here).
# No broad `try`/`except` is used around these imports: a genuine import
# error in `raptor`/`scripts` code must still surface, not be masked.
# --------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
for _bootstrap_path in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _bootstrap_path not in sys.path:
        sys.path.insert(0, _bootstrap_path)

from raptor.census.cli import (
    _validate_predictor_policy,
    _validate_predictor_policy_source,
    _validate_provenance,
    _verify_bound_hashes,
)
from raptor.census.strata import STRENGTH_MAP, load_manifest, reproduce_census_strata
from raptor.eval.config import load_config as load_eval_config
from raptor.packet.comparator import load_comparator_config
from raptor.packet.config import (
    load_narrative_catalog,
    load_packet_config,
    load_render_config,
    load_selection_config,
)
from raptor.packet.corrected_universe import (
    build_full_vus_universe,
    conserve_current_policy,
    select_discovery_sample,
    write_corrected_run_outputs,
)
from raptor.packet.git_provenance import resolve_corrected_provenance
from raptor.packet.model import PacketPolicyDisposition, ReviewState
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.parse import parse_rationale

from scripts.build_tsc_calibration_batch import RunPins

#: The fixed, canonical `lineage_policy`/`packet_candidate_direction` paths
#: bound into the approved predictor policy -- there is no
#: `--lineage-policy`/`--packet-candidate-direction` CLI flag (see the
#: authoritative spec's `cli_and_output_boundary.cli.args`); both are
#: verified via `raptor.census.cli._verify_bound_hashes` (policy-field-
#: derived expected hash, never hardcoded here). Fixed, never a CLI
#: override, so always anchored against `_REPO_ROOT` -- never the caller's
#: cwd.
_CANONICAL_LINEAGE_POLICY_PATH = _REPO_ROOT / "configs" / "eval" / "bias_lineage.yaml"
_CANONICAL_PACKET_CANDIDATE_DIRECTION_PATH = (
    _REPO_ROOT / "configs" / "packet" / "candidate_direction.yaml"
)

#: Repository-relative defaults for the packet/scorer/eval/predictor-policy
#: config flags below. `_resolve_repo_default` anchors these against
#: `_REPO_ROOT` (never the caller's cwd) ONLY when the caller leaves the
#: corresponding flag unset; an explicit `--*-config`/`--predictor-policy`
#: value is always resolved normally (as given, or relative to the
#: caller's own cwd, exactly like any ordinary CLI path).
_DEFAULT_PACKET_CONFIG = "configs/packet/schema.yaml"
_DEFAULT_SELECTION_CONFIG = "configs/packet/selection.yaml"
_DEFAULT_RENDER_CONFIG = "configs/packet/render.yaml"
_DEFAULT_NARRATIVE_CATALOG = "configs/packet/narrative_templates.yaml"
_DEFAULT_COMPARATOR_CONFIG = "configs/packet/comparator.yaml"
_DEFAULT_SCORER_CONFIG = "configs/acmg/tsc.yaml"
_DEFAULT_EVAL_CONFIG = "configs/eval/tsc2.yaml"
_DEFAULT_PREDICTOR_POLICY = "configs/eval/bp4pp3_predictor_policy.json"

#: Fixed nirvana worker-version pin (there is no committed config source for
#: this value -- see `bias_version`/`bias_commit`, which ARE derived from
#: `packet_config.lineage_policy` below). Not a benchmark/expected-count
#: literal (P1): a worker-identity string, never compared against a derived
#: universe/pattern/point count.
_NIRVANA_VERSION = "3.18.1"

#: RAW on-disk byte SHA-256 pins for the packet render/selection/narrative/
#: comparator/schema configs (hash_contract.packet_render_and_selection_configs).
_PACKET_RENDER_CONFIG_SHA256 = "d9f7ef8fd90769fe671ee1b3d1f7dac42351a8045b50c2ec5535029366f4ba3a"
_PACKET_SELECTION_CONFIG_SHA256 = "f7198b68e72e3bb27fe8a2c17eeb9365c31739fc6b218f50f7fda167955156ad"
_PACKET_NARRATIVE_CATALOG_SHA256 = "64359a533e430c670327e3b90a4ae89dd248e5fd3c76234904896e60ad67d0ed"
_PACKET_COMPARATOR_CONFIG_SHA256 = "e1703d7f14b1d87e012e3d98bc39fe6a839a520544a49ab43622f3c0e85c4eea"
_PACKET_SCHEMA_CONFIG_SHA256 = "6d4e458cd54bce469cd16a93a2792529b6028e3d8e714954474fd9034bd1260a"

#: Canonical Git/LF-blob SHA-256 of the single current-policy census oracle
#: (`committed_data_inputs.current_disabled_manual_census`).
_CURRENT_POLICY_CENSUS_SHA256 = "45ff9f9abada7d5369c131bf7ffde28d0786eea41ff9bf7905f51da0cabd59ac"

#: RAW on-disk byte SHA-256 of the pinned `--provenance` artifact
#: (`immutable_external_inputs.provenance.sha256`,
#: `sha256_provenance: raw_path_bytes_external`). Verified BEFORE this
#: input's own JSON is ever parsed -- the caller may point `--provenance`
#: at any path; its raw bytes must match this pin. This is an immutable
#: EXTERNAL INPUT identity hash, not a derived benchmark/expected-count
#: literal -- P1 bans the latter, never a pinned input's own content hash.
_PROVENANCE_ARTIFACT_RAW_BYTE_SHA256 = "7272529546ad43ac0196523ad83d66eab8388a66a08f589bf10fc296b2110f55"


class InputVerificationError(RuntimeError):
    """A supplied config/data artifact failed hash/content verification --
    raised before any strata/packet/output work begins."""


def _sha256_bytes(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical_lf_sha256_of_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _verify_raw_byte_pin(label: str, path: str | Path, expected_sha256: str) -> str:
    actual = _sha256_bytes(path)
    if actual != expected_sha256:
        raise InputVerificationError(
            f"{label} raw-byte sha256 drift: expected {expected_sha256!r}, got {actual!r} ({path})"
        )
    return actual


def _verify_current_policy_census(path: str | Path) -> tuple[str, Mapping[str, Any]]:
    """Verify the committed current-policy census oracle's canonical-LF
    sha256 against the fixed pin, then load and return its parsed JSON
    (read once, alongside the verified hash). The parsed census becomes the
    single oracle `_verify_input_bundle_against_census` cross-checks the
    `--manifest`/`--bias-tsv`/`--provenance` input bundle against below."""
    raw = Path(path).read_bytes()
    actual = _canonical_lf_sha256_of_bytes(raw)
    if actual != _CURRENT_POLICY_CENSUS_SHA256:
        raise InputVerificationError(
            "current-policy census oracle content drift: canonical LF sha256 does not match "
            f"the committed pin (expected {_CURRENT_POLICY_CENSUS_SHA256!r}, got {actual!r})"
        )
    census = json.loads(raw.decode("utf-8"))
    return actual, census


def _verify_input_bundle_against_census(
    *,
    manifest_sha256: str,
    bias_tsv_sha256: str,
    provenance: Mapping[str, Any],
    census: Mapping[str, Any],
) -> None:
    """Cross-verify the raw `--manifest`/`--bias-tsv` bytes and the
    ALREADY schema-validated `--provenance` artifact's own recorded
    `vcf_hash`/`source_snapshot` against the verified current-policy census
    oracle's OWN recorded `source_hashes`/`snapshot` -- fails closed with
    `InputVerificationError` on any mismatch, BEFORE any manifest/BIAS
    parsing or packet assembly. Every expected value comes from the
    verified census oracle itself (never a hardcoded/test-side pin), so
    this cross-check holds for any manifest/BIAS-TSV/provenance/census set,
    not just the one pinned real dataset."""
    source_hashes = census.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        raise InputVerificationError(
            f"current-policy census oracle is missing a source_hashes object; got {source_hashes!r}"
        )

    expected_manifest = source_hashes.get("manifest")
    if manifest_sha256 != expected_manifest:
        raise InputVerificationError(
            "--manifest sha256 does not match the current-policy census oracle's "
            f"source_hashes.manifest: expected {expected_manifest!r}, got {manifest_sha256!r}"
        )

    expected_bias_tsv = source_hashes.get("bias_tsv")
    if bias_tsv_sha256 != expected_bias_tsv:
        raise InputVerificationError(
            "--bias-tsv sha256 does not match the current-policy census oracle's "
            f"source_hashes.bias_tsv: expected {expected_bias_tsv!r}, got {bias_tsv_sha256!r}"
        )

    expected_input_vcf = source_hashes.get("input_vcf")
    provenance_vcf_hash = provenance.get("vcf_hash")
    if provenance_vcf_hash != expected_input_vcf:
        raise InputVerificationError(
            "--provenance's vcf_hash does not match the current-policy census oracle's "
            f"source_hashes.input_vcf: expected {expected_input_vcf!r}, got {provenance_vcf_hash!r}"
        )

    expected_snapshot = census.get("snapshot")
    provenance_snapshot = provenance.get("source_snapshot")
    if provenance_snapshot != expected_snapshot:
        raise InputVerificationError(
            "--provenance's source_snapshot does not match the current-policy census oracle's "
            f"snapshot: expected {expected_snapshot!r}, got {provenance_snapshot!r}"
        )


def _verify_manifest_provenance_binding(manifest_path: str | Path, provenance: Mapping[str, Any]) -> str:
    """Cross-verify the ALREADY-verified `--provenance` artifact's own
    recorded `manifest_hash` (when present) against the actual `--manifest`
    bytes -- fails closed on drift. Returns the manifest's raw-byte sha256
    for `RunPins.manifest_sha256`. Never hardcodes an expected manifest hash
    (this cross-check must hold for any manifest/provenance pair, not just
    the one pinned real dataset)."""
    actual = _sha256_bytes(manifest_path)
    recorded = provenance.get("manifest_hash")
    if recorded is not None and recorded != actual:
        raise InputVerificationError(
            f"--manifest sha256 does not match --provenance's own recorded manifest_hash: "
            f"expected {recorded!r}, got {actual!r}"
        )
    return actual


def _resolve_repo_default(value: Optional[str], relative_default: str) -> str:
    """Resolve a config-flag value the caller may have left unset. An
    explicit `value` (the caller passed `--packet-config`/etc.) is returned
    completely unchanged -- resolved normally afterwards, exactly like any
    ordinary CLI path (as given, or relative to the caller's own cwd). An
    unset (`None`) value falls back to this script's OWN
    repository-relative default, anchored against `_REPO_ROOT` -- never
    the caller's cwd -- so the script's built-in defaults behave
    identically regardless of where it is invoked from."""
    if value is not None:
        return value
    return str(_REPO_ROOT / relative_default)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the corrected all-VUS expert-review packet universe"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bias-tsv", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--census-stats", required=True)
    parser.add_argument("--packet-config", default=None)
    parser.add_argument("--selection-config", default=None)
    parser.add_argument("--render-config", default=None)
    parser.add_argument("--narrative-catalog", default=None)
    parser.add_argument("--comparator-config", default=None)
    parser.add_argument("--scorer-config", default=None)
    parser.add_argument("--eval-config", default=None)
    parser.add_argument("--predictor-policy", default=None)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--aavc-comparator", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # 0. Every repository-default config flag the caller left unset is
    # anchored against `_REPO_ROOT` here, ONCE, before any of it is used --
    # never the caller's cwd. A flag the caller DID pass is left exactly as
    # given (resolved normally, like any ordinary CLI path, below).
    args.packet_config = _resolve_repo_default(args.packet_config, _DEFAULT_PACKET_CONFIG)
    args.selection_config = _resolve_repo_default(args.selection_config, _DEFAULT_SELECTION_CONFIG)
    args.render_config = _resolve_repo_default(args.render_config, _DEFAULT_RENDER_CONFIG)
    args.narrative_catalog = _resolve_repo_default(args.narrative_catalog, _DEFAULT_NARRATIVE_CATALOG)
    args.comparator_config = _resolve_repo_default(args.comparator_config, _DEFAULT_COMPARATOR_CONFIG)
    args.scorer_config = _resolve_repo_default(args.scorer_config, _DEFAULT_SCORER_CONFIG)
    args.eval_config = _resolve_repo_default(args.eval_config, _DEFAULT_EVAL_CONFIG)
    args.predictor_policy = _resolve_repo_default(args.predictor_policy, _DEFAULT_PREDICTOR_POLICY)

    # 1. Predictor-policy ARTIFACT identity (canonical path + LF blob),
    # then its {schema, status, mode} contract -- before parsing anything
    # else (reused verbatim from raptor.census.cli).
    _validate_predictor_policy_source(args.predictor_policy)
    predictor_policy = json.loads(Path(args.predictor_policy).read_text(encoding="utf-8"))
    _validate_predictor_policy(predictor_policy)

    # 2. Four subordinate configs, RAW on-disk bytes, against the hashes
    # recorded INSIDE the approved policy (never hardcoded here).
    _verify_bound_hashes(
        predictor_policy,
        {
            "scorer_config": Path(args.scorer_config),
            "eval_config": Path(args.eval_config),
            "lineage_policy": Path(_CANONICAL_LINEAGE_POLICY_PATH),
            "packet_candidate_direction": Path(_CANONICAL_PACKET_CANDIDATE_DIRECTION_PATH),
        },
    )

    # 3. Five packet render/selection/narrative/comparator/schema configs,
    # RAW on-disk bytes, against this module's own fixed pins.
    _verify_raw_byte_pin("packet schema config", args.packet_config, _PACKET_SCHEMA_CONFIG_SHA256)
    _verify_raw_byte_pin("selection config", args.selection_config, _PACKET_SELECTION_CONFIG_SHA256)
    _verify_raw_byte_pin("render config", args.render_config, _PACKET_RENDER_CONFIG_SHA256)
    _verify_raw_byte_pin("narrative catalog", args.narrative_catalog, _PACKET_NARRATIVE_CATALOG_SHA256)
    _verify_raw_byte_pin("comparator config", args.comparator_config, _PACKET_COMPARATOR_CONFIG_SHA256)

    # 4. Committed current-policy census oracle, canonical Git/LF blob --
    # load its JSON once; it becomes the oracle step 5 cross-checks against.
    _, census_stats = _verify_current_policy_census(args.census_stats)

    # 5. Provenance artifact's own raw on-disk byte identity
    # (immutable_external_inputs.provenance, raw_path_bytes_external) --
    # verified BEFORE this file's JSON is ever parsed -- then its
    # vcf_hash/source_snapshot, then the manifest<->provenance
    # self-consistency hash binding, then the whole manifest/BIAS-TSV/
    # provenance input bundle against the verified current-policy census
    # oracle's OWN recorded hashes/snapshot -- all before any manifest/BIAS
    # parsing or packet assembly.
    _verify_raw_byte_pin("provenance artifact", args.provenance, _PROVENANCE_ARTIFACT_RAW_BYTE_SHA256)
    provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
    _validate_provenance(provenance)
    manifest_sha256 = _verify_manifest_provenance_binding(args.manifest, provenance)
    bias_tsv_sha256 = _sha256_bytes(args.bias_tsv)
    _verify_input_bundle_against_census(
        manifest_sha256=manifest_sha256,
        bias_tsv_sha256=bias_tsv_sha256,
        provenance=provenance,
        census=census_stats,
    )

    # 6. Load + schema-validate every config the packet path consumes.
    packet_config = load_packet_config(args.packet_config)
    load_selection_config(args.selection_config)
    render_config = load_render_config(args.render_config)
    load_narrative_catalog(args.narrative_catalog)
    load_comparator_config(args.comparator_config)
    scorer_config = load_scorer_config(args.scorer_config)
    eval_config = load_eval_config(args.eval_config)

    # 7. Full 40-hex code_commit on a CLEAN tree -- fails closed before any
    # write (dirty/abbreviated/unresolvable commit never silently falls
    # back to a placeholder).
    code_commit = resolve_corrected_provenance()

    run_pins = RunPins(
        input_sha256=provenance["vcf_hash"],
        output_sha256=bias_tsv_sha256,
        manifest_sha256=manifest_sha256,
        source_snapshot=provenance["source_snapshot"],
        bias_version=packet_config.lineage_policy.bias_version,
        bias_commit=packet_config.lineage_policy.bias_commit,
        nirvana_version=_NIRVANA_VERSION,
        code_commit=code_commit,
    )

    # 8. Load the immutable manifest + BIAS rows and reproduce the exact-
    # join current-policy strata (fails closed on any duplicate/missing/
    # extra join before any packet is built).
    manifest = load_manifest(args.manifest)
    bias_records = tuple(BiasTsvSource(args.bias_tsv).records())
    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest}
    strata = reproduce_census_strata(bias_records, manifest_by_vcf_key, scorer_config, eval_config)

    lp_count = sum(1 for entry in strata if entry.stratum == "candidate_LP_review")
    lb_count = sum(1 for entry in strata if entry.stratum == "candidate_LB_review")
    unresolved_count = sum(1 for entry in strata if entry.stratum == "no_deterministic_resolution")
    manual_count = sum(1 for entry in strata if entry.stratum == "manual_review")
    lp_patterns = len({entry.pattern_id for entry in strata if entry.stratum == "candidate_LP_review" and entry.pattern_id})
    lb_patterns = len({entry.pattern_id for entry in strata if entry.stratum == "candidate_LB_review" and entry.pattern_id})

    # 9. Independently derive the current PP3/BP4 firing incidence directly
    # from the BIAS rows (never a spec/historical/gate literal).
    raw_pp3_firings = 0
    raw_bp4_firings = 0
    pp3_or_bp4_union_variants = 0
    for row in bias_records:
        fired = {call.criterion for call in parse_rationale(row.criteria, STRENGTH_MAP)}
        has_pp3 = "PP3" in fired
        has_bp4 = "BP4" in fired
        if has_pp3:
            raw_pp3_firings += 1
        if has_bp4:
            raw_bp4_firings += 1
        if has_pp3 or has_bp4:
            pp3_or_bp4_union_variants += 1

    point_distribution_expected = dict(sorted(Counter(str(entry.signed_points) for entry in strata).items()))

    # 10. Fail closed before any packet is built unless the derived current-
    # policy counts still conserve the committed census oracle.
    conserve_current_policy(
        total_vus=len(manifest),
        lp_count=lp_count,
        lb_count=lb_count,
        unresolved_count=unresolved_count,
        manual_count=manual_count,
        lp_patterns=lp_patterns,
        lb_patterns=lb_patterns,
        census_stats_path=Path(args.census_stats),
    )

    # 11. Assemble the full four-stratum universe and the deterministic
    # discovery sample.
    packets = build_full_vus_universe(
        manifest,
        bias_records,
        run_pins,
        packet_config,
        expected_total=len(manifest),
        expected_lp=lp_count,
        expected_lb=lb_count,
        expected_unresolved=unresolved_count,
        expected_manual=manual_count,
        expected_lp_patterns=lp_patterns,
        expected_lb_patterns=lb_patterns,
    )
    discovery_sample = select_discovery_sample(packets)

    policy_blocked_count = sum(1 for packet in packets if packet.review_state is ReviewState.POLICY_BLOCKED)
    scored_pp3bp4_calls = sum(
        1
        for packet in packets
        for entry in packet.entries
        if entry.criterion in ("PP3", "BP4") and entry.packet_policy_disposition is PacketPolicyDisposition.INCLUDED
    )

    aggregate_manifest = {
        "universe_size": len(manifest),
        "conservation": {
            "manifest_identities": len(manifest),
            "bias_rows": len(bias_records),
            "candidate_LP_review": lp_count,
            "candidate_LB_review": lb_count,
            "no_deterministic_resolution": unresolved_count,
            "manual_review": manual_count,
            "lp_patterns": lp_patterns,
            "lb_patterns": lb_patterns,
        },
        "pp3bp4_suppression_full_census": {
            "raw_pp3_firings": raw_pp3_firings,
            "raw_bp4_firings": raw_bp4_firings,
            "pp3_or_bp4_union_variants": pp3_or_bp4_union_variants,
            "scored_pp3bp4_calls": scored_pp3bp4_calls,
        },
        "point_distribution_expected": point_distribution_expected,
        "policy_blocked_review_state_count": policy_blocked_count,
        "preregistered_discovery_sample": [
            {
                "packet_id": packet.packet_id,
                "packet_hash": packet.packet_envelope_hash,
                "evidence_core_hash": packet.evidence_core_hash,
            }
            for packet in discovery_sample
        ],
        "run_pins": {
            "source_snapshot": run_pins.source_snapshot,
            "bias_version": run_pins.bias_version,
            "bias_commit": run_pins.bias_commit,
            "nirvana_version": run_pins.nirvana_version,
            "code_commit": run_pins.code_commit,
        },
        "source_hashes": {
            "input_vcf_sha256": run_pins.input_sha256,
            "bias_tsv_sha256": run_pins.output_sha256,
            "manifest_sha256": run_pins.manifest_sha256,
        },
    }

    if args.summary:
        print(json.dumps(aggregate_manifest, sort_keys=True, indent=2))

    if args.dry_run:
        return 0

    write_corrected_run_outputs(
        output_root=Path(args.output_root),
        run_name=args.run_name,
        packets=packets,
        aggregate_manifest=aggregate_manifest,
        render_config=render_config,
        discovery_sample=discovery_sample,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
