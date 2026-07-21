"""raptor.census.cli — deterministic ADR-0012 VUS census CLI (D5, D6, output boundary).

Verifies the approved disabled/manual predictor policy + bound config hashes
BEFORE any processing, loads the immutable manifest + BIAS TSV, conserves the
exact identity/row/join invariants (via `reproduce_census_strata`), derives
the non-identifying aggregate (`build_census_record`), and writes it ONLY to
the single hard-pinned `data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`
path as canonical UTF-8/LF bytes -- never overwriting an existing artifact.

Imports only `raptor.census` (packet-free), `raptor.scorer`, and
`raptor.eval` -- NEVER `raptor.packet` (P7).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from raptor.eval.config import load_config as load_eval_config
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import load_config as load_scorer_config

from .aggregate import build_census_record
from .strata import load_manifest, reproduce_census_strata

#: This file's fixed location is `<repo>/src/raptor/census/cli.py`, so the
#: repo root is always this file's great-grandparent. Tests monkeypatch this
#: module attribute directly to inject an isolated tmp-path "repo root".
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

#: The ONLY permitted census output filename (output_schema.only_permitted_output_path).
CANONICAL_CENSUS_FILENAME = "tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json"

#: Approved predictor-policy contract (hash_contract.inputs.approved_predictor_policy).
_PREDICTOR_POLICY_SCHEMA = "bp4pp3-predictor-policy/2"
_PREDICTOR_POLICY_REQUIRED_STATUS = "approved"
_PREDICTOR_POLICY_REQUIRED_MODE = "disabled_manual"
_PREDICTOR_POLICY_ALLOWED_KEYS = frozenset({
    "schema",
    "status",
    "mode",
    "production_config_hash",
    "eval_config_hash",
    "lineage_policy_hash",
    "packet_policy_hash",
    "predictor_source_hash",
    "correction_hash",
    "runtime_bundle_hash",
    "decision_reference",
})

#: CLI-arg-key -> (bound_hashes record key, predictor-policy field it must equal).
_BOUND_CONFIG_CONTRACT: tuple[tuple[str, str, str], ...] = (
    ("scorer_config", "acmg_scorer_policy", "production_config_hash"),
    ("eval_config", "eval_config", "eval_config_hash"),
    ("lineage_policy", "bias_lineage_policy", "lineage_policy_hash"),
    ("packet_candidate_direction", "packet_candidate_direction", "packet_policy_hash"),
)


class OutputBoundaryError(RuntimeError):
    """`--emit-census-record` resolves outside the single hard-pinned
    `data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`
    target, or that target already exists -- raised before any write."""


def _sha256_bytes(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_predictor_policy(policy: Mapping[str, Any]) -> None:
    """Fail closed on a non-approved/non-disabled_manual policy or any field
    outside the closed policy schema (G-VC14 / D5)."""
    extra_keys = set(policy.keys()) - _PREDICTOR_POLICY_ALLOWED_KEYS
    if extra_keys:
        raise ValueError(f"predictor policy has unrecognized field(s): {sorted(extra_keys)!r}")
    missing_keys = {"schema", "status", "mode"} - set(policy.keys())
    if missing_keys:
        raise ValueError(f"predictor policy is missing required field(s): {sorted(missing_keys)!r}")
    if policy["schema"] != _PREDICTOR_POLICY_SCHEMA:
        raise ValueError(
            f"predictor policy schema drift: expected {_PREDICTOR_POLICY_SCHEMA!r}, got {policy['schema']!r}"
        )
    if policy["status"] != _PREDICTOR_POLICY_REQUIRED_STATUS:
        raise ValueError(f"predictor policy is not approved: status={policy['status']!r}")
    if policy["mode"] != _PREDICTOR_POLICY_REQUIRED_MODE:
        raise ValueError(
            f"predictor policy mode drift: expected {_PREDICTOR_POLICY_REQUIRED_MODE!r}, got {policy['mode']!r}"
        )


def _verify_bound_hashes(policy: Mapping[str, Any], paths: Mapping[str, Path]) -> dict[str, str]:
    """Verify the CURRENT raw sha256 of every bound config surface equals the
    hash the approved policy already records for it; fail closed on drift.
    Never hardcodes an expected hash value (D5) -- always derived + cross-
    checked against the policy's own recorded fields."""
    bound_hashes: dict[str, str] = {
        "approved_predictor_policy": _sha256_bytes(paths["predictor_policy"]),
    }
    for arg_key, record_key, policy_field in _BOUND_CONFIG_CONTRACT:
        file_path = paths[arg_key]
        current_hash = _sha256_bytes(file_path)
        expected_hash = policy.get(policy_field)
        if not isinstance(expected_hash, str) or current_hash != expected_hash:
            raise ValueError(
                f"{arg_key} hash drift: on-disk sha256 does not match the approved policy's "
                f"{policy_field!r} pin (config changed since policy approval?)"
            )
        bound_hashes[record_key] = current_hash
    return bound_hashes


def _assert_output_boundary(path: str | Path) -> Path:
    """Refuse any `--emit-census-record` path except the single hard-pinned
    `data/census/<canonical>.json` target, and refuse an already-existing
    target (never overwrite ANY existing artifact) -- raised before any
    aggregate byte is emitted (G-VC11)."""
    canonical_path = (REPO_ROOT / "data" / "census" / CANONICAL_CENSUS_FILENAME).resolve()
    resolved = Path(path).resolve()
    if resolved != canonical_path:
        raise OutputBoundaryError(
            f"--emit-census-record must be exactly {canonical_path}; got {resolved}"
        )
    if resolved.exists():
        raise OutputBoundaryError(f"refusing to overwrite existing census artifact: {resolved}")
    return resolved


def _resolve_code_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if commit else "unknown"


def _canonical_json_bytes(record: Mapping[str, Any]) -> bytes:
    """UTF-8, sort_keys, indent 2, exactly one terminal LF, LF-only on every
    platform, via an explicit binary byte write (never `Path.write_text`)."""
    return json.dumps(record, sort_keys=True, indent=2).encode("utf-8") + b"\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the ADR-0012 VUS disabled/manual census aggregate")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--bias-tsv", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--scorer-config", required=True)
    parser.add_argument("--eval-config", required=True)
    parser.add_argument("--predictor-policy", required=True)
    parser.add_argument("--lineage-policy", required=True)
    parser.add_argument("--packet-candidate-direction", required=True)
    parser.add_argument("--historical-stats", required=True)
    parser.add_argument("--emit-census-record", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    predictor_policy = json.loads(Path(args.predictor_policy).read_text(encoding="utf-8"))
    _validate_predictor_policy(predictor_policy)

    bound_hashes = _verify_bound_hashes(
        predictor_policy,
        {
            "predictor_policy": Path(args.predictor_policy),
            "scorer_config": Path(args.scorer_config),
            "eval_config": Path(args.eval_config),
            "lineage_policy": Path(args.lineage_policy),
            "packet_candidate_direction": Path(args.packet_candidate_direction),
        },
    )

    write_target: Path | None = None
    if args.emit_census_record:
        write_target = _assert_output_boundary(args.emit_census_record)
    elif not args.dry_run and not args.summary:
        raise ValueError("--emit-census-record is required unless --dry-run/--summary is set")

    manifest = load_manifest(args.manifest)
    bias_rows = tuple(BiasTsvSource(args.bias_tsv).records())
    provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
    historical_stats = json.loads(Path(args.historical_stats).read_text(encoding="utf-8"))

    scorer_config = load_scorer_config(args.scorer_config)
    eval_config = load_eval_config(args.eval_config)

    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest}
    strata = reproduce_census_strata(bias_rows, manifest_by_vcf_key, scorer_config, eval_config)

    run_pins = SimpleNamespace(
        input_sha256=str(provenance["vcf_hash"]),
        output_sha256=_sha256_bytes(args.bias_tsv),
        manifest_sha256=_sha256_bytes(args.manifest),
        source_snapshot=str(provenance["source_snapshot"]),
        code_commit=_resolve_code_commit(),
    )

    record = build_census_record(
        strata=strata,
        bias_rows=bias_rows,
        manifest=manifest,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    if args.dry_run or args.summary:
        if args.summary:
            direction = record["raptor_current_policy_internal_direction"]
            print(
                "census dry-run summary: "
                f"total_vus={record['corpus']['total_vus']} "
                f"directions={direction}",
                file=sys.stderr,
            )
        return 0

    assert write_target is not None  # guaranteed by the emit/dry-run/summary check above
    write_target.parent.mkdir(parents=True, exist_ok=True)
    with open(write_target, "wb") as handle:
        handle.write(_canonical_json_bytes(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
