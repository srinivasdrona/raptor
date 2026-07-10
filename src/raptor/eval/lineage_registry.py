"""Slot 2 sec 1.3 `lineage_registry.py` — exact-set registry meta-checks.

`assert_registry_consistency` reconciles the `LineagePolicy` static oracle
against RAPTOR's own scorer/eval config registries (`configs/acmg/tsc.yaml`,
`configs/eval/tsc2.yaml`): eval/production parity, the scorer's ACMG
registry vs `can_fire`, `included ⊆ can_fire`, every omitted can-fire
criterion carrying an explicit disposition, the forbidden/transitive sets
never drifting from the policy's own derivation, and a `deferred`/
`forbidden` criterion never being silently included without its named
decision. Every breach is collected (never just the first) into a single
structured `LineageRegistryMismatchError(sets_by_kind=...)`.
"""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .config import FORBIDDEN_CRITERIA

if TYPE_CHECKING:
    from raptor.eval.config import EvalConfig
    from raptor.scorer.config import ScorerConfig

    from .lineage_policy import LineagePolicy

#: Dispositions that legitimately explain a can-fire criterion's omission
#: from `included_criteria`/`automatable_criteria` (slot 2 sec 1.3).
_OMISSION_DISPOSITIONS: frozenset[str] = frozenset({"forbidden", "requires_heldout_mask", "deferred"})

#: Dispositions that must never be silently carried by an INCLUDED criterion
#: without an authorized decision (slot 2 sec 1.3 / AC-L13).
_BLOCKING_INCLUSION_DISPOSITIONS: frozenset[str] = frozenset({"deferred", "forbidden"})

#: The two ClinVar-comparator lineage classes that make up the derived
#: `transitive_suspect` net (slot 2 sec 1.1).
_TRANSITIVE_LINEAGE_CLASSES: frozenset[str] = frozenset({"cross_variant_clinvar", "aggregate_clinvar"})


class LineageRegistryMismatchError(ValueError):
    """Raised when the scorer/eval registries drift from the lineage
    policy's static oracle (slot 2 sec 1.3). `sets_by_kind` is a structured,
    deterministic mapping of breach-kind -> the exact set of criteria that
    breach -- every detected breach is reported together, never just the
    first."""

    def __init__(self, sets_by_kind: dict[str, set[str]]) -> None:
        self.sets_by_kind = dict(sets_by_kind)
        super().__init__(
            "lineage registry consistency breach(es): "
            + ", ".join(f"{kind}={sorted(criteria)!r}" for kind, criteria in sorted(self.sets_by_kind.items()))
        )


def _normalize(values) -> tuple[str, ...]:
    return tuple(str(c).strip().upper() for c in values)


def _sequence_drift(left: tuple[str, ...], right: tuple[str, ...]) -> set[str]:
    """The set of criteria whose MULTIPLICITY differs between two
    sequences -- catches both a set-level difference and a same-set
    duplicate-count drift (a criterion listed twice on one side only)."""
    left_counts = Counter(left)
    right_counts = Counter(right)
    if left_counts == right_counts:
        return set()
    drifted = {c for c in (set(left_counts) | set(right_counts)) if left_counts[c] != right_counts[c]}
    return drifted or (set(left_counts) ^ set(right_counts))


def assert_registry_consistency(
    policy: "LineagePolicy", scorer_config: "ScorerConfig", eval_config: "EvalConfig"
) -> None:
    """Raise `LineageRegistryMismatchError` iff any exact-set invariant
    between the lineage policy and RAPTOR's scorer/eval registries breaks
    (slot 2 sec 1.3). All breaches are collected before raising."""
    breaches: dict[str, set[str]] = {}

    included = _normalize(scorer_config.included_criteria)
    automatable = _normalize(eval_config.automatable_criteria)
    drift = _sequence_drift(included, automatable)
    if drift:
        breaches["included_automatable_drift"] = drift

    included_set = set(included)
    can_fire = set(policy.can_fire)

    scored_not_can_fire = included_set - can_fire
    if scored_not_can_fire:
        breaches["scored_not_can_fire"] = scored_not_can_fire

    registry_keys = {str(c).strip().upper() for c in scorer_config.acmg_criteria.keys()}
    registry_drift = registry_keys ^ can_fire
    if registry_drift:
        breaches["registry_can_fire_drift"] = registry_drift

    oracle_allowed = set(policy.oracle_allowed)

    omitted = can_fire - included_set
    undispositioned = set()
    for criterion in omitted:
        record = policy.records.get(criterion)
        if criterion in oracle_allowed:
            continue
        if record is not None and record.validation_disposition in _OMISSION_DISPOSITIONS:
            continue
        undispositioned.add(criterion)
    if undispositioned:
        breaches["omitted_without_disposition"] = undispositioned

    deferred_included = set()
    for criterion in included_set:
        record = policy.records.get(criterion)
        if record is None:
            continue
        if criterion in oracle_allowed:
            continue
        if (
            record.validation_disposition in _BLOCKING_INCLUSION_DISPOSITIONS
            or record.production_disposition in _BLOCKING_INCLUSION_DISPOSITIONS
        ):
            deferred_included.add(criterion)
    if deferred_included:
        breaches["deferred_included_without_decision"] = deferred_included

    derived_forbidden = {
        criterion for criterion in can_fire if policy.records[criterion].validation_disposition == "forbidden"
    }
    if derived_forbidden != set(FORBIDDEN_CRITERIA):
        breaches["forbidden_set_drift"] = derived_forbidden ^ set(FORBIDDEN_CRITERIA)

    derived_transitive = {
        criterion for criterion in can_fire if policy.records[criterion].lineage_class in _TRANSITIVE_LINEAGE_CLASSES
    }
    if set(policy.transitive_suspect) != derived_transitive:
        breaches["transitive_set_drift"] = set(policy.transitive_suspect) ^ derived_transitive

    if breaches:
        raise LineageRegistryMismatchError(breaches)
