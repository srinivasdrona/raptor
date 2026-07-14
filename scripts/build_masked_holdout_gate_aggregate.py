#!/usr/bin/env python3
"""Build the committed non-identifying aggregate from a terminal gate envelope."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from raptor.eval.config import (
    _PINNED_FULL_SPECTRUM_SCOPES,
    _PINNED_GOVERNANCE_STATEMENTS,
    _PINNED_RESEARCH_SCOPE_REQUIRES,
    _PINNED_RESEARCH_USE_DISCLAIMER,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def build_aggregate(
    envelope: dict,
    *,
    date: str,
    terminal_json_hash: str,
    terminal_report_hash: str,
    published_pm1_scope: dict,
    reproduced_pm1_scope: dict,
    production_policy_status: str,
) -> dict:
    report = envelope["report"]
    config_pins = report["config_pins"]
    gate = report["gate"]
    mask = envelope["mask_attestation"]
    lineage = envelope["lineage_audit"]
    skipped = list(config_pins["evaluation_skipped_criteria"])
    pm1_skipped = "PM1" in skipped

    return {
        "schema": "raptor.tsc.masked_holdout_gate.v1",
        "date": date,
        "scope": "evaluation_only_non_authoritative",
        "status": gate["status"],
        "binding_stratum": gate["stratum"],
        "vus_authorized": gate["vus_authorized"],
        "content_hash": envelope["content_hash"],
        "integrity": {
            "returned_artifacts_verified": len(envelope["verified_return_artifacts"]),
            "bias_tsv_sha256": config_pins["bias_tsv_sha256"],
            "bias_rows": report["holdout_size"],
            "canonical_join_rows": report["holdout_size"],
            "mask_removed_identities": mask["removed_count"],
            "remask_survivors": 0 if mask["zero_survivors"] else None,
            "effective_lineage_blockers": list(lineage["effective_blocking_criteria"]),
            "manifest_sha256": config_pins["manifest_sha256"],
            "mask_ledger_sha256": config_pins["mask_ledger_sha256"],
            "remask_audit_sha256": config_pins["remask_audit_sha256"],
            "return_manifest_sha256": config_pins["return_manifest_sha256"],
        },
        "benchmark": {
            "snapshot": report["labels_snapshot"],
            "benchmark_size": report["benchmark_size"],
            "train_dev_size": report["train_dev_size"],
            "holdout_size": report["holdout_size"],
            "holdout_labels": report["holdout_label_counts"],
            "holdout_classes": report["holdout_class_counts"],
        },
        "policy": {
            "bp4pp3": envelope["predictor_policy"],
            "predictor_correction_counts": config_pins["predictor_correction_counts"],
            "operationally_skipped": config_pins["operational_skipped_criteria"],
            "evaluation_skipped": skipped,
            "pm1_status": (
                "SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH" if pm1_skipped else "scored"
            ),
            "pm1_published_reachable_rows": published_pm1_scope["reachable_pm1_rows"],
            "pm1_reproduced_reachable_rows": reproduced_pm1_scope["reachable_pm1_rows"],
            "production_candidate_policy_status": production_policy_status,
        },
        "thresholds": config_pins["oracle_thresholds"],
        "metrics": report["metrics"],
        "gate": gate,
        "limitations": [
            "PM1 was excluded from this fixed evaluation after both published and reproduced resources had zero held-out-reachable rows; production PM1 remains unvalidated.",
            "The evaluation-only BP4/PP3 approval does not approve production candidate policy or variant classifications.",
            "No VUS worklist, clinical classification, or ClinVar submission is authorized.",
        ],
        "external_report_hashes": {
            "MASKED_EVAL_REPORT.txt": terminal_report_hash,
            "MASKED_EVAL_REPORT.json": terminal_json_hash,
        },
    }


def _verify_scope_gate_integrity(report: dict) -> dict:
    """Checker finding 4 (GPT-5.4) integrity boundary: `build_aggregate_v2`
    must NEVER trust `report['scope_gate']`'s precomputed
    `full_spectrum_vus_authorized`/`research_scope_flags`/
    `governance_state`/`governance_statement`/`research_use_disclaimer`
    fields at face value. It independently RECOMPUTES every one of them
    from `scope_gate['scopes']`, using the pinned, hardcoded
    required-scope sets imported from `raptor.eval.config` -- never an
    envelope-declared `requires` list -- so there is no empty-`all([])`
    bypass (the pinned sets are fixed and non-empty). Any declared value
    that disagrees with the recomputation raises `ValueError` (an
    inconsistent/tampered envelope must never reach a published aggregate).
    Returns the recomputed, trustworthy values for the caller to emit
    (never the raw declared ones) for `vus_authorized`/`research_scope_flags`.
    """
    scope_gate = report.get("scope_gate")
    if not isinstance(scope_gate, dict):
        raise ValueError(
            "build_aggregate_v2 requires report['scope_gate'] (the v2 scope-specific gate "
            "decision) -- it is never derived from the pooled v1 gate/metrics"
        )
    scopes = scope_gate.get("scopes")
    if not isinstance(scopes, dict):
        raise ValueError(
            "scope_gate integrity error: report['scope_gate']['scopes'] must be a mapping -- "
            "inconsistent/tampered envelope"
        )

    def _scope_validated(key: str) -> bool:
        entry = scopes.get(key)
        return isinstance(entry, dict) and entry.get("scope_status") == "VALIDATED"

    # Independently recompute full-spectrum validity and every narrow
    # research-scope flag from the PINNED, hardcoded required-scope sets --
    # never trusting an envelope-declared `requires` list (no empty-
    # `all([])` bypass: both pinned sets are fixed and non-empty).
    recomputed_full_spectrum = all(_scope_validated(key) for key in _PINNED_FULL_SPECTRUM_SCOPES)
    recomputed_flags = {
        name: all(_scope_validated(key) for key in requires)
        for name, requires in _PINNED_RESEARCH_SCOPE_REQUIRES.items()
    }

    declared_authorized = scope_gate.get("full_spectrum_vus_authorized")
    declared_status = scope_gate.get("full_spectrum_status")
    declared_flags = scope_gate.get("research_scope_flags")
    if not isinstance(declared_flags, dict):
        raise ValueError(
            "scope_gate integrity error: research_scope_flags must be a mapping -- "
            "inconsistent/tampered envelope"
        )

    if declared_authorized is not recomputed_full_spectrum:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"full_spectrum_vus_authorized={declared_authorized!r} does not match the "
            f"recomputed value {recomputed_full_spectrum!r} derived from report['scope_gate']['scopes']"
        )
    if recomputed_full_spectrum and declared_status != "PASS":
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"full_spectrum_status={declared_status!r} but every required full-spectrum scope "
            "is VALIDATED (expected 'PASS')"
        )
    if not recomputed_full_spectrum and declared_status == "PASS":
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            "full_spectrum_status='PASS' but not every required full-spectrum scope is VALIDATED"
        )

    for name, recomputed_value in recomputed_flags.items():
        declared_value = declared_flags.get(name)
        if declared_value is not recomputed_value:
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                f"research_scope_flags[{name!r}]={declared_value!r} does not match the "
                f"recomputed value {recomputed_value!r} derived from report['scope_gate']['scopes']"
            )

    # Recompute the expected governance state from the SAME recomputed
    # booleans (never the declared ones), then pin the exact, verbatim
    # governance statement/disclaimer text for that state.
    if recomputed_full_spectrum:
        expected_state = "FULL_SPECTRUM"
    elif recomputed_flags.get("truncating_pathogenic_research_scope_validated"):
        expected_state = "TRUNCATING_PATHOGENIC_ONLY"
    else:
        expected_state = "NONE_VALIDATED"

    declared_state = scope_gate.get("governance_state")
    if declared_state != expected_state:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"governance_state={declared_state!r} does not match the recomputed state "
            f"{expected_state!r}"
        )
    declared_statement = scope_gate.get("governance_statement")
    pinned_statement = _PINNED_GOVERNANCE_STATEMENTS[expected_state]
    if declared_statement != pinned_statement:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"governance_statement does not match the exact pinned {expected_state!r} statement, "
            f"got {declared_statement!r}"
        )
    declared_disclaimer = scope_gate.get("research_use_disclaimer")
    if declared_disclaimer != _PINNED_RESEARCH_USE_DISCLAIMER:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            "research_use_disclaimer does not match the exact pinned mandatory disclaimer, "
            f"got {declared_disclaimer!r}"
        )

    return {
        "full_spectrum_vus_authorized": recomputed_full_spectrum,
        "research_scope_flags": recomputed_flags,
        "governance_state": expected_state,
    }


def build_aggregate_v2(
    envelope: dict,
    *,
    date: str,
    terminal_json_hash: str,
    terminal_report_hash: str,
    published_pm1_scope: dict,
    reproduced_pm1_scope: dict,
    production_policy_status: str,
) -> dict:
    """v2 scope-specific aggregate (ADDITIVE) -- schema
    `raptor.tsc.masked_holdout_gate.v2`. `build_aggregate` (v1) stays
    completely untouched; this is a NEW sibling function, never a dispatch
    inside it (sec 5/7 of the v2 preregistration contract). The primary
    verdict fields (`vus_authorized`/`status`) derive ONLY from
    `report["scope_gate"]` (the per-scope authorization decision), NEVER
    from the pooled/`overall` `report["metrics"]` or the v1 `report["gate"]`
    -- those are retained here strictly descriptive-only (AC-S5/E1).

    Checker finding 4 (GPT-5.4): before emitting anything, independently
    recomputes/validates every scope-gate-derived field via
    `_verify_scope_gate_integrity` (an integrity boundary, not a pass-
    through) -- an inconsistent/tampered envelope raises `ValueError`
    rather than ever reaching a published aggregate. The emitted
    `vus_authorized`/`research_scope_flags`/`governance_state` come ONLY
    from that recomputation, never the raw declared envelope values.
    """
    report = envelope["report"]
    scope_gate = report.get("scope_gate")
    recomputed = _verify_scope_gate_integrity(report)

    # Reuse the v1 builder for every field that is NOT scope-authorization
    # specific (benchmark/integrity/policy/thresholds/limitations/hashes)
    # -- descriptive-only continuity, never the verdict source here.
    v1_aggregate = build_aggregate(
            envelope,
            date=date,
            terminal_json_hash=terminal_json_hash,
            terminal_report_hash=terminal_report_hash,
            published_pm1_scope=published_pm1_scope,
            reproduced_pm1_scope=reproduced_pm1_scope,
            production_policy_status=production_policy_status,
    )
    v1_aggregate = dict(v1_aggregate)
    # Checker finding 4: the v1 `status`/`binding_stratum` fields are the v1
    # POOLED gate's primary verdict -- they must never be presented as (or
    # alongside) the v2 primary verdict, which is scope-specific. The v1
    # `gate` payload is retained ONLY as a clearly-named nested legacy field
    # (never top-level, never read as authoritative by any v2 consumer).
    v1_aggregate.pop("status", None)
    v1_aggregate.pop("binding_stratum", None)
    legacy_v1_gate = v1_aggregate.pop("gate", None)

    return {
            **v1_aggregate,
            "schema": "raptor.tsc.masked_holdout_gate.v2",
            "full_spectrum_status": scope_gate["full_spectrum_status"],
            # Checker finding 4: `vus_authorized` is emitted ONLY from the
            # independently recomputed full-spectrum result, never the raw
            # (already-validated-equal, but never directly trusted) declared value.
            "vus_authorized": recomputed["full_spectrum_vus_authorized"],
            "scopes": scope_gate["scopes"],
            "research_scope_flags": recomputed["research_scope_flags"],
            "governance_state": recomputed["governance_state"],
            "governance_statement": scope_gate["governance_statement"],
            "research_use_disclaimer": scope_gate["research_use_disclaimer"],
            "scope_gate_reason": scope_gate.get("reason", ""),
            # `metrics` is retained descriptive-only (v1 pooled values,
            # AC-S5/E1) -- never the verdict source for this v2 schema. The
            # v1 gate payload is nested under a clearly-named legacy field,
            # never presented as (or alongside) the v2 primary verdict.
            "legacy_v1_gate": legacy_v1_gate,
    }



def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terminal-json", type=Path, required=True)
    parser.add_argument("--terminal-report", type=Path, required=True)
    parser.add_argument("--return-dir", type=Path, required=True)
    parser.add_argument(
        "--production-policy",
        type=Path,
        default=Path("configs/packet/candidate_direction.yaml"),
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    production_policy = yaml.safe_load(args.production_policy.read_text(encoding="utf-8"))
    if not isinstance(production_policy, dict):
        raise ValueError("production candidate policy root must be a mapping")
    aggregate = build_aggregate(
        _read_json(args.terminal_json),
        date=args.date,
        terminal_json_hash=_sha256(args.terminal_json),
        terminal_report_hash=_sha256(args.terminal_report),
        published_pm1_scope=_read_json(args.return_dir / "pm1_published_scope.json"),
        reproduced_pm1_scope=_read_json(args.return_dir / "pm1_reproduced_scope.json"),
        production_policy_status=str(production_policy["approval_status"]),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
