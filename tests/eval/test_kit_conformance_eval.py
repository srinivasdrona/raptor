"""Conformance-kit wiring for the PRD-06 eval harness (todo: kit-retrofit).

Wires the REAL `raptor.testkit.invariants` (no silent-fallback stub) + two
harness-specific property tests that are candidates for promotion into the kit if
they recur: no-leakage split, and gate-never-PASS-when-thresholds-empty.
"""
from hypothesis import given, settings, strategies as st

from raptor.testkit import invariants
from raptor.eval.split import split_benchmark
from raptor.eval.gate import decide_gate
from raptor.eval.harness import run_eval
from raptor.eval.model import BenchmarkRow, Metrics
from conftest import make_eval_config, make_labeled, evidence_for


def test_kit_determinism():
    """Universal determinism invariant wired to run_eval."""
    variants = [make_labeled(f"v{i}", label=("P" if i % 2 else "B"), submitter_count=3)
                for i in range(10)]
    cfg = make_eval_config()

    def _run(inputs, _store):
        return run_eval(cfg, list(inputs), evidence_for(list(inputs)))

    invariants.assert_determinism(_run, variants, lambda: None, lambda r: r.content_hash())


@settings(max_examples=40)
@given(ids=st.lists(st.integers(0, 10_000), min_size=2, max_size=20, unique=True))
def test_kit_split_is_leakage_free(ids):
    """No-leakage property: train/dev and held-out never share a variant identity."""
    rows = [BenchmarkRow(variant_id=f"v{i}", label="P", variant_class="missense") for i in ids]
    train, holdout = split_benchmark(rows, make_eval_config())
    train_ids = {r.variant_id for r in train}
    holdout_ids = {r.variant_id for r in holdout}
    assert train_ids.isdisjoint(holdout_ids), "split leakage: train ∩ held-out != empty"
    assert train_ids | holdout_ids == {r.variant_id for r in rows}, "split dropped/duplicated a row"


@settings(max_examples=40)
@given(precision=st.floats(0.0, 1.0), recall=st.floats(0.0, 1.0))
def test_kit_gate_never_passes_with_empty_thresholds(precision, recall):
    """Gate-honesty property (GP-9/H13): with thresholds unset, no metric — however
    high — yields PASS or VUS authorization."""
    cfg = make_eval_config(oracle_thresholds={})
    metrics = {"missense": Metrics(precision=precision, recall=recall, concordance=1.0,
                                   counts={}, stratum="missense", gating=True)}
    decision = decide_gate(metrics, cfg)
    assert decision.status != "PASS"
    assert decision.vus_authorized is False
