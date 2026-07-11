from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path

import pytest

from raptor.eval.config import load_config as load_eval_config
from raptor.eval.lineage_audit import LineageGateError
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.contract import BiasOutputContract
from raptor.scorer.parse import UnmappedStrengthError


def _api():
    try:
        from raptor.eval.live_source import (
            BiasEvidenceSource,
            ConfigConsistencyError,
            ExactSetMismatchError,
            MalformedManifestError,
            UnknownVariantError,
        )
    except ImportError as exc:
        pytest.fail(f"live evidence source is not implemented: {exc}")
    return locals()


class FakeCanonicalNormalizer:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def normalize(self, chromosome, position, ref, alt, accession):
        key = (chromosome, position, ref, alt, accession)
        if key in self.mapping:
            value = self.mapping[key]
            if isinstance(value, Exception):
                raise value
            return value
        return f"{accession}:{position - 1}:{ref}:{alt}"


def _manifest(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rationale(criteria) -> str:
    nested = {"pvs": {}, "ps": {}, "pm": {}, "pp": {}, "ba": {}, "bs": {}, "bp": {}}
    for criterion, value in criteria.items():
        family = next(prefix for prefix in nested if criterion.lower().startswith(prefix))
        nested[family][criterion.lower()] = list(value)
    return json.dumps(nested, sort_keys=True)


def _bias_tsv(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=BiasOutputContract.REQUIRED_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for index, row in enumerate(rows):
            payload = {
                "chromosome": row.get("chromosome", "chr9"),
                "position": str(row.get("position", 101 + index)),
                "refAllele": row.get("ref", "A"),
                "altAllele": row.get("alt", "G"),
                "variantType": row.get("variant_type", "SNV"),
                "consequence": "missense_variant",
                "acmgClassification": row.get("classification", "uncertain"),
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
                "rationale": _rationale(row.get("criteria", {})),
            }
            writer.writerow(payload)


def _configs():
    return (
        load_eval_config("configs/eval/tsc2.yaml"),
        load_scorer_config("configs/acmg/tsc.yaml"),
    )


def _source(tmp_path, *, bias_rows, manifest_rows, normalizer=None, eval_config=None, scorer_config=None):
    api = _api()
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifest_path = tmp_path / "manifest.jsonl"
    bias_path = tmp_path / "bias.tsv"
    _manifest(manifest_path, manifest_rows)
    _bias_tsv(bias_path, bias_rows)
    current_eval, current_scorer = _configs()
    return api["BiasEvidenceSource"](
        bias_path,
        manifest_path,
        eval_config or current_eval,
        scorer_config or current_scorer,
        normalizer or FakeCanonicalNormalizer(),
    )


def test_ac_b1_b2_fired_evidence_only_and_combined_call_ignored(tmp_path: Path) -> None:
    manifest = [{
        "variant_id": "NC_000009.12:100:A:G",
        "vcf_key": "chr9:101:A:G",
        "accession": "NC_000009.12",
        "contig": "chr9",
    }]
    first = _source(
        tmp_path / "first",
        bias_rows=[{
            "classification": "pathogenic",
            "criteria": {"pvs1": (4, "LoF"), "pm2": (1, "absent")},
        }],
        manifest_rows=manifest,
    )
    second = _source(
        tmp_path / "second",
        bias_rows=[{
            "classification": "benign",
            "criteria": {"pvs1": (4, "LoF"), "pm2": (1, "absent")},
        }],
        manifest_rows=manifest,
    )
    expected = {
        ("PVS1", "very_strong", "pathogenic"),
        ("PM2", "supporting", "pathogenic"),
    }
    assert set(first.get_evidence("NC_000009.12:100:A:G")) == expected
    assert list(first.get_evidence("NC_000009.12:100:A:G")) == list(
        second.get_evidence("NC_000009.12:100:A:G")
    )


def test_ac_b3_exact_set_breaches_are_structured_and_preflight_fatal(tmp_path: Path) -> None:
    api = _api()
    manifest = [
        {"variant_id": "NC_000009.12:100:A:G", "vcf_key": "chr9:101:A:G", "accession": "NC_000009.12", "contig": "chr9"},
        {"variant_id": "NC_000009.12:101:C:T", "vcf_key": "chr9:102:C:T", "accession": "NC_000009.12", "contig": "chr9"},
    ]
    with pytest.raises(api["ExactSetMismatchError"]) as exc:
        _source(tmp_path, bias_rows=[{"criteria": {}}], manifest_rows=manifest)
    assert exc.value.sets_by_kind["missing_holdout_row"] == {"NC_000009.12:101:C:T"}

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    with pytest.raises(api["MalformedManifestError"]):
        _source(
            malformed,
            bias_rows=[{"criteria": {}}],
            manifest_rows=[{"variant_id": "NC_000009.12:100:A:G", "extra": "field"}],
        )

    invalid_json_dir = tmp_path / "invalid-json"
    invalid_json_dir.mkdir()
    manifest_path = invalid_json_dir / "manifest.jsonl"
    bias_path = invalid_json_dir / "bias.tsv"
    manifest_path.write_text("{not-json}\n", encoding="utf-8")
    _bias_tsv(bias_path, [{"criteria": {}}])
    eval_config, scorer_config = _configs()
    with pytest.raises(api["MalformedManifestError"]):
        api["BiasEvidenceSource"](
            bias_path,
            manifest_path,
            eval_config,
            scorer_config,
            FakeCanonicalNormalizer(),
        )


def test_ac_b4_unmapped_strength_and_unknown_variant_fail_loud(tmp_path: Path) -> None:
    api = _api()
    source = _source(
        tmp_path,
        bias_rows=[{"criteria": {"pvs1": (999, "unknown strength")}}],
        manifest_rows=[{
            "variant_id": "NC_000009.12:100:A:G",
            "vcf_key": "chr9:101:A:G",
            "accession": "NC_000009.12",
            "contig": "chr9",
        }],
    )
    with pytest.raises(UnmappedStrengthError):
        list(source.get_evidence("NC_000009.12:100:A:G"))
    with pytest.raises(api["UnknownVariantError"]):
        list(source.get_evidence("NC_000009.12:999:A:G"))


def test_ac_b5_config_parity_is_preflight_guard(tmp_path: Path) -> None:
    api = _api()
    eval_config, scorer_config = _configs()
    drifty = replace(
        scorer_config,
        included_criteria=tuple(scorer_config.included_criteria) + ("PS3",),
    )
    with pytest.raises(api["ConfigConsistencyError"]):
        _source(
            tmp_path,
            bias_rows=[{"criteria": {}}],
            manifest_rows=[{
                "variant_id": "NC_000009.12:100:A:G",
                "vcf_key": "chr9:101:A:G",
                "accession": "NC_000009.12",
                "contig": "chr9",
            }],
            eval_config=eval_config,
            scorer_config=drifty,
        )


def test_ac_b7_canonical_indel_join_and_duplicate_collapse(tmp_path: Path) -> None:
    api = _api()
    canonical = "NC_000009.12:100::T"
    manifest = [{
        "variant_id": canonical,
        "vcf_key": "chr9:100:A:AT",
        "accession": "NC_000009.12",
        "contig": "chr9",
    }]
    mapping = {
        ("chr9", 100, "A", "AT", "NC_000009.12"): canonical,
        ("chr9", 101, "C", "CT", "NC_000009.12"): canonical,
    }
    source = _source(
        tmp_path / "one",
        bias_rows=[{"position": 101, "ref": "C", "alt": "CT", "criteria": {}}],
        manifest_rows=manifest,
        normalizer=FakeCanonicalNormalizer(mapping),
    )
    assert source.get_evidence(canonical) == ()

    with pytest.raises(api["ExactSetMismatchError"]) as exc:
        _source(
            tmp_path / "duplicate",
            bias_rows=[
                {"position": 100, "ref": "A", "alt": "AT", "criteria": {}},
                {"position": 101, "ref": "C", "alt": "CT", "criteria": {}},
            ],
            manifest_rows=manifest,
            normalizer=FakeCanonicalNormalizer(mapping),
        )
    assert canonical in exc.value.sets_by_kind["duplicate_canonical_bias_row"]


def test_ac_b8_lineage_gate_blocks_leaky_and_allows_clean(tmp_path: Path) -> None:
    manifest = [{
        "variant_id": "NC_000009.12:100:A:G",
        "vcf_key": "chr9:101:A:G",
        "accession": "NC_000009.12",
        "contig": "chr9",
    }]
    with pytest.raises(LineageGateError):
        _source(
            tmp_path / "leaky",
            bias_rows=[{"criteria": {"pm5": (2, "ClinVar comparator")}}],
            manifest_rows=manifest,
        )
    clean = _source(
        tmp_path / "clean",
        bias_rows=[{"criteria": {"pm2": (1, "gnomAD absent")}}],
        manifest_rows=manifest,
    )
    assert clean.get_evidence("NC_000009.12:100:A:G") == (
        ("PM2", "supporting", "pathogenic"),
    )


def test_ac_b7_reference_failure_is_fatal(tmp_path: Path) -> None:
    manifest = [{
        "variant_id": "NC_000009.12:100:A:G",
        "vcf_key": "chr9:101:A:G",
        "accession": "NC_000009.12",
        "contig": "chr9",
    }]
    normalizer = FakeCanonicalNormalizer({
        ("chr9", 101, "A", "G", "NC_000009.12"): ValueError("reference mismatch"),
    })
    with pytest.raises(ValueError, match="reference mismatch"):
        _source(
            tmp_path,
            bias_rows=[{"criteria": {}}],
            manifest_rows=manifest,
            normalizer=normalizer,
        )
