"""PRD-01 sec 10.4 `parse.py` — parse a `BiasRecord.criteria` table into
`CriterionCall`s (only fired, i.e. `strength_int > 0`).

RAPTOR never re-derives ACMG thresholds (ADR-0007/0008): BIAS's fired
strength int is the authority; this module only NORMALIZES it via the
config-driven `strength_map` (FR7/GP-6) and classifies direction from the
generic ACMG naming convention (PVS/PS/PM/PP => pathogenic; BA/BS/BP =>
benign) -- never from a hardcoded per-criterion/per-variant lookup.

This is parsing/mapping ONLY -- policy (which fired criteria actually
become KB evidence, e.g. excluding PP5/BP6 for R-A2 circularity) lives in
`policy.py`. `parse_rationale` is deliberately faithful to every fired
criterion (the oracle fixture expects PP5/BP6 to still show up here).
"""
from __future__ import annotations

from typing import Mapping

from .model import CriterionCall

#: ACMG category-code prefixes (public standard, not a per-variant
#: hardcode): PVS/PS/PM/PP fire toward a pathogenic call, BA/BS/BP toward
#: benign. Sorted longest-first so "pvs" is checked before "ps".
_PATHOGENIC_PREFIXES: tuple[str, ...] = ("pvs", "ps", "pm", "pp")
_BENIGN_PREFIXES: tuple[str, ...] = ("ba", "bs", "bp")


class UnknownCriterionDirectionError(ValueError):
    """Raised when a criterion key's ACMG category prefix cannot be
    classified pathogenic/benign -- fail loud rather than silently guess
    (R-A3): an unrecognized BIAS category is a contract drift, not
    something to score around."""


class UnmappedStrengthError(KeyError):
    """Raised when `strength_map` (config, FR7) has no entry for a fired
    BIAS strength int -- a config drift (H7) must fail loud, never
    silently coerce to some default strength."""


def _direction_for(criterion_key: str) -> str:
    key = criterion_key.lower()
    for prefix in sorted(_PATHOGENIC_PREFIXES, key=len, reverse=True):
        if key.startswith(prefix):
            return "pathogenic"
    for prefix in sorted(_BENIGN_PREFIXES, key=len, reverse=True):
        if key.startswith(prefix):
            return "benign"
    raise UnknownCriterionDirectionError(
        f"cannot classify pathogenic/benign direction for criterion key {criterion_key!r} "
        "(unrecognized ACMG category prefix -- BIAS source-contract drift?)"
    )


def parse_rationale(
    criteria: Mapping[str, tuple[int, str]], strength_map: Mapping[str, str]
) -> list[CriterionCall]:
    """Parse a `BiasRecord.criteria` table into `CriterionCall`s.

    Only criteria with a fired int > 0 are returned (BIAS's own convention:
    0 = not fired). Deterministic (sorted by criterion key) regardless of
    the input mapping's iteration order (R-A11).
    """
    calls: list[CriterionCall] = []
    for key in sorted(criteria.keys()):
        fired_int, explanation = criteria[key]
        fired_int = int(fired_int)
        if fired_int <= 0:
            continue
        strength_key = str(fired_int)
        if strength_key not in strength_map:
            raise UnmappedStrengthError(
                f"strength_map has no entry for fired strength {strength_key!r} "
                f"(criterion {key!r}) -- config drift (H7), refusing to guess"
            )
        calls.append(
            CriterionCall(
                criterion=key.upper(),
                strength=strength_map[strength_key],
                direction=_direction_for(key),
                rationale=str(explanation),
            )
        )
    return calls
