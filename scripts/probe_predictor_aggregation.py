"""Policy blocker A / slot 2 sec 1.2-1.3 + sec 2.3 + sec 3
`probe_predictor_aggregation.py` -- the real-corpus emitted-vs-corrected
diff (Probe 2), the information-completeness/decidability proof (Probe 3),
and the resulting wrapper-vs-upstream route decision (sec 3), run over a
committed pinned-BIAS output TSV.

Usage::

    python scripts/probe_predictor_aggregation.py BIAS_TSV [BIAS_TSV ...] \\
        --output REPORT_JSON [--config configs/eval/predictor_aggregation.yaml]

For every fired PP3/BP4 row across the given TSV(s) this parses the
observable `printout_text` tokens, reconstructs `per_tool_scores`, computes
the corrected strength (`raptor.eval.predictor_aggregation.recompute_strength`),
and compares it to BIAS's emitted strength. Counts (never magic constants)
are derived and persisted; an undecidable row is counted, never silently
treated as corrected (AC-A4). The report is a NON-IDENTIFYING aggregate:
only bounded, sorted example variant coordinates (already-public genomic
positions, never patient data) are retained, and no label/benchmark/
clinical-classification field is read or written anywhere in this module
(ADR-0007/R-A2/H1) -- this is a materiality measurement only, never a
clinical call.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

from raptor.eval.predictor_aggregation import (
    AggregationSpec,
    AggregationUndecidableError,
    load_aggregation_spec,
    recompute_strength,
)
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.model import BiasRecord

_DEFAULT_CONFIG_PATH = "configs/eval/predictor_aggregation.yaml"

#: Bound on how many example variant ids a bucket carries -- deterministic
#: (sorted), never unbounded (mirrors `lineage_audit.py`'s convention).
_MAX_EXAMPLE_VARIANT_IDS = 10

#: Published Tavtigian-2018 per-strength point magnitudes (the SAME values
#: `configs/eval/tsc2.yaml::tavtigian_points` pins for production scoring),
#: redefined locally so this probe never opens a labels-bearing eval config
#: file. Used ONLY to derive a materiality signal -- whether an isolated,
#: single-criterion strength alone would independently cross a Tavtigian
#: category threshold -- never to produce an actual combined clinical call.
_TAVTIGIAN_POINTS: dict[int, int] = {1: 1, 2: 2, 3: 4, 4: 8}

#: Tavtigian-2018 signed-point-sum category cutoffs (same published values
#: as `tsc2.yaml::tavtigian_cutoffs`), used only for the single-criterion
#: materiality signal above.
_LIKELY_PATHOGENIC_MIN = 6
_LIKELY_BENIGN_MAX = -1


def _isolated_points(criterion: str, strength: int) -> int:
    """Signed Tavtigian point value of `strength` in isolation (PP3 is
    pathogenic-direction/positive, BP4 is benign-direction/negative). Not a
    real combined call -- a materiality signal only (never persisted as a
    clinical classification)."""
    if strength <= 0:
        return 0
    magnitude = _TAVTIGIAN_POINTS[strength]
    return magnitude if criterion == "PP3" else -magnitude


def _crosses_to_lp(points: int) -> bool:
    return points >= _LIKELY_PATHOGENIC_MIN


def _crosses_to_lb(points: int) -> bool:
    return points <= _LIKELY_BENIGN_MAX


class _CriterionAccumulator:
    """Mutable per-criterion tally for one probe run (kept private/internal
    -- callers only ever see the frozen `to_dict()` snapshot)."""

    def __init__(self, criterion: str) -> None:
        self.criterion = criterion
        self.n_fired = 0
        self.n_decidable = 0
        self.n_undecidable = 0
        self.n_emitted_ne_corrected = 0
        self.inflated = 0
        self.deflated = 0
        self.to_lp = 0
        self.to_lb = 0
        self.to_no_call = 0
        self._diff_variant_ids: list[str] = []
        self._undecidable_variant_ids: list[str] = []

    def record_decidable(self, variant_id: str, emitted: int, corrected: int) -> None:
        self.n_decidable += 1
        if corrected == emitted:
            return
        self.n_emitted_ne_corrected += 1
        if len(self._diff_variant_ids) < _MAX_EXAMPLE_VARIANT_IDS:
            self._diff_variant_ids.append(variant_id)
        if corrected < emitted:
            self.inflated += 1
        else:
            self.deflated += 1

        if emitted > 0 and corrected == 0:
            self.to_no_call += 1
            return
        emitted_points = _isolated_points(self.criterion, emitted)
        corrected_points = _isolated_points(self.criterion, corrected)
        if self.criterion == "PP3" and _crosses_to_lp(corrected_points) and not _crosses_to_lp(emitted_points):
            self.to_lp += 1
        elif self.criterion == "BP4" and _crosses_to_lb(corrected_points) and not _crosses_to_lb(emitted_points):
            self.to_lb += 1

    def record_undecidable(self, variant_id: str) -> None:
        self.n_undecidable += 1
        if len(self._undecidable_variant_ids) < _MAX_EXAMPLE_VARIANT_IDS:
            self._undecidable_variant_ids.append(variant_id)

    def to_dict(self) -> dict:
        return {
            "criterion": self.criterion,
            "n_fired": self.n_fired,
            "n_decidable": self.n_decidable,
            "undecidable": self.n_undecidable,
            "n_emitted_ne_corrected": self.n_emitted_ne_corrected,
            "inflated": self.inflated,
            "deflated": self.deflated,
            "category_flips": {
                "to_LP": self.to_lp,
                "to_LB": self.to_lb,
                "to_no_call": self.to_no_call,
            },
            "example_variant_ids": sorted(self._diff_variant_ids),
            "example_undecidable_variant_ids": sorted(self._undecidable_variant_ids),
        }


def run_probe(records: Iterable[BiasRecord], spec: AggregationSpec) -> dict:
    """Run Probe 2 (emitted-vs-corrected diff) + Probe 3 (decidability) over
    `records` and return the canonical, deterministic report dict (sec
    1.2/1.3/2.3). Reads only `BiasRecord.criteria`'s PP3/BP4 entries + the
    aggregation spec -- no label/benchmark field is read."""
    accumulators = {"PP3": _CriterionAccumulator("PP3"), "BP4": _CriterionAccumulator("BP4")}

    for record in records:
        for criterion in ("PP3", "BP4"):
            entry = record.criteria.get(criterion.lower())
            if entry is None:
                continue
            fired_int, rationale_text = int(entry[0]), str(entry[1])
            if fired_int <= 0:
                continue
            acc = accumulators[criterion]
            acc.n_fired += 1
            try:
                correction = recompute_strength(criterion, rationale_text, spec)
            except AggregationUndecidableError:
                acc.record_undecidable(record.variant_id)
                continue
            acc.record_decidable(record.variant_id, correction.emitted_strength, correction.corrected_strength)

    total_undecidable = sum(acc.n_undecidable for acc in accumulators.values())
    if total_undecidable == 0:
        route = "raptor_side_wrapper"
        rationale = (
            "Probe 3 found undecidable == 0 across all fired PP3/BP4 rows: the observable "
            "rationale output is information-complete, so the RAPTOR-side arm's-length wrapper "
            "(recompute_strength) is the primary correction route (slot 2 sec 3)."
        )
    else:
        route = "upstream_contribution_required_for_undecidable_class"
        rationale = (
            f"Probe 3 found {total_undecidable} undecidable fired PP3/BP4 row(s): the wrapper "
            "cannot be faithful for those rows, so an upstream contribution to bitscopic/BIAS-2015 "
            "is required for the undecidable class (slot 2 sec 3). This task does not adopt or "
            "merge such a fix, and does not alter the pinned BIAS commit or vendored source."
        )

    return {
        "bias_version": spec.bias_version,
        "bias_commit": spec.bias_commit,
        "criteria": {criterion: acc.to_dict() for criterion, acc in accumulators.items()},
        "route_decision": {
            "route": route,
            "undecidable_total": total_undecidable,
            "rationale": rationale,
            "upstream_pr_proposal": (
                "Documented, good-citizen proposal only (not adopted/merged here): fix the dead "
                "`best_score` sentinel in pathogenic_classifiers.py::get_pp3 L944-954 and "
                "benign_classifiers.py::get_bp4 L491-503 so the selection loop reassigns "
                "`best_score` on `a_score > best_score` (matching the correct idiom already used "
                "for a different criterion at get_pm1 L405-433). Adoption is gated on a separate "
                "re-pin + full re-score + re-validation, out of scope for this task."
            ),
        },
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the real-corpus emitted-vs-corrected BP4/PP3 aggregation diff and "
        "decidability over one or more pinned BIAS-2015 output TSVs, and record the "
        "wrapper-vs-upstream correction route decision."
    )
    parser.add_argument("bias_tsv", nargs="+", help="Path(s) to a pinned BIAS-2015 output TSV (18-column contract).")
    parser.add_argument("--output", required=True, help="Path to write the canonical materiality report JSON.")
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG_PATH,
        help=f"Path to the predictor-aggregation spec YAML (default: {_DEFAULT_CONFIG_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    spec = load_aggregation_spec(args.config)

    def _all_records() -> Iterable[BiasRecord]:
        for tsv_path in args.bias_tsv:
            yield from BiasTsvSource(tsv_path).records()

    report = run_probe(_all_records(), spec)

    canonical_json = json.dumps(report, sort_keys=True, indent=2)
    Path(args.output).write_text(canonical_json, encoding="utf-8")
    print(canonical_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
