"""v3 tiered post-hoc re-adjudication gate (ADDITIVE,
`docs/project/specs/tiered-gate-v3-posthoc.yaml`).

`decide_tiered_gate` is a NEW, additive companion to the frozen v1
`raptor.eval.gate.decide_gate` and the frozen v2
`raptor.eval.scope_gate.decide_scope_gate` -- it never replaces, dispatches
from, or mutates either, and both stay byte-identical (see
`tests/eval/test_tiered_gate_preservation.py`). Where v2 collapses every
scope into one overloaded `scope_status`, this module emits SIX independent
per-scope axes (never a single overloaded status) plus one whole-run axis
(`A0_run_integrity`):

  A0 run_integrity     -- whole-run: PASS | INVALID
  A1 data_sufficiency  -- ADEQUATE | UNDERPOWERED | NO_CALLS
  A2 conditional_performance -- MET | UNMET | NOT_ESTIMABLE | NOT_APPLICABLE
  A3 policy_parity     -- CLEAR | BLOCKED
  A4 end_to_end_correct_call_coverage -- reported "{correct}/{actual}" metric
  A5 scope_evidence_status -- deterministic summary label (precedence below)
  A6 authorization_status  -- NOT_AUTHORIZED | PENDING_PROSPECTIVE | AUTHORIZED_RESEARCH_ONLY

This is STRICTLY a post-hoc RE-adjudication of the frozen R2 masked-holdout
aggregate (`data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json`)
under the locked `tiered_authorization` rule -- it performs no new run,
scoring, annotation, benchmark read, network access, or data generation
(`no_new_evidence_statement`). It therefore NEVER emits
`VALIDATED_PROSPECTIVE`, `AUTHORIZED_RESEARCH_ONLY`, or a `True`
`research_scope_flags[...]` value -- `SUPPORTED_POSTHOC` alone can never by
itself authorize (spec §4a). Every validation/config-drift/malformed-input
check raises BEFORE any axis is computed -- there is no partial or
per-scope decision on a fail-closed error (spec §4b).
"""
from __future__ import annotations

from typing import Any, Mapping

from .config import (
    EvalConfig,
    TieredReadjudicationConfigError,
    TieredReadjudicationError,
    TieredReadjudicationInputError,
    _PINNED_MIN_COUNT_PER_CLASS,
    _PINNED_TIERED_AUTHORIZATION,
)
from .gate import _DIRECTION_COUNT_FIELDS, _DIRECTION_LB_FIELDS
from .model import Metrics, TieredGateDecision, TieredScopeVerdict

__all__ = [
    "decide_tiered_gate",
    "TieredReadjudicationError",
    "TieredReadjudicationInputError",
    "TieredReadjudicationConfigError",
    "SOURCE_R2_CANONICAL_SHA256",
    "SOURCE_R2_INTERNAL_CONTENT_HASH",
]

#: The frozen R2 masked-holdout aggregate this module re-adjudicates --
#: source/hash constants are explicitly allowed to be pinned (spec §4b/§5:
#: "source/hash/config constants are allowed, measured scope-result
#: constants are not").
SOURCE_R2_CANONICAL_SHA256 = "7c55cd4e3059713d1d53886d8893a3819153375b62ce9d37187d731132c6a77f"
SOURCE_R2_INTERNAL_CONTENT_HASH = "2ead589d2f129f988d9932bb01153891902f0d675000554887a1524e567413b2"

_DIRECTIONS: tuple = ("pathogenic", "benign")

#: Every `Metrics.counts` key a v3 axis reads (directly or via
#: `_DIRECTION_COUNT_FIELDS`/`tp`/`tn`/`fp`/`fn`/`abstain`) -- ALL eleven
#: MUST be present with a valid non-bool non-negative int value before any
#: axis is computed (spec §4b: malformed/missing input ABORTS generation
#: fail-closed). A key silently absent from `counts` is exactly as fatal as
#: a malformed value for that key -- never defaulted via `.get(key, 0)`.
_REQUIRED_COUNT_KEYS: tuple = (
    "total",
    "total_called",
    "abstain",
    "path_actual",
    "path_called",
    "benign_actual",
    "benign_called",
    "tp",
    "tn",
    "fp",
    "fn",
)


def _scope_key(stratum: str, direction: str) -> str:
    return f"{stratum}:{direction}"


def _valid_count(value: Any) -> bool:
    """A non-bool, non-negative int -- the only shape a scope count field
    may take (spec A1_data_sufficiency: malformed counts ABORT generation
    fail-closed BEFORE any axis is computed)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_metrics_counts(metrics: Mapping[str, Metrics]) -> None:
    """Validate EVERY required key's PRESENCE and value in EVERY stratum's
    `Metrics.counts` mapping -- not merely a fixed subset of "meaningful"
    fields, and not merely the keys that happen to be present. A key
    entirely ABSENT from `counts` is exactly as fatal as a malformed value
    for that key (e.g. a stratum missing `"fn"` fails closed exactly like
    `"total": -10` would) -- callers must never `.get(key, 0)` a required
    count and silently treat a missing key as zero."""
    for stratum, m in metrics.items():
        counts = getattr(m, "counts", None)
        if not isinstance(counts, Mapping):
            raise TieredReadjudicationInputError(
                f"stratum {stratum!r} Metrics.counts must be a mapping, got {type(counts).__name__}"
            )
        for key in _REQUIRED_COUNT_KEYS:
            if key not in counts:
                raise TieredReadjudicationInputError(
                    f"stratum {stratum!r} Metrics.counts is missing required key {key!r}"
                )
        for key, value in counts.items():
            if not _valid_count(value):
                raise TieredReadjudicationInputError(
                    f"stratum {stratum!r} counts[{key!r}]={value!r} is not a valid non-bool "
                    "non-negative int"
                )


def _validate_config(config: EvalConfig) -> Mapping[str, Any]:
    """Validate `config.tiered_authorization` against the locked pin
    (`_PINNED_TIERED_AUTHORIZATION`, strict recursive equality) AND the
    pinned `min_count_per_class` floor. Defense-in-depth: this re-checks a
    hand-built `EvalConfig` that bypasses `config.load_config`'s own
    `_validate_tiered_authorization` call, exactly mirroring
    `scope_gate.py`'s pattern for `scope_authorization`. Returns the
    validated `tiered_authorization` mapping on success."""
    tiered_auth = getattr(config, "tiered_authorization", None)
    if tiered_auth != _PINNED_TIERED_AUTHORIZATION:
        raise TieredReadjudicationConfigError(
            "`tiered_authorization` does not match the locked pinned v3 config block "
            "(docs/project/specs/tiered-gate-v3-posthoc.yaml §4a/§8) -- any drift in the "
            "criterion-scope map, full_spectrum/research-scope requires, governance "
            "statements, disclaimer, no-new-evidence statement, or prospective dataset "
            "rule is rejected fail-closed."
        )
    min_count_per_class = getattr(config, "min_count_per_class", None)
    if (
        not isinstance(min_count_per_class, int)
        or isinstance(min_count_per_class, bool)
        or min_count_per_class != _PINNED_MIN_COUNT_PER_CLASS
    ):
        raise TieredReadjudicationConfigError(
            "`min_count_per_class` must equal the pinned pre-registered floor "
            f"{_PINNED_MIN_COUNT_PER_CLASS} for a v3 tiered re-adjudication -- "
            f"got {min_count_per_class!r}"
        )
    return tiered_auth


def _validate_evaluation_skipped(run_meta: Any, criterion_map: Mapping[str, Any]) -> list:
    """Every criterion named in `run_meta.evaluation_skipped` MUST have an
    entry in the locked `criterion_scope_applicability` map -- an unknown
    criterion is config/input drift and ABORTS generation fail-closed
    (never a per-scope BLOCKED verdict, spec §4b)."""
    evaluation_skipped = list(getattr(run_meta, "evaluation_skipped", None) or [])
    for criterion in evaluation_skipped:
        if criterion not in criterion_map:
            raise TieredReadjudicationConfigError(
                f"evaluation_skipped criterion {criterion!r} has no entry in the locked "
                "`criterion_scope_applicability` map -- an unmapped exclusion is config/input "
                "drift and aborts generation (no partial/per-scope BLOCKED record is ever emitted)"
            )
    return evaluation_skipped


def _run_integrity(run_meta: Any) -> str:
    """A0_run_integrity (spec §3): PASS iff
    `effective_lineage_blockers == []` AND `remask_survivors == 0` AND
    `canonical_join_rows == bias_rows` AND `returned_artifacts_verified >= 1`;
    else INVALID."""
    effective_lineage_blockers = list(getattr(run_meta, "effective_lineage_blockers", None) or [])
    remask_survivors = getattr(run_meta, "remask_survivors", None)
    canonical_join_rows = getattr(run_meta, "canonical_join_rows", None)
    bias_rows = getattr(run_meta, "bias_rows", None)
    returned_artifacts_verified = getattr(run_meta, "returned_artifacts_verified", None)
    if (
        effective_lineage_blockers == []
        and remask_survivors == 0
        and canonical_join_rows == bias_rows
        and isinstance(returned_artifacts_verified, int)
        and not isinstance(returned_artifacts_verified, bool)
        and returned_artifacts_verified >= 1
    ):
        return "PASS"
    return "INVALID"


def _threshold_for(stratum: str, direction: str, oracle_thresholds: Any) -> tuple:
    """Return `(registered, precision_threshold, recall_threshold)` for a
    `(stratum, direction)` scope -- `registered` is False iff no Oracle
    threshold is registered for this scope (A2_conditional_performance ==
    NOT_APPLICABLE), never a fabricated threshold."""
    strata_cfg = oracle_thresholds.get("strata") if isinstance(oracle_thresholds, Mapping) else None
    if not isinstance(strata_cfg, Mapping):
        return False, None, None
    spec = strata_cfg.get(stratum)
    if not isinstance(spec, Mapping):
        return False, None, None
    directions = spec.get("directions") or []
    if direction not in directions:
        return False, None, None
    return True, spec.get("precision"), spec.get("recall")


def _build_scope_verdict(
    *,
    stratum: str,
    direction: str,
    m: Metrics,
    run_integrity: str,
    oracle_thresholds: Any,
    min_count_per_class: int,
    evaluation_skipped: list,
    criterion_map: Mapping[str, Any],
) -> TieredScopeVerdict:
    actual_field, called_field = _DIRECTION_COUNT_FIELDS[direction]
    precision_field, recall_field = _DIRECTION_LB_FIELDS[direction]

    # No `.get(key, 0)` masking here: `_validate_metrics_counts` has
    # already required every key in `_REQUIRED_COUNT_KEYS` to be present
    # (spec §4b) -- direct indexing is the only shape that can't silently
    # substitute 0 for an absent key.
    actual_count = m.counts[actual_field]
    called_count = m.counts[called_field]
    tp = m.counts["tp"]
    tn = m.counts["tn"]
    fp = m.counts["fp"]
    fn = m.counts["fn"]
    abstain_count = m.counts["abstain"]

    # A1_data_sufficiency
    if called_count == 0:
        data_sufficiency = "NO_CALLS"
    elif min(actual_count, called_count) < min_count_per_class:
        data_sufficiency = "UNDERPOWERED"
    else:
        data_sufficiency = "ADEQUATE"

    # A2_conditional_performance -- threshold lookup NEVER fabricated.
    registered, precision_threshold, recall_threshold = _threshold_for(stratum, direction, oracle_thresholds)
    precision_lb = getattr(m, precision_field, None)
    recall_lb = getattr(m, recall_field, None)
    if not registered:
        conditional_performance = "NOT_APPLICABLE"
        out_precision_lb: float | None = None
        out_recall_lb: float | None = None
        precision_threshold = None
        recall_threshold = None
    elif data_sufficiency != "ADEQUATE":
        conditional_performance = "NOT_ESTIMABLE"
        out_precision_lb = None
        out_recall_lb = None
    else:
        precision_ok = (
            isinstance(precision_lb, (int, float))
            and not isinstance(precision_lb, bool)
            and precision_threshold is not None
            and precision_lb >= precision_threshold
        )
        recall_ok = (
            isinstance(recall_lb, (int, float))
            and not isinstance(recall_lb, bool)
            and recall_threshold is not None
            and recall_lb >= recall_threshold
        )
        conditional_performance = "MET" if (precision_ok and recall_ok) else "UNMET"
        out_precision_lb = precision_lb
        out_recall_lb = recall_lb

    # A3_policy_parity
    scope_key_str = _scope_key(stratum, direction)
    blocked = any(scope_key_str in (criterion_map.get(c) or []) for c in evaluation_skipped)
    policy_parity = "BLOCKED" if blocked else "CLEAR"

    # A4_end_to_end_coverage -- CORRECT counts (never `called`) over `actual`.
    correct = tp if direction == "pathogenic" else tn
    end_to_end_correct_call_coverage = f"{correct}/{actual_count}"

    # A5_scope_evidence_status -- deterministic precedence (spec §3):
    # INVALID > NOT_APPLICABLE > NO_CALLS > UNDERPOWERED > BLOCKED_POLICY >
    # NOT_SUPPORTED > SUPPORTED_POSTHOC. Data-first precedence keeps a
    # no-calls/underpowered scope from being mislabeled a policy failure.
    reasons: list = []
    if run_integrity == "INVALID":
        scope_evidence_status = "INVALID"
        reasons.append("A0_run_integrity == INVALID: whole-run integrity meta failed")
    elif conditional_performance == "NOT_APPLICABLE":
        scope_evidence_status = "NOT_APPLICABLE"
        reasons.append("no Oracle threshold registered for this scope")
    elif data_sufficiency == "NO_CALLS":
        scope_evidence_status = "NO_CALLS"
        reasons.append(f"{called_field}=0")
    elif data_sufficiency == "UNDERPOWERED":
        scope_evidence_status = "UNDERPOWERED"
        reasons.append(
            f"min({actual_field}={actual_count}, {called_field}={called_count}) < "
            f"min_count_per_class={min_count_per_class}"
        )
    elif policy_parity == "BLOCKED":
        scope_evidence_status = "BLOCKED_POLICY"
        reasons.append(f"blocked by evaluation_skipped criterion mapped to {scope_key_str!r}")
    elif conditional_performance == "UNMET":
        scope_evidence_status = "NOT_SUPPORTED"
        reasons.append(f"{precision_field}={out_precision_lb!r}<{precision_threshold!r} or {recall_field}={out_recall_lb!r}<{recall_threshold!r}")
    else:
        scope_evidence_status = "SUPPORTED_POSTHOC"

    # A6_authorization_status -- SUPPORTED_POSTHOC alone never authorizes;
    # it gets PENDING_PROSPECTIVE (research-evidence support recorded,
    # authorization withheld pending a prospective run). Everything else is
    # NOT_AUTHORIZED. This re-adjudication NEVER emits AUTHORIZED_RESEARCH_ONLY.
    authorization_status = "PENDING_PROSPECTIVE" if scope_evidence_status == "SUPPORTED_POSTHOC" else "NOT_AUTHORIZED"

    return TieredScopeVerdict(
        stratum=stratum,
        direction=direction,
        data_sufficiency=data_sufficiency,
        conditional_performance=conditional_performance,
        policy_parity=policy_parity,
        precision_lb=out_precision_lb,
        recall_lb=out_recall_lb,
        precision_threshold=precision_threshold,
        recall_threshold=recall_threshold,
        actual_count=actual_count,
        called_count=called_count,
        tp=tp,
        tn=tn,
        fp=fp,
        fn=fn,
        min_count=min_count_per_class,
        end_to_end_correct_call_coverage=end_to_end_correct_call_coverage,
        abstain_count=abstain_count,
        scope_evidence_status=scope_evidence_status,
        authorization_status=authorization_status,
        reasons=reasons,
    )


def decide_tiered_gate(metrics: Mapping[str, Metrics], config: EvalConfig, run_meta: Any) -> TieredGateDecision:
    """v3 tiered post-hoc re-adjudication of a frozen masked-holdout
    aggregate (spec `docs/project/specs/tiered-gate-v3-posthoc.yaml`).

    Emits a `TieredGateDecision` with one `TieredScopeVerdict` per
    `(stratum, direction)` scope for EVERY stratum present in `metrics`
    (never short-circuiting, mirroring v2 AC-S1) -- `metrics` is the ONLY
    source of which strata exist; `config.oracle_thresholds` supplies
    thresholds where registered (else `NOT_APPLICABLE`, never fabricated).

    Raises `TieredReadjudicationConfigError` on any `tiered_authorization`/
    `min_count_per_class` drift from the locked pin, or an
    `evaluation_skipped` criterion absent from `criterion_scope_applicability`.
    Raises `TieredReadjudicationInputError` on any malformed (non-int / bool
    / negative) per-scope count. Both are raised BEFORE any axis is
    computed -- there is no partial decision on a fail-closed error.
    """
    tiered_auth = _validate_config(config)
    _validate_metrics_counts(metrics)

    criterion_map = tiered_auth["criterion_scope_applicability"]
    evaluation_skipped = _validate_evaluation_skipped(run_meta, criterion_map)

    run_integrity = _run_integrity(run_meta)
    oracle_thresholds = config.oracle_thresholds or {}
    min_count_per_class = config.min_count_per_class

    scopes: dict = {}
    for stratum, m in metrics.items():
        for direction in _DIRECTIONS:
            scopes[_scope_key(stratum, direction)] = _build_scope_verdict(
                stratum=stratum,
                direction=direction,
                m=m,
                run_integrity=run_integrity,
                oracle_thresholds=oracle_thresholds,
                min_count_per_class=min_count_per_class,
                evaluation_skipped=evaluation_skipped,
                criterion_map=criterion_map,
            )

    # full_spectrum aggregate -- a post-hoc re-adjudication NEVER validates
    # full-spectrum (requires an EXECUTED prospective run); ALWAYS
    # NOT_VALIDATED / NOT_AUTHORIZED here regardless of per-scope outcomes.
    full_spectrum_status = "NOT_VALIDATED"
    full_spectrum_authorization = "NOT_AUTHORIZED"

    # research_scope aggregate (single canonical key, spec §4a).
    research_scopes_cfg = tiered_auth["research_scopes"]
    research_key = next(iter(research_scopes_cfg))
    research_requires = research_scopes_cfg[research_key]["requires"]
    research_scope_evidence_status = "NOT_SUPPORTED"
    if run_integrity == "PASS" and all(
        scopes.get(req) is not None and scopes[req].scope_evidence_status == "SUPPORTED_POSTHOC"
        for req in research_requires
    ):
        research_scope_evidence_status = "SUPPORTED_POSTHOC"
    research_scope_authorization = (
        "PENDING_PROSPECTIVE" if research_scope_evidence_status == "SUPPORTED_POSTHOC" else "NOT_AUTHORIZED"
    )
    # Post-hoc NEVER sets the canonical "_validated" boolean True -- only an
    # EXECUTED prospective run (VALIDATED_PROSPECTIVE) can.
    research_scope_flags = {research_key: False}

    governance_state = "RESEARCH_ONLY_NO_CLINICAL_USE"
    governance_statement = tiered_auth["governance_statements"][governance_state]
    research_use_disclaimer = tiered_auth["research_use_disclaimer"]
    no_new_evidence_statement = tiered_auth["no_new_evidence_statement"]
    prospective_validation_status = tiered_auth["prospective_validation"]["status"]

    reason = (
        "post-hoc re-adjudication: run_integrity INVALID, every scope forced to INVALID/NOT_AUTHORIZED"
        if run_integrity == "INVALID"
        else "post-hoc re-adjudication complete: no scope is authorized pending a prospective validation"
    )

    return TieredGateDecision(
        schema_version="3",
        run_integrity=run_integrity,
        scopes=scopes,
        full_spectrum_status=full_spectrum_status,
        full_spectrum_authorization=full_spectrum_authorization,
        research_scope_evidence_status=research_scope_evidence_status,
        research_scope_authorization=research_scope_authorization,
        research_scope_flags=research_scope_flags,
        governance_state=governance_state,
        governance_statement=governance_statement,
        research_use_disclaimer=research_use_disclaimer,
        prospective_validation_status=prospective_validation_status,
        source_record="data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json",
        source_canonical_lf_sha256=SOURCE_R2_CANONICAL_SHA256,
        source_content_hash=SOURCE_R2_INTERNAL_CONTENT_HASH,
        post_hoc=True,
        no_new_evidence_statement=no_new_evidence_statement,
        reason=reason,
    )
