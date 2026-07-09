"""AC6/AC7/AC9 — end-to-end harness invariants (real assertions, no hollow try/except).

AC6 (H1): labels never reach the evidence path.
AC7 (R-A11): deterministic content hash.
AC9 (GP-9): the report states benchmark version, held-out size, and threshold status.
"""
from raptor.eval.harness import run_eval
from conftest import make_eval_config, make_labeled, evidence_for


def _scenario(n=12):
    # A mix of pathogenic/benign, missense/truncating, enough for a non-empty split.
    variants = []
    for i in range(n):
        label = "P" if i % 2 == 0 else "B"
        vclass = "missense" if i % 3 else "truncating"
        variants.append(make_labeled(f"v{i}", label=label, submitter_count=3, variant_class=vclass))
    return variants


def test_ac6_labels_never_reach_evidence_source():
    """AC6/H1: the harness reads labels ONLY in the benchmark path; the injected
    evidence source is asked for evidence by plain variant_id and never receives a
    label or a LabeledVariant."""
    variants = _scenario()
    src = evidence_for(variants)
    report = run_eval(make_eval_config(), variants, src)  # must not raise
    assert report is not None
    assert src.requested, "harness never consulted the injected evidence source"
    for arg in src.requested:
        assert isinstance(arg, str), f"evidence source received a non-variant_id arg: {arg!r}"
        assert not hasattr(arg, "label"), "a LabeledVariant leaked into the evidence path (H1)"


def test_ac7_determinism():
    """AC7/R-A11: identical pinned inputs -> identical content_hash (run metadata excluded)."""
    variants = _scenario()
    cfg = make_eval_config()
    h1 = run_eval(cfg, variants, evidence_for(variants)).content_hash()
    h2 = run_eval(cfg, list(variants), evidence_for(variants)).content_hash()
    assert h1 == h2


def test_ac9_report_states_required_fields():
    """AC9/GP-9: a result is citable only if it states benchmark version, per-class
    held-out size, metrics, and threshold status (EVAL_PLAN §5)."""
    variants = _scenario()
    report = run_eval(make_eval_config(), variants, evidence_for(variants))
    text = report.render()
    low = text.lower()
    assert "clinvar_2026-07-01" in text, "report omits the benchmark/labels snapshot version"
    assert "held-out" in low or "holdout" in low or "held out" in low, "report omits held-out size"
    # threshold status must be stated; thresholds are unset -> UNVERIFIED
    assert "unverified" in low or "threshold" in low, "report omits threshold status"
