"""Arm C gate-fidelity — exact Clopper-Pearson (Beta-quantile) lower bound.

The gate compares the 95% Clopper-Pearson LOWER bound (not the point estimate
`k/n`) to each pre-registered per-stratum threshold (`docs/EVAL_RUBRIC.md`
§1/§2, corrected anchors n>=36/72/368 -- gate-fidelity slot 2 §0.1/§6). The
independent oracle is `scipy.stats.beta.ppf` itself (a distinct
implementation from any hand-rolled incomplete-beta) -- this module IS that
call, pinned once, so no self-rolled Beta/Wald approximation is ever
substituted at the gate boundary.
"""
from __future__ import annotations

from scipy.stats import beta as _beta


class InsufficientCountError(ValueError):
    """Raised when `n == 0` -- there is no call to compute a bound from.

    Never silently return 0.0 for `n=0`: that would be indistinguishable
    from a genuine "measured k=0 successes" zero lower bound.
    """


def clopper_pearson_lower(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact (Clopper-Pearson) one-sided lower confidence bound for a
    binomial proportion: `k` successes observed in `n` trials.

    `k=0` -> `0.0` (no successes observed; the Beta-quantile degenerates to
    0 here too, but the shortcut avoids a `Beta(0, n+1)` edge case). `n=0`
    raises `InsufficientCountError`. Pure + deterministic; takes no label
    input (the gate/metrics call this on plain counts only).
    """
    if n == 0:
        raise InsufficientCountError("cannot compute a Clopper-Pearson bound with n=0 (no calls)")
    if not (0 < confidence < 1):
        raise ValueError(f"confidence must be strictly between 0 and 1, got {confidence!r}")
    if not (0 <= k <= n):
        raise ValueError(f"k must satisfy 0 <= k <= n, got k={k!r} n={n!r}")
    if k == 0:
        return 0.0
    alpha = 1.0 - confidence
    return float(_beta.ppf(alpha / 2.0, k, n - k + 1))
