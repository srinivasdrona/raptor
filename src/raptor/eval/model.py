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
    """Class-stratified metrics for one stratum (FR4/FR5)."""

    precision: float
    recall: float
    concordance: float
    counts: dict = field(default_factory=dict)
    stratum: str = ""
    gating: bool = True
    benign_precision: float = 0.0
    benign_recall: float = 0.0


@dataclass
class GateDecision:
    """The VUS-authorization gate decision (FR6/AC5)."""

    status: str  # "PASS" | "FAIL" | "UNVERIFIED" | "UNDERPOWERED"
    stratum: str
    reason: str
    vus_authorized: bool
