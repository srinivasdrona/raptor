"""PRD-06 sec 10.3 `model.py` — the eval-harness data model.

Plain (non-frozen) dataclasses so the LOCKED tests can construct them either
positionally or by keyword (`tests/eval/conftest.py`) -- only `EvalConfig`
(config.py) is frozen (sec 10.6). Field order matches the build contract
exactly; do not reorder without checking every positional test construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LabeledVariant:
    """A known-classification variant + its best-available label (FR1).

    This is the ONLY object that carries a label. It flows into
    `benchmark.build_benchmark` and never into an evidence source (FR8/AC6).
    """

    variant_id: str
    label: str  # "P" | "LP" | "LB" | "B" | "Conflicting" | ...
    review_status: str
    submitter_count: int
    source: str
    snapshot: str
    raptor_influenced: bool
    variant_class: str  # "missense" | "truncating" | "other" | ...


@dataclass
class BenchmarkRow:
    """A frozen benchmark row (FR1) -- label + variant_class only, plus
    optional provenance carried through from the source `LabeledVariant`.
    The scored/metrics path only ever needs `variant_id`/`label`/
    `variant_class`; `source`/`snapshot` are provenance-only (GP-9)."""

    variant_id: str
    label: str
    variant_class: str
    source: str | None = None
    snapshot: str | None = None


@dataclass
class ImpliedCall:
    """The eval-only, non-authoritative implied direction (FR3/sec 10.6).

    `variant_id` is assigned by the CALLER (`combine.implied_direction`
    itself never knows which variant it was called for); `points` is the
    signed Tavtigian-2018 sum; `implied` in {"LP", "LB", "no_call"}.
    """

    variant_id: str | None
    implied: str
    points: int


@dataclass
class Metrics:
    """Class-stratified metrics for one stratum (FR4/FR5).

    `precision_lb`/`recall_lb`/`benign_precision_lb`/`benign_recall_lb`
    (gate-fidelity, Arm C) are the 95%-CI Clopper-Pearson LOWER bounds the
    gate compares against `EvalConfig.oracle_thresholds` -- additive fields
    alongside the existing point estimates; `compute_metrics` populates them
    from `raptor.eval.stats.clopper_pearson_lower`. Default 0.0 for
    hand-built `Metrics` fixtures that don't set them explicitly (never
    silently "passing" by omission -- 0.0 fails any positive threshold).
    """

    precision: float
    recall: float
    concordance: float
    counts: dict = field(default_factory=dict)
    stratum: str = ""
    gating: bool = True
    benign_precision: float = 0.0
    benign_recall: float = 0.0
    precision_lb: float = 0.0
    recall_lb: float = 0.0
    benign_precision_lb: float = 0.0
    benign_recall_lb: float = 0.0


@dataclass
class StratumVerdict:
    """Per-stratum, per-direction gate verdict (Arm C gate-fidelity).

    `threshold` is the resolved `oracle_thresholds.strata[name]` spec dict;
    `powered` is whether the stratum cleared the per-direction
    `min_count_per_class` coverage floor (FR5); `met` is whether every
    gated direction's lower bound cleared its threshold (only meaningful
    when `powered`); `gating` mirrors the config spec's own `gating` flag
    (e.g. `truncating-benign` is report-only, `gating=False`).
    """

    precision_lb: float
    recall_lb: float
    threshold: dict
    met: bool
    gating: bool
    powered: bool


@dataclass
class GateDecision:
    """The VUS-authorization gate decision (FR6/AC5).

    `status` in {"PASS", "FAIL", "UNVERIFIED", "UNDERPOWERED",
    "BLOCKED_POLICY"}. `BLOCKED_POLICY` is emitted ONLY by the terminal
    masked-rerun harness (`scripts/run_masked_holdout_eval.py`) when the
    required `bp4pp3-predictor-policy` artifact is missing/unapproved/
    malformed -- `decide_gate` itself never emits it. `per_stratum` (Arm C
    gate-fidelity, additive) maps stratum name -> `StratumVerdict`.
    """

    status: str
    stratum: str
    reason: str
    vus_authorized: bool
    per_stratum: dict = field(default_factory=dict)


@dataclass
class DirectionVerdict:
    """One `(stratum, direction)` scope verdict -- v2 additive, ADDITIVE
    ONLY (does not replace `StratumVerdict`). Preserves TWO orthogonal axes
    a v1 `StratumVerdict` collapses: `metric_status` (did the 95%
    Clopper-Pearson lower bound clear its registered threshold?) and
    `coverage_adequate` (did held-out coverage clear `min_count_per_class`?)
    -- so a scope that is both metric-UNMET and coverage-inadequate (e.g.
    missense) reports BOTH facts instead of losing one to the other.
    `precision_threshold`/`recall_threshold` are `None` when this
    `(stratum, direction)` has no Oracle-registered threshold (e.g.
    truncating-benign) -- never fabricated.
    """

    stratum: str
    direction: str  # "pathogenic" | "benign"
    precision_lb: float
    recall_lb: float
    precision_threshold: float | None
    recall_threshold: float | None
    actual_count: int
    called_count: int
    min_count: int
    coverage_adequate: bool
    metric_status: str  # "MET" | "UNMET" | "NO_THRESHOLD"
    scope_status: str  # "VALIDATED" | "FAIL" | "UNDERPOWERED" | "DESCRIPTIVE"
    reasons: list = field(default_factory=list)


@dataclass
class ScopeGateDecision:
    """v2 scope-specific gate decision (schema `raptor.tsc.masked_holdout_gate.v2`).

    Additive alongside the frozen v1 `GateDecision` -- `decide_gate` never
    dispatches into this shape. `scopes` maps the `"{stratum}:{direction}"`
    scope key to its `DirectionVerdict`; EVERY configured stratum x
    direction (plus any stratum present only in `metrics`, e.g. `other`) is
    present -- no short-circuit (AC-S1). `full_spectrum_vus_authorized` and
    `research_scope_flags` are computed ONLY from per-scope `scope_status`
    values, never from a pooled/`overall` metric (AC-S5).
    `research_use_disclaimer` is a separate, mandatory, non-blank field --
    it is never appended to `governance_statement`, which stays the exact
    preregistered string verbatim.
    """

    schema_version: str = "2"
    scopes: dict = field(default_factory=dict)  # scope-key -> DirectionVerdict
    full_spectrum_status: str = "UNVERIFIED"  # PASS|FAIL|UNVERIFIED|UNDERPOWERED|BLOCKED_POLICY|BLOCKED_CONFIG
    full_spectrum_vus_authorized: bool = False
    research_scope_flags: dict = field(default_factory=dict)  # narrow flag name -> bool
    governance_state: str = "NONE_VALIDATED"  # FULL_SPECTRUM|TRUNCATING_PATHOGENIC_ONLY|NONE_VALIDATED
    governance_statement: str = ""  # non-statistical; exact preregistered string for the state
    research_use_disclaimer: str = ""  # mandatory, non-blank, never merged into governance_statement
    reason: str = ""
    #: Explicit, machine-readable, deterministic authorization blockers
    #: (ADDITIVE) -- e.g. `"evaluation_skipped_criteria:PM1"`. Empty by
    #: default (the normal, non-blocked path). Populated by
    #: `scripts/run_masked_holdout_eval.py::compute_report_scope_gate` when
    #: an evaluation-only criterion exclusion (parity break) forces every
    #: authorization surface closed -- the per-scope statistical `scopes`
    #: verdicts are NEVER altered/hidden by a blocker (a scope may still
    #: legitimately read VALIDATED); only the authorization booleans/state
    #: are withheld, and the reason is surfaced explicitly here instead of
    #: silently.
    authorization_blockers: list = field(default_factory=list)


@dataclass
class TieredScopeVerdict:
    """v3 tiered post-hoc re-adjudication -- one `(stratum, direction)` scope
    verdict (ADDITIVE, `docs/project/specs/tiered-gate-v3-posthoc.yaml`).

    Six independent per-scope axes (`data_sufficiency`, `conditional_performance`,
    `policy_parity`, plus the summary `scope_evidence_status`/`authorization_status`)
    are ALWAYS emitted -- never a single overloaded status. `precision_lb`/
    `recall_lb`/`precision_threshold`/`recall_threshold` are `None` (never a
    fabricated `0.0`) whenever no threshold is registered for this scope OR the
    scope is not `data_sufficiency == "ADEQUATE"`. `tp`/`tn`/`fp`/`fn` are the
    RAW shared per-stratum confusion-matrix counts (identical on both the
    pathogenic and benign scope of the same stratum) -- `end_to_end_correct_call_coverage`
    is the `"{correct}/{actual}"` string using the CORRECT count for this
    direction (`tp` for pathogenic, `tn` for benign), never `called_count`
    substituted for the correct count (e.g. `other:benign` is `112/2095`, not
    `113/2095`).
    """

    stratum: str
    direction: str  # "pathogenic" | "benign"
    data_sufficiency: str  # "ADEQUATE" | "UNDERPOWERED" | "NO_CALLS"
    conditional_performance: str  # "MET" | "UNMET" | "NOT_ESTIMABLE" | "NOT_APPLICABLE"
    policy_parity: str  # "CLEAR" | "BLOCKED"
    precision_lb: float | None
    recall_lb: float | None
    precision_threshold: float | None
    recall_threshold: float | None
    actual_count: int
    called_count: int
    tp: int
    tn: int
    fp: int
    fn: int
    min_count: int
    end_to_end_correct_call_coverage: str  # "{correct}/{actual}" -- correct = tp (pathogenic) / tn (benign)
    abstain_count: int
    scope_evidence_status: str
    authorization_status: str  # "NOT_AUTHORIZED" | "PENDING_PROSPECTIVE" | "AUTHORIZED_RESEARCH_ONLY"
    reasons: list = field(default_factory=list)


@dataclass
class TieredGateDecision:
    """v3 tiered post-hoc re-adjudication decision (schema
    `raptor.tsc.tiered_readjudication.v3`, ADDITIVE) --
    `raptor.eval.tiered_gate.decide_tiered_gate`'s return value.

    Additive alongside the frozen v1 `GateDecision` and v2 `ScopeGateDecision`
    -- `decide_tiered_gate` never dispatches from or replaces either. A
    post-hoc re-adjudication NEVER emits `"AUTHORIZED_RESEARCH_ONLY"` or
    `"VALIDATED_PROSPECTIVE"` anywhere in this decision, and
    `research_scope_flags[...]` stays `False` -- `post_hoc` is always `True`
    here. `implementation_commit`/`implementation_module_sha256`/
    `tiered_config_canonical_sha256`/`content_hash` are `None` until the
    orchestrator CLI (`scripts/build_tiered_readjudication.py`) fills them in
    when writing the committed record -- `decide_tiered_gate` itself never
    touches the filesystem or git.
    """

    schema_version: str = "3"
    run_integrity: str = "PASS"  # "PASS" | "INVALID"
    scopes: dict = field(default_factory=dict)  # "{stratum}:{direction}" -> TieredScopeVerdict
    full_spectrum_status: str = "NOT_VALIDATED"  # "NOT_VALIDATED" | "VALIDATED_PROSPECTIVE"
    full_spectrum_authorization: str = "NOT_AUTHORIZED"
    research_scope_evidence_status: str = "NOT_SUPPORTED"  # "NOT_SUPPORTED" | "SUPPORTED_POSTHOC" | "VALIDATED_PROSPECTIVE"
    research_scope_authorization: str = "NOT_AUTHORIZED"
    research_scope_flags: dict = field(default_factory=dict)  # canonical key -> bool
    governance_state: str = "RESEARCH_ONLY_NO_CLINICAL_USE"
    governance_statement: str = ""
    research_use_disclaimer: str = ""
    prospective_validation_status: str = "PENDING"
    source_record: str = ""
    source_canonical_lf_sha256: str = ""
    source_content_hash: str = ""
    tiered_config_canonical_sha256: str | None = None
    implementation_commit: str | None = None
    implementation_module_sha256: str | None = None
    content_hash: str | None = None
    post_hoc: bool = True
    no_new_evidence_statement: str = ""
    reason: str = ""
