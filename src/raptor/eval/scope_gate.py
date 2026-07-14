"""PRD-06 v2 scope-specific research-authorization gate (ADDITIVE).

`decide_scope_gate` is a NEW, additive companion to the frozen v1
`raptor.eval.gate.decide_gate` -- it never replaces or dispatches from it,
and `decide_gate`/`GateDecision`/`StratumVerdict` stay byte-identical
(see `docs/DECISIONS.md` ADR-0011). Where v1 binds on a single gating
stratum (`missense`) and short-circuits the moment it fails, this module
evaluates EVERY configured `(stratum, direction)` scope independently and
NEVER short-circuits (AC-S1) -- a truncating-pathogenic PASS must remain
visible even when missense fails.

Two orthogonal axes are preserved per scope (AC-S2): `metric_status` (did
the 95% Clopper-Pearson lower bound clear its Oracle-registered threshold?)
and `coverage_adequate` (did held-out coverage clear
`min_count_per_class`?). `scope_status == "VALIDATED"` iff BOTH a threshold
is registered AND `metric_status == "MET"` AND `coverage_adequate` --
fail-closed in every other combination (AC-S4). No authorization boolean
here ever reads a pooled/`overall` metric (AC-S5) -- only per-scope
`scope_status` values, computed from `EvalConfig.scope_authorization`
(itself schema-validated + semantics-locked at `config.load_config` time,
but re-checked structurally here too since a hand-built `EvalConfig`
bypasses that validation, sec 4 step 1).

This module authorizes NOTHING clinical, full-spectrum, or production --
see `governance_statement`/`research_use_disclaimer` (mandatory, separate,
never merged into the exact preregistered governance string).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

from .config import EvalConfig
from .gate import _DIRECTION_COUNT_FIELDS, _DIRECTION_LB_FIELDS
from .model import DirectionVerdict, Metrics, ScopeGateDecision

_DIRECTIONS: tuple = ("pathogenic", "benign")

#: The narrow, independently-authorizing research scope flag (exact name,
#: user-specified) -- distinct from (and never implying) full-spectrum or
#: clinical authorization.
_TRUNCATING_PATHOGENIC_FLAG = "truncating_pathogenic_research_scope_validated"

#: Hardcoded, most-restrictive fallback strings used ONLY when
#: `scope_authorization` is missing/malformed (config strings may be
#: unavailable) -- never over-claims a validation that did not happen.
_FALLBACK_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical "
    "classification, VUS worklist, or ClinVar submission."
)
_FALLBACK_NONE_VALIDATED_STATEMENT = (
    "Full-spectrum VUS automation is not authorized; no pre-registered research scope is "
    "currently validated."
)


def _scope_key(stratum: str, direction: str) -> str:
    return f"{stratum}:{direction}"


def _split_scope_key(scope_key: Any) -> Optional[tuple]:
    if not isinstance(scope_key, str) or scope_key.count(":") != 1:
        return None
    stratum, _, direction = scope_key.partition(":")
    if not stratum or direction not in _DIRECTIONS:
        return None
    return stratum, direction


def _structurally_valid(scope_auth: Any) -> bool:
    """Shape-only validity check (NO registration lookup -- an
    empty-`oracle_thresholds` config is handled by a separate, earlier
    guard, sec 4 step 3). A hand-built `EvalConfig` bypasses
    `config._validate_scope_authorization`, so this is defense-in-depth,
    never a substitute for it."""
    if not isinstance(scope_auth, dict):
        return False
    if scope_auth.get("schema_version") not in (2, "2"):
        return False
    disclaimer = scope_auth.get("research_use_disclaimer")
    if not isinstance(disclaimer, str) or not disclaimer.strip():
        return False
    full_spectrum = scope_auth.get("full_spectrum")
    if not isinstance(full_spectrum, dict):
        return False
    requires = full_spectrum.get("requires")
    if not isinstance(requires, list) or not requires or any(_split_scope_key(s) is None for s in requires):
        return False
    research_scopes = scope_auth.get("research_scopes", {})
    if not isinstance(research_scopes, dict):
        return False
    for spec in research_scopes.values():
        if not isinstance(spec, dict):
            return False
        r = spec.get("requires")
        if not isinstance(r, list) or not r or any(_split_scope_key(s) is None for s in r):
            return False
    governance_statements = scope_auth.get("governance_statements")
    if not isinstance(governance_statements, dict):
        return False
    for state in ("FULL_SPECTRUM", "TRUNCATING_PATHOGENIC_ONLY", "NONE_VALIDATED"):
        text = governance_statements.get(state)
        if not isinstance(text, str) or not text.strip():
            return False
    return True


def _registered_scopes(strata_cfg: Mapping[str, Any]) -> frozenset:
    scopes = set()
    for name, spec in strata_cfg.items():
        for direction in spec.get("directions", []) or []:
            if direction in _DIRECTIONS:
                scopes.add(_scope_key(name, direction))
    return frozenset(scopes)


def _requires_registered(scope_auth: Mapping[str, Any], registered: frozenset) -> bool:
    """All `requires` scope keys (full-spectrum + every research scope) must
    name a scope actually registered in `oracle_thresholds` -- never
    authorize on an unregistered/typo'd/renamed scope (BLOCKED_CONFIG)."""
    if not set(scope_auth["full_spectrum"]["requires"]).issubset(registered):
        return False
    for spec in scope_auth.get("research_scopes", {}).values():
        if not set(spec["requires"]).issubset(registered):
            return False
    return True


def _blocked_config(reason: str) -> ScopeGateDecision:
    return ScopeGateDecision(
        schema_version="2",
        scopes={},
        full_spectrum_status="BLOCKED_CONFIG",
        full_spectrum_vus_authorized=False,
        research_scope_flags={},
        governance_state="NONE_VALIDATED",
        governance_statement=_FALLBACK_NONE_VALIDATED_STATEMENT,
        research_use_disclaimer=_FALLBACK_DISCLAIMER,
        reason=reason,
    )


def _direction_verdict(
    stratum: str,
    direction: str,
    spec: Optional[dict],
    m: Optional[Metrics],
    min_count_per_class: int,
) -> DirectionVerdict:
    registered_directions = (spec or {}).get("directions", []) if spec else []
    has_threshold = spec is not None and direction in registered_directions
    precision_threshold = float(spec["precision"]) if has_threshold else None
    recall_threshold = float(spec["recall"]) if has_threshold else None

    precision_field, recall_field = _DIRECTION_LB_FIELDS[direction]
    actual_field, called_field = _DIRECTION_COUNT_FIELDS[direction]

    precision_lb = getattr(m, precision_field, None) if m is not None else None
    recall_lb = getattr(m, recall_field, None) if m is not None else None
    actual_count = (m.counts.get(actual_field) if m is not None else None)
    called_count = (m.counts.get(called_field) if m is not None else None)

    coverage_adequate = (
        min_count_per_class > 0
        and actual_count is not None
        and called_count is not None
        and min(actual_count, called_count) >= min_count_per_class
    )

    reasons: list = []
    if not has_threshold:
        metric_status = "NO_THRESHOLD"
    else:
        precision_ok = isinstance(precision_lb, (int, float)) and math.isfinite(precision_lb) and precision_lb >= precision_threshold
        recall_ok = isinstance(recall_lb, (int, float)) and math.isfinite(recall_lb) and recall_lb >= recall_threshold
        if precision_ok and recall_ok:
            metric_status = "MET"
        else:
            metric_status = "UNMET"
            if not precision_ok:
                reasons.append(f"{precision_field}={precision_lb!r}<{precision_threshold!r}")
            if not recall_ok:
                reasons.append(f"{recall_field}={recall_lb!r}<{recall_threshold!r}")
    if not coverage_adequate:
        reasons.append(
            f"coverage inadequate: min({actual_count!r}, {called_count!r}) < {min_count_per_class!r}"
        )

    if metric_status == "NO_THRESHOLD":
        scope_status = "DESCRIPTIVE"
    elif metric_status == "MET":
        scope_status = "VALIDATED" if coverage_adequate else "UNDERPOWERED"
    else:  # UNMET
        scope_status = "FAIL"

    return DirectionVerdict(
        stratum=stratum,
        direction=direction,
        precision_lb=precision_lb if isinstance(precision_lb, (int, float)) else 0.0,
        recall_lb=recall_lb if isinstance(recall_lb, (int, float)) else 0.0,
        precision_threshold=precision_threshold,
        recall_threshold=recall_threshold,
        actual_count=actual_count if actual_count is not None else 0,
        called_count=called_count if called_count is not None else 0,
        min_count=min_count_per_class,
        coverage_adequate=coverage_adequate,
        metric_status=metric_status,
        scope_status=scope_status,
        reasons=reasons,
    )


def decide_scope_gate(metrics: Dict[str, Metrics], config: EvalConfig) -> ScopeGateDecision:
    """Enumerate every configured `(stratum, direction)` scope (plus any
    metrics-only stratum, e.g. `other`, for descriptive completeness) with
    NO short-circuit, then compute a non-statistical, scope-specific
    research-authorization summary (§4 of the v2 preregistration contract).
    """
    scope_auth = config.scope_authorization

    # sec 4 step 1: scope_authorization missing/empty/malformed -> nothing
    # validated, no scopes computed at all.
    if not scope_auth or not _structurally_valid(scope_auth):
        return _blocked_config(
            "scope_authorization is missing, empty, or structurally malformed -- "
            "no pre-registered research scope can be evaluated"
        )

    # sec 4 step 1 (BLOCKER-2 parity with decide_gate): min_count_per_class
    # <= 0 disables every coverage floor -- must never authorize.
    if config.min_count_per_class <= 0:
        return _blocked_config(
            f"invalid config -- min_count_per_class={config.min_count_per_class!r} must be "
            ">= 1; cannot authorize"
        )

    oracle_thresholds = config.oracle_thresholds or {}
    strata_cfg = oracle_thresholds.get("strata") or {}

    # sec 4 step 1: empty/missing oracle_thresholds -> UNVERIFIED, but still
    # compute descriptive-only scopes from whatever metrics exist.
    thresholds_unset = not oracle_thresholds or not strata_cfg

    registered = _registered_scopes(strata_cfg)
    if not thresholds_unset and not _requires_registered(scope_auth, registered):
        return _blocked_config(
            "scope_authorization.full_spectrum/research_scopes.requires names a scope not "
            "registered in oracle_thresholds -- cannot authorize on an unregistered scope"
        )

    # sec 4 step 2: enumerate EVERY stratum x direction, no short-circuit --
    # union of oracle-registered strata and metrics-only strata (e.g.
    # `other`) so every reported class is at least descriptively present.
    all_strata = sorted(set(strata_cfg.keys()) | set(metrics.keys()))
    scopes: Dict[str, DirectionVerdict] = {}
    for stratum in all_strata:
        spec = strata_cfg.get(stratum)
        m = metrics.get(stratum)
        for direction in _DIRECTIONS:
            scopes[_scope_key(stratum, direction)] = _direction_verdict(
                stratum, direction, spec, m, config.min_count_per_class
            )

    if thresholds_unset:
        return ScopeGateDecision(
            schema_version="2",
            scopes=scopes,
            full_spectrum_status="UNVERIFIED",
            full_spectrum_vus_authorized=False,
            research_scope_flags={name: False for name in scope_auth.get("research_scopes", {})},
            governance_state="NONE_VALIDATED",
            governance_statement=scope_auth["governance_statements"]["NONE_VALIDATED"],
            research_use_disclaimer=scope_auth["research_use_disclaimer"],
            reason=(
                "oracle_thresholds is empty or missing strata -- no pre-registered target "
                "(GP-9/H13); never invent one"
            ),
        )

    # sec 4 step 3: authorization booleans -- computed ONLY from per-scope
    # `scope_status`, never from a pooled/overall metric (AC-S5).
    full_spectrum_requires = scope_auth["full_spectrum"]["requires"]
    full_spectrum_vus_authorized = all(
        scopes.get(s) is not None and scopes[s].scope_status == "VALIDATED"
        for s in full_spectrum_requires
    )

    research_scope_flags = {
        name: all(
            scopes.get(s) is not None and scopes[s].scope_status == "VALIDATED"
            for s in spec["requires"]
        )
        for name, spec in scope_auth.get("research_scopes", {}).items()
    }

    # sec 4 step 4: full_spectrum_status.
    if full_spectrum_vus_authorized:
        full_spectrum_status = "PASS"
    elif any(scopes.get(s) is not None and scopes[s].scope_status == "FAIL" for s in full_spectrum_requires):
        full_spectrum_status = "FAIL"
    else:
        full_spectrum_status = "UNDERPOWERED"

    # sec 4 step 5: governance_state -- never asserts a validation the
    # verdicts don't support (computed FROM the verdicts, by construction).
    if full_spectrum_vus_authorized:
        governance_state = "FULL_SPECTRUM"
    elif research_scope_flags.get(_TRUNCATING_PATHOGENIC_FLAG, False):
        governance_state = "TRUNCATING_PATHOGENIC_ONLY"
    else:
        governance_state = "NONE_VALIDATED"

    governance_statement = scope_auth["governance_statements"].get(
        governance_state, _FALLBACK_NONE_VALIDATED_STATEMENT
    )

    reason = "; ".join(f"{key}={verdict.scope_status}" for key, verdict in sorted(scopes.items()))

    return ScopeGateDecision(
        schema_version="2",
        scopes=scopes,
        full_spectrum_status=full_spectrum_status,
        full_spectrum_vus_authorized=full_spectrum_vus_authorized,
        research_scope_flags=research_scope_flags,
        governance_state=governance_state,
        governance_statement=governance_statement,
        research_use_disclaimer=scope_auth["research_use_disclaimer"],
        reason=reason,
    )
