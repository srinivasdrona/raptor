"""raptor.census.cli — deterministic ADR-0012 VUS census CLI (D5, D6, output boundary).

Verifies the approved disabled/manual predictor policy + bound config hashes
BEFORE any processing, validates the immutable historical-stats source and
provenance (vcf_hash/source_snapshot) fail closed, loads the immutable
manifest + BIAS TSV, conserves the exact identity/row/join invariants (via
`reproduce_census_strata`), derives the non-identifying aggregate
(`build_census_record`), and writes it ONLY to the single hard-pinned
`data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`
path as canonical UTF-8/LF bytes -- never overwriting an existing artifact.

Imports only `raptor.census` (packet-free), `raptor.scorer`, and
`raptor.eval` -- NEVER `raptor.packet` (P7).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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

#: The ONLY permitted `--historical-stats` filename/source (immutable, committed data artifact).
_HISTORICAL_STATS_FILENAME = "tsc_vus_clinvar_2026-07-07_stats.json"

#: Canonical LF/Git-blob sha256 of `data/census/tsc_vus_clinvar_2026-07-07_stats.json`
#: (i.e. `git hash-object`'s content hash, NOT the raw CRLF-checkout bytes on
#: Windows): the committed historical-stats data artifact's identity is
#: pinned here so a mutated/substituted/CRLF-mangled source fails closed
#: before any processing or output (never applied to raw config hashes).
HISTORICAL_CENSUS_SHA256 = "389e93d5b37f686b8d5e1115e2ebbfcdee6a060417300e5ed38d46304abac6e7"

_VCF_HASH_LOWER_RE = re.compile(r"^[0-9a-f]{64}$")
_VCF_HASH_UPPER_RE = re.compile(r"^[0-9A-F]{64}$")
_CODE_COMMIT_RE = re.compile(r"^[0-9a-f]+$")

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


class CodeCommitResolutionError(RuntimeError):
    """`_resolve_code_commit` could not resolve a valid git commit -- a git
    invocation failure, blank stdout, or non-hex output. Fails loud rather
    than falling back to an `unknown` sentinel (provenance must never be
    silently unresolvable)."""


def _sha256_bytes(path: str | Path) -> str:
    """Raw-byte sha256 -- used for every bound config surface (scorer/eval/
    lineage/packet-direction/predictor-policy configs) and the manifest/BIAS
    TSV. NEVER LF-normalized: only the committed historical-stats data
    artifact gets that treatment (see `_historical_stats_lf_sha256`)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _historical_stats_lf_sha256(path: str | Path) -> str:
    """Hash the committed historical-stats data artifact using its
    canonical LF bytes: a Windows CRLF checkout is normalized ONLY for this
    committed-data-artifact identity check, never for any raw config hash
    computed by `_sha256_bytes` above."""
    raw = Path(path).read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


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


def _validate_historical_stats_source(path: str | Path) -> str:
    """Require `--historical-stats` to resolve EXACTLY to the single
    immutable, committed `data/census/tsc_vus_clinvar_2026-07-07_stats.json`
    data artifact, and its canonical LF-normalized sha256 to match
    `HISTORICAL_CENSUS_SHA256` -- fails closed (before any processing or
    output) on any alternate path, substitution, or one-byte tamper.
    Returns the verified canonical hash for recording in bound provenance.
    """
    canonical_path = (REPO_ROOT / "data" / "census" / _HISTORICAL_STATS_FILENAME).resolve()
    resolved = Path(path).resolve()
    if resolved != canonical_path:
        raise ValueError(f"--historical-stats must be exactly {canonical_path}; got {resolved}")
    current_hash = _historical_stats_lf_sha256(resolved)
    if current_hash != HISTORICAL_CENSUS_SHA256:
        raise ValueError(
            "historical-stats content drift: canonical LF sha256 does not match "
            f"HISTORICAL_CENSUS_SHA256 (expected {HISTORICAL_CENSUS_SHA256!r}, got {current_hash!r})"
        )
    return current_hash


def _validate_provenance(provenance: Mapping[str, Any]) -> None:
    """Fail closed on a missing/malformed/non-hex `vcf_hash` (a lowercase-
    OR uppercase-hex sha256, 64 hex chars; never a mixed-case or short
    value) or a blank/missing `source_snapshot`."""
    vcf_hash = provenance.get("vcf_hash")
    is_valid_hex64 = isinstance(vcf_hash, str) and bool(
        _VCF_HASH_LOWER_RE.fullmatch(vcf_hash) or _VCF_HASH_UPPER_RE.fullmatch(vcf_hash)
    )
    if not is_valid_hex64:
        raise ValueError(
            f"provenance vcf_hash must be a lowercase- or uppercase-hex sha256 (64 hex "
            f"chars); got {vcf_hash!r}"
        )
    source_snapshot = provenance.get("source_snapshot")
    if not isinstance(source_snapshot, str) or not source_snapshot.strip():
        raise ValueError(f"provenance source_snapshot must be non-blank; got {source_snapshot!r}")


def _resolve_code_commit() -> str:
    """Resolve the current git commit (short hex SHA). Fails closed with
    `CodeCommitResolutionError` on a git invocation failure, blank stdout,
    or non-hex output -- never a broad catch that falls back to an
    `unknown` sentinel (provenance must always be a real, verifiable
    commit or the run must refuse to proceed)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as err:
        raise CodeCommitResolutionError(f"failed to resolve the current git commit: {err}") from err
    commit = result.stdout.strip()
    if not commit or not _CODE_COMMIT_RE.fullmatch(commit):
        raise CodeCommitResolutionError(
            f"git rev-parse returned a blank or non-hex commit: {commit!r}"
        )
    return commit


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
    bound_hashes["historical_stats"] = _validate_historical_stats_source(args.historical_stats)

    provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
    _validate_provenance(provenance)

    write_target: Path | None = None
    if args.emit_census_record:
        write_target = _assert_output_boundary(args.emit_census_record)
    elif not args.dry_run and not args.summary:
        raise ValueError("--emit-census-record is required unless --dry-run/--summary is set")

    manifest = load_manifest(args.manifest)
    bias_rows = tuple(BiasTsvSource(args.bias_tsv).records())
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
        automatable_criteria=eval_config.automatable_criteria,
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
