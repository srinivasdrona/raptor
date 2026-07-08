"""Conformance-kit wiring for the PRD-02 ingestion pipeline (todo: kit-retrofit).

Wires the universal invariants (`raptor.testkit.invariants`) to `run_ingest`.
Same kit as the scorer — proving the invariants are reused across modules, not
re-authored. (Ingestion's fail-loud/no-state-change on checksum breaches is
covered by the module's native tests; here we wire conservation/determinism/
grounding through an injected fake normalizer.)
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from raptor.kb.store import KBStore
from raptor.testkit import invariants
from raptor.ingest.config import IngestConfig, GeneConfig
from raptor.ingest.model import RawVariant
from raptor.ingest.pipeline import run_ingest
from conftest import FakeNormalizer  # locked ingest test double


def _cfg():
    return IngestConfig(
        genes=["TSC1", "TSC2"], assembly="GRCh38", assembly_patch="p14", mane_release="1.4",
        normalizer={"tool": "fake", "version": "1.0"},
        clinvar_snapshot_id="s", clinvar_snapshot_date="d", clinvar_snapshot_file_checksum="c",
        reference_checksums={},
        gene_configs={
            "TSC1": GeneConfig("NC_000009.12", "NM_000368.5", "NP_000359.2"),
            "TSC2": GeneConfig("NC_000016.10", "NM_000548.5", "NP_000539.2"),
        },
    )


class _Reader:
    def __init__(self, variants):
        self._variants = variants

    def __iter__(self):
        return iter(self._variants)


def _raw(i, chrom="NC_000016.10", gene="TSC2"):
    return RawVariant(
        chromosome=chrom, position=1000 + i, ref="A", alt="T", gene=gene,
        variation_id=str(i), snapshot_id="s1", snapshot_date="d1",
        source_file_checksum="c1", row_locator=str(i), raw_source_value=f"raw{i}",
    )


def _fake_for(variants):
    fake = FakeNormalizer()
    for i, v in enumerate(variants):
        if i % 3 == 0:  # deterministically route a subset to manual queue
            fake.manual_queue_coords.add(f"{v.chromosome}:{v.position}:{v.ref}:{v.alt}")
    return fake


def _run(inputs, store):
    items = list(inputs)
    return run_ingest(_cfg(), _Reader(items), _fake_for(items), store)


def _store():
    return KBStore(":memory:")


@st.composite
def _distinct_variants(draw):
    n = draw(st.integers(min_value=0, max_value=6))
    return [_raw(i) for i in range(n)]


@settings(max_examples=30)
@given(variants=_distinct_variants())
def test_conservation(variants):
    invariants.assert_conservation(
        _run, variants, _store, lambda r, s: r.total_normalized + r.total_manual_queue
    )


@settings(max_examples=20)
@given(variants=_distinct_variants())
def test_determinism(variants):
    invariants.assert_determinism(_run, variants, _store, lambda r: r.content_hash())


def test_grounding():
    variants = [_raw(i) for i in range(5)]
    store = _store()
    try:
        _run(variants, store)
        invariants.assert_grounding(store, [
            ("variant_source_refs", "variant_id", "source_ref_id"),
            ("manual_queue", "mq_id", "source_ref_id"),
        ])
    finally:
        store.close()
