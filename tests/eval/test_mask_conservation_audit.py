from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

try:
    from raptor.eval.mask_clinvar import (
        MaskConfig,
        audit_mask_conservation,
    )
except ImportError:
    MaskConfig = None
    audit_mask_conservation = None

class MockNormalizer:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
    def normalize(self, record: Any) -> str:
        ident = record.get("variant_id") or record.get("VariationID") or str(record)
        return self.mapping.get(ident, ident)

def test_ac_m3_m4_conservation_audit() -> None:
    if audit_mask_conservation is None:
        pytest.fail("implementation missing")
    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=["PS1", "PM5", "PM1", "PP2", "BP1"],
        direct_copy_fallbacks=["PS4", "PP5", "BP6"],
        clinvar_inputs=[
            {"stream": "vcf", "resources": ["PM1", "PP2", "BP1"]},
        ],
        full_resource_paths=[],
        masked_namespace="masked/",
        bias_version="3.0.0"
    )

    holdout_ids = frozenset(["NC_000009.12:100:A:G"])
    normalizer = MockNormalizer({
        "V1": "NC_000009.12:100:A:G",
        "V2": "NC_000009.12:101:A:T",
    })

    # Synthetic masked resources mapping mock resources to domain stats
    # Suppose PM1 domain "D1" had a held-out variant injected that we expect the audit to catch.
    # The audit will recompute domain/gene aggregates from the provided masked ClinVar.

    # We simulate the masked ClinVar having only V2. The expected recomputed aggregate for D1 is X.
    # But the rebuilt resource contains aggregate Y (which includes the held-out V1).

    # Clean case: masked resources strictly reflect only SPDI_SAFE
    masked_resources_clean = {
        "clinvar_records": {
            "vcf": [{
                "variant_id": "V2",
                "domain": "D1",
                "gene": "GENE1",
                "pathogenic": True,
                "missense_pathogenic": True,
                "truncating_pathogenic": False,
            }]
        },
        "comparators": {
            "PM1": {"D1": {"pathogenic_count": 1, "total": 1}},
            "PP2": {"GENE1": {"missense_path": 1, "total": 1}},
            "BP1": {"GENE1": {"trunc_path": 0, "total": 1}}
        }
    }

    report_clean = audit_mask_conservation(masked_resources_clean, holdout_ids, normalizer, config)
    assert report_clean.clean is True
    assert not report_clean.transitive_survivors
    assert not report_clean.aggregate_mismatches

    # Dirty case: A rebuilt resource contains an aggregate that includes V1 (the zero-incidence injected variant)
    masked_resources_dirty = {
        # The masked ClinVar provided to the audit has ONLY V2 (the mask was correct)
        "clinvar_records": {
            "vcf": [{
                "variant_id": "V2",
                "domain": "D1",
                "gene": "GENE1",
                "pathogenic": True,
                "missense_pathogenic": True,
                "truncating_pathogenic": False,
            }]
        },
        # BUT the rebuilt comparator somehow still has V1's contribution (e.g. pathogenic_count=2)
        "comparators": {
            "PM1": {"D1": {"pathogenic_count": 2, "total": 2}}, # Includes the V1 contribution!
            "PP2": {"GENE1": {"missense_path": 1, "total": 1}},
            "BP1": {"GENE1": {"trunc_path": 0, "total": 1}}
        }
    }

    # The audit should independently recompute D1 from the VCF (getting 1/1) and compare it to the resource (2/2).
    report_dirty = audit_mask_conservation(masked_resources_dirty, holdout_ids, normalizer, config)
    assert report_dirty.clean is False
    # AC-M4: flag aggregate mismatches
    assert any("PM1" in mismatch for mismatch in report_dirty.aggregate_mismatches) or report_dirty.aggregate_mismatches

    empty_source_stale_aggregate = {
        "clinvar_records": {"vcf": []},
        "comparators": {
            "PM1": {"D1": {"pathogenic_count": 1, "total": 1}},
        },
    }
    empty_report = audit_mask_conservation(
        empty_source_stale_aggregate,
        holdout_ids,
        normalizer,
        config,
    )
    assert empty_report.clean is False
    assert any("PM1:D1" in item for item in empty_report.aggregate_mismatches)

    # Transitive survivors (e.g. PS1 direct mapping)
    masked_resources_transitive = {
        "clinvar_records": {"vcf": []},
        "comparators": {
            "PS1": {"MUT1": {"variant_id": "V1"}} # Survivor! V1 normalizes to SPDI_HELD
        }
    }
    report_trans = audit_mask_conservation(masked_resources_transitive, holdout_ids, normalizer, config)
    assert report_trans.clean is False
    assert "NC_000009.12:100:A:G" in report_trans.transitive_survivors.get("PS1", [])
