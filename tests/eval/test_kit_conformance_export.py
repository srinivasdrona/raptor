"""Testkit conformance for live eval export (Task A).

Wires raptor.testkit.invariants where they fit without semantic distortion.
"""
from typing import Any, Sequence

from raptor.testkit.invariants import (
    assert_conservation,
    assert_determinism,
    assert_fail_loud_propagates,
)
from raptor.eval.export import (
    ExportConfig,
    export_holdout,
)

class _FakeReference:
    def fetch(self, contig: str, start: int, end: int) -> str:
        # Dummy sequence that won't trigger ReferenceMismatch for these tests
        return ("ACGT" * 100)[start:end]

def _run_export(inputs: Sequence[Any], store: Any) -> Any:
    config = ExportConfig(
        assembly="GRCh38",
        contigs=[{"accession": "NC_1", "vcf_contig": "chr1"}]
    )
    return export_holdout(inputs, _FakeReference(), config)

def _store_factory() -> Any:
    return None

def _count_accounted(report: Any, store: Any) -> int:
    return report.conservation_count

def _content_hash(report: Any) -> str:
    return report.vcf_hash + report.manifest_hash

def test_kit_conservation():
    """Conservation/bijection: every input yields exactly one accounted outcome."""
    inputs = ["NC_1:1:C:T", "NC_1:3:T:A"]
    assert_conservation(_run_export, inputs, _store_factory, _count_accounted)

def test_kit_determinism():
    """Determinism: identical inputs -> identical content_hash."""
    inputs = ["NC_1:1:C:T", "NC_1:3:T:A"]
    assert_determinism(_run_export, inputs, _store_factory, _content_hash)

def test_kit_fail_loud_propagates():
    """Fail-loud-propagation: ref-mismatch, contig-start, collision must raise."""
    # Collision (bijection breach)
    inputs_collision = ["NC_1:1:C:T", "NC_1:1:C:T"]
    assert_fail_loud_propagates(_run_export, inputs_collision, _store_factory)

    # Contig-start breach (pure indel at pos0=0)
    inputs_contig_start = ["NC_1:0::A"]
    assert_fail_loud_propagates(_run_export, inputs_contig_start, _store_factory)

    # Ref-mismatch breach
    inputs_ref_mismatch = ["NC_1:1:A:T"] # The ref at 1 is C, not A
    assert_fail_loud_propagates(_run_export, inputs_ref_mismatch, _store_factory)
