"""Evaluation-only evidence wrappers: the approved BP4/PP3 correction
(`PredictorCorrectedEvidenceSource`, preserved for a future `corrected_enabled`
activation -- never wired into a proceed path this track), production
strength-vocabulary parity (`ProductionVocabEvidenceSource`), and the
approved disabled/manual PP3/BP4 suppression wrapper
(`PolicyDisabledEvidenceSource`, planner D5)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from .predictor_aggregation import AggregationSpec

_SCORE_TO_STRENGTH = {
    1: "supporting",
    2: "moderate",
    3: "strong",
    4: "very_strong",
}


class PredictorCorrectedEvidenceSource:
    """Replace only BP4/PP3 scoring strengths while retaining corrections."""

    def __init__(self, source: Any, spec: AggregationSpec) -> None:
        self._source = source
        self._spec = spec
        self.variant_ids = source.variant_ids
        self._corrections: dict[str, dict[str, Any]] = defaultdict(dict)

    def get_evidence(self, variant_id: str):
        corrected_calls: list[tuple[str, str, str]] = []
        for criterion, strength, direction in self._source.get_evidence(variant_id):
            if criterion not in {"PP3", "BP4"}:
                corrected_calls.append((criterion, strength, direction))
                continue
            correction = self._source.get_predictor_correction(
                variant_id, criterion, self._spec
            )
            self._corrections[variant_id][criterion] = correction
            if correction.corrected_strength == 0:
                continue
            corrected_calls.append(
                (
                    criterion,
                    _SCORE_TO_STRENGTH[correction.corrected_strength],
                    direction,
                )
            )
        return tuple(corrected_calls)

    def corrections_for(self, variant_id: str) -> dict[str, Any]:
        return dict(self._corrections.get(variant_id, {}))

    def correction_counts(self) -> dict[str, int]:
        counts = {"PP3": 0, "BP4": 0}
        for corrections in self._corrections.values():
            for criterion, correction in corrections.items():
                if correction.emitted_strength != correction.corrected_strength:
                    counts[criterion] += 1
        return counts


class PolicyDisabledEvidenceSource:
    """Evaluation-only wrapper enforcing the approved disabled/manual PP3/BP4
    policy mode (planner D5): strips every disabled-criterion call BEFORE it
    reaches scoring while counting exactly how many were suppressed, per
    criterion -- never applying `PredictorCorrectedEvidenceSource`'s
    correction. Replaces (never composes with) that wrapper in the disabled
    proceed path.

    Bookkeeping is keyed by `variant_id` so repeated `get_evidence` calls for
    the same variant recompute rather than double-count (mirrors
    `ProductionVocabEvidenceSource`'s idempotency). A disabled criterion that
    never fires for a given variant still yields an explicit `0` count for
    that variant's bucket, never an absent key -- `suppressed_counts`
    aggregates every disabled criterion across all seen variants, always
    including every disabled criterion even if never suppressed anywhere.
    """

    def __init__(
        self,
        source: Any,
        disabled_criteria: frozenset[str] = frozenset({"PP3", "BP4"}),
    ) -> None:
        self._source = source
        self._disabled_criteria = frozenset(str(c).strip().upper() for c in disabled_criteria)
        self.variant_ids = source.variant_ids
        self._suppressed_by_variant: dict[str, dict[str, int]] = {}

    @property
    def disabled_criteria(self) -> frozenset[str]:
        return self._disabled_criteria

    def get_evidence(self, variant_id: str):
        kept: list[tuple[str, str, str]] = []
        counts = {criterion: 0 for criterion in self._disabled_criteria}
        for criterion, strength, direction in self._source.get_evidence(variant_id):
            if criterion in self._disabled_criteria:
                counts[criterion] += 1
                continue
            kept.append((criterion, strength, direction))
        # Recompute (never accumulate) this variant's bucket so a repeated
        # call for the same variant_id is idempotent -- it never double-counts.
        self._suppressed_by_variant[variant_id] = counts
        return tuple(kept)

    @property
    def suppressed_counts(self) -> dict[str, int]:
        totals = {criterion: 0 for criterion in self._disabled_criteria}
        for counts in self._suppressed_by_variant.values():
            for criterion, count in counts.items():
                totals[criterion] += count
        return totals

    @property
    def suppressed_variant_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                variant_id
                for variant_id, counts in self._suppressed_by_variant.items()
                if any(counts.values())
            )
        )

    @property
    def total_suppressed(self) -> int:
        return sum(self.suppressed_counts.values())


class ProductionVocabEvidenceSource:
    """Evaluation-only wrapper enforcing production strength-vocabulary parity.

    Wraps a (typically already `PredictorCorrectedEvidenceSource`-wrapped)
    evidence source and checks every AUTOMATABLE criterion call's strength
    against the scorer's configured `scorer_config.acmg_criteria[criterion]
    .strength_vocab` -- the identical production rule enforced in
    `raptor.scorer.pipeline` (the `STRENGTH_OUT_OF_VOCAB` manual-routing
    path). A call whose strength falls outside its criterion's vocab is
    never emitted with a nonsensical strength: the WHOLE variant is routed
    to manual review (`get_evidence` returns `()`), preserving the
    production one-outcome-per-variant conservation rule -- never a mix of
    scored + manual for the same variant. Non-automatable criteria pass
    through untouched: this wrapper only gates criteria actually authorized
    to fire in production.

    The manual-routing audit trail (`manual_routed_counts`,
    `manual_routed_variant_ids`, `reason_for`) is deterministic and
    label-free -- it records only the criterion/strength/vocab that
    triggered routing, never a ClinVar label -- and idempotent: calling
    `get_evidence` again for an already-routed (or already-clean) variant
    id recomputes the identical result rather than double-counting. A
    missing `acmg_criteria` entry (or a missing `strength_vocab` key) for an
    automatable criterion fails loud (`KeyError`) -- there is no silent
    default vocabulary.
    """

    #: The single manual-routing reason code this wrapper can emit --
    #: mirrors `raptor.scorer.pipeline`'s `STRENGTH_OUT_OF_VOCAB` code.
    _OUT_OF_VOCAB_CODE = "STRENGTH_OUT_OF_VOCAB"

    def __init__(
        self,
        source: Any,
        acmg_criteria: Mapping[str, Mapping[str, Any]],
        automatable_criteria: Any,
    ) -> None:
        self._source = source
        self._acmg_criteria = acmg_criteria
        self._automatable_criteria = frozenset(automatable_criteria)
        self.variant_ids = source.variant_ids
        self._manual_routed_reasons: dict[str, str] = {}

    def get_evidence(self, variant_id: str):
        calls = self._source.get_evidence(variant_id)
        out_of_vocab = None
        for criterion, strength, _direction in calls:
            if criterion not in self._automatable_criteria:
                continue
            # Direct indexing (not `.get`) so a missing criterion/vocab
            # pin fails loud (`KeyError`) rather than silently allowing
            # every strength through.
            vocab = self._acmg_criteria[criterion]["strength_vocab"]
            if strength not in vocab:
                out_of_vocab = (criterion, strength, vocab)
                break

        if out_of_vocab is not None:
            criterion, strength, vocab = out_of_vocab
            self._manual_routed_reasons[variant_id] = (
                f"strength_out_of_vocab: criterion {criterion!r} fired with strength "
                f"{strength!r}, which is not in its configured strength_vocab {list(vocab)!r}"
            )
            return ()

        self._manual_routed_reasons.pop(variant_id, None)
        return calls

    @property
    def manual_routed_counts(self) -> dict[str, int]:
        if not self._manual_routed_reasons:
            return {}
        return {self._OUT_OF_VOCAB_CODE: len(self._manual_routed_reasons)}

    @property
    def manual_routed_variant_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._manual_routed_reasons))

    def reason_for(self, variant_id: str) -> str | None:
        return self._manual_routed_reasons.get(variant_id)
