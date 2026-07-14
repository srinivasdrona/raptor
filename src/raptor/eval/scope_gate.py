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

from .config import (
    EvalConfig,
    _PINNED_FULL_SPECTRUM_SCOPES,
    _PINNED_GOVERNANCE_STATEMENTS,
    _PINNED_MIN_COUNT_PER_CLASS,
    _PINNED_ORACLE_CONFIDENCE,
    _PINNED_RESEARCH_SCOPE_REQUIRES,
    _PINNED_RESEARCH_USE_DISCLAIMER,
    _PINNED_STRATUM_SEMANTICS,
    _PINNED_STRATUM_THRESHOLDS,
    _POOLED_OVERALL_STRATUM,
)
from .gate import _DIRECTION_COUNT_FIELDS, _DIRECTION_LB_FIELDS
from .model import DirectionVerdict, Metrics, ScopeGateDecision

_DIRECTIONS: tuple = ("pathogenic", "benign")

#: v2 registered stratum names -- `oracle_thresholds.strata` may declare
#: ONLY these two pinned strata (BLOCKER 2, GPT-5.4). Descriptive-only
#: strata that show up purely in `metrics` (e.g. `other`) never need -- and
#: must never require -- a config entry; see `decide_scope_gate` sec 4.
_ALLOWED_STRATUM_NAMES: frozenset = frozenset(_PINNED_STRATUM_THRESHOLDS.keys())

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


def _pinned_authorization_valid(scope_auth: Mapping[str, Any]) -> bool:
    """Runtime defense-in-depth (checker findings 1+2): re-validate the
    pinned full-spectrum required set, the pinned research-scope
    key/`requires` mapping, AND the pinned governance/disclaimer text
    against a HAND-BUILT `EvalConfig` that bypasses
    `config._validate_scope_authorization` entirely. A test/caller building
    an `EvalConfig` directly (never through `load_config`) must not be able
    to retarget/narrow/widen any pin -- including tampering with the
    governance statements or the mandatory research-use disclaimer -- and
    still get a validated scope (checker finding 1: never echo tampered
    safe text)."""
    full_spectrum = scope_auth.get("full_spectrum")
    if not isinstance(full_spectrum, dict):
        return False
    if frozenset(full_spectrum.get("requires") or []) != _PINNED_FULL_SPECTRUM_SCOPES:
        return False

    research_scopes = scope_auth.get("research_scopes", {})
    if not isinstance(research_scopes, dict):
        return False
    if frozenset(research_scopes.keys()) != frozenset(_PINNED_RESEARCH_SCOPE_REQUIRES.keys()):
        return False
    for name, pinned_requires in _PINNED_RESEARCH_SCOPE_REQUIRES.items():
        spec = research_scopes.get(name)
        if not isinstance(spec, dict):
            return False
        if frozenset(spec.get("requires") or []) != pinned_requires:
            return False

    # Checker finding 1 (GPT-5.4): the disclaimer AND all three
    # governance-state strings are authorization surfaces -- a hand-built
    # `EvalConfig` that tampers with any of them must fail closed exactly
    # like `config._validate_scope_authorization` does at load time.
    if scope_auth.get("research_use_disclaimer") != _PINNED_RESEARCH_USE_DISCLAIMER:
        return False
    governance_statements = scope_auth.get("governance_statements")
    if not isinstance(governance_statements, dict):
        return False
    for state, pinned_statement in _PINNED_GOVERNANCE_STATEMENTS.items():
        if governance_statements.get(state) != pinned_statement:
            return False
    return True


def _min_count_pinned_valid(min_count_per_class: Any) -> bool:
    """Checker finding 2 (GPT-5.4) defense-in-depth: the preregistered v2
    floor is EXACTLY 36 -- a hand-built `EvalConfig` drifting `min_count_per_class`
    away from 36 (including a "more conservative" upward drift, e.g. 37, or a
    seemingly-safe positive value like 1) must never authorize anything."""
    return (
        isinstance(min_count_per_class, int)
        and not isinstance(min_count_per_class, bool)
        and min_count_per_class == _PINNED_MIN_COUNT_PER_CLASS
    )



def _pinned_oracle_semantics_valid(oracle_thresholds: Mapping[str, Any], strata_cfg: Mapping[str, Any]) -> bool:
    """Runtime defense-in-depth (checker finding 2): re-validate the locked
    Oracle semantics (confidence + missense/truncating precision, recall,
    gating, directions) against a hand-built `EvalConfig.oracle_thresholds`
    that bypasses `config._validate_oracle_thresholds`. Any drift in a
    threshold/direction/gating/confidence value is rejected -- fail closed,
    never authorize on a silently-relaxed rubric."""
    confidence = oracle_thresholds.get("confidence")
    try:
        if isinstance(confidence, bool) or not math.isclose(
            float(confidence), _PINNED_ORACLE_CONFIDENCE, rel_tol=0.0, abs_tol=1e-9
        ):
            return False
    except (TypeError, ValueError):
        return False

    for name, pinned_metrics in _PINNED_STRATUM_THRESHOLDS.items():
        spec = strata_cfg.get(name)
        if not isinstance(spec, dict):
            continue  # unregistered pinned stratum is caught separately (requires-registered check)
        for metric_key, pinned_value in pinned_metrics.items():
            value = spec.get(metric_key)
            try:
                if isinstance(value, bool) or not math.isclose(
                    float(value), pinned_value, rel_tol=0.0, abs_tol=1e-9
                ):
                    return False
            except (TypeError, ValueError):
                return False

        pinned_gating, pinned_directions = _PINNED_STRATUM_SEMANTICS[name]
        if spec.get("gating") is not pinned_gating:
            return False
        if tuple(spec.get("directions", []) or []) != pinned_directions:
            return False
    return True


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


def _valid_lower_bound(value: Any) -> bool:
    """Checker finding 3 (GPT-5.4): a lower-bound metric must be a
    non-bool, finite numeric value clamped to the valid `[0, 1]`
    probability domain -- `bool` (a `int` subclass), NaN/+-inf, out-of-range
    values (e.g. `1.2`, `-0.5`), and non-numeric types (`str`, `None`) are
    all malformed and must never be treated as a met threshold."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _valid_count(value: Any) -> bool:
    """Checker finding 3 (GPT-5.4): an actual/called count must be a
    non-bool, non-negative integer -- floats (`36.5`), negative ints,
    `bool`, strings, and `None` are all malformed and must never be
    compared numerically against `min_count_per_class` (which would either
    raise or silently coerce)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def canonical_direction_reasons(
    *,
    metric_status: str,
    coverage_adequate: bool,
    precision_field: str,
    recall_field: str,
    precision_lb: Any,
    recall_lb: Any,
    precision_threshold: Optional[float],
    recall_threshold: Optional[float],
    actual_field: str,
    called_field: str,
    actual_count: Any,
    called_count: Any,
    min_count_per_class: int,
    actual_count_valid: bool = True,
    called_count_valid: bool = True,
) -> list:
    """CANONICAL per-scope reason derivation -- the single shared source
    used by BOTH `_direction_verdict` (the genuine runner path, via
    `decide_scope_gate`) and `scripts.build_masked_holdout_gate_aggregate`
    (the independent aggregate-integrity path). Deterministic given only
    verified numeric/policy state (`metric_status`/`coverage_adequate`/
    thresholds/lower-bounds/counts) -- NEVER given, and NEVER echoes, any
    arbitrary envelope-supplied prose. Centralizing this here means a
    genuine `decide_scope_gate` run and the aggregate builder's
    independent recomputation always produce byte-identical reason text
    for the same underlying verdict, so the aggregate's cross-check never
    spuriously disagrees with a real run.
    """
    reasons: list = []
    if not (actual_count_valid and called_count_valid):
        if not actual_count_valid:
            reasons.append(f"{actual_field}={actual_count!r} is not a valid non-negative integer count")
        if not called_count_valid:
            reasons.append(f"{called_field}={called_count!r} is not a valid non-negative integer count")

    if metric_status == "UNMET":
        precision_ok = _valid_lower_bound(precision_lb) and precision_threshold is not None and precision_lb >= precision_threshold
        recall_ok = _valid_lower_bound(recall_lb) and recall_threshold is not None and recall_lb >= recall_threshold
        if not precision_ok:
            reasons.append(f"{precision_field}={precision_lb!r}<{precision_threshold!r}")
        if not recall_ok:
            reasons.append(f"{recall_field}={recall_lb!r}<{recall_threshold!r}")

    if not coverage_adequate and actual_count_valid and called_count_valid:
        reasons.append(
            f"coverage inadequate: min({actual_count!r}, {called_count!r}) < {min_count_per_class!r}"
        )
    return reasons


def canonical_scope_gate_reason(scope_statuses: Mapping[str, str], authorization_blockers: Optional[list] = None) -> str:
    """CANONICAL top-level `scope_gate.reason` derivation -- the single
    shared source used by BOTH `decide_scope_gate` (genuine runner path)
    and the aggregate builder's independent recomputation. Deterministic
    from the canonical, sorted per-scope `scope_status` values plus any
    (sorted) `authorization_blockers` -- NEVER from arbitrary
    envelope-supplied prose, so a tampered/injected `reason` string can
    never survive into a published aggregate.
    """
    summary = "; ".join(f"{key}={status}" for key, status in sorted(scope_statuses.items()))
    blockers = sorted(set(authorization_blockers)) if authorization_blockers else []
    if blockers:
        return "BLOCKED_POLICY: " + "; ".join(blockers) + " | " + summary
    return summary


def _direction_verdict(
    stratum: str,
    direction: str,
    spec: Optional[dict],
    m: Optional[Metrics],
    min_count_per_class: int,
) -> DirectionVerdict:
    # Defense-in-depth (BLOCKER 2, GPT-5.4): `decide_scope_gate` already
    # rejects any malformed/extra stratum spec as BLOCKED_CONFIG before this
    # is ever reached, so in the normal flow `spec` is always `None` or a
    # well-formed pinned dict. This function must still never raw-index or
    # `float()` an unchecked value -- a malformed hand-built spec (wrong
    # type, missing keys, non-numeric/NaN/out-of-range thresholds) must
    # degrade to "no registered threshold" (NO_THRESHOLD/DESCRIPTIVE), never
    # crash and never fabricate a threshold/verdict.
    spec = spec if isinstance(spec, dict) else None
    registered_directions = spec.get("directions") if spec is not None else None
    registered_directions = registered_directions if isinstance(registered_directions, list) else []
    has_threshold = spec is not None and direction in registered_directions

    precision_threshold: Optional[float] = None
    recall_threshold: Optional[float] = None
    if has_threshold:
        raw_precision = spec.get("precision")
        raw_recall = spec.get("recall")
        if _valid_lower_bound(raw_precision) and _valid_lower_bound(raw_recall):
            precision_threshold = float(raw_precision)
            recall_threshold = float(raw_recall)
        else:
            has_threshold = False  # malformed threshold spec -- never fabricate a verdict

    precision_field, recall_field = _DIRECTION_LB_FIELDS[direction]
    actual_field, called_field = _DIRECTION_COUNT_FIELDS[direction]

    precision_lb = getattr(m, precision_field, None) if m is not None else None
    recall_lb = getattr(m, recall_field, None) if m is not None else None
    actual_count = (m.counts.get(actual_field) if m is not None else None)
    called_count = (m.counts.get(called_field) if m is not None else None)

    actual_count_valid = _valid_count(actual_count)
    called_count_valid = _valid_count(called_count)

    coverage_adequate = (
        min_count_per_class > 0
        and actual_count_valid
        and called_count_valid
        and min(actual_count, called_count) >= min_count_per_class
    )

    if not has_threshold:
        metric_status = "NO_THRESHOLD"
    else:
        precision_ok = _valid_lower_bound(precision_lb) and precision_lb >= precision_threshold
        recall_ok = _valid_lower_bound(recall_lb) and recall_lb >= recall_threshold
        metric_status = "MET" if (precision_ok and recall_ok) else "UNMET"

    reasons = canonical_direction_reasons(
        metric_status=metric_status,
        coverage_adequate=coverage_adequate,
        precision_field=precision_field,
        recall_field=recall_field,
        precision_lb=precision_lb,
        recall_lb=recall_lb,
        precision_threshold=precision_threshold,
        recall_threshold=recall_threshold,
        actual_field=actual_field,
        called_field=called_field,
        actual_count=actual_count,
        called_count=called_count,
        min_count_per_class=min_count_per_class,
        actual_count_valid=actual_count_valid,
        called_count_valid=called_count_valid,
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
        precision_lb=precision_lb if _valid_lower_bound(precision_lb) else 0.0,
        recall_lb=recall_lb if _valid_lower_bound(recall_lb) else 0.0,
        precision_threshold=precision_threshold,
        recall_threshold=recall_threshold,
        actual_count=actual_count if actual_count_valid else 0,
        called_count=called_count if called_count_valid else 0,
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

    # Runtime defense-in-depth (checker findings 1+2): a hand-built
    # `EvalConfig` never passes through `config._validate_scope_authorization`,
    # so re-check the pinned full-spectrum/research-scope requires mapping
    # here too -- a retargeted/narrowed/renamed pin must fail closed exactly
    # like the config-load path does.
    if not _pinned_authorization_valid(scope_auth):
        return _blocked_config(
            "scope_authorization deviates from the pinned pre-registered full_spectrum/"
            "research_scopes requires mapping -- defense-in-depth rejection on a hand-built "
            "EvalConfig"
        )

    # sec 4 step 1 (BLOCKER-2 parity with decide_gate): min_count_per_class
    # <= 0 disables every coverage floor -- must never authorize.
    if config.min_count_per_class <= 0:
        return _blocked_config(
            f"invalid config -- min_count_per_class={config.min_count_per_class!r} must be "
            ">= 1; cannot authorize"
        )

    # Runtime defense-in-depth (checker finding 2): the preregistered v2
    # floor is EXACTLY 36 -- a hand-built `EvalConfig` that drifts
    # `min_count_per_class` away from 36 (in EITHER direction: 1, 35, or
    # even a "more conservative" 37) must never authorize anything.
    if not _min_count_pinned_valid(config.min_count_per_class):
        return _blocked_config(
            f"invalid config -- min_count_per_class={config.min_count_per_class!r} must equal "
            f"the pinned pre-registered v2 floor {_PINNED_MIN_COUNT_PER_CLASS!r}; cannot "
            "authorize on a drifted coverage floor"
        )

    oracle_thresholds = config.oracle_thresholds or {}

    # sec 4 step 1: an entirely empty/missing oracle_thresholds block is the
    # honest pre-Oracle state (AC5/H13) -> UNVERIFIED, computed descriptively
    # from whatever metrics exist. This is DISTINCT from the case handled
    # right below (BLOCKER 2, GPT-5.4): once oracle_thresholds carries ANY
    # content at all (e.g. a `confidence`), `strata` is no longer optional.
    thresholds_unset = not oracle_thresholds
    if thresholds_unset:
        strata_cfg: Mapping[str, Any] = {}
    else:
        # BLOCKER 2 (GPT-5.4): a present-but-malformed top-level `strata`
        # (missing key, `None`, `[]`, a bare string, an int, ...) must fail
        # closed as BLOCKED_CONFIG -- never silently degrade to the
        # `thresholds_unset`/UNVERIFIED branch above (that branch is ONLY
        # the legitimate "not yet configured" state) and never let a
        # non-mapping reach `.get`/`.keys()` below and raise.
        raw_strata = oracle_thresholds.get("strata")
        if not isinstance(raw_strata, dict) or not raw_strata:
            return _blocked_config(
                "oracle_thresholds.strata must be a non-empty mapping once oracle_thresholds "
                f"is otherwise configured -- got {raw_strata!r}"
            )
        strata_cfg = raw_strata

        # BLOCKER 2 (GPT-5.4): `strata` may declare ONLY the pinned
        # registered stratum names (missense/truncating) -- an extra
        # stratum entry, WELL-FORMED OR NOT, is BLOCKED_CONFIG. Metrics-only
        # descriptive strata (e.g. `other`) never need -- and must never
        # require -- a config entry at all; they are already handled below
        # via the metrics/strata key union with `spec=None`. Accepting an
        # extra configured stratum would let a forged/extra entry smuggle a
        # new authorizing threshold past the pinned-semantics check, which
        # only re-validates the two pinned names.
        extra_strata = set(strata_cfg.keys()) - _ALLOWED_STRATUM_NAMES
        if extra_strata:
            return _blocked_config(
                f"oracle_thresholds.strata names stratum/strata {sorted(extra_strata)!r} "
                f"outside the pinned registered set {sorted(_ALLOWED_STRATUM_NAMES)!r} -- extra "
                "configured strata are not permitted (descriptive-only strata are handled from "
                "metrics alone, without any config entry)"
            )

    # Runtime defense-in-depth (checker finding 2): re-check the locked
    # Oracle threshold/direction/gating/confidence semantics against a
    # hand-built `EvalConfig.oracle_thresholds` -- any drift fails closed.
    # Skipped when thresholds are legitimately unset (AC5/H13 -> UNVERIFIED).
    if not thresholds_unset and not _pinned_oracle_semantics_valid(oracle_thresholds, strata_cfg):
        return _blocked_config(
            "oracle_thresholds deviates from the locked pre-registered confidence/precision/"
            "recall/gating/directions semantics -- defense-in-depth rejection on a hand-built "
            "EvalConfig"
        )

    registered = _registered_scopes(strata_cfg)
    if not thresholds_unset and not _requires_registered(scope_auth, registered):
        return _blocked_config(
            "scope_authorization.full_spectrum/research_scopes.requires names a scope not "
            "registered in oracle_thresholds -- cannot authorize on an unregistered scope"
        )

    # sec 4 step 2: enumerate EVERY stratum x direction, no short-circuit --
    # union of oracle-registered strata and metrics-only strata (e.g.
    # `other`) so every reported class is at least descriptively present.
    # The reserved pooled `overall` stratum is EXCLUDED here (AC-S5): it is
    # never a scope/DirectionVerdict, only a descriptive cross-class metric
    # that may still be present in `metrics` (and stays there untouched --
    # only excluded from scope enumeration).
    all_strata = sorted(
        (set(strata_cfg.keys()) | set(metrics.keys())) - {_POOLED_OVERALL_STRATUM}
    )
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

    reason = canonical_scope_gate_reason({key: verdict.scope_status for key, verdict in scopes.items()})

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
