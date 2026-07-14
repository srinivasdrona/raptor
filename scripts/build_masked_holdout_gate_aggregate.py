#!/usr/bin/env python3
"""Build the committed non-identifying aggregate from a terminal gate envelope."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from raptor.eval.config import (
    _PINNED_FULL_SPECTRUM_SCOPES,
    _PINNED_GOVERNANCE_STATEMENTS,
    _PINNED_MIN_COUNT_PER_CLASS,
    _PINNED_RESEARCH_SCOPE_REQUIRES,
    _PINNED_RESEARCH_USE_DISCLAIMER,
)
from raptor.eval.scope_gate import _valid_count, _valid_lower_bound

#: GPT-5.4 BLOCKER (minimal-scope bypass closure): the complete set of
#: fields a v2 `scopes[...]` entry must carry -- the full serialized
#: `DirectionVerdict` shape (sec 3.2 of the v2 preregistration contract),
#: including `stratum`/`direction` (must match the scope key) and
#: `reasons`. There is no longer a "minimal legacy" shape that skips
#: recomputation: EVERY scope entry -- required, optional, or
#: descriptive -- must carry every one of these fields before
#: `_recompute_scope_entry` will independently recompute and verify it.
#: A scope entry missing ANY of these fields raises `ValueError` before
#: authorization is ever derived.
_SCOPE_REQUIRED_FIELDS: tuple = (
    "stratum", "direction",
    "precision_lb", "recall_lb", "precision_threshold", "recall_threshold",
    "actual_count", "called_count", "min_count", "coverage_adequate", "metric_status",
    "scope_status", "reasons",
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


def _recompute_scope_entry(scope_key: str, entry: Any) -> str:
    """GPT-5.4 BLOCKER (minimal-scope bypass closure) per-scope integrity
    boundary: `build_aggregate_v2` must NEVER trust a scope entry's own
    `scope_status` (or `metric_status`/`coverage_adequate`) at face value --
    it independently RECOMPUTES all three from the entry's raw numeric/count
    fields, using the exact same canonical rules as
    `raptor.eval.scope_gate._direction_verdict` (sec 3.3 of the v2
    preregistration contract), and raises `ValueError` on ANY disagreement,
    malformed numeric/type domain, partial threshold pair, scope-key/
    stratum/direction mismatch, or missing field.

    EVERY scope entry -- required, optional, or descriptive -- must carry
    the complete serialized `DirectionVerdict` shape (`_SCOPE_REQUIRED_FIELDS`):
    there is no minimal/legacy `{"scope_status": ...}` shape that bypasses
    recomputation. Any entry missing so much as one required field raises
    `ValueError` before authorization is ever derived from it.
    """
    if not isinstance(entry, dict):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] must be a mapping -- "
            "inconsistent/tampered envelope"
        )

    missing_fields = [f for f in _SCOPE_REQUIRED_FIELDS if f not in entry]
    if missing_fields:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] is missing required field(s) "
            f"{sorted(missing_fields)!r} -- incomplete/tampered scope entry; every v2 scope must "
            "carry the complete serialized DirectionVerdict payload"
        )

    expected_stratum, sep, expected_direction = scope_key.partition(":")
    if sep != ":" or not expected_stratum or expected_direction not in ("pathogenic", "benign"):
        raise ValueError(
            f"scope_gate integrity error: scope key {scope_key!r} is not a valid "
            "'{stratum}:{direction}' key -- inconsistent/tampered envelope"
        )
    if entry["stratum"] != expected_stratum:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].stratum={entry['stratum']!r} "
            f"does not match its scope key -- inconsistent/tampered envelope"
        )
    if entry["direction"] != expected_direction:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].direction={entry['direction']!r} "
            f"does not match its scope key -- inconsistent/tampered envelope"
        )

    reasons = entry["reasons"]
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].reasons={reasons!r} must be a "
            "list of strings -- malformed/tampered reasons"
        )

    precision_threshold = entry["precision_threshold"]
    recall_threshold = entry["recall_threshold"]
    thresholds_none = precision_threshold is None and recall_threshold is None
    thresholds_registered = (
        precision_threshold is not None
        and recall_threshold is not None
        and _valid_lower_bound(precision_threshold)
        and _valid_lower_bound(recall_threshold)
    )
    if not (thresholds_none or thresholds_registered):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] precision_threshold="
            f"{precision_threshold!r}/recall_threshold={recall_threshold!r} must be BOTH `None` "
            "(NO_THRESHOLD) or BOTH finite non-bool numbers in [0,1] -- malformed/tampered "
            "partial threshold pair"
        )

    precision_lb = entry["precision_lb"]
    recall_lb = entry["recall_lb"]
    if not (_valid_lower_bound(precision_lb) and _valid_lower_bound(recall_lb)):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] precision_lb={precision_lb!r}/"
            f"recall_lb={recall_lb!r} must be finite non-bool numbers in [0,1] -- malformed/"
            "tampered numeric domain"
        )

    actual_count = entry["actual_count"]
    called_count = entry["called_count"]
    if not (_valid_count(actual_count) and _valid_count(called_count)):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] actual_count={actual_count!r}/"
            f"called_count={called_count!r} must be non-bool, non-negative integers -- "
            "malformed/tampered numeric domain"
        )

    min_count = entry["min_count"]
    if not (isinstance(min_count, int) and not isinstance(min_count, bool) and min_count > 0):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] min_count={min_count!r} must be "
            "a non-bool, positive integer -- malformed/tampered numeric domain"
        )
    if min_count != _PINNED_MIN_COUNT_PER_CLASS:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}] min_count={min_count!r} does not "
            f"match the pinned pre-registered v2 coverage floor {_PINNED_MIN_COUNT_PER_CLASS!r} -- "
            "inconsistent/tampered envelope"
        )

    # Independently RECOMPUTE coverage_adequate/metric_status/scope_status
    # from the raw numeric fields (sec 3.3 canonical mapping) -- NEVER
    # trust the declared axis values, even when internally self-consistent.
    recomputed_coverage_adequate = min(actual_count, called_count) >= min_count
    if thresholds_none:
        recomputed_metric_status = "NO_THRESHOLD"
    elif precision_lb >= precision_threshold and recall_lb >= recall_threshold:
        recomputed_metric_status = "MET"
    else:
        recomputed_metric_status = "UNMET"

    if recomputed_metric_status == "NO_THRESHOLD":
        recomputed_scope_status = "DESCRIPTIVE"
    elif recomputed_metric_status == "MET":
        recomputed_scope_status = "VALIDATED" if recomputed_coverage_adequate else "UNDERPOWERED"
    else:  # UNMET
        recomputed_scope_status = "FAIL"

    declared_coverage_adequate = entry["coverage_adequate"]
    if not isinstance(declared_coverage_adequate, bool):
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].coverage_adequate="
            f"{declared_coverage_adequate!r} must be a bool -- inconsistent/tampered envelope"
        )
    if declared_coverage_adequate is not recomputed_coverage_adequate:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].coverage_adequate="
            f"{declared_coverage_adequate!r} does not match the recomputed value "
            f"{recomputed_coverage_adequate!r} derived from min(actual_count, called_count) vs "
            "min_count -- forged/tampered coverage"
        )

    declared_metric_status = entry["metric_status"]
    if declared_metric_status != recomputed_metric_status:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].metric_status="
            f"{declared_metric_status!r} does not match the recomputed value "
            f"{recomputed_metric_status!r} derived from precision_lb/recall_lb vs thresholds -- "
            "forged/tampered metric_status"
        )

    declared_scope_status = entry["scope_status"]
    if declared_scope_status != recomputed_scope_status:
        raise ValueError(
            f"scope_gate integrity error: scopes[{scope_key!r}].scope_status="
            f"{declared_scope_status!r} does not match the recomputed value "
            f"{recomputed_scope_status!r} derived from metric_status={recomputed_metric_status!r} "
            f"and coverage_adequate={recomputed_coverage_adequate!r} -- forged/tampered scope_status"
        )

    return recomputed_scope_status


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

    # BLOCKER 1 (GPT-5.4): independently recompute/validate EVERY scope
    # payload's `metric_status`/`coverage_adequate`/`scope_status` from its
    # own raw numeric/count fields -- never trust any of those three
    # declared values at face value, for any scope key (not just the
    # pinned full-spectrum/research-scope required ones). Any forged/
    # tampered/malformed entry raises `ValueError` here, before anything
    # downstream (full-spectrum/narrow-flag/governance recomputation) ever
    # reads a scope's status.
    recomputed_scope_status_by_key = {
        key: _recompute_scope_entry(key, entry) for key, entry in scopes.items()
    }

    # Blocker 2a (required scope completeness): every pinned full-spectrum
    # required scope must actually be present in the envelope -- a scope
    # silently dropped from `scopes` must never be treated as merely
    # "not validated" (which would be indistinguishable from a real FAIL);
    # it is an incomplete/tampered envelope and must raise loud.
    missing_scopes = sorted(key for key in _PINNED_FULL_SPECTRUM_SCOPES if key not in scopes)
    if missing_scopes:
        raise ValueError(
            "scope_gate integrity error: report['scope_gate']['scopes'] is missing required "
            f"pinned full-spectrum scope(s) {missing_scopes!r} -- an incomplete envelope must "
            "never be published"
        )

    def _scope_status(key: str) -> Any:
        # Checker finding 4 + BLOCKER 1: read the INDEPENDENTLY RECOMPUTED
        # status, never the raw declared `scope_status` -- everything
        # downstream (full-spectrum/narrow-flag/governance derivation) is
        # therefore derived only from recomputed canonical statuses.
        return recomputed_scope_status_by_key.get(key)

    def _scope_validated(key: str) -> bool:
        return _scope_status(key) == "VALIDATED"

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

    # Blocker 1 (explicit parity-authorization blocker): inspect the actual
    # runner envelope path `report['config_pins']['evaluation_skipped_criteria']`.
    # When any evaluation-only criterion was skipped (a production-parity
    # break) AND the recomputed per-scope facts would otherwise authorize
    # either the full-spectrum scope or ANY narrow research scope, the run
    # is genuinely "parity-blocked": the underlying statistical scope
    # verdicts (`scopes`) may legitimately still say VALIDATED (preserved,
    # never hidden/relabeled -- AC-S2), but the ENVELOPE must explicitly and
    # correctly declare `authorization_blockers` naming every skipped
    # criterion, and must show every authorization boolean/state withheld.
    # A parity-broken run that fails to declare (or mis-declares) its
    # blockers, or that still claims any authorization, is an
    # inconsistent/tampered envelope and must never be published. An
    # already-non-authorizing envelope (nothing recomputed True) with skips
    # recorded needs no blocker and may still be published (test_blocker_1c).
    config_pins = report.get("config_pins") or {}
    evaluation_skipped = sorted(str(c) for c in (config_pins.get("evaluation_skipped_criteria") or []))
    is_parity_blocked = bool(
        evaluation_skipped and (recomputed_full_spectrum or any(recomputed_flags.values()))
    )

    if is_parity_blocked:
        expected_blockers = sorted(f"evaluation_skipped_criteria:{c}" for c in evaluation_skipped)
        declared_blockers = scope_gate.get("authorization_blockers")
        if not isinstance(declared_blockers, list) or sorted(declared_blockers) != expected_blockers:
            raise ValueError(
                "scope_gate integrity error: evaluation_skipped_criteria "
                f"{evaluation_skipped!r} indicates a production-parity break, and the "
                "underlying scope verdicts would otherwise authorize a scope, but "
                f"authorization_blockers={declared_blockers!r} does not match the required "
                f"deterministic blocker set {expected_blockers!r} -- a parity-broken run must "
                "explicitly and correctly declare its blockers; a missing, empty, or wrong "
                "blocker is an inconsistent/tampered envelope and must never be published"
            )
        if declared_authorized is not False:
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                f"full_spectrum_vus_authorized={declared_authorized!r} but evaluation_skipped_criteria "
                f"{evaluation_skipped!r} (authorization_blockers={expected_blockers!r}) requires it be "
                "forced False; a skipped-criterion run must never authorize a scope"
            )
        if any(value is not False for value in declared_flags.values()):
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                f"research_scope_flags={declared_flags!r} must be entirely False under an active "
                f"parity blocker (authorization_blockers={expected_blockers!r}); a skipped-criterion "
                "run must never authorize a narrow research scope"
            )
        declared_state = scope_gate.get("governance_state")
        if declared_state != "NONE_VALIDATED":
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                f"governance_state={declared_state!r} must be NONE_VALIDATED under an active "
                f"parity blocker (authorization_blockers={expected_blockers!r})"
            )
        declared_statement = scope_gate.get("governance_statement")
        if declared_statement != _PINNED_GOVERNANCE_STATEMENTS["NONE_VALIDATED"]:
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                "governance_statement does not match the exact pinned NONE_VALIDATED statement "
                f"required under an active parity blocker, got {declared_statement!r}"
            )
        declared_disclaimer = scope_gate.get("research_use_disclaimer")
        if declared_disclaimer != _PINNED_RESEARCH_USE_DISCLAIMER:
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                "research_use_disclaimer does not match the exact pinned mandatory disclaimer, "
                f"got {declared_disclaimer!r}"
            )
        if declared_status != "BLOCKED_POLICY":
            raise ValueError(
                "scope_gate integrity error: inconsistent/tampered envelope -- "
                f"full_spectrum_status={declared_status!r} must be BLOCKED_POLICY under an active "
                f"parity blocker (authorization_blockers={expected_blockers!r}) -- the top-level "
                "status must explicitly reflect policy blocking, never a statistical "
                "PASS/FAIL/UNDERPOWERED verdict"
            )

        # Genuinely parity-blocked: preserve every per-scope statistical
        # verdict untouched (returned separately via `scope_gate['scopes']`
        # by the caller) while forcing every authorization surface closed.
        return {
            "full_spectrum_status": "BLOCKED_POLICY",
            "full_spectrum_vus_authorized": False,
            "research_scope_flags": {name: False for name in recomputed_flags},
            "governance_state": "NONE_VALIDATED",
            "authorization_blockers": expected_blockers,
        }

    if declared_authorized is not recomputed_full_spectrum:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"full_spectrum_vus_authorized={declared_authorized!r} does not match the "
            f"recomputed value {recomputed_full_spectrum!r} derived from report['scope_gate']['scopes']"
        )

    # Blocker 2b/2c (status recomputation, not just the authorized bool):
    # `full_spectrum_status` is recomputed SOLELY from the required scope
    # statuses -- PASS iff every required scope is VALIDATED; FAIL if any
    # required scope is FAIL (a FAIL must never be softened to
    # UNDERPOWERED); UNDERPOWERED otherwise (UNDERPOWERED/DESCRIPTIVE among
    # required). The declared value must equal this exactly.
    required_statuses = {key: _scope_status(key) for key in _PINNED_FULL_SPECTRUM_SCOPES}
    if all(status == "VALIDATED" for status in required_statuses.values()):
        expected_full_spectrum_status = "PASS"
    elif any(status == "FAIL" for status in required_statuses.values()):
        expected_full_spectrum_status = "FAIL"
    else:
        expected_full_spectrum_status = "UNDERPOWERED"

    if declared_status != expected_full_spectrum_status:
        raise ValueError(
            "scope_gate integrity error: inconsistent/tampered envelope -- "
            f"full_spectrum_status={declared_status!r} does not match the recomputed value "
            f"{expected_full_spectrum_status!r} derived from required scope statuses "
            f"{required_statuses!r} -- a FAIL must never be represented/softened as "
            "UNDERPOWERED (or any other inconsistent status)"
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
        "full_spectrum_status": expected_full_spectrum_status,
        "full_spectrum_vus_authorized": recomputed_full_spectrum,
        "research_scope_flags": recomputed_flags,
        "governance_state": expected_state,
        "authorization_blockers": [],
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
            # Checker finding 4 (+ final blocker): `full_spectrum_status`/
            # `vus_authorized`/`research_scope_flags`/`governance_state` are
            # emitted ONLY from the independently recomputed/verified
            # result, never the raw declared envelope values -- under an
            # active parity blocker this is forced to `BLOCKED_POLICY`/
            # `False`/`NONE_VALIDATED` even though the underlying
            # `scopes` may still say VALIDATED (preserved, never hidden).
            "full_spectrum_status": recomputed["full_spectrum_status"],
            "vus_authorized": recomputed["full_spectrum_vus_authorized"],
            "scopes": scope_gate["scopes"],
            "research_scope_flags": recomputed["research_scope_flags"],
            "governance_state": recomputed["governance_state"],
            "governance_statement": _PINNED_GOVERNANCE_STATEMENTS[recomputed["governance_state"]],
            "research_use_disclaimer": _PINNED_RESEARCH_USE_DISCLAIMER,
            # Explicit, machine-readable, deterministic authorization
            # blockers (e.g. `"evaluation_skipped_criteria:PM1"`) -- empty
            # when no parity break withholds an otherwise-authorized scope.
            "authorization_blockers": recomputed["authorization_blockers"],
            "scope_gate_reason": scope_gate.get("reason", ""),
            # `metrics` is retained descriptive-only (v1 pooled values,
            # AC-S5/E1) -- never the verdict source for this v2 schema. The
            # v1 gate payload is nested under a clearly-named legacy field,
            # never presented as (or alongside) the v2 primary verdict.
            "legacy_v1_gate": legacy_v1_gate,
    }


def build_aggregate_for_envelope(
    envelope: dict,
    *,
    date: str,
    terminal_json_hash: str,
    terminal_report_hash: str,
    published_pm1_scope: dict,
    reproduced_pm1_scope: dict,
    production_policy_status: str,
) -> dict:
    """Pure v1/v2 dispatch helper (checker finding 3): route to
    `build_aggregate_v2` when the envelope's `report['scope_gate']` is
    present/non-null (a real v2 runner envelope), else fall back to the v1
    `build_aggregate`. This is the single dispatch point the shipped CLI
    (`main`) must use, so a real future v2 runner envelope can produce
    `raptor.tsc.masked_holdout_gate.v2` through the shipped CLI without any
    behavior change to either builder.
    """
    report = envelope.get("report", {})
    builder = build_aggregate_v2 if report.get("scope_gate") is not None else build_aggregate
    return builder(
        envelope,
        date=date,
        terminal_json_hash=terminal_json_hash,
        terminal_report_hash=terminal_report_hash,
        published_pm1_scope=published_pm1_scope,
        reproduced_pm1_scope=reproduced_pm1_scope,
        production_policy_status=production_policy_status,
    )


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
    aggregate = build_aggregate_for_envelope(
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
