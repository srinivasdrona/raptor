from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import hashlib

import pytest

try:
    from raptor.eval.mask_clinvar import (
        HoldoutIdentityError,
        MaskAmbiguityError,
        MaskConfig,
        MaskConfigError,
        MaskLedger,
        MaskResult,
        MaskReferenceError,
        load_holdout_identities,
        load_mask_config,
        mask_clinvar_source,
    )
except ImportError:
    HoldoutIdentityError = Exception
    MaskAmbiguityError = Exception
    MaskConfigError = Exception
    MaskReferenceError = Exception
    MaskConfig = None
    load_holdout_identities = None
    load_mask_config = None
    mask_clinvar_source = None

class MockNormalizer:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
    def normalize(self, record: Any) -> str:
        # Simplistic mock normalization
        ident = record.get("variant_id") or record.get("VariationID") or str(record)
        if ident not in self.mapping and "fail" in ident:
            raise ValueError("un-normalizable")
        return self.mapping.get(ident, ident)


def test_ac_m1_m2_exact_set_conservation(tmp_path: Path) -> None:
    if mask_clinvar_source is None:
        pytest.fail("implementation missing")
    # Setup mock config
    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=["PS1", "PM5", "PM1", "PP2", "BP1"],
        direct_copy_fallbacks=["PS4", "PP5", "BP6"],
        clinvar_inputs=[{"stream": "variant_summary", "resources": ["PS4"]}],
        full_resource_paths=[],
        masked_namespace="masked/",
        bias_version="3.0.0"
    )

    # Synthetic holdout ids (canonical SPDI)
    holdout_ids = frozenset(["NC_000009.12:100:A:G", "NC_000016.10:200:C:T"])

    # Synthetic ClinVar stream (dicts for simplicity)
    # 3 records: one held-out, two non-held-out
    clinvar_records = {
        "variant_summary": [
            {"VariationID": "V1", "data": "keep"},
            {"VariationID": "V2", "data": "remove"},  # maps to SPDI_1
            {"VariationID": "V3", "data": "keep_2"},
        ]
    }

    normalizer = MockNormalizer({
        "V1": "NC_000009.12:99:A:G",
        "V2": "NC_000009.12:100:A:G",
        "V3": "NC_000016.10:201:C:T",
    })

    # Execute
    result = mask_clinvar_source(clinvar_records, holdout_ids, normalizer, config)

    masked_stream = result.masked_streams["variant_summary"]

    # AC-M1: Canonical-SPDI set membership exact-set conservation
    remaining_ids = {normalizer.normalize(r) for r in masked_stream}
    assert remaining_ids.isdisjoint(holdout_ids), "Held-out ID survived in masked stream"

    # AC-M2: No silent row loss (remaining == input_total - matched_removed)
    ledger = result.ledger["variant_summary"]
    assert ledger.input_total == 3
    assert ledger.matched_removed == 1
    assert ledger.remaining == 2
    assert len(masked_stream) == 2

    # Expected exact match based on hand-computed set difference
    expected_remaining_variations = {"V1", "V3"}
    actual_remaining_variations = {r["VariationID"] for r in masked_stream}
    assert actual_remaining_variations == expected_remaining_variations, "Silent row loss or over-removal detected"


def test_ac_m5_direct_copy_own_variant_mask() -> None:
    if mask_clinvar_source is None:
        pytest.fail("implementation missing")
    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=["PS1", "PM5", "PM1", "PP2", "BP1"],
        direct_copy_fallbacks=["PS4", "PP5", "BP6"],
        clinvar_inputs=[
            {"stream": "variant_summary", "resources": ["PS4"]},
            {"stream": "clinvar_nirvana_json", "resources": ["PP5", "BP6"]}
        ],
        full_resource_paths=[],
        masked_namespace="masked/",
        bias_version="3.0.0"
    )

    holdout_ids = frozenset(["NC_000009.12:100:A:G"])

    clinvar_records = {
        "variant_summary": [
            {"VariationID": "HELD", "gene": "BRCA1"},
            {"VariationID": "NEIGHBOUR", "gene": "BRCA1"}
        ],
        "clinvar_nirvana_json": [
            {"variant_id": "HELD", "significance": "Pathogenic"},
            {"variant_id": "NEIGHBOUR", "significance": "Benign"}
        ]
    }
    normalizer = MockNormalizer({
        "HELD": "NC_000009.12:100:A:G",
        "NEIGHBOUR": "NC_000009.12:101:A:T",
    })

    result = mask_clinvar_source(clinvar_records, holdout_ids, normalizer, config)

    # Assert own variant is removed, neighbour is retained
    assert len(result.masked_streams["variant_summary"]) == 1
    assert result.masked_streams["variant_summary"][0]["VariationID"] == "NEIGHBOUR"

    assert len(result.masked_streams["clinvar_nirvana_json"]) == 1
    assert result.masked_streams["clinvar_nirvana_json"][0]["variant_id"] == "NEIGHBOUR"


def test_ac_m6_label_free_identity_access(tmp_path: Path) -> None:
    if load_holdout_identities is None:
        pytest.fail("implementation missing")
    sentinel_label = "SENTINEL_LABEL_VAL"
    heldout_jsonl = tmp_path / "heldout.jsonl"
    heldout_jsonl.write_text(json.dumps({
        "variant_id": "NC_000009.12:100:A:G",
        "label": sentinel_label,
        "source": "SENTINEL_SOURCE"
    }))

    normalizer = MockNormalizer({})
    # Should only read variant_id, never fail due to other fields
    ids = load_holdout_identities(heldout_jsonl, normalizer)
    assert ids == frozenset(["NC_000009.12:100:A:G"])

    # We prove label-free identity access by ensuring the sentinel doesn't cause errors
    # and isn't required by the parser.
    heldout_jsonl_clean = tmp_path / "heldout_clean.jsonl"
    heldout_jsonl_clean.write_text(json.dumps({"variant_id": "NC_000009.12:100:A:G"}))
    ids_clean = load_holdout_identities(heldout_jsonl_clean, normalizer)
    assert ids == ids_clean


def test_ac_m7_full_vus_resources_untouched(tmp_path: Path) -> None:
    if MaskConfig is None:
        pytest.fail("implementation missing")
    full_resource = tmp_path / "full_PS1.json"
    full_resource.write_text("FULL_VUS_DATA")
    original_hash = hashlib.sha256(b"FULL_VUS_DATA").hexdigest()

    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=[],
        direct_copy_fallbacks=[],
        clinvar_inputs=[],
        full_resource_paths=[str(full_resource)],
        masked_namespace=str(tmp_path / "masked"),
        bias_version="3.0.0"
    )

    # Attempting to write into a full resource path should raise MaskConfigError
    # The config validator should reject overlapping namespaces
    with pytest.raises(MaskConfigError):
        MaskConfig(
            assembly="GRCh38",
            mask_criteria=[],
            direct_copy_fallbacks=[],
            clinvar_inputs=[],
            full_resource_paths=[str(tmp_path)],
            masked_namespace=str(tmp_path), # overlap
            bias_version="3.0.0"
        )

    # Assert byte-identical
    assert hashlib.sha256(full_resource.read_bytes()).hexdigest() == original_hash

    result = MaskResult(
        masked_streams={"vcf": []},
        ledger={"vcf": MaskLedger(0, 0, 0, ())},
        masked_namespace="masked",
        full_resource_paths=(str(tmp_path / "masked"),),
    )
    with pytest.raises(MaskConfigError):
        result.write(tmp_path)

    full_target = tmp_path / "full.json"
    full_target.write_text("FULL", encoding="utf-8")
    traversal = MaskResult(
        masked_streams={"../full": [{"unsafe": True}]},
        ledger={"../full": MaskLedger(1, 0, 1, ())},
        masked_namespace="masked",
        full_resource_paths=(str(full_target),),
    )
    with pytest.raises(MaskConfigError):
        traversal.write(tmp_path)
    assert full_target.read_text(encoding="utf-8") == "FULL"


def test_ac_m8_determinism_provenance(tmp_path: Path) -> None:
    if mask_clinvar_source is None:
        pytest.fail("implementation missing")
    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=[],
        direct_copy_fallbacks=[],
        clinvar_inputs=[{"stream": "vcf", "resources": []}],
        full_resource_paths=[],
        masked_namespace=str(tmp_path / "masked"),
        bias_version="3.0.0"
    )
    holdout_ids = frozenset(["NC_000009.12:100:A:G"])
    clinvar_records = {"vcf": [{"variant_id": "V1", "data": "x"}]}
    normalizer = MockNormalizer({"V1": "NC_000009.12:99:A:G"}) # Not held out, stays

    result1 = mask_clinvar_source(clinvar_records, holdout_ids, normalizer, config)
    result2 = mask_clinvar_source(clinvar_records, holdout_ids, normalizer, config)

    assert result1.content_hash() == result2.content_hash()


def test_ac_m9_fail_loud_ambiguity_and_unnormalizable() -> None:
    if mask_clinvar_source is None:
        pytest.fail("implementation missing")
    config = MaskConfig(
        assembly="GRCh38",
        mask_criteria=[],
        direct_copy_fallbacks=[],
        clinvar_inputs=[{"stream": "vcf", "resources": []}],
        full_resource_paths=[],
        masked_namespace="masked/",
        bias_version="3.0.0"
    )

    # Un-normalizable
    with pytest.raises(MaskReferenceError):
        mask_clinvar_source(
            {"vcf": [{"variant_id": "fail_unnorm"}]},
            frozenset(["NC_000009.12:100:A:G"]),
            MockNormalizer({}),
            config
        )

    # Ambiguity: held-out ID matching multiple NON-EQUIVALENT coordinates (mock this by having normalizer map two different ones)
    # The logic in mask_clinvar_source should raise MaskAmbiguityError if it detects this.
    # We expect the implementer to throw this.
    clinvar_records = {"vcf": [
        {"variant_id": "V1", "coord": "chr1:100"},
        {"variant_id": "V2", "coord": "chr2:200"}
    ]}
    # Both map to one canonical identity through non-equivalent coordinates.
    normalizer = MockNormalizer({
        "V1": "NC_000009.12:100:A:G",
        "V2": "NC_000009.12:100:A:G",
    })

    with pytest.raises(MaskAmbiguityError):
        mask_clinvar_source(
            clinvar_records,
            frozenset(["NC_000009.12:100:A:G"]),
            normalizer,
            config
        )
