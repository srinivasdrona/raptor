"""PRD-06 sec 10.3 `combine.py` — the eval-only implied-direction combiner
(FR3). Sums Tavtigian-2018 points over a variant's fired criterion calls
(pathogenic family POSITIVE, benign family NEGATIVE), maps the signed sum to
a category via `config.tavtigian_cutoffs`, then to the eval-only implied
call. This call is NON-AUTHORITATIVE (STRATEGY sec 9): used only for
metrics, never a classification. Abstain (`no_call`) is first-class -- zero
fired criteria, or a sum landing in the VUS band, both abstain (never a
forced call).

`implied_direction` does not know which variant it was called for -- the
CALLER assigns `ImpliedCall.variant_id` (sec 10.6).
"""
from __future__ import annotations

from typing import Iterable, Tuple

from .config import EvalConfig, FORBIDDEN_CRITERIA, VALID_CRITERIA
from .model import ImpliedCall

#: A criterion call as the harness/tests pass it: (criterion, strength, direction).
CriterionCall = Tuple[str, str, str]


def _category(points: int, cutoffs) -> str:
    """Map a signed Tavtigian point sum to a category via the config's
    cutoffs (sec 10.2) -- never invented/hardcoded in code."""
    if points >= cutoffs["pathogenic_min"]:
        return "P"
    if points >= cutoffs["likely_pathogenic_min"]:
        return "LP"
    if cutoffs["vus_min"] <= points <= cutoffs["vus_max"]:
        return "VUS"
    if points >= cutoffs["benign_max"] + 1 and points <= cutoffs["likely_benign_max"]:
        return "LB"
    return "B"


_CATEGORY_TO_IMPLIED = {
    "P": "LP",
    "LP": "LP",
    "VUS": "no_call",
    "LB": "LB",
    "B": "LB",
}


def _family_sign(criterion: str) -> int:
    """Derive the pathogenic/benign sign from the ACMG criterion FAMILY --
    never from a caller-supplied `direction` arg (BLOCKER 2: a launderable
    arg must not be able to flip the sign). Pathogenic-family codes (PVS/PS/
    PM/PP) start with `P`; benign-family codes (BA/BS/BP) start with `B`. An
    automatable criterion with an unknown family is a config error, not a
    silently-ignored call."""
    if not criterion:
        raise ValueError(f"unknown criterion family for {criterion!r}")
    lead = criterion[0].upper()
    if lead == "P":
        return 1
    if lead == "B":
        return -1
    raise ValueError(f"unknown criterion family for {criterion!r} (expected P*/B* ACMG code)")


def implied_direction(calls: Iterable[CriterionCall], config: EvalConfig) -> ImpliedCall:
    """Combine fired criterion calls into an eval-only implied direction
    (FR3/sec 10.6). `calls` is `[(criterion, strength, direction), ...]`.
    The pathogenic/benign sign is derived from the criterion's ACMG FAMILY
    (BLOCKER 2), never from the supplied `direction` -- so a mislabeled
    `direction` cannot flip a call's contribution. Zero calls -> 0 points ->
    `no_call` (abstain is first-class, never forced)."""
    points = 0
    automatable = {str(c).strip().upper() for c in config.automatable_criteria}
    scored: set[str] = set()
    for criterion, strength, direction in calls:
        crit = str(criterion).strip().upper()
        if crit in FORBIDDEN_CRITERIA:
            # PP5/BP6 are structurally excluded (R-A2 ClinVar circularity)
            # -- never scored, even if a hand-built config lists them in
            # `automatable_criteria` (MAJOR-2 defense-in-depth), and even if
            # the caller passes them lowercase or with surrounding whitespace
            # (MAJOR-1 / round-5: the ban is case- AND whitespace-insensitive).
            continue
        if crit not in VALID_CRITERIA:
            # round-6 BLOCKER: hidden/internal whitespace (e.g. a zero-width
            # space) or any other malformed/unknown code is never a valid
            # ACMG code -- SKIP it (never score it), but never raise: an
            # unknown/malformed criterion is not a corrupt-direction error,
            # it simply cannot contribute.
            continue
        if crit not in automatable:
            # Non-automatable criteria must never be scored.
            continue
        if direction not in ("pathogenic", "benign"):
            raise ValueError(f"unknown criterion direction {direction!r} (expected pathogenic/benign)")
        sign = _family_sign(crit)
        expected_direction = "pathogenic" if sign > 0 else "benign"
        if direction != expected_direction:
            raise ValueError(
                f"criterion {criterion!r} family implies direction {expected_direction!r} "
                f"but was labeled {direction!r} -- corrupt upstream data (MAJOR-1); "
                "would also blind checks.py, which keys on `direction`"
            )
        if crit in scored:
            # round-6 MAJOR-1: a criterion fires at most once per ACMG rules
            # -- a duplicate (canonical) criterion call is corrupt scorer
            # output and must fail loud, never be silently summed into an
            # inflated point total. Duplicates of SKIPPED codes (forbidden/
            # unknown/non-automatable) never reach here, since those were
            # never scored.
            raise ValueError(
                f"criterion {crit!r} fired more than once -- a criterion may fire at most "
                "once per ACMG; corrupt scorer output"
            )
        scored.add(crit)
        magnitude = config.tavtigian_points[strength]
        points += sign * magnitude

    category = _category(points, config.tavtigian_cutoffs)
    implied = _CATEGORY_TO_IMPLIED[category]
    return ImpliedCall(variant_id=None, implied=implied, points=points)
