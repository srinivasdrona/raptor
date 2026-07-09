"""Universal, executable conformance invariants for RAPTOR data pipelines.

Higher-order assertions generic over a pipeline. A module wires them by
providing thin adapters — a ``run(inputs, store) -> report`` callable, a
``store_factory() -> fresh store``, and small accessors — in its
``test_kit_conformance.py``. Each function raises ``AssertionError`` with a
message naming the violated invariant + the governing risk id.

Invariants (the universal set; new classes are added here once and then apply to
every module that wires the kit):
- conservation (R-A10): every input yields exactly one durable, accounted outcome.
- grounding (GP-9): every emitted record resolves to a real ``source_ref``.
- determinism (R-A11): identical inputs → identical ``content_hash``.
- fail-loud-propagation: a source-contract/reproducibility breach RAISES through
  the entry point (never swallowed into a per-record outcome).
- no-state-change-on-failure: ANY failed run leaves published state byte-identical.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence


def assert_conservation(
    run: Callable[[Sequence[Any], Any], Any],
    inputs: Iterable[Any],
    store_factory: Callable[[], Any],
    count_accounted: Callable[[Any, Any], int],
) -> None:
    """R-A10: no silent drops. ``count_accounted(report, store)`` must equal the
    number of inputs — every input maps to exactly one durable outcome."""
    items = list(inputs)
    store = store_factory()
    try:
        report = run(items, store)
        n = count_accounted(report, store)
        assert n == len(items), (
            f"conservation violated (R-A10): {n} accounted outcomes != {len(items)} inputs "
            "— an input was silently dropped or double-counted"
        )
    finally:
        _close(store)


def assert_grounding(store: Any, links: Sequence[tuple[str, str, str]]) -> None:
    """GP-9: every row in each ``(table, id_col, source_ref_col)`` carries a
    non-null ``source_ref_id`` that resolves in ``source_refs``."""
    conn = store.conn
    for table, id_col, ref_col in links:
        for rid, ref in conn.execute(f"SELECT {id_col}, {ref_col} FROM {table}").fetchall():
            assert ref is not None, f"grounding violated (GP-9): {table}.{id_col}={rid!r} has null {ref_col}"
            hit = conn.execute(
                "SELECT 1 FROM source_refs WHERE source_ref_id = ?", (ref,)
            ).fetchone()
            assert hit is not None, (
                f"grounding violated (GP-9): {table}.{id_col}={rid!r} {ref_col}={ref!r} "
                "does not resolve in source_refs"
            )


def assert_determinism(
    run: Callable[[Sequence[Any], Any], Any],
    inputs: Iterable[Any],
    store_factory: Callable[[], Any],
    content_hash: Callable[[Any], str],
) -> None:
    """R-A11: two runs on identical inputs (separate fresh stores) produce an
    identical deterministic-content hash (run metadata excluded)."""
    items = list(inputs)
    s1, s2 = store_factory(), store_factory()
    try:
        h1 = content_hash(run(items, s1))
        h2 = content_hash(run(list(items), s2))
        assert h1 == h2, (
            "determinism violated (R-A11): identical inputs produced different content_hash "
            f"({h1[:12]}… != {h2[:12]}…)"
        )
    finally:
        _close(s1)
        _close(s2)


def assert_fail_loud_propagates(
    run: Callable[[Sequence[Any], Any], Any],
    breaching_inputs: Iterable[Any],
    store_factory: Callable[[], Any],
) -> None:
    """A source-contract / reproducibility breach must RAISE through the entry
    point — never be swallowed into a per-record manual-queue outcome."""
    store = store_factory()
    try:
        if _raises(run, list(breaching_inputs), store):
            return
        raise AssertionError(
            "fail-loud violated: a contract/reproducibility breach did not raise "
            "(it was swallowed instead of propagating)"
        )
    finally:
        _close(store)


def assert_no_state_change_on_failure(
    run: Callable[[Sequence[Any], Any], Any],
    failing_inputs: Iterable[Any],
    store_factory: Callable[[], Any],
    state_hash: Callable[[Any], str],
) -> None:
    """ANY failed run must leave published state byte-identical (a failed run is a
    no-op). Retires the whole 'raise-after-mutate' class."""
    store = store_factory()
    try:
        before = state_hash(store)
        assert _raises(run, list(failing_inputs), store), (
            "no-state-change-on-failure: expected the input to raise, but the run succeeded"
        )
        after = state_hash(store)
        assert after == before, (
            "no-state-change-on-failure violated: a FAILED run mutated published state "
            f"({before[:12]}… -> {after[:12]}…)"
        )
    finally:
        _close(store)


def assert_never_emits(
    classify: Callable[[Any], Any],
    protected_output: Any,
    out_of_vocabulary_inputs: Iterable[Any],
    *,
    label: str = "",
) -> None:
    """C1 (strict-canonical-whitelist validation): a domain classifier/validator must
    NEVER emit ``protected_output`` for a known out-of-vocabulary input. Retires the
    normalization/whitelist bug class (accept-then-harden). Example: a variant-consequence
    classifier must never return ``"missense"`` for a non-substitution token (del/dup/
    unknown-aa/stop-loss)."""
    offenders = [x for x in out_of_vocabulary_inputs if classify(x) == protected_output]
    tag = f" [{label}]" if label else ""
    assert not offenders, (
        f"strict-whitelist violated (C1){tag}: classifier emitted {protected_output!r} for "
        f"out-of-vocabulary input(s) {offenders!r} -- validate against a canonical set, "
        "never accept-then-harden"
    )


def assert_no_label_leak(
    run_capturing: Callable[[], Iterable[Any]],
    label_values: Iterable[str],
    *,
    label: str = "",
) -> None:
    """C2 (H1 anti-circularity / label-blindness): no known label value may reach a
    scorer-side object. ``run_capturing()`` runs the pipeline and returns EVERY object
    handed to the scorer/normalizer path; assert none of them carries any ``label_values``
    string in any field (via ``repr``). Retires the trace-cribbing/label-leak class
    (e.g. a label smuggled through a ``raw_source_value`` provenance field)."""
    values = list(label_values)
    tag = f" [{label}]" if label else ""
    for obj in run_capturing():
        blob = repr(obj)
        for lv in values:
            assert lv not in blob, (
                f"label-blindness violated (C2/H1){tag}: label {lv!r} reached a scorer-side "
                f"object handed to the identity/normalizer path: {obj!r}"
            )


def _raises(run: Callable[[Sequence[Any], Any], Any], items: Sequence[Any], store: Any) -> bool:
    try:
        run(items, store)
        return False
    except Exception:
        return True


def _close(store: Any) -> None:
    close = getattr(store, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
