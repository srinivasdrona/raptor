#!/usr/bin/env python
"""Normalize the RAPTOR v2 TSC2 functional-row identity normalization pilot
(``docs/project/specs/raptor-v2-functional-identity-normalization-v1.yaml``).

This is the operator for ``raptor.external.tsc2_functional`` -- a pure,
offline, deterministic package (see that package's module docstrings for
the full design). This script:

1. Loads ``configs/external/tsc2_functional_identity_normalization_v1.yaml``
   (the frozen TSC2 source-ingestion bundle pins, the pinned
   ``NC_000016.10`` reference FASTA, the identity pins, and the exact
   expected pilot totals).
2. Reads the already-published TSC2 source-ingestion bundle manifest and
   its three required artifact files from ``--source-root`` (default
   ``$RAPTOR_TSC2_SOURCE_ROOT``).
3. Verifies the pinned reference FASTA's checksum from ``--reference-root``
   (default ``$RAPTOR_TSC2_REFERENCE_ROOT``) -- BEFORE any SGE row is
   normalized -- and instantiates
   ``raptor.ingest.normalizer.SeqRepoGenomicNormalizer`` against it.
4. Runs ``raptor.external.tsc2_functional.ingest.normalize_functional_
   bundle`` entirely offline over the injected bytes, builds a
   normalization manifest + canonical per-source JSONL artifacts
   (``raptor.external.tsc2_functional.bundle``), and publishes them to an
   external, create-only run directory under ``--output-root`` (default
   ``$RAPTOR_TSC2_FUNCTIONAL_NORMALIZATION_ROOT``).
5. Optionally writes a compact, aggregate-only committed summary (counts,
   hashes, identity-state/variant-kind counts -- never per-row identities,
   HGVS/SPDI strings, raw scores or source functional classes) to an
   EXPLICITLY supplied ``--summary-output`` path.

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

from raptor.external.tsc2_functional.bundle import (  # noqa: E402
    FunctionalBundleBoundaryError,
    NormalizationManifestError,
    build_committed_summary,
    build_normalization_manifest,
    canonical_jsonl_bytes,
    publish_normalized_bundle,
)
from raptor.external.tsc2_functional.ingest import (  # noqa: E402
    FunctionalNormalizationError,
    normalize_functional_bundle,
)
from raptor.external.tsc2_functional.model import (  # noqa: E402
    ALLOWED_IDENTITY_STATES,
    ALLOWED_VARIANT_KINDS,
    NormalizationContractError,
    NormalizationOutcomeError,
    ScoreValidationError,
)
from raptor.ingest.normalizer import (  # noqa: E402
    ReferenceChecksumMismatchError,
    ReferenceNotAvailableError,
    SeqRepoGenomicNormalizer,
)

DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_functional_identity_normalization_v1.yaml"
DEFAULT_SOURCE_ROOT_ENV = "RAPTOR_TSC2_SOURCE_ROOT"
DEFAULT_REFERENCE_ROOT_ENV = "RAPTOR_TSC2_REFERENCE_ROOT"
DEFAULT_OUTPUT_ROOT_ENV = "RAPTOR_TSC2_FUNCTIONAL_NORMALIZATION_ROOT"
DEFAULT_OUTPUT_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-functional-normalization"

_REQUIRED_SOURCE_ORDER: tuple[str, ...] = ("mavedb_clipe", "igvf_vamp_seq", "igvf_sge")


class Tsc2FunctionalOperatorError(RuntimeError):
    """Base error for this operator CLI's own config/plan-building failures."""


class _NormalizerConfig:
    """Minimal ``config`` object ``SeqRepoGenomicNormalizer.normalize``
    expects: ``reference_checksums`` (accession -> pinned sha256, re-
    verified by the normalizer on every call) and a ``pins_dict()`` used
    only to annotate any manual-queue item it emits."""

    def __init__(self, *, reference_checksums: dict[str, str], pins: dict[str, Any], run_id: str) -> None:
        self.reference_checksums = reference_checksums
        self._pins = pins
        self.run_id = run_id

    def pins_dict(self) -> dict[str, Any]:
        return dict(self._pins)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise Tsc2FunctionalOperatorError(f"config file not found: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise Tsc2FunctionalOperatorError(f"config {config_path} did not parse to a mapping")
    return loaded


def _read_source_manifest(source_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    source_bundle_cfg = config["inputs"]["source_bundle"]
    run_dir = source_root / source_bundle_cfg["run_name"]
    manifest_path = run_dir / source_bundle_cfg["manifest_filename"]
    if not manifest_path.is_file():
        raise Tsc2FunctionalOperatorError(
            f"source bundle manifest not found at {manifest_path}; is RAPTOR_TSC2_SOURCE_ROOT "
            "correctly set to the published tsc2-source-pilot run's parent directory?"
        )
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Tsc2FunctionalOperatorError(f"source bundle manifest {manifest_path} is not valid JSON: {exc}") from exc


def _assert_no_symlink_ancestor(path: Path, *, context: str) -> None:
    """Raise ``Tsc2FunctionalOperatorError`` if ``path`` itself, or any of
    its ancestor directories, is a symlink/reparse point. Never follows a
    symlink to decide this -- ``Path.is_symlink`` inspects the link itself,
    never its target."""
    current = path
    while True:
        if current.is_symlink():
            raise Tsc2FunctionalOperatorError(
                f"{context} path {path} has a symlink/reparse ancestor at {current}; refusing to "
                "read through a symlink"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _resolve_pinned_artifact_path(run_dir: Path, relative_path: Any) -> Path:
    """Resolve ``relative_path`` (a config-PINNED path, never a manifest-
    supplied one) against ``run_dir`` and verify it is safe to read: not a
    symlink (nor any ancestor), and its fully-resolved location remains
    under ``run_dir``. Raises ``Tsc2FunctionalOperatorError`` -- and never
    reads any bytes -- on any violation."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise Tsc2FunctionalOperatorError(f"invalid pinned relative_path: {relative_path!r}")
    candidate = run_dir / relative_path
    _assert_no_symlink_ancestor(candidate, context="pinned artifact")
    resolved_run_dir = run_dir.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise Tsc2FunctionalOperatorError(
            f"pinned artifact relative_path {relative_path!r} escapes the source run directory "
            f"{run_dir}"
        ) from exc
    return candidate


def _read_artifact_payloads(
    source_root: Path, config: dict[str, Any], source_manifest: dict[str, Any]
) -> dict[str, bytes]:
    """Read every required source artifact's bytes from its config-PINNED
    relative path (never a manifest-supplied ``relative_path`` -- a
    manifest is untrusted input until ``validate_frozen_source_bundle``
    has verified it, and even then this operator never lets a manifest
    field choose which file on disk gets read). ``source_manifest`` is
    accepted for interface symmetry with the rest of the pipeline but is
    never consulted to resolve a path."""
    del source_manifest  # never used to resolve a read path -- see docstring
    source_bundle_cfg = config["inputs"]["source_bundle"]
    run_dir = source_root / source_bundle_cfg["run_name"]
    required_artifacts = source_bundle_cfg["required_artifacts"]

    payloads: dict[str, bytes] = {}
    for pin in required_artifacts.values():
        artifact_id = pin["artifact_id"]
        resolved_path = _resolve_pinned_artifact_path(run_dir, pin["relative_path"])
        if not resolved_path.is_file():
            raise Tsc2FunctionalOperatorError(f"required source artifact not found at {resolved_path}")
        payloads[artifact_id] = resolved_path.read_bytes()

    return payloads


def _build_plan(config: dict[str, Any]) -> dict[str, Any]:
    inputs = config["inputs"]
    source_bundle_cfg = inputs["source_bundle"]
    reference_cfg = inputs["genomic_reference"]
    identity_pins = inputs["identity_pins"]
    source_rules = config["source_rules"]
    expected_pilot = config["expected_pilot"]

    expected_artifacts = []
    for source_id, pin in source_bundle_cfg["required_artifacts"].items():
        expected_artifacts.append(
            {
                "artifact_id": pin["artifact_id"],
                "source_id": source_id,
                "relative_path": pin["relative_path"],
                "sha256": pin["sha256"],
                **({"md5": pin["md5"]} if "md5" in pin else {}),
                "byte_length": pin["byte_length"],
            }
        )

    return {
        "reference": {
            "accession": reference_cfg["accession"],
            "assembly": reference_cfg["assembly"],
            "sha256": reference_cfg["sha256"],
        },
        "expected_source_rows": dict(expected_pilot["source_rows"]),
        "identity_pins": dict(identity_pins),
        "input_bundle": {
            "bundle_id": source_bundle_cfg["bundle_id"],
            "manifest_content_hash": source_bundle_cfg["manifest_content_hash"],
            "artifacts": expected_artifacts,
        },
        "header_pins": {
            source_id: list(source_rules[source_id]["exact_header"]) for source_id in _REQUIRED_SOURCE_ORDER
        },
    }


def _count_by(rows: list[dict[str, Any]], field: str, allowed: frozenset[str]) -> dict[str, int]:
    counts: dict[str, int] = {value: 0 for value in allowed}
    for row in rows:
        counts[row[field]] += 1
    return {key: value for key, value in counts.items() if value}


def _build_manifest_and_payloads(
    *, config: dict[str, Any], rows_by_source: dict[str, list[dict[str, Any]]], created_at: str
) -> tuple[dict[str, Any], dict[str, bytes]]:
    output_cfg = config["output"]["external_bundle"]
    source_bundle_cfg = config["inputs"]["source_bundle"]

    artifacts = []
    jsonl_payloads: dict[str, bytes] = {}
    all_rows: list[dict[str, Any]] = []
    for source_id in _REQUIRED_SOURCE_ORDER:
        rows = rows_by_source[source_id]
        all_rows.extend(rows)
        payload = canonical_jsonl_bytes(rows)
        relative_path = f"normalized/{source_id}.jsonl"
        jsonl_payloads[relative_path] = payload
        artifacts.append(
            {
                "artifact_id": f"{source_id}-normalized-jsonl",
                "source_id": source_id,
                "relative_path": relative_path,
                "byte_length": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "row_count": len(rows),
            }
        )

    counts = {
        "sources": len(_REQUIRED_SOURCE_ORDER),
        "artifacts": len(artifacts),
        "rows": len(all_rows),
    }
    identity_state_counts = _count_by(all_rows, "identity_state", ALLOWED_IDENTITY_STATES)
    variant_kind_counts = _count_by(all_rows, "variant_kind", ALLOWED_VARIANT_KINDS)

    manifest = build_normalization_manifest(
        bundle_id=output_cfg["bundle_id"],
        created_at=created_at,
        input_bundle={
            "bundle_id": source_bundle_cfg["bundle_id"],
            "content_hash": source_bundle_cfg["manifest_content_hash"],
        },
        reference={
            "accession": config["inputs"]["genomic_reference"]["accession"],
            "sha256": config["inputs"]["genomic_reference"]["sha256"],
        },
        artifacts=artifacts,
        counts=counts,
        identity_state_counts=identity_state_counts,
        variant_kind_counts=variant_kind_counts,
        boundaries={"network": "forbidden", "external_output_only": True},
    )
    return manifest, jsonl_payloads


def _validate_expected_pilot_counts(manifest: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
    """Fail-closed gate: the normalization manifest's actual row/source/
    identity-state/variant-kind totals must match the frozen pilot
    expectations (config ``expected_pilot``) EXACTLY before publication.
    ``source_rows`` is always DERIVED from ``manifest["artifacts"]``
    (``source_id`` -> ``row_count``) -- never read from any other,
    possibly stale, manifest field. Raises ``Tsc2FunctionalOperatorError``
    naming the specific mismatched axis (``total_rows``, ``source_rows``,
    ``identity_state_counts`` or ``variant_kind_counts``)."""
    if manifest["counts"]["rows"] != expected_pilot["total_rows"]:
        raise Tsc2FunctionalOperatorError(
            f"expected_pilot gate failed on total_rows: manifest counts.rows "
            f"{manifest['counts']['rows']!r} != expected {expected_pilot['total_rows']!r}"
        )

    derived_source_rows: dict[str, int] = {}
    for artifact in manifest["artifacts"]:
        source_id = artifact["source_id"]
        if source_id in derived_source_rows:
            raise Tsc2FunctionalOperatorError(
                f"expected_pilot gate failed on source_rows: duplicate source_id {source_id!r} "
                "across manifest.artifacts"
            )
        derived_source_rows[source_id] = artifact["row_count"]
    if derived_source_rows != expected_pilot["source_rows"]:
        raise Tsc2FunctionalOperatorError(
            f"expected_pilot gate failed on source_rows: derived {derived_source_rows!r} != "
            f"expected {expected_pilot['source_rows']!r}"
        )

    if manifest["identity_state_counts"] != expected_pilot["identity_state_counts"]:
        raise Tsc2FunctionalOperatorError(
            "expected_pilot gate failed on identity_state_counts: manifest "
            f"{manifest['identity_state_counts']!r} != expected "
            f"{expected_pilot['identity_state_counts']!r}"
        )

    if manifest["variant_kind_counts"] != expected_pilot["variant_kind_counts"]:
        raise Tsc2FunctionalOperatorError(
            "expected_pilot gate failed on variant_kind_counts: manifest "
            f"{manifest['variant_kind_counts']!r} != expected "
            f"{expected_pilot['variant_kind_counts']!r}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument(
        "--source-root", type=Path, default=None,
        help=f"published TSC2 source-ingestion bundle root (default: ${DEFAULT_SOURCE_ROOT_ENV})",
    )
    parser.add_argument(
        "--reference-root", type=Path, default=None,
        help=f"pinned genomic reference FASTA root (default: ${DEFAULT_REFERENCE_ROOT_ENV})",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help=(
            f"external normalization bundle root (default: ${DEFAULT_OUTPUT_ROOT_ENV} or "
            f"{DEFAULT_OUTPUT_ROOT})"
        ),
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

        if args.source_root is not None:
            source_root = args.source_root
        else:
            source_root_env = os.environ.get(DEFAULT_SOURCE_ROOT_ENV)
            if not source_root_env or not source_root_env.strip():
                raise Tsc2FunctionalOperatorError(
                    f"no --source-root supplied and ${DEFAULT_SOURCE_ROOT_ENV} is not set"
                )
            source_root = Path(source_root_env)
        source_root = source_root.expanduser()

        if args.reference_root is not None:
            reference_root = args.reference_root
        else:
            reference_root_env = os.environ.get(DEFAULT_REFERENCE_ROOT_ENV)
            if not reference_root_env or not reference_root_env.strip():
                raise Tsc2FunctionalOperatorError(
                    f"no --reference-root supplied and ${DEFAULT_REFERENCE_ROOT_ENV} is not set"
                )
            reference_root = Path(reference_root_env)
        reference_root = reference_root.expanduser()

        if args.output_root is not None:
            output_root = args.output_root
        else:
            output_root_env = os.environ.get(DEFAULT_OUTPUT_ROOT_ENV)
            output_root = Path(output_root_env) if output_root_env and output_root_env.strip() else DEFAULT_OUTPUT_ROOT
        output_root = output_root.expanduser()

        source_manifest = _read_source_manifest(source_root, config)
        artifact_payloads = _read_artifact_payloads(source_root, config, source_manifest)
        plan = _build_plan(config)

        reference_cfg = config["inputs"]["genomic_reference"]
        reference_fasta_path = reference_root / reference_cfg["fasta_filename"]
        normalizer = SeqRepoGenomicNormalizer(reference_root=reference_root)
        normalizer_config = _NormalizerConfig(
            reference_checksums={reference_cfg["accession"]: reference_cfg["sha256"]},
            pins=dict(config["inputs"]["identity_pins"]),
            run_id=config["output"]["external_bundle"]["bundle_id"],
        )

        result = normalize_functional_bundle(
            plan=plan,
            source_manifest=source_manifest,
            artifact_payloads=artifact_payloads,
            reference_fasta_path=reference_fasta_path,
            normalizer=normalizer,
            normalizer_config=normalizer_config,
        )

        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest, jsonl_payloads = _build_manifest_and_payloads(
            config=config, rows_by_source=result["rows_by_source"], created_at=created_at
        )

        _validate_expected_pilot_counts(manifest, config["expected_pilot"])

        publish_result = publish_normalized_bundle(
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=config["output"]["external_bundle"]["run_name"],
            manifest=manifest,
            artifact_payloads=jsonl_payloads,
        )
    except Tsc2FunctionalOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (ReferenceNotAvailableError, ReferenceChecksumMismatchError) as exc:
        print(f"ERROR: reference integrity failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except FunctionalNormalizationError as exc:
        print(f"ERROR: input validation failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (NormalizationContractError, ScoreValidationError, NormalizationOutcomeError) as exc:
        print(f"ERROR: normalization failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (FunctionalBundleBoundaryError, NormalizationManifestError) as exc:
        print(f"ERROR: bundle publication failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"normalization bundle written: {publish_result['run_dir']}")
    print(
        f"sources={manifest['counts']['sources']} artifacts={manifest['counts']['artifacts']} "
        f"rows={manifest['counts']['rows']} content_hash={manifest['content_hash']}"
    )

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
