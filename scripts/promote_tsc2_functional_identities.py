#!/usr/bin/env python
"""Promote the RAPTOR v2 TSC2 functional-identity promotion pilot
(``docs/project/specs/raptor-v2-functional-identity-promotion-v1.yaml``).

This is the operator for ``raptor.external.tsc2_identity_promotion`` -- a
pure, offline, deterministic package (see that package's module
docstrings for the full design). This script:

1. Loads ``configs/external/tsc2_functional_identity_promotion_v1.yaml``
   (the exact pinned hashes/counts for all three upstream input bundles,
   the identity pins, and the exact expected pilot totals).
2. Reads the three already-published upstream bundle manifests
   (functional normalization, cliPE cDNA->SPDI projector, VAMP-seq
   genomic crosswalk) from their respective roots (``--*-root``, default
   ``$RAPTOR_TSC2_FUNCTIONAL_NORMALIZATION_ROOT`` /
   ``$RAPTOR_TSC2_CDNA_PROJECTOR_ROOT`` / ``$RAPTOR_TSC2_VAMP_CROSSWALK_ROOT``
   -- there is NO current-working-directory fallback for any of these)
   and re-verifies them against the config's exact pins BEFORE reading any
   artifact bytes (``raptor.external.tsc2_identity_promotion.ingest.
   validate_input_bundle_manifests``).
3. Reads every pinned artifact's actual bytes from a trusted, safety-
   re-verified path (``ingest.read_pinned_artifact_payloads``).
4. Runs the exact, offline cliPE/VAMP/SGE join
   (``ingest.promote_functional_identities``) and computes deterministic
   verified-SPDI overlap statistics (``ingest.compute_verified_spdi_
   overlap``).
5. Builds a promotion manifest + canonical per-source JSONL artifacts
   (``raptor.external.tsc2_identity_promotion.bundle``), gates publication
   on an EXACT match against the config's ``expected_pilot`` totals across
   every axis (``_validate_expected_pilot_result``), and publishes them to
   an external, create-only run directory under ``--output-root``
   (default ``$RAPTOR_TSC2_FUNCTIONAL_IDENTITY_PROMOTION_ROOT``).
6. Optionally writes a compact, aggregate-only committed summary (counts,
   hashes, identity-state/unresolved-reason/variant-kind counts, verified-
   observation/unique-SPDI/overlap statistics -- never per-row identities,
   HGVS/SPDI strings, raw scores or clinical/evidence-strength claims) to
   an EXPLICITLY supplied ``--summary-output`` path.

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
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.tsc2_functional.model import (  # noqa: E402
    ALLOWED_IDENTITY_STATES,
    ALLOWED_VARIANT_KINDS,
    IDENTITY_STATE_TO_UNRESOLVED_REASON,
)
from raptor.external.tsc2_identity_promotion.bundle import (  # noqa: E402
    PromotionBundleBoundaryError,
    PromotionManifestError,
    build_committed_summary,
    build_identity_promotion_manifest,
    canonical_jsonl_bytes,
    publish_identity_promotion_bundle,
)
from raptor.external.tsc2_identity_promotion.ingest import (  # noqa: E402
    InputPinMismatchError,
    PromotionInvariantError,
    PromotionJoinError,
    compute_verified_spdi_overlap,
    promote_functional_identities,
    read_pinned_artifact_payloads,
    validate_input_bundle_manifests,
)
from raptor.external.tsc2_functional.model import NormalizationContractError  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_functional_identity_promotion_v1.yaml"

_FUNCTIONAL_NORMALIZATION_ROOT_ENV = "RAPTOR_TSC2_FUNCTIONAL_NORMALIZATION_ROOT"
_CLIPE_PROJECTOR_ROOT_ENV = "RAPTOR_TSC2_CDNA_PROJECTOR_ROOT"
_VAMP_CROSSWALK_ROOT_ENV = "RAPTOR_TSC2_VAMP_CROSSWALK_ROOT"
_OUTPUT_ROOT_ENV = "RAPTOR_TSC2_FUNCTIONAL_IDENTITY_PROMOTION_ROOT"
_DEFAULT_OUTPUT_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-functional-identity-promotion"

_SOURCE_ORDER: tuple[str, ...] = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")


class FunctionalIdentityPromotionOperatorError(RuntimeError):
    """Base error for this operator CLI's own config/plan-building/path-
    containment/expected-pilot-gate failures (never a library-domain
    error)."""


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise FunctionalIdentityPromotionOperatorError(f"config file not found: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise FunctionalIdentityPromotionOperatorError(f"config {config_path} did not parse to a mapping")
    return loaded


def _resolve_root(*, cli_value: Path | None, env_var: str, default: Path | None = None) -> Path:
    """Resolve an operator root explicitly: the CLI flag if given,
    otherwise the pinned environment variable, otherwise ``default`` (only
    the output root has one) -- NEVER the current working directory."""
    if cli_value is not None:
        return cli_value.expanduser()
    env_value = os.environ.get(env_var)
    if env_value and env_value.strip():
        return Path(env_value).expanduser()
    if default is not None:
        return default.expanduser()
    raise FunctionalIdentityPromotionOperatorError(f"no root supplied and ${env_var} is not set")


def _assert_no_symlink_ancestor(path: Path, *, context: str) -> None:
    """Raise ``FunctionalIdentityPromotionOperatorError`` if ``path``
    itself, or any of its ancestor directories, is a symlink/reparse
    point. Never follows a symlink to decide this -- ``Path.is_symlink``
    inspects the link itself, never its target."""
    current = path
    while True:
        if current.is_symlink():
            raise FunctionalIdentityPromotionOperatorError(
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
        raise FunctionalIdentityPromotionOperatorError(
            f"{label}: manifest path escapes its run directory {run_dir}"
        ) from exc
    if not manifest_path.is_file():
        raise FunctionalIdentityPromotionOperatorError(
            f"{label}: bundle manifest not found at {manifest_path}; is the corresponding root "
            "environment variable/--*-root correctly set to the published bundle's parent directory?"
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FunctionalIdentityPromotionOperatorError(
            f"{label}: bundle manifest {manifest_path} is not valid JSON: {exc}"
        ) from exc


def _build_expected_pins(config: dict[str, Any]) -> dict[str, Any]:
    fn_cfg = config["inputs"]["functional_normalization_bundle"]
    cp_cfg = config["inputs"]["clipe_projector_bundle"]
    vx_cfg = config["inputs"]["vamp_crosswalk_bundle"]

    def _artifact_pin(pin: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": pin["artifact_id"],
            "relative_path": pin["relative_path"],
            "sha256": pin["sha256"],
            "byte_length": pin["byte_length"],
            "row_count": pin["row_count"],
        }

    return {
        "functional_normalization_bundle": {
            "run_name": fn_cfg["run_name"],
            "bundle_id": fn_cfg["bundle_id"],
            "manifest_content_hash": fn_cfg["manifest_content_hash"],
            "artifacts": {key: _artifact_pin(pin) for key, pin in fn_cfg["artifacts"].items()},
        },
        "clipe_projector_bundle": {
            "run_name": cp_cfg["run_name"],
            "bundle_id": cp_cfg["bundle_id"],
            "manifest_content_hash": cp_cfg["manifest_content_hash"],
            "mapping": _artifact_pin(cp_cfg["mapping"]),
        },
        "vamp_crosswalk_bundle": {
            "run_name": vx_cfg["run_name"],
            "bundle_id": vx_cfg["bundle_id"],
            "manifest_content_hash": vx_cfg["manifest_content_hash"],
            "crosswalk": _artifact_pin(vx_cfg["crosswalk"]),
        },
    }


def _parse_jsonl(payload: bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line == "":
            continue
        rows.append(json.loads(line))
    return rows


def _count_by(rows: list[dict[str, Any]], field: str, allowed: frozenset[str]) -> dict[str, int]:
    """Count ``rows`` by ``field``, with EVERY value in ``allowed`` present
    in the result (defaulting to 0) -- the promotion manifest contract
    requires the exact, full vocabulary key set, including states/reasons
    this particular run happens to see zero occurrences of."""
    counts: dict[str, int] = {value: 0 for value in allowed}
    for row in rows:
        counts[row[field]] += 1
    return counts


def _validate_expected_pilot_result(*, manifest: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
    """Fail-closed gate: the promotion manifest's actual totals must match
    the frozen pilot expectations (config ``expected_pilot``) EXACTLY,
    across every axis, before publication. Raises
    ``FunctionalIdentityPromotionOperatorError`` naming the specific
    mismatched axis."""
    if manifest["counts"]["rows"] != expected_pilot["total_rows"]:
        raise FunctionalIdentityPromotionOperatorError(
            f"expected_pilot gate failed on total_rows: manifest counts.rows "
            f"{manifest['counts']['rows']!r} != expected {expected_pilot['total_rows']!r}"
        )
    if manifest["source_row_counts"] != expected_pilot["source_rows"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on source_rows: manifest source_row_counts "
            f"{manifest['source_row_counts']!r} != expected {expected_pilot['source_rows']!r}"
        )
    if manifest["identity_state_counts"] != expected_pilot["identity_state_counts"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on identity_state_counts: manifest "
            f"{manifest['identity_state_counts']!r} != expected {expected_pilot['identity_state_counts']!r}"
        )
    if manifest["unresolved_reason_counts"] != expected_pilot["unresolved_reason_counts"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on unresolved_reason_counts: manifest "
            f"{manifest['unresolved_reason_counts']!r} != expected "
            f"{expected_pilot['unresolved_reason_counts']!r}"
        )
    if manifest["variant_kind_counts"] != expected_pilot["variant_kind_counts"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on variant_kind_counts: manifest "
            f"{manifest['variant_kind_counts']!r} != expected {expected_pilot['variant_kind_counts']!r}"
        )
    if manifest["verified_observations_by_source"] != expected_pilot["verified_observations_by_source"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on verified_observations_by_source: manifest "
            f"{manifest['verified_observations_by_source']!r} != expected "
            f"{expected_pilot['verified_observations_by_source']!r}"
        )
    if manifest["verified_observations"] != expected_pilot["verified_observations"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on verified_observations: manifest "
            f"{manifest['verified_observations']!r} != expected {expected_pilot['verified_observations']!r}"
        )
    if manifest["verified_unique_spdi"] != expected_pilot["verified_unique_spdi"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on verified_unique_spdi: manifest "
            f"{manifest['verified_unique_spdi']!r} != expected {expected_pilot['verified_unique_spdi']!r}"
        )
    if manifest["duplicate_verified_observations"] != expected_pilot["duplicate_verified_observations"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on duplicate_verified_observations: manifest "
            f"{manifest['duplicate_verified_observations']!r} != expected "
            f"{expected_pilot['duplicate_verified_observations']!r}"
        )
    if manifest["source_overlap"] != expected_pilot["source_overlap"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on source_overlap: manifest "
            f"{manifest['source_overlap']!r} != expected {expected_pilot['source_overlap']!r}"
        )
    if manifest["conservation"] != expected_pilot["conservation"]:
        raise FunctionalIdentityPromotionOperatorError(
            "expected_pilot gate failed on conservation: manifest "
            f"{manifest['conservation']!r} != expected {expected_pilot['conservation']!r}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument(
        "--functional-normalization-root", type=Path, default=None,
        help=f"published functional normalization bundle root (default: ${_FUNCTIONAL_NORMALIZATION_ROOT_ENV})",
    )
    parser.add_argument(
        "--clipe-projector-root", type=Path, default=None,
        help=f"published cliPE cDNA->SPDI projector bundle root (default: ${_CLIPE_PROJECTOR_ROOT_ENV})",
    )
    parser.add_argument(
        "--vamp-crosswalk-root", type=Path, default=None,
        help=f"published VAMP-seq genomic crosswalk bundle root (default: ${_VAMP_CROSSWALK_ROOT_ENV})",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help=f"external promotion bundle root (default: ${_OUTPUT_ROOT_ENV} or {_DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--summary-output", type=Path, default=None,
        help="optional path to write the aggregate-only committed summary JSON; never written unless supplied",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        config = _load_config(args.config)

        functional_normalization_root = _resolve_root(
            cli_value=args.functional_normalization_root, env_var=_FUNCTIONAL_NORMALIZATION_ROOT_ENV,
        )
        clipe_projector_root = _resolve_root(
            cli_value=args.clipe_projector_root, env_var=_CLIPE_PROJECTOR_ROOT_ENV,
        )
        vamp_crosswalk_root = _resolve_root(
            cli_value=args.vamp_crosswalk_root, env_var=_VAMP_CROSSWALK_ROOT_ENV,
        )
        output_root = _resolve_root(
            cli_value=args.output_root, env_var=_OUTPUT_ROOT_ENV, default=_DEFAULT_OUTPUT_ROOT,
        )

        fn_cfg = config["inputs"]["functional_normalization_bundle"]
        cp_cfg = config["inputs"]["clipe_projector_bundle"]
        vx_cfg = config["inputs"]["vamp_crosswalk_bundle"]

        functional_normalization_manifest = _read_bundle_manifest(
            root=functional_normalization_root, run_name=fn_cfg["run_name"],
            manifest_filename=fn_cfg["manifest_filename"], label="functional_normalization_bundle",
        )
        clipe_projector_manifest = _read_bundle_manifest(
            root=clipe_projector_root, run_name=cp_cfg["run_name"],
            manifest_filename=cp_cfg["manifest_filename"], label="clipe_projector_bundle",
        )
        vamp_crosswalk_manifest = _read_bundle_manifest(
            root=vamp_crosswalk_root, run_name=vx_cfg["run_name"],
            manifest_filename=vx_cfg["manifest_filename"], label="vamp_crosswalk_bundle",
        )

        expected_pins = _build_expected_pins(config)
        validated_inputs = validate_input_bundle_manifests(
            functional_normalization_manifest=functional_normalization_manifest,
            clipe_projector_manifest=clipe_projector_manifest,
            vamp_crosswalk_manifest=vamp_crosswalk_manifest,
            expected_pins=expected_pins,
        )

        payloads = read_pinned_artifact_payloads(
            functional_normalization_root=functional_normalization_root,
            clipe_projector_root=clipe_projector_root,
            vamp_crosswalk_root=vamp_crosswalk_root,
            validated_inputs=validated_inputs,
        )

        functional_rows: list[dict[str, Any]] = []
        for source_id in _SOURCE_ORDER:
            functional_rows.extend(_parse_jsonl(payloads["functional_normalization"][source_id]))
        clipe_mapping_rows = _parse_jsonl(payloads["clipe_projector_mapping"])
        vamp_crosswalk_rows = _parse_jsonl(payloads["vamp_crosswalk"])

        identity_pins = config["inputs"]["identity_pins"]
        expected_source_rows = {
            source_id: validated_inputs["functional_normalization_bundle"]["artifacts"][source_id]["row_count"]
            for source_id in _SOURCE_ORDER
        }

        promotion_result = promote_functional_identities(
            functional_rows=functional_rows,
            clipe_mapping_rows=clipe_mapping_rows,
            vamp_crosswalk_rows=vamp_crosswalk_rows,
            expected_source_rows=expected_source_rows,
            transcript=identity_pins["transcript"],
            genomic_accession=identity_pins["genomic_accession"],
            assembly=identity_pins["assembly"],
        )
        promoted_rows = promotion_result["promoted_rows"]

        overlap = compute_verified_spdi_overlap(rows=promoted_rows)

        identity_state_counts = _count_by(promoted_rows, "identity_state", ALLOWED_IDENTITY_STATES)
        variant_kind_counts = _count_by(promoted_rows, "variant_kind", ALLOWED_VARIANT_KINDS)
        unresolved_reason_counts = {
            reason: identity_state_counts[state]
            for state, reason in IDENTITY_STATE_TO_UNRESOLVED_REASON.items()
            if reason is not None
        }
        source_row_counts = {
            source_id: sum(1 for row in promoted_rows if row["source_id"] == source_id)
            for source_id in _SOURCE_ORDER
        }

        output_artifact_cfg = config["output"]["external_bundle"]["artifacts"]
        artifacts: list[dict[str, Any]] = []
        payloads_by_artifact_id: dict[str, bytes] = {}
        for source_id in _SOURCE_ORDER:
            rows_for_source = [row for row in promoted_rows if row["source_id"] == source_id]
            payload = canonical_jsonl_bytes(rows_for_source)
            artifact_pin = output_artifact_cfg[source_id]
            artifacts.append(
                {
                    "artifact_id": artifact_pin["artifact_id"],
                    "relative_path": artifact_pin["relative_path"],
                    "byte_length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "row_count": len(rows_for_source),
                }
            )
            payloads_by_artifact_id[artifact_pin["artifact_id"]] = payload

        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = build_identity_promotion_manifest(
            bundle_id=config["output"]["external_bundle"]["bundle_id"],
            created_at=created_at,
            input_manifests={
                "functional_normalization": validated_inputs["functional_normalization_bundle"]["manifest_content_hash"],
                "clipe_projector": validated_inputs["clipe_projector_bundle"]["manifest_content_hash"],
                "vamp_crosswalk": validated_inputs["vamp_crosswalk_bundle"]["manifest_content_hash"],
            },
            artifacts=artifacts,
            counts={"rows": len(promoted_rows)},
            source_row_counts=source_row_counts,
            identity_state_counts=identity_state_counts,
            unresolved_reason_counts=unresolved_reason_counts,
            variant_kind_counts=variant_kind_counts,
            verified_observations_by_source=overlap["verified_observations_by_source"],
            verified_observations=overlap["verified_observations"],
            verified_unique_spdi=overlap["verified_unique_spdi"],
            duplicate_verified_observations=overlap["duplicate_verified_observations"],
            source_overlap=overlap["source_overlap"],
            conservation={
                "input_rows": promotion_result["counts"]["input_rows"],
                "output_rows": promotion_result["counts"]["output_rows"],
                "dropped_rows": promotion_result["counts"]["dropped_rows"],
                "duplicate_source_rows": 0,
            },
            boundaries=dict(config["output"]["committed_summary"]["boundaries"]),
        )

        _validate_expected_pilot_result(manifest=manifest, expected_pilot=config["expected_pilot"])

        publish_result = publish_identity_promotion_bundle(
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=config["output"]["external_bundle"]["run_name"],
            manifest=manifest,
            payloads=payloads_by_artifact_id,
        )
    except FunctionalIdentityPromotionOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except InputPinMismatchError as exc:
        print(f"ERROR: input pin mismatch ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (PromotionJoinError, PromotionInvariantError, NormalizationContractError) as exc:
        print(f"ERROR: promotion failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (PromotionBundleBoundaryError, PromotionManifestError) as exc:
        print(f"ERROR: bundle publication failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"promotion bundle written: {publish_result['run_dir']}")
    print(f"rows={manifest['counts']['rows']} content_hash={manifest['content_hash']}")

    if args.summary_output is not None:
        summary = build_committed_summary(manifest)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
