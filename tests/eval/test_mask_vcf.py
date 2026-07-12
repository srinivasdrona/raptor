from __future__ import annotations

from pathlib import Path

import pytest

from raptor.eval.mask_vcf import VcfMaskError, mask_tsc_holdout_from_vcf


def _canonicalize(accession: str, position: int, ref: str, alt: str) -> str:
    return f"{accession}:{position - 1}:{ref}:{alt}"


def test_stream_mask_preserves_non_tsc_and_symbolic_rows_byte_for_byte(tmp_path: Path) -> None:
    source = tmp_path / "clinvar.vcf"
    output = tmp_path / "masked" / "clinvar.vcf"
    non_tsc = b"1\t100\t1\tA\tG\t.\t.\tX=1\r\n"
    symbolic = b"chr9\t101\t2\tA\t<DEL>\t.\t.\tX=2\n"
    heldout = b"9\t102\t3\tC\tT\t.\t.\tX=3\n"
    survivor = b"NC_000016.10\t103\t4\tG\tA\t.\t.\tX=4\n"
    source.write_bytes(
        b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        + non_tsc
        + symbolic
        + heldout
        + survivor
    )

    ledger = mask_tsc_holdout_from_vcf(
        source,
        output,
        frozenset({"NC_000009.12:101:C:T"}),
        _canonicalize,
    )

    masked = output.read_bytes()
    assert non_tsc in masked
    assert symbolic in masked
    assert heldout not in masked
    assert survivor in masked
    assert ledger.input_records == 4
    assert ledger.output_records == 3
    assert ledger.target_records_normalized == 2
    assert ledger.symbolic_target_records_preserved == 1
    assert ledger.matched_records_removed == 1
    assert ledger.matched_holdout_identities == ("NC_000009.12:101:C:T",)


def test_stream_mask_fails_on_partial_multiallelic_match(tmp_path: Path) -> None:
    source = tmp_path / "clinvar.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr16\t201\t5\tA\tC,G\t.\t.\tX=5\n",
        encoding="ascii",
    )

    with pytest.raises(VcfMaskError, match="only partly held out"):
        mask_tsc_holdout_from_vcf(
            source,
            tmp_path / "masked.vcf",
            frozenset({"NC_000016.10:200:A:C"}),
            _canonicalize,
        )


def test_stream_mask_never_overwrites_source(tmp_path: Path) -> None:
    source = tmp_path / "clinvar.vcf"
    source.write_text("##fileformat=VCFv4.2\n", encoding="ascii")

    with pytest.raises(VcfMaskError, match="must differ"):
        mask_tsc_holdout_from_vcf(source, source, frozenset(), _canonicalize)
