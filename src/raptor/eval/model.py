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
