#!/usr/bin/env python3
"""Build the committed non-identifying aggregate from a terminal gate envelope."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml


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
    """
    report = envelope["report"]
    scope_gate = report.get("scope_gate")
    if not isinstance(scope_gate, dict):
            raise ValueError(
                "build_aggregate_v2 requires report['scope_gate'] (the v2 scope-specific gate "
                "decision) -- it is never derived from the pooled v1 gate/metrics"
            )

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
            "vus_authorized": scope_gate["full_spectrum_vus_authorized"],
            "scopes": scope_gate["scopes"],
            "research_scope_flags": scope_gate["research_scope_flags"],
            "governance_state": scope_gate["governance_state"],
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
