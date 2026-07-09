"""Shared fixtures for PRD-06 eval-harness tests.

Binds tests to the REAL `raptor.eval` public API (not local mocks — a mock would
let the doer diverge from the contract). Because `EvalConfig` is FROZEN (§10.3),
tests never mutate it — they build variants via `make_eval_config(**overrides)`.

Collection fails with `ModuleNotFoundError: raptor.eval` until the doer builds the
module — that is the correct pre-implementation RED state.
"""
from __future__ import annotations

import pytest

# Real contract types (§10.3) — re-exported so `from tests.eval.conftest import X`
# binds to the REAL classes, never a shadow mock.
from raptor.eval.config import EvalConfig
from raptor.eval.model import (
    LabeledVariant,
    BenchmarkRow,
    ImpliedCall,
    Metrics,
    GateDecision,
)

__all__ = [
    "EvalConfig", "LabeledVariant", "BenchmarkRow", "ImpliedCall", "Metrics",
    "GateDecision", "make_eval_config", "make_labeled", "evidence_for",
    "FakeEvidenceSource",
]


def make_eval_config(**overrides) -> EvalConfig:
    """Build a valid, frozen `EvalConfig`; `overrides` replace individual pins
    (so tests never mutate the frozen instance)."""
    base = dict(
        automatable_criteria=["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        tavtigian_points={
            "supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8,
        },
        tavtigian_cutoffs={
            "pathogenic_min": 10, "likely_pathogenic_min": 6,
            "vus_min": 0, "vus_max": 5,
            "likely_benign_max": -1, "benign_max": -7,
        },
        min_count_per_class=10,
        split={"seed": 42, "holdout_fraction": 0.3},
        oracle_thresholds={},  # empty until the Oracle pre-registers (AC5 -> UNVERIFIED)
        labels_snapshot="clinvar_2026-07-01",
    )
    base.update(overrides)
    return EvalConfig(**base)


@pytest.fixture
def valid_eval_config() -> EvalConfig:
    return make_eval_config()


def make_labeled(variant_id, label="P", *, review_status="reviewed", submitter_count=2,
                 source="clinvar", snapshot="clinvar_2026-07-01", raptor_influenced=False,
                 variant_class="missense") -> LabeledVariant:
    return LabeledVariant(
        variant_id=variant_id, label=label, review_status=review_status,
        submitter_count=submitter_count, source=source, snapshot=snapshot,
        raptor_influenced=raptor_influenced, variant_class=variant_class,
    )


class FakeEvidenceSource:
    """Injected evidence double: maps ``variant_id -> [(criterion, strength, direction), …]``.

    Records EVERY argument the harness passes so a test can prove no label ever
    reaches the evidence path (AC6/H1). Enforces at construction that no criterion
    payload carries a label field.
    """

    def __init__(self, data: dict):
        for vid, calls in data.items():
            for call in calls:
                # a criterion call is (criterion, strength, direction) — never a label
                assert not (isinstance(call, dict) and "label" in call), (
                    "AC6/H1 violation: evidence payload carries a label"
                )
        self.data = dict(data)
        self.requested: list = []

    def get_evidence(self, variant_id):
        self.requested.append(variant_id)
        return self.data.get(variant_id, [])


def evidence_for(variants, calls_by_id=None) -> "FakeEvidenceSource":
    """Build a FakeEvidenceSource for a set of (labeled) variants. Default: a
    single fired PM2 (supporting) per variant unless overridden per id."""
    calls_by_id = calls_by_id or {}
    data = {
        v.variant_id: calls_by_id.get(v.variant_id, [("PM2", "supporting", "pathogenic")])
        for v in variants
    }
    return FakeEvidenceSource(data)
