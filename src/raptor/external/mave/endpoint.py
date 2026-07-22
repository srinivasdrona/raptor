"""Fixed, non-clinical MAVE functional-score thresholds + label-blind runner.

`FunctionalClass` is deliberately NOT the ACMG/ClinVar vocabulary (no `B`/
`LB`/`P`/`LP`, no "clinical" anywhere in a member's value) -- it is a
distinct, orthogonal functional read-out. Thresholds are FIXED, pre-
registered constants (never derived from the data being classified, never
config-tunable per-run): `< 0.242` -> functional_BLB, `> 0.477` ->
functional_PLP, the closed interval `[0.242, 0.477]` -> ambiguous.

`run_label_blind_validation` calls the injected scorer with ONLY the
variant's opaque `variant_id` (never a label, never a MAVE score) and
returns a report whose `.aggregate()` is always `NON_GATING` and never
contains a `vus_authorized`/`gate` key -- this endpoint cannot authorize
anything.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Sequence

from .report import LabelBlindReport
from .source import MaveScoreRecord

#: Pre-registered, fixed functional thresholds (not config-tunable per run --
#: EVALUATION Part I orthogonal-validation scope). Boundaries are ambiguous, not
#: rounded into either functional bucket.
FUNCTIONAL_BLB_BELOW = 0.242
FUNCTIONAL_PLP_ABOVE = 0.477


class FunctionalClass(Enum):
    """A MAVE functional read-out class. Not a clinical significance."""

    FUNCTIONAL_BLB = "functional_BLB"
    AMBIGUOUS = "ambiguous"
    FUNCTIONAL_PLP = "functional_PLP"


def classify_functional_score(score: float) -> FunctionalClass:
    """Classify one MAVE functional score against the fixed thresholds.
    Boundary values (`== 0.242`, `== 0.477`) are ambiguous, not rounded into
    either functional bucket."""
    if score < FUNCTIONAL_BLB_BELOW:
        return FunctionalClass.FUNCTIONAL_BLB
    if score > FUNCTIONAL_PLP_ABOVE:
        return FunctionalClass.FUNCTIONAL_PLP
    return FunctionalClass.AMBIGUOUS


def run_label_blind_validation(
    rows: Sequence[MaveScoreRecord],
    scorer: Callable[[str], float],
    *,
    bootstrap_resamples: int,
    random_seed: int,
) -> LabelBlindReport:
    """Call `scorer(variant_id)` once per row, in row order (never a label,
    never the MAVE score itself -- label-blind by construction), then build
    a deterministic, identity-free, NON_GATING `LabelBlindReport`."""
    observations = []
    for row in rows:
        if row.variant_id is None:
            raise ValueError("run_label_blind_validation requires a resolved variant_id per row")
        raptor_score = scorer(row.variant_id)
        observations.append((row.variant_id, float(raptor_score), row.score))

    return LabelBlindReport.build(
        observations,
        bootstrap_resamples=bootstrap_resamples,
        random_seed=random_seed,
    )


__all__ = [
    "FUNCTIONAL_BLB_BELOW",
    "FUNCTIONAL_PLP_ABOVE",
    "FunctionalClass",
    "classify_functional_score",
    "run_label_blind_validation",
]
