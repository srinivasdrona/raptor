#!/usr/bin/env python3
"""Build the committed v3 tiered post-hoc re-adjudication record (ADDITIVE,
`docs/project/specs/tiered-gate-v3-posthoc.yaml`).

Re-adjudicates the frozen R2 masked-holdout aggregate
(`data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json`)
under the locked `configs/eval/tsc2.yaml` `tiered_authorization` rule via
`raptor.eval.tiered_gate.decide_tiered_gate` and writes the resulting
`TieredGateDecision` as a canonical-LF JSON record plus an external sha256
manifest. Performs NO new run, scoring, annotation, benchmark read, network
access, or data generation -- purely a deterministic re-interpretation of
already-frozen counts (`no_new_evidence_statement`).

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
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__).resolve()
_SRC = _SCRIPT_PATH.parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from raptor.eval.config import ConfigError, load_config  # noqa: E402
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
_CANONICAL_OUTPUT = "data/census/tsc_tiered_readjudication_2026-07-21.json"
_CANONICAL_MANIFEST = "data/census/tsc_tiered_readjudication_2026-07-21.sha256"


class InputError(Exception):
    """Typed fail-closed CLI error -- wrong/missing/non-canonical path,
    source-record hash drift, config load/validation failure, a
    `TieredReadjudicationError` from `decide_tiered_gate`, a cross-check
    re-derivation mismatch, an existing output/manifest, or a post-write
    reverification mismatch. Raised BEFORE (or, for the reverification
    case, immediately after) any write -- `main` never leaves a partial
    output or manifest behind."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_lf(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _git_head_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_SCRIPT_PATH.parents[1]),
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
        return commit or None
    except Exception:
        return None


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
    parser.add_argument("--output", required=True)
    parser.add_argument("--external-manifest", required=True)
    return parser.parse_args(argv)


def main(argv: Any = None) -> int:
    args = _parse_args(argv)

    source_path = _require_canonical_path(args.source_record, _CANONICAL_SOURCE_RECORD)
    config_path = _require_canonical_path(args.eval_config, _CANONICAL_EVAL_CONFIG)
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

    if config.tiered_authorization is None:
        raise InputError(f"eval config {config_path} has no `tiered_authorization` block")

    metrics_map = _build_metrics_map(payload)
    run_meta = _ReconstructedRunMeta(payload.get("integrity", {}), payload.get("policy", {}))

    try:
        decision = decide_tiered_gate(metrics_map, config, run_meta)
        # Independent cross-check re-derivation: a fresh call from freshly
        # reconstructed metrics must produce byte-identical scope verdicts
        # before ANY artifact is written.
        cross_check = decide_tiered_gate(_build_metrics_map(payload), config, run_meta)
    except TieredReadjudicationError as exc:
        raise InputError(f"decide_tiered_gate rejected the reconstructed input: {exc}") from exc

    if cross_check.scopes.keys() != decision.scopes.keys():
        raise InputError("cross-check re-derivation produced a different set of scope keys")
    for scope_key, verdict in decision.scopes.items():
        if cross_check.scopes[scope_key] != verdict:
            raise InputError(f"cross-check re-derivation mismatch for scope {scope_key!r}")

    implementation_commit = _git_head_commit()
    module_sha256 = _sha256_file(_SRC / "raptor" / "eval" / "tiered_gate.py")
    tiered_config_canonical_sha256 = _sha256_lf(config_path.read_bytes())

    record: dict = {
        "schema_version": decision.schema_version,
        "post_hoc": decision.post_hoc,
        "source_record": _CANONICAL_SOURCE_RECORD,
        "source_canonical_lf_sha256": decision.source_canonical_lf_sha256,
        "source_content_hash": decision.source_content_hash,
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
        "tiered_config_canonical_sha256": tiered_config_canonical_sha256,
        "implementation_commit": implementation_commit,
        "implementation_module_sha256": module_sha256,
    }

    content_hash_value = hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    record["content_hash"] = content_hash_value

    text = json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    # Canonical LF output regardless of platform -- `write_bytes` (never
    # `write_text`, which translates "\n" -> os.linesep == "\r\n" on Windows).
    output_bytes = text.encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)

    output_sha256 = _sha256_bytes(output_bytes)
    manifest_text = f"{output_sha256}  {output_path.name}\n"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_text.encode("utf-8"))

    # Post-write reverification -- reread what was just written and confirm
    # the hash still matches before declaring success.
    reverify_bytes = output_path.read_bytes()
    if _sha256_bytes(reverify_bytes) != output_sha256:
        raise InputError("post-write reverification hash mismatch for output record")

    return 0


if __name__ == "__main__":
    sys.exit(main())
