#!/usr/bin/env python
"""Build the RAPTOR v2 TSC2 functional coverage map
(``docs/project/specs/raptor-v2-functional-coverage-map-v1.yaml``).

This is the operator for ``raptor.external.tsc2_functional_coverage`` -- a
pure, offline, deterministic package (see that package's module
docstrings for the full design). This script:

1. Loads ``configs/external/tsc2_functional_coverage_map_v1.yaml`` (the
   exact pinned hashes/counts/paths for all seven external input roots
   and the frozen expected pilot totals).
2. Resolves all seven input roots (functional promotion, VUS identity/
   BIAS, priority queue, prospective holdout, Atlas identity map/panel)
   plus the output root, and validates every one of them is an absolute
   path (``ingest.validate_input_roots_absolute``) BEFORE any reader is
   ever invoked.
3. Reads and re-verifies the already-published functional-identity-
   promotion bundle manifest and its three per-source artifact payloads,
   fully reconstructs every promoted row and keeps only the
   ``GENOMIC_SPDI_VERIFIED`` ones.
4. Reads and re-verifies the frozen VUS universe, its internal priority
   subset (reproduced through the disabled/manual census seam), the
   protected prospective holdout, the Atlas contrast-candidate identity
   map (via the public Atlas loader seam) and the $R611Q$ Atlas anchor.
5. Builds the exact-SPDI-join coverage rows and full-cohort statistics,
   gates publication on an EXACT match against the config's
   ``expected_pilot`` totals (``_validate_expected_pilot_result``) BEFORE
   any publish/summary step, and -- unless ``--dry-run`` was supplied --
   publishes the coverage bundle to an external, create-only run
   directory and optionally writes an aggregate-only committed summary
   to an EXPLICITLY supplied ``--summary-output`` path.

This script performs no network I/O of its own; every byte it operates on
is read from the local filesystem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.tsc2_functional.model import NormalizationContractError  # noqa: E402
from raptor.external.tsc2_functional.model import NormalizedFunctionalRow  # noqa: E402
from raptor.external.tsc2_functional_coverage.bundle import (  # noqa: E402
    CoverageBundleBoundaryError,
    CoverageManifestError,
    build_coverage_bundle_manifest,
    build_committed_summary,
    canonical_coverage_jsonl_bytes,
    publish_coverage_bundle,
)
from raptor.external.tsc2_functional_coverage.coverage import (  # noqa: E402
    CoverageBuildError,
    build_functional_coverage_rows,
    compute_coverage_statistics,
)
from raptor.external.tsc2_functional_coverage.ingest import (  # noqa: E402
    CoverageInputError,
    InputPinMismatchError,
    _is_symlink_or_reparse_point,
    load_atlas_contrast_replays,
    read_input_payload,
    reproduce_priority_subset,
    validate_atlas_anchor_input,
    validate_functional_promotion_manifest,
    validate_input_roots_absolute,
    validate_promoted_functional_rows,
    validate_prospective_holdout_inputs,
    validate_vus_inputs,
)

DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_functional_coverage_map_v1.yaml"

#: The pinned canonical-LF (CRLF/CR normalized to LF) SHA-256 of the ONE
#: trusted config file (spec_version 1.0.1). ``_load_config`` compares
#: this fixed constant against a freshly-read file's canonical bytes --
#: never a hash recomputed from whatever file happens to be at
#: ``DEFAULT_CONFIG`` -- so neither a byte-identical copy at a different
#: path nor a symlink alias, nor a silently drifted ``DEFAULT_CONFIG``
#: itself, is ever trusted.
CONFIG_CANONICAL_LF_SHA256 = "e5082dcbe75338949f386c6b193016befc0f9f7e56b6371267ba07584576ad05"

_FUNCTIONAL_PROMOTION_ROOT_ENV = "RAPTOR_TSC2_FUNCTIONAL_IDENTITY_PROMOTION_ROOT"
_VUS_IDENTITY_ROOT_ENV = "RAPTOR_TSC_VUS_IDENTITY_ROOT"
_VUS_BIAS_ROOT_ENV = "RAPTOR_TSC_VUS_BIAS_ROOT"
_PRIORITY_QUEUE_ROOT_ENV = "RAPTOR_TSC_PRIORITY_QUEUE_ROOT"
_PROSPECTIVE_HOLDOUT_ROOT_ENV = "RAPTOR_TSC_PROSPECTIVE_HOLDOUT_ROOT"
_ATLAS_IDENTITY_MAP_ROOT_ENV = "RAPTOR_ATLAS_TSC2_IDENTITY_MAP_ROOT"
_ATLAS_PANEL_ROOT_ENV = "RAPTOR_ATLAS_TSC2_PANEL_ROOT"
_OUTPUT_ROOT_ENV = "RAPTOR_TSC2_FUNCTIONAL_COVERAGE_ROOT"
_DEFAULT_OUTPUT_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-functional-coverage"

_INPUT_ROOT_ENV_VARS = frozenset(
    {
        _FUNCTIONAL_PROMOTION_ROOT_ENV,
        _VUS_IDENTITY_ROOT_ENV,
        _VUS_BIAS_ROOT_ENV,
        _PRIORITY_QUEUE_ROOT_ENV,
        _PROSPECTIVE_HOLDOUT_ROOT_ENV,
        _ATLAS_IDENTITY_MAP_ROOT_ENV,
        _ATLAS_PANEL_ROOT_ENV,
    }
)

_SOURCE_ORDER: tuple[str, ...] = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")


class Tsc2FunctionalCoverageMapOperatorError(RuntimeError):
    """Base error for this operator CLI's own config/plan-building/path-
    containment/expected-pilot-gate failures (never a library-domain
    error)."""


def _load_config(config_path: Path) -> dict[str, Any]:
    """Load, path-safety-check and hash-verify the operator's ONE trusted
    config file. ``config_path`` must be absolute; every path component
    from the filesystem anchor down to the leaf must be free of a
    symlink/junction/reparse point (checked BEFORE any ``resolve()``);
    the resolved path must equal exactly the resolved ``DEFAULT_CONFIG``
    (no alias, copy or symlink substitution is ever trusted, however
    byte-identical); and its canonical-LF (CRLF/CR normalized to LF)
    bytes must match the pinned ``CONFIG_CANONICAL_LF_SHA256`` BEFORE any
    ``yaml.safe_load`` is ever attempted. Every OS/decode/YAML failure is
    translated narrowly into ``Tsc2FunctionalCoverageMapOperatorError``."""
    config_path = Path(config_path)
    if not config_path.is_absolute():
        raise Tsc2FunctionalCoverageMapOperatorError(f"config path must be absolute, got {config_path!s}")

    _assert_no_symlink_ancestor(config_path, context="config")

    try:
        resolved_config_path = config_path.resolve()
        resolved_default_config = DEFAULT_CONFIG.resolve()
    except OSError as exc:
        raise Tsc2FunctionalCoverageMapOperatorError(f"config: unable to resolve {config_path}: {exc}") from exc
    if resolved_config_path != resolved_default_config:
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"config path {config_path} does not resolve to the canonical config path {DEFAULT_CONFIG}; "
            "no alias/copy/symlink substitution is ever trusted"
        )

    if not config_path.is_file():
        raise Tsc2FunctionalCoverageMapOperatorError(f"config file not found: {config_path}")
    try:
        raw_bytes = config_path.read_bytes()
    except OSError as exc:
        raise Tsc2FunctionalCoverageMapOperatorError(f"config: unable to read {config_path}: {exc}") from exc

    canonical_bytes = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    observed_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    if observed_sha256.lower() != CONFIG_CANONICAL_LF_SHA256.lower():
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"config canonical-LF sha256 mismatch: expected {CONFIG_CANONICAL_LF_SHA256!r}, observed "
            f"{observed_sha256!r}"
        )

    try:
        loaded = yaml.safe_load(canonical_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Tsc2FunctionalCoverageMapOperatorError(f"config {config_path} is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise Tsc2FunctionalCoverageMapOperatorError(f"config {config_path} did not parse to a mapping")
    return loaded


def _resolve_root(*, cli_value: Path | None, env_var: str, default: Path | None = None) -> Path:
    """Resolve a root as CLI flag > environment variable > ``default``,
    applying only ``expanduser()`` (never resolving symlinks or the
    working directory). For every pinned input root, the result must be
    absolute regardless of its source."""
    if cli_value is not None:
        root = cli_value.expanduser()
    elif os.environ.get(env_var, "").strip():
        root = Path(os.environ[env_var]).expanduser()
    elif default is not None:
        root = default.expanduser()
    else:
        raise Tsc2FunctionalCoverageMapOperatorError(f"no root supplied and ${env_var} is not set")
    if env_var in _INPUT_ROOT_ENV_VARS and not root.is_absolute():
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"${env_var} root must be an absolute path, got relative path {root!s}"
        )
    return root


def _assert_no_symlink_ancestor(path: Path, *, context: str) -> None:
    """Raise ``Tsc2FunctionalCoverageMapOperatorError`` if ``path`` itself,
    or any of its ancestor directories, is a symlink/reparse point --
    reusing the shared ``_is_symlink_or_reparse_point`` predicate rather
    than duplicating that detection here."""
    current = path
    while True:
        try:
            is_reparse = _is_symlink_or_reparse_point(current)
        except (CoverageInputError, OSError) as exc:
            raise Tsc2FunctionalCoverageMapOperatorError(
                f"{context}: unable to inspect {current} for a symlink/reparse point: {exc}"
            ) from exc
        if is_reparse:
            raise Tsc2FunctionalCoverageMapOperatorError(
                f"{context} path {path} has a symlink/reparse ancestor at {current}; refusing to "
                "read through a symlink"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _read_bundle_manifest(*, root: Path, run_name: str, manifest_filename: str, label: str) -> dict[str, Any]:
    run_dir = root / run_name
    manifest_path = run_dir / manifest_filename
    _assert_no_symlink_ancestor(manifest_path, context=label)
    resolved_run_dir = run_dir.resolve()
    resolved_manifest_path = manifest_path.resolve()
    try:
        resolved_manifest_path.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"{label}: manifest path escapes its run directory {run_dir}"
        ) from exc
    if not manifest_path.is_file():
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"{label}: bundle manifest not found at {manifest_path}; is the corresponding root "
            "environment variable/--*-root correctly set to the published bundle's parent directory?"
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"{label}: bundle manifest {manifest_path} is not valid JSON: {exc}"
        ) from exc


def _parse_jsonl(payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line == "":
            continue
        rows.append(json.loads(line))
    return rows


def _read_repo_file_pin(
    *, relative_path: str, expected_sha256: str, label: str, hash_mode: str = "raw",
) -> bytes:
    """Read a repo-tracked config/policy file with path-safety, verifying
    its bytes against ``expected_sha256`` under one of two hash modes:
    ``"raw"`` hashes the bytes verbatim (used for the frozen Atlas
    anchor); ``"canonical_lf"`` first normalizes CRLF/CR line endings to
    LF (used for the approved predictor policy, whose config pin is a
    ``canonical_lf_sha256``)."""
    path = REPO_ROOT / relative_path
    _assert_no_symlink_ancestor(path, context=label)
    if not path.is_file():
        raise Tsc2FunctionalCoverageMapOperatorError(f"{label}: file not found at {path}")
    payload = path.read_bytes()
    if hash_mode == "raw":
        basis = payload
    elif hash_mode == "canonical_lf":
        basis = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    else:
        raise Tsc2FunctionalCoverageMapOperatorError(f"{label}: unknown hash_mode {hash_mode!r}")
    observed_sha256 = hashlib.sha256(basis).hexdigest()
    if observed_sha256.lower() != str(expected_sha256).lower():
        raise Tsc2FunctionalCoverageMapOperatorError(
            f"{label}: {hash_mode} sha256 mismatch: expected {expected_sha256!r}, observed {observed_sha256!r}"
        )
    return payload


def _read_repo_file_raw(*, relative_path: str, label: str) -> bytes:
    """Read a repo-tracked file's raw bytes with path-safety only -- no
    hash comparison here. Used for artifacts (like the Atlas tracked
    lock) whose pinned value is a canonical SELF-hash of their own parsed
    content rather than a fixed raw-byte digest; the self-hash check
    happens downstream in ``ingest.load_atlas_contrast_replays``."""
    path = REPO_ROOT / relative_path
    _assert_no_symlink_ancestor(path, context=label)
    if not path.is_file():
        raise Tsc2FunctionalCoverageMapOperatorError(f"{label}: file not found at {path}")
    return path.read_bytes()


def _compute_response_bundle_observed(
    response_root: Path, *, compute_bundle_hash_fn: Callable[[Path], tuple[str, int, int]] | None = None,
) -> dict[str, Any]:
    """Compute the Atlas official-response-tree commitment
    (``{sha256, file_count, byte_count}``) this operator passes to
    ``ingest.load_atlas_contrast_replays`` as ``response_bundle_observed``.
    ``response_root`` (and every one of its ancestors) is checked for a
    symlink/junction/reparse point BEFORE any tree-hash call is ever made
    -- never after. ``compute_bundle_hash_fn`` defaults to the real
    ``raptor.atlas.identity_map._compute_bundle_hash`` seam; tests may
    inject a stand-in to decouple this path-safety gate from a real
    directory walk."""
    _assert_no_symlink_ancestor(response_root, context="atlas_response_root")
    if compute_bundle_hash_fn is None:
        from raptor.atlas.identity_map import _compute_bundle_hash as compute_bundle_hash_fn
    sha256, file_count, byte_count = compute_bundle_hash_fn(response_root)
    return {"sha256": sha256, "file_count": file_count, "byte_count": byte_count}


def _validate_expected_pilot_result(*, manifest: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
    """Fail-closed gate: the coverage manifest's ``coverage_statistics``
    must match the frozen pilot expectations (config ``expected_pilot``)
    EXACTLY, across every axis, before publication. Scalar leaves are
    compared by EXACT type as well as value (``True != 1`` and
    ``1.0 != 1``). Raises ``Tsc2FunctionalCoverageMapOperatorError``
    naming the first mismatched path."""
    if "coverage_statistics" not in manifest:
        raise Tsc2FunctionalCoverageMapOperatorError(
            "expected_pilot gate failed: manifest is missing its coverage_statistics field"
        )
    computed = manifest["coverage_statistics"]

    def _walk(actual: Any, expected: Any, path: str) -> None:
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise Tsc2FunctionalCoverageMapOperatorError(
                    f"expected_pilot gate failed at {path or '<root>'}: expected a mapping"
                )
            missing = set(expected) - set(actual)
            extra = set(actual) - set(expected)
            if missing or extra:
                raise Tsc2FunctionalCoverageMapOperatorError(
                    f"expected_pilot gate failed at {path or '<root>'}: missing={sorted(missing)!r} "
                    f"extra={sorted(extra)!r}"
                )
            for key in expected:
                _walk(actual[key], expected[key], f"{path}.{key}" if path else str(key))
            return
        if type(actual) is not type(expected) or actual != expected:
            raise Tsc2FunctionalCoverageMapOperatorError(
                f"expected_pilot gate failed at {path or '<root>'}: {actual!r} ({type(actual).__name__}) != "
                f"{expected!r} ({type(expected).__name__})"
            )

    _walk(computed, expected_pilot, "")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument("--functional-promotion-root", type=Path, default=None)
    parser.add_argument("--vus-identity-root", type=Path, default=None)
    parser.add_argument("--vus-bias-root", type=Path, default=None)
    parser.add_argument("--priority-queue-root", type=Path, default=None)
    parser.add_argument("--prospective-holdout-root", type=Path, default=None)
    parser.add_argument("--atlas-identity-map-root", type=Path, default=None)
    parser.add_argument("--atlas-panel-root", type=Path, default=None)
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help=f"external coverage bundle root (default: ${_OUTPUT_ROOT_ENV} or {_DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--summary-output", type=Path, default=None,
        help="optional path to write the aggregate-only committed summary JSON; never written unless supplied",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run full validation/statistics/expected-pilot gating and exit before publication or summary writes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        config = _load_config(args.config)

        functional_promotion_root = _resolve_root(
            cli_value=args.functional_promotion_root, env_var=_FUNCTIONAL_PROMOTION_ROOT_ENV,
        )
        vus_identity_root = _resolve_root(cli_value=args.vus_identity_root, env_var=_VUS_IDENTITY_ROOT_ENV)
        vus_bias_root = _resolve_root(cli_value=args.vus_bias_root, env_var=_VUS_BIAS_ROOT_ENV)
        priority_queue_root = _resolve_root(cli_value=args.priority_queue_root, env_var=_PRIORITY_QUEUE_ROOT_ENV)
        prospective_holdout_root = _resolve_root(
            cli_value=args.prospective_holdout_root, env_var=_PROSPECTIVE_HOLDOUT_ROOT_ENV,
        )
        atlas_identity_map_root = _resolve_root(
            cli_value=args.atlas_identity_map_root, env_var=_ATLAS_IDENTITY_MAP_ROOT_ENV,
        )
        atlas_panel_root = _resolve_root(cli_value=args.atlas_panel_root, env_var=_ATLAS_PANEL_ROOT_ENV)
        output_root = _resolve_root(cli_value=args.output_root, env_var=_OUTPUT_ROOT_ENV, default=_DEFAULT_OUTPUT_ROOT)

        validate_input_roots_absolute(
            functional_promotion_root=functional_promotion_root,
            vus_identity_root=vus_identity_root,
            vus_bias_root=vus_bias_root,
            priority_queue_root=priority_queue_root,
            prospective_holdout_root=prospective_holdout_root,
            atlas_identity_map_root=atlas_identity_map_root,
            atlas_panel_root=atlas_panel_root,
            output_root=output_root,
        )

        # ------------------------------------------------------------
        # 1. Functional identity promotion.
        # ------------------------------------------------------------
        fn_cfg = config["inputs"]["functional_identity_promotion"]
        promotion_manifest = _read_bundle_manifest(
            root=functional_promotion_root, run_name=fn_cfg["run_name"],
            manifest_filename=fn_cfg["manifest_filename"], label="functional_identity_promotion",
        )
        fn_expected_pins = {
            "bundle_id": fn_cfg["bundle_id"],
            "manifest_content_hash": fn_cfg["manifest_content_hash"],
            "required_identity_state": fn_cfg["required_identity_state"],
            "artifacts": fn_cfg["artifacts"],
        }
        validated_promotion = validate_functional_promotion_manifest(
            promotion_manifest=promotion_manifest, expected_pins=fn_expected_pins,
        )

        functional_rows_all: list[dict[str, Any]] = []
        for source_id in _SOURCE_ORDER:
            artifact = validated_promotion["artifacts"][source_id]
            payload = read_input_payload(
                root=functional_promotion_root, run_name=fn_cfg["run_name"],
                relative_path=artifact["relative_path"], label=f"functional_promotion.{source_id}",
                expected_sha256=artifact["sha256"], expected_byte_length=artifact["byte_length"],
            )
            rows = _parse_jsonl(payload)
            for row in rows:
                NormalizedFunctionalRow(**row)  # fully reconstruct/validate every promoted row.
            functional_rows_all.extend(rows)

        verified_rows_raw = [
            row for row in functional_rows_all if row["identity_state"] == fn_cfg["required_identity_state"]
        ]
        verified_rows = validate_promoted_functional_rows(
            promoted_rows=verified_rows_raw,
            required_identity_state=fn_cfg["required_identity_state"],
            expected_source_rows=dict(fn_cfg["expected"]["source_verified_observations"]),
            source_order=_SOURCE_ORDER,
        )

        # ------------------------------------------------------------
        # 2. VUS universe.
        # ------------------------------------------------------------
        vus_cfg = config["inputs"]["vus_universe"]
        vus_manifest_payload = read_input_payload(
            root=vus_identity_root, run_name=None, relative_path=vus_cfg["manifest"]["relative_path"],
            label="vus_manifest", expected_sha256=vus_cfg["manifest"]["sha256"],
            expected_byte_length=vus_cfg["manifest"]["byte_length"],
        )
        vus_provenance_payload = read_input_payload(
            root=vus_identity_root, run_name=None, relative_path=vus_cfg["provenance"]["relative_path"],
            label="vus_provenance", expected_sha256=vus_cfg["provenance"]["sha256"],
            expected_byte_length=vus_cfg["provenance"]["byte_length"],
        )
        vus_bias_payload = read_input_payload(
            root=vus_bias_root, run_name=None, relative_path=vus_cfg["bias_tsv"]["relative_path"],
            label="vus_bias", expected_sha256=vus_cfg["bias_tsv"]["sha256"],
            expected_byte_length=vus_cfg["bias_tsv"]["byte_length"],
        )
        vus_result = validate_vus_inputs(
            manifest_payload=vus_manifest_payload, provenance_payload=vus_provenance_payload,
            bias_payload=vus_bias_payload, expected_manifest_pin=vus_cfg["manifest"],
            expected_provenance_pin=vus_cfg["provenance"], expected_bias_pin=vus_cfg["bias_tsv"],
            expected_gene_counts=vus_cfg["gene_counts"],
        )
        vus_spdis = {row["variant_id"] for row in vus_result["rows"]}

        # ------------------------------------------------------------
        # 3. Priority subset (reproduced through the disabled/manual census seam).
        # ------------------------------------------------------------
        priority_cfg = config["inputs"]["priority_subset_policy"]
        queue_payload = read_input_payload(
            root=priority_queue_root, run_name=priority_cfg["queue_run_name"],
            relative_path=priority_cfg["queue"]["relative_path"], label="priority_queue",
            expected_sha256=priority_cfg["queue"]["sha256"], expected_byte_length=priority_cfg["queue"]["byte_length"],
        )
        aggregate_manifest_payload = read_input_payload(
            root=priority_queue_root, run_name=priority_cfg["queue_run_name"],
            relative_path=priority_cfg["aggregate_manifest"]["relative_path"], label="priority_aggregate_manifest",
            expected_sha256=priority_cfg["aggregate_manifest"]["sha256"],
            expected_byte_length=priority_cfg["aggregate_manifest"]["byte_length"],
        )
        predictor_policy_payload = _read_repo_file_pin(
            relative_path=priority_cfg["approved_predictor_policy"]["path"],
            expected_sha256=priority_cfg["approved_predictor_policy"]["canonical_lf_sha256"],
            label="approved_predictor_policy", hash_mode="canonical_lf",
        )
        predictor_policy = json.loads(predictor_policy_payload.decode("utf-8"))
        predictor_policy = {key: predictor_policy[key] for key in ("schema", "status", "mode")}

        priority_result = reproduce_priority_subset(
            vus_manifest_payload=vus_manifest_payload, bias_payload=vus_bias_payload,
            aggregate_manifest_payload=aggregate_manifest_payload, queue_payload=queue_payload,
            expected=priority_cfg["expected"], queue_pin=priority_cfg["queue"],
            aggregate_manifest_pin=priority_cfg["aggregate_manifest"], predictor_policy=predictor_policy,
            scorer_config_pin={
                "path": str(REPO_ROOT / priority_cfg["scorer_config"]["path"]),
                "raw_sha256": priority_cfg["scorer_config"]["raw_sha256"],
            },
            eval_config_pin={
                "path": str(REPO_ROOT / priority_cfg["eval_config"]["path"]),
                "raw_sha256": priority_cfg["eval_config"]["raw_sha256"],
            },
            lineage_policy_pin={
                "path": str(REPO_ROOT / priority_cfg["lineage_policy"]["path"]),
                "raw_sha256": priority_cfg["lineage_policy"]["raw_sha256"],
            },
            packet_policy_pin={
                "path": str(REPO_ROOT / priority_cfg["packet_policy"]["path"]),
                "raw_sha256": priority_cfg["packet_policy"]["raw_sha256"],
            },
        )
        priority_by_spdi = priority_result["priority_by_spdi"]
        priority_spdis = set(priority_by_spdi)

        # ------------------------------------------------------------
        # 4. Prospective holdout.
        # ------------------------------------------------------------
        holdout_cfg = config["inputs"]["prospective_holdout"]
        holdout_manifest_payload = read_input_payload(
            root=prospective_holdout_root, run_name=None, relative_path=holdout_cfg["manifest"]["relative_path"],
            label="prospective_holdout_manifest", expected_sha256=holdout_cfg["manifest"]["sha256"],
            expected_byte_length=holdout_cfg["manifest"]["byte_length"],
        )
        holdout_provenance_payload = read_input_payload(
            root=prospective_holdout_root, run_name=None, relative_path=holdout_cfg["provenance"]["relative_path"],
            label="prospective_holdout_provenance", expected_sha256=holdout_cfg["provenance"]["sha256"],
            expected_byte_length=holdout_cfg["provenance"]["byte_length"],
        )
        holdout_result = validate_prospective_holdout_inputs(
            manifest_payload=holdout_manifest_payload, provenance_payload=holdout_provenance_payload,
            expected_manifest_pin=holdout_cfg["manifest"], expected_provenance_pin=holdout_cfg["provenance"],
            expected_gene_counts=holdout_cfg["gene_counts"], forbidden_reads=holdout_cfg["forbidden_reads"],
        )
        prospective_holdout_spdis = {row["variant_id"] for row in holdout_result["rows"]}

        # ------------------------------------------------------------
        # 5. Atlas contrast identities + anchor.
        # ------------------------------------------------------------
        atlas_cfg = config["inputs"]["atlas_contrast_identities"]
        map_payload = read_input_payload(
            root=atlas_identity_map_root, run_name=None, relative_path=atlas_cfg["map"]["relative_path"],
            label="atlas_raw_identity_map", expected_sha256=atlas_cfg["map"]["raw_sha256"],
            expected_byte_length=atlas_cfg["map"]["byte_length"],
        )
        # The tracked lock's pinned value is a canonical SELF-hash of its
        # own parsed content (never a fixed raw-byte digest) -- read its
        # raw bytes path-safely only; the self-hash check happens inside
        # ingest.load_atlas_contrast_replays.
        lock_payload = _read_repo_file_raw(
            relative_path=atlas_cfg["tracked_lock"]["path"], label="atlas_tracked_lock",
        )
        raw_inventory_payload = read_input_payload(
            root=atlas_panel_root, run_name=None, relative_path=atlas_cfg["raw_inventory"]["relative_path"],
            label="atlas_raw_inventory", expected_sha256=atlas_cfg["raw_inventory"]["sha256"],
            expected_byte_length=atlas_cfg["raw_inventory"]["byte_length"],
        )
        raw_inventory = yaml.safe_load(raw_inventory_payload.decode("utf-8"))
        raw_inventory_rows = raw_inventory.get("rows", raw_inventory.get("records", []))

        # The official response tree lives under the identity-map root,
        # not the panel root (spec
        # ``atlas_contrast_identities.official_response_root_relative_path``).
        response_root = atlas_identity_map_root / atlas_cfg["official_response_root_relative_path"]
        response_bundle_observed = _compute_response_bundle_observed(response_root)

        atlas_result = load_atlas_contrast_replays(
            map_path=atlas_identity_map_root / atlas_cfg["map"]["relative_path"],
            response_root=response_root,
            lock_path=REPO_ROOT / atlas_cfg["tracked_lock"]["path"],
            disease_pack_path=REPO_ROOT / atlas_cfg["disease_pack"]["path"],
            raw_inventory_path=atlas_panel_root / atlas_cfg["raw_inventory"]["relative_path"],
            map_payload=map_payload, lock_payload=lock_payload, raw_inventory_payload=raw_inventory_payload,
            response_bundle_observed=response_bundle_observed, raw_inventory_rows=raw_inventory_rows,
            expected_map_pin={
                "schema": atlas_cfg["map"]["schema"], "sha256": atlas_cfg["map"]["raw_sha256"],
                "byte_length": atlas_cfg["map"]["byte_length"], "map_record_count": atlas_cfg["map"]["map_record_count"],
            },
            expected_lock_pin={
                "schema": atlas_cfg["tracked_lock"]["schema"],
                "lock_content_hash": atlas_cfg["tracked_lock"]["lock_content_hash"],
            },
            expected_raw_inventory_pin={
                "sha256": atlas_cfg["raw_inventory"]["sha256"], "byte_length": atlas_cfg["raw_inventory"]["byte_length"],
                "row_count": atlas_cfg["raw_inventory"]["row_count"],
            },
            expected_response_bundle_pin={
                "sha256": atlas_cfg["response_bundle"]["sha256"],
                "file_count": atlas_cfg["response_bundle"]["file_count"],
                "byte_count": atlas_cfg["response_bundle"]["byte_count"],
            },
            expected_counts=atlas_cfg["expected"],
        )
        atlas_contrast_spdis = atlas_result["resolved_spdis"]

        anchor_cfg = config["inputs"]["atlas_anchor"]
        anchor_payload_bytes = _read_repo_file_pin(
            relative_path=anchor_cfg["path"], expected_sha256=anchor_cfg["raw_sha256"], label="atlas_anchor",
            hash_mode="raw",
        )
        anchor_payload = json.loads(anchor_payload_bytes.decode("utf-8"))
        anchor_result = validate_atlas_anchor_input(
            anchor_payload=anchor_payload, anchor_payload_bytes=anchor_payload_bytes, expected_pin=anchor_cfg,
        )
        atlas_anchor_spdi = anchor_result["spdi"]

        # ------------------------------------------------------------
        # 6. Build coverage rows + statistics.
        # ------------------------------------------------------------
        coverage_rows = build_functional_coverage_rows(
            functional_rows=verified_rows, vus_spdis=vus_spdis, priority_by_spdi=priority_by_spdi,
            prospective_holdout_spdis=prospective_holdout_spdis, atlas_contrast_spdis=atlas_contrast_spdis,
            atlas_anchor_spdi=atlas_anchor_spdi,
        )
        coverage_statistics = compute_coverage_statistics(
            coverage_rows=coverage_rows, vus_spdis=vus_spdis, priority_spdis=priority_spdis,
            priority_by_spdi=priority_by_spdi, prospective_holdout_spdis=prospective_holdout_spdis,
            atlas_contrast_spdis=atlas_contrast_spdis, atlas_anchor_spdi=atlas_anchor_spdi,
            vus_gene_counts=vus_result["gene_counts"], priority_gene_counts=priority_result["gene_counts"],
            prospective_holdout_gene_counts=holdout_result["gene_counts"],
            atlas_raw_records=atlas_result["raw_records"], atlas_resolved_count=atlas_result["resolved_count"],
            atlas_unresolved_count=atlas_result["unresolved_count"],
        )

        coverage_payload = canonical_coverage_jsonl_bytes(coverage_rows)
        output_cfg = config["output"]["external_bundle"]
        artifact_cfg = output_cfg["artifacts"]["coverage"]
        manifest = build_coverage_bundle_manifest(
            bundle_id=output_cfg["bundle_id"],
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            input_manifests={
                "functional_identity_promotion": validated_promotion["manifest_content_hash"],
                "vus_manifest": vus_cfg["manifest"]["sha256"],
                "prospective_holdout_manifest": holdout_cfg["manifest"]["sha256"],
                "atlas_identity_map": atlas_cfg["map"]["map_content_hash"],
            },
            artifacts=[
                {
                    "artifact_id": artifact_cfg["artifact_id"],
                    "relative_path": artifact_cfg["relative_path"],
                    "sha256": hashlib.sha256(coverage_payload).hexdigest(),
                    "byte_length": len(coverage_payload),
                    "row_count": len(coverage_rows),
                }
            ],
            counts={"rows": len(coverage_rows), "artifacts": 1},
            coverage_statistics=coverage_statistics,
            boundaries=dict(config["boundaries"]),
        )

        _validate_expected_pilot_result(manifest=manifest, expected_pilot=config["expected_pilot"])

        if args.dry_run:
            print("dry-run: expected_pilot gate passed; skipping publication and summary writes")
            return 0

        publish_result = publish_coverage_bundle(
            repo_root=REPO_ROOT, output_root=output_root, run_name=output_cfg["run_name"],
            manifest=manifest, artifact_payloads={artifact_cfg["relative_path"]: coverage_payload},
        )
    except Tsc2FunctionalCoverageMapOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (InputPinMismatchError, CoverageInputError) as exc:
        print(f"ERROR: input validation failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (CoverageBuildError, NormalizationContractError) as exc:
        print(f"ERROR: coverage build failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (CoverageBundleBoundaryError, CoverageManifestError) as exc:
        print(f"ERROR: bundle publication failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"coverage bundle written: {publish_result['run_dir']}")
    print(f"rows={manifest['counts']['rows']} content_hash={manifest['content_hash']}")

    if args.summary_output is not None:
        summary = build_committed_summary(manifest)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
