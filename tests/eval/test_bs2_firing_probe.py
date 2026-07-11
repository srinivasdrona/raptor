from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

from raptor.scorer.contract import BiasOutputContract


def _api():
    try:
        from scripts.probe_bs2_firings import main
    except ImportError as exc:
        pytest.fail(f"BS2 firing probe is not implemented: {exc}")
    return main


def _rationale(*, bs2: tuple[int, str] = (0, ""), pvs1: tuple[int, str] = (0, "")) -> str:
    return json.dumps(
        {
            "pvs": {"pvs1": list(pvs1)},
            "ps": {},
            "pm": {},
            "pp": {},
            "ba": {},
            "bs": {"bs2": list(bs2)},
            "bp": {},
        },
        sort_keys=True,
    )


def _write_bias_tsv(path: Path) -> None:
    rows = [
        {
            "chromosome": "chr9",
            "position": "1",
            "refAllele": "A",
            "altAllele": "G",
            "variantType": "SNV",
            "consequence": "missense_variant",
            "acmgClassification": "uncertain",
            "alleleFreq": "",
            "hgvsg": "",
            "hgvsc": "",
            "hgvsp": "",
            "aaChange": "",
            "geneName": "TSC1",
            "pubmedIds": "",
            "associatedDiseases": "tuberous sclerosis",
            "dbSnpids": "",
            "transcript": "NM_000368.4",
            "rationale": _rationale(
                bs2=(
                    3,
                    "BS2: Observed in 6 healthy individuals for autosomal dominant disease "
                    "tuberous sclerosis exceeding LOEUF(TSC1:0.11800)-based threshold (6).",
                )
            ),
        },
        {
            "chromosome": "chr16",
            "position": "2",
            "refAllele": "C",
            "altAllele": "T",
            "variantType": "SNV",
            "consequence": "stop_gained",
            "acmgClassification": "uncertain",
            "alleleFreq": "",
            "hgvsg": "",
            "hgvsc": "",
            "hgvsp": "",
            "aaChange": "",
            "geneName": "TSC2",
            "pubmedIds": "",
            "associatedDiseases": "tuberous sclerosis",
            "dbSnpids": "",
            "transcript": "NM_000548.4",
            "rationale": _rationale(
                bs2=(3, "BS2: Observed in 3 healthy individuals."),
                pvs1=(4, "PVS1: Null variant."),
            ),
        },
        {
            "chromosome": "chr16",
            "position": "3",
            "refAllele": "G",
            "altAllele": "A",
            "variantType": "SNV",
            "consequence": "missense_variant",
            "acmgClassification": "uncertain",
            "alleleFreq": "",
            "hgvsg": "",
            "hgvsc": "",
            "hgvsp": "",
            "aaChange": "",
            "geneName": "TSC2",
            "pubmedIds": "",
            "associatedDiseases": "tuberous sclerosis",
            "dbSnpids": "",
            "transcript": "NM_000548.4",
            "rationale": _rationale(),
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=BiasOutputContract.REQUIRED_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def test_ac_b1_probe_reads_real_bias_contract_and_is_deterministic(tmp_path: Path) -> None:
    main = _api()
    input_path = tmp_path / "bias.tsv"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    _write_bias_tsv(input_path)

    assert main([str(input_path), "--output", str(first_path)]) == 0
    assert main([str(input_path), "--output", str(second_path)]) == 0
    first = json.loads(first_path.read_text(encoding="utf-8"))
    second = json.loads(second_path.read_text(encoding="utf-8"))

    assert first == second
    assert first["total_rows"] == 3
    assert first["total_bs2_firings"] == 2
    assert first["gene_distribution"] == {"TSC1": 1, "TSC2": 1}
    assert first["pathogenic_cofires"] == {"PVS1": 1}
    assert first["source_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert first["signals"]["healthy_individual_counts"] == [3, 6]


@pytest.mark.skipif(
    not os.environ.get("RAPTOR_BIAS_OUTPUT_TSV"),
    reason="RAPTOR_BIAS_OUTPUT_TSV not set",
)
def test_ac_b1_real_data_reconciles_to_34(tmp_path: Path) -> None:
    main = _api()
    output = tmp_path / "real.json"
    assert main([os.environ["RAPTOR_BIAS_OUTPUT_TSV"], "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["total_bs2_firings"] == 34


def test_ac_b2_b3_b6_authority_memo_is_source_cited_and_deferred() -> None:
    memo_path = Path("docs/reference/bs2-tsc-penetrance-mosaicism-review.md")
    if not memo_path.is_file():
        pytest.fail(f"{memo_path} is not implemented")
    content = memo_path.read_text(encoding="utf-8")
    lower = content.lower()

    assert "benign_classifiers.get_bs2" in content
    assert "clinvar" not in lower or "label-independent" in lower
    assert "clingen" in lower and ("vcep" in lower or "svi" in lower)
    for required_gap in ("penetrance", "age", "mosaic"):
        assert required_gap in lower
    assert "verdict: insufficient for automated bs2" in lower
    assert "decision: deferred" in lower
