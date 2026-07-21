#!/usr/bin/env python3
"""Build the committed v3 tiered post-hoc re-adjudication record (ADDITIVE,
`docs/project/specs/tiered-gate-v3-posthoc.yaml`).

Re-adjudicates the frozen R2 masked-holdout aggregate
(`data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json`)
under the locked STANDALONE `configs/eval/tiered_gate_v3.yaml`
`tiered_authorization` rule (`--tiered-config`, loaded via
`raptor.eval.config.load_tiered_authorization` -- entirely separate from
`configs/eval/tsc2.yaml`, which supplies only the Oracle thresholds/
`min_count_per_class` via the UNCHANGED `load_config` and is never
mutated) via `raptor.eval.tiered_gate.decide_tiered_gate` and writes the
resulting `TieredGateDecision` as a canonical-LF JSON record plus an
external sha256 manifest. Performs NO new run, scoring, annotation,
benchmark read, network access, or data generation -- purely a
deterministic re-interpretation of already-frozen counts
(`no_new_evidence_statement`).

Fail-closed: every input path must resolve to its EXACT canonical location
under `REPO_ROOT`; the source record's canonical-LF sha256 AND internal
`content_hash` must match the frozen pins; neither the output nor the
external manifest may already exist; `decide_tiered_gate` is called TWICE
(an independent cross-check re-derivation) and any mismatch, any
`TieredReadjudicationError`, or any post-write reverification mismatch
raises the typed `InputError` and writes NOTHING.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__).resolve()
_SRC = _SCRIPT_PATH.parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from raptor.eval.config import ConfigError, load_config, load_tiered_authorization  # noqa: E402
from raptor.eval.model import Metrics  # noqa: E402
from raptor.eval.tiered_gate import (  # noqa: E402
    SOURCE_R2_CANONICAL_SHA256,
    SOURCE_R2_INTERNAL_CONTENT_HASH,
    TieredReadjudicationError,
    decide_tiered_gate,
)

__all__ = ["main", "REPO_ROOT", "SOURCE_R2_CANONICAL_SHA256", "InputError"]

#: Monkeypatchable repo root (tests replace this with a `tmp_path` sandbox
#: laid out with the same canonical relative paths) -- read dynamically at
#: call time, never cached at import.
REPO_ROOT = str(_SCRIPT_PATH.parents[1])

_CANONICAL_SOURCE_RECORD = "data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json"
_CANONICAL_EVAL_CONFIG = "configs/eval/tsc2.yaml"
_CANONICAL_TIERED_CONFIG = "configs/eval/tiered_gate_v3.yaml"
_CANONICAL_OUTPUT = "data/census/tsc_tiered_readjudication_2026-07-21.json"
_CANONICAL_MANIFEST = "data/census/tsc_tiered_readjudication_2026-07-21.sha256"

#: Top-level v3 envelope constants (spec `docs/project/specs/tiered-gate-v3-posthoc.yaml`).
_SCHEMA_V3 = "raptor.tsc.tiered_readjudication.v3"
_RECORD_DATE = "2026-07-21"

_FULL_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class InputError(Exception):
    """Typed fail-closed CLI error -- wrong/missing/non-canonical path,
    source-record hash drift, config load/validation failure, a
    `TieredReadjudicationError` from `decide_tiered_gate`, a cross-check
    re-derivation mismatch, a non-40-hex/failed `git rev-parse HEAD`, an
    existing output/manifest, a staged-bytes verification failure, or a
    post-publish reverification mismatch. Raised BEFORE any write begins,
    or -- for failures discovered once staging/publication has started --
    only after every temp file and any newly-created final output/manifest
    has been removed (`main` never leaves a partial or residual output,
    manifest, or temp file behind)."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_lf(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _require_canonical_path(provided: str, canonical_relative: str) -> Path:
    root = Path(REPO_ROOT).resolve()
    expected = (root / canonical_relative).resolve()
    actual = Path(provided).resolve()
    if actual != expected:
        raise InputError(
            f"path {provided!r} does not resolve to the canonical path "
            f"{str(expected)!r} under REPO_ROOT={REPO_ROOT!r}"
        )
    return actual


def _git_head_commit() -> str:
    """Fail-closed full 40-hex-lowercase `git rev-parse HEAD` -- NEVER
    `None` and never a short/abbreviated/dirty value. Any non-zero exit,
    subprocess failure, or malformed (non-40-hex) stdout raises `InputError`
    BEFORE any artifact is written (spec: implementation_commit is never
    null)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_SCRIPT_PATH.parents[1]),
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        raise InputError(f"failed to invoke `git rev-parse HEAD`: {exc}") from exc
    commit = result.stdout.strip()
    if result.returncode != 0 or not _FULL_COMMIT_SHA_RE.match(commit):
        raise InputError(
            "`git rev-parse HEAD` did not return a full 40-hex-lowercase commit sha "
            f"(fail-closed, never None): returncode={result.returncode!r} stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
    return commit


def _build_metrics_map(payload: dict) -> dict:
    """Reconstruct the `{stratum: Metrics}` map from an R2 record's
    `metrics` block -- `overall` is a pooled, descriptive-only aggregate
    and is NEVER a `(stratum, direction)` scope input (mirrors the
    protected test's own reconstruction)."""
    metrics_map = {}
    for stratum_name, data in payload.get("metrics", {}).items():
        if stratum_name == "overall":
            continue
        metrics_map[stratum_name] = Metrics(
            precision=data.get("precision", 0.0),
            recall=data.get("recall", 0.0),
            concordance=data.get("concordance", 0.0),
            counts=data.get("counts", {}),
            stratum=stratum_name,
            gating=data.get("gating", True),
            benign_precision=data.get("benign_precision", 0.0),
            benign_recall=data.get("benign_recall", 0.0),
            precision_lb=data.get("precision_lb", 0.0),
            recall_lb=data.get("recall_lb", 0.0),
            benign_precision_lb=data.get("benign_precision_lb", 0.0),
            benign_recall_lb=data.get("benign_recall_lb", 0.0),
        )
    return metrics_map


def _build_old_semantic_outcome(payload: dict) -> dict:
    """Copy/derive the frozen R2 record's OLD (pre-v3) semantic outcome --
    the legacy v1 `decide_gate` FAIL and the v2 `decide_scope_gate`
    BLOCKED_POLICY/no-authorization result -- verbatim from the payload.
    This is read-only provenance alongside `new_tiered_outcome`; it is
    NEVER recomputed or reinterpreted, only copied from the already-frozen
    R2 fields. Every required source field is validated present (fail-closed,
    never `.get(..., <fabricated default>)` masking a missing/malformed
    legacy field)."""
    legacy_v1_gate = payload.get("legacy_v1_gate")
    if not isinstance(legacy_v1_gate, dict) or not isinstance(legacy_v1_gate.get("status"), str):
        raise InputError(
            "source record is missing a valid `legacy_v1_gate.status` string required to derive "
            "`old_semantic_outcome.legacy_v1_missense_gate`"
        )
    full_spectrum_status = payload.get("full_spectrum_status")
    if not isinstance(full_spectrum_status, str):
        raise InputError(
            "source record is missing a valid `full_spectrum_status` string required to derive "
            "`old_semantic_outcome.full_spectrum_status`"
        )
    vus_authorized = payload.get("vus_authorized")
    if not isinstance(vus_authorized, bool):
        raise InputError(
            "source record is missing a valid `vus_authorized` bool required to derive "
            "`old_semantic_outcome.vus_authorized`"
        )
    return {
        "schema": payload.get("schema"),
        "legacy_v1_gate": legacy_v1_gate,
        "legacy_v1_missense_gate": legacy_v1_gate["status"],
        "full_spectrum_status": full_spectrum_status,
        "vus_authorized": vus_authorized,
        "governance_state": payload.get("governance_state"),
        "scope_gate_reason": payload.get("scope_gate_reason"),
        "research_scope_flags": dict(payload.get("research_scope_flags") or {}),
        "authorization_blockers": list(payload.get("authorization_blockers") or []),
    }


class _ReconstructedRunMeta:
    """Whole-run integrity + policy metadata reconstructed from the R2
    record's `integrity`/`policy` blocks (mirrors the protected tests'
    `MockRunMeta`)."""

    def __init__(self, integrity: dict, policy: dict):
        self.effective_lineage_blockers = integrity.get("effective_lineage_blockers", [])
        self.remask_survivors = integrity.get("remask_survivors", 0)
        self.canonical_join_rows = integrity.get("canonical_join_rows", 0)
        self.bias_rows = integrity.get("bias_rows", 0)
        self.returned_artifacts_verified = integrity.get("returned_artifacts_verified", 0)
        self.evaluation_skipped = policy.get("evaluation_skipped", [])


def _parse_args(argv: Any) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-record", required=True)
    parser.add_argument("--eval-config", required=True)
    parser.add_argument("--tiered-config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--external-manifest", required=True)
    return parser.parse_args(argv)


def main(argv: Any = None) -> int:
    args = _parse_args(argv)

    source_path = _require_canonical_path(args.source_record, _CANONICAL_SOURCE_RECORD)
    config_path = _require_canonical_path(args.eval_config, _CANONICAL_EVAL_CONFIG)
    tiered_config_path = _require_canonical_path(args.tiered_config, _CANONICAL_TIERED_CONFIG)
    output_path = _require_canonical_path(args.output, _CANONICAL_OUTPUT)
    manifest_path = _require_canonical_path(args.external_manifest, _CANONICAL_MANIFEST)

    if output_path.exists():
        raise InputError(f"refusing to overwrite existing output: {output_path}")
    if manifest_path.exists():
        raise InputError(f"refusing to overwrite existing external manifest: {manifest_path}")
    if not source_path.exists():
        raise InputError(f"source record not found: {source_path}")
    if not config_path.exists():
        raise InputError(f"eval config not found: {config_path}")
    if not tiered_config_path.exists():
        raise InputError(f"tiered-authorization config not found: {tiered_config_path}")

    raw_bytes = source_path.read_bytes()
    lf_hash = _sha256_lf(raw_bytes)
    if lf_hash != SOURCE_R2_CANONICAL_SHA256:
        raise InputError(
            "source record canonical-LF sha256 mismatch: expected "
            f"{SOURCE_R2_CANONICAL_SHA256}, got {lf_hash}"
        )

    try:
        payload = json.loads(raw_bytes.replace(b"\r\n", b"\n").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"source record is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputError("source record JSON root must be an object")

    content_hash = payload.get("content_hash")
    if content_hash != SOURCE_R2_INTERNAL_CONTENT_HASH:
        raise InputError(
            "source record content_hash mismatch: expected "
            f"{SOURCE_R2_INTERNAL_CONTENT_HASH}, got {content_hash!r}"
        )

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise InputError(f"eval config failed to load/validate: {exc}") from exc

    # The standalone v3 tiered-authorization block is loaded SEPARATELY from
    # tsc2.yaml (rev 3) via `load_tiered_authorization`, which returns the
    # VALIDATED, schema-tag-STRIPPED mapping -- this same validated mapping
    # is both passed explicitly to `decide_tiered_gate` AND used to derive
    # `tiered_config_canonical_sha256` (never the raw YAML wrapper, which
    # still carries the top-level `schema` tag).
    try:
        tiered_authorization = load_tiered_authorization(tiered_config_path)
    except ConfigError as exc:
        raise InputError(f"tiered-authorization config failed to load/validate: {exc}") from exc

    metrics_map = _build_metrics_map(payload)
    run_meta = _ReconstructedRunMeta(payload.get("integrity", {}), payload.get("policy", {}))

    try:
        decision = decide_tiered_gate(metrics_map, config, run_meta, tiered_authorization)
        # Independent cross-check re-derivation: a fresh call from freshly
        # reconstructed metrics must produce byte-identical scope verdicts
        # before ANY artifact is written.
        cross_check = decide_tiered_gate(_build_metrics_map(payload), config, run_meta, tiered_authorization)
    except TieredReadjudicationError as exc:
        raise InputError(f"decide_tiered_gate rejected the reconstructed input: {exc}") from exc

    if cross_check.scopes.keys() != decision.scopes.keys():
        raise InputError("cross-check re-derivation produced a different set of scope keys")
    for scope_key, verdict in decision.scopes.items():
        if cross_check.scopes[scope_key] != verdict:
            raise InputError(f"cross-check re-derivation mismatch for scope {scope_key!r}")

    implementation_commit = _git_head_commit()
    module_sha256 = _sha256_lf((_SRC / "raptor" / "eval" / "tiered_gate.py").read_bytes())
    tiered_config_canonical_sha256 = hashlib.sha256(
        json.dumps(tiered_authorization, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    old_semantic_outcome = _build_old_semantic_outcome(payload)

    new_tiered_outcome: dict = {
        "run_integrity": decision.run_integrity,
        "scopes": {
            scope_key: {
                "stratum": verdict.stratum,
                "direction": verdict.direction,
                "data_sufficiency": verdict.data_sufficiency,
                "conditional_performance": verdict.conditional_performance,
                "policy_parity": verdict.policy_parity,
                "precision_lb": verdict.precision_lb,
                "recall_lb": verdict.recall_lb,
                "precision_threshold": verdict.precision_threshold,
                "recall_threshold": verdict.recall_threshold,
                "actual_count": verdict.actual_count,
                "called_count": verdict.called_count,
                "tp": verdict.tp,
                "tn": verdict.tn,
                "fp": verdict.fp,
                "fn": verdict.fn,
                "min_count": verdict.min_count,
                "end_to_end_correct_call_coverage": verdict.end_to_end_correct_call_coverage,
                "abstain_count": verdict.abstain_count,
                "scope_evidence_status": verdict.scope_evidence_status,
                "authorization_status": verdict.authorization_status,
                "reasons": list(verdict.reasons),
            }
            for scope_key, verdict in sorted(decision.scopes.items())
        },
        "full_spectrum_status": decision.full_spectrum_status,
        "full_spectrum_authorization": decision.full_spectrum_authorization,
        "research_scope_evidence_status": decision.research_scope_evidence_status,
        "research_scope_authorization": decision.research_scope_authorization,
        "research_scope_flags": dict(decision.research_scope_flags),
        "governance_state": decision.governance_state,
        "governance_statement": decision.governance_statement,
        "research_use_disclaimer": decision.research_use_disclaimer,
        "prospective_validation_status": decision.prospective_validation_status,
        "no_new_evidence_statement": decision.no_new_evidence_statement,
        "reason": decision.reason,
    }

    record: dict = {
        "schema": _SCHEMA_V3,
        "schema_version": decision.schema_version,
        "date": _RECORD_DATE,
        "post_hoc": decision.post_hoc,
        "source_record": _CANONICAL_SOURCE_RECORD,
        "source_canonical_lf_sha256": decision.source_canonical_lf_sha256,
        "source_content_hash": decision.source_content_hash,
        "old_semantic_outcome": old_semantic_outcome,
        "new_tiered_outcome": new_tiered_outcome,
        "tiered_config_canonical_sha256": tiered_config_canonical_sha256,
        "implementation_commit": implementation_commit,
        "implementation_module_sha256": module_sha256,
    }

    # content_hash = compact canonical JSON (sort_keys, no whitespace) of the
    # FULL record EXCLUDING content_hash itself.
    content_hash_value = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    record["content_hash"] = content_hash_value

    # Canonical published bytes: indented, fully key-sorted (INCLUDING
    # content_hash), LF-only regardless of platform -- `write_bytes` (never
    # `write_text`, which translates "\n" -> os.linesep == "\r\n" on
    # Windows).
    output_bytes = (
        json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    output_sha256 = _sha256_bytes(output_bytes)
    manifest_bytes = f"{output_sha256}  {output_path.name}\n".encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic/no-residue publication: stage to temp files first, fully
    # verify the staged bytes, THEN publish (atomic rename) to the
    # canonical final paths, THEN reverify the published bytes. On ANY
    # exception from here on, guarded cleanup removes every temp file and
    # any final output/manifest THIS invocation itself created before
    # re-raising a typed `InputError` -- never overwriting a pre-existing
    # file and never leaving a partial/residual artifact behind.
    temp_output_path = output_path.with_name(".tmp-" + output_path.name)
    temp_manifest_path = manifest_path.with_name(".tmp-" + manifest_path.name)
    for stale in (temp_output_path, temp_manifest_path):
        if stale.exists():
            stale.unlink()

    output_published = False
    manifest_published = False
    try:
        # --- Stage ---
        temp_output_path.write_bytes(output_bytes)
        if _sha256_bytes(temp_output_path.read_bytes()) != output_sha256:
            raise InputError("staged output bytes failed verification before publication")

        temp_manifest_path.write_bytes(manifest_bytes)
        if temp_manifest_path.read_bytes() != manifest_bytes:
            raise InputError("staged external manifest bytes failed verification before publication")

        # --- Publish (never overwrite a pre-existing final file) ---
        if output_path.exists():
            raise InputError(f"refusing to overwrite existing output: {output_path}")
        temp_output_path.replace(output_path)
        output_published = True

        if manifest_path.exists():
            raise InputError(f"refusing to overwrite existing external manifest: {manifest_path}")
        temp_manifest_path.replace(manifest_path)
        manifest_published = True

        # --- Reverify the PUBLISHED artifacts ---
        if _sha256_bytes(output_path.read_bytes()) != output_sha256:
            raise InputError("post-publish reverification hash mismatch for output record")
        if manifest_path.read_bytes() != manifest_bytes:
            raise InputError("post-publish reverification mismatch for external manifest")
    except Exception as exc:
        for path, published in ((output_path, output_published), (manifest_path, manifest_published)):
            if published and path.exists():
                path.unlink()
        for temp in (temp_output_path, temp_manifest_path):
            if temp.exists():
                temp.unlink()
        if isinstance(exc, InputError):
            raise
        raise InputError(f"tiered readjudication publication failed: {exc}") from exc

    return 0


if __name__ == "__main__":
    sys.exit(main())
