"""Conformance-kit wiring for the PRD-01 scorer (todo: kit-retrofit).

Wires the universal invariants (`raptor.testkit.invariants`) to `run_scorer`, so
the recurring bug classes (silent drop, ungrounded, non-determinism, swallowed
fail-loud, failed-run state mutation) are enforced generically — reusing the kit,
not re-deriving per feature. New universal invariants added to the kit apply here
automatically.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from raptor.kb.store import KBStore
from raptor.testkit import invariants
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.pipeline import run_scorer


def _cfg():
    return ScorerConfig(
        bias_version="3.0.0", bias_data_version="2026.03.01",
        included_criteria=["PVS1", "PM2", "PM4"],
        strength_map={"1": "supporting", "2": "moderate", "3": "strong",
                      "4": "very_strong", "5": "stand_alone"},
        acmg_criteria={
            "PVS1": {"direction": "pathogenic",
                     "strength_vocab": ["very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["moderate", "supporting"]},
            "PM4": {"direction": "pathogenic", "strength_vocab": ["moderate"]},
        },
        edge_cases={"splice_region": True, "non_mane_transcript": True},
        genes={"TSC2": "NM_000548.5"}, licensing={"revel": "research"},
    )


class _Source:
    def __init__(self, records):
        self._records = records

    def records(self, run=None):
        return self._records


def _rec(vid, criteria, gene="TSC2", consequence="missense_variant", transcript="NM_000548.5"):
    return BiasRecord(
        chromosome="chr16", position=100, ref_allele="A", alt_allele="T",
        variant_id=vid, variant_type="SNV", consequence=consequence,
        acmg_classification="uncertain", gene_name=gene, transcript=transcript,
        criteria=criteria, provenance={"source": "bias"},
    )


def _run(inputs, store):
    return run_scorer(_cfg(), _Source(list(inputs)), store)


def _store():
    return KBStore(":memory:")


@st.composite
def _distinct_records(draw):
    """Valid, in-scope BiasRecords with DISTINCT variant_ids (no fail-loud dup)
    spanning the cardinality boundary (0, 1, many) and mixed outcomes
    (scored / no_evidence)."""
    n = draw(st.integers(min_value=0, max_value=6))
    out = []
    for i in range(n):
        crit = draw(st.sampled_from(["pm2", "pvs1", "pm4"]))
        strength = draw(st.sampled_from([0, 1, 2, 3]))  # 0 -> no_evidence
        out.append(_rec(f"chr16:{1000 + i}:A:T", {crit: (strength, "x")}))
    return out


@settings(max_examples=30)
@given(records=_distinct_records())
def test_conservation(records):
    invariants.assert_conservation(_run, records, _store, lambda r, s: len(r.variant_outcomes))


@settings(max_examples=20)
@given(records=_distinct_records())
def test_determinism(records):
    invariants.assert_determinism(_run, records, _store, lambda r: r.content_hash())


def test_grounding():
    records = [
        _rec("chr16:1:A:T", {"pm2": (1, "x")}),                        # scored
        _rec("chr16:2:C:G", {"pm2": (0, ""), "pvs1": (0, "")}),        # no_evidence
        _rec("chr9:3:A:T", {"pm2": (1, "x")}, gene="TSC1"),            # out-of-scope -> manual
    ]
    store = _store()
    try:
        _run(records, store)
        invariants.assert_grounding(store, [
            ("evidence", "evidence_id", "source_ref_id"),
            ("manual_queue", "mq_id", "source_ref_id"),
        ])
    finally:
        store.close()


def test_fail_loud_and_no_state_change_on_duplicate():
    dup = [
        _rec("chr16:9:A:T", {"pm4": (2, "PM4_moderate")}),
        _rec("chr16:9:A:T", {"pm2": (1, "x")}),  # duplicate variant_id -> source-contract breach
    ]
    invariants.assert_fail_loud_propagates(_run, dup, _store)
    invariants.assert_no_state_change_on_failure(_run, dup, _store, lambda s: s.published_state_hash())
