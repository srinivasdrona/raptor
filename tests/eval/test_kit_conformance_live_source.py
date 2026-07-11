from __future__ import annotations

import pytest

import test_live_source as live


def test_live_source_preflight_is_deterministic(tmp_path) -> None:
    manifest = [{
        "variant_id": "NC_000009.12:100:A:G",
        "vcf_key": "chr9:101:A:G",
        "accession": "NC_000009.12",
        "contig": "chr9",
    }]
    first = live._source(
        tmp_path / "first",
        bias_rows=[{"criteria": {"pm2": (1, "gnomAD absent")}}],
        manifest_rows=manifest,
    )
    second = live._source(
        tmp_path / "second",
        bias_rows=[{"criteria": {"pm2": (1, "gnomAD absent")}}],
        manifest_rows=manifest,
    )
    assert first.get_evidence("NC_000009.12:100:A:G") == second.get_evidence(
        "NC_000009.12:100:A:G"
    )


def test_live_source_conserves_one_outcome_per_manifest_identity(tmp_path) -> None:
    source = live._source(
        tmp_path,
        bias_rows=[{"criteria": {}}],
        manifest_rows=[{
            "variant_id": "NC_000009.12:100:A:G",
            "vcf_key": "chr9:101:A:G",
            "accession": "NC_000009.12",
            "contig": "chr9",
        }],
    )
    assert source.variant_ids == ("NC_000009.12:100:A:G",)
