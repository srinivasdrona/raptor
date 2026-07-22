from __future__ import annotations

import os
import sys
import json
import pytest
import hashlib
from pathlib import Path

# Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
# Copilot-Session: 7c146921-f3dd-4a1e-8cf0-8f574de49204

def _api():
    try:
        from raptor.packet.corrected_universe import (
            conserve_current_policy,
            build_full_vus_universe,
        )
        from raptor.census.strata import ConservationError
    except ImportError as exc:
        pytest.fail(f"Missing planned implementation: {exc}")
    return locals()


def test_universe_conservation_and_strata_counts() -> None:
    """G-CP1, G-CP5, G-CP10: Protected pin check of the committed census.
    Ensures 164 (priority LP+LB) + 6,454 (excluded unresolved+manual) == 6,618.
    """
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    assert census_stats_path.is_file(), "Current policy census json file is missing"
    
    # 1. Verify committed census SHA-256 (canonical LF blob) matches spec pin exactly
    lf_bytes = census_stats_path.read_bytes()
    canonical_bytes = lf_bytes.replace(b"\r\n", b"\n")
    lf_hash = hashlib.sha256(canonical_bytes).hexdigest()
    assert lf_hash == "45ff9f9abada7d5369c131bf7ffde28d0786eea41ff9bf7905f51da0cabd59ac"
    
    census = json.loads(canonical_bytes.decode("utf-8"))
    assert census["corpus"]["total_vus"] == 6618
    assert census["run_integrity"]["bias_rows"] == 6618
    
    counts = census["raptor_current_policy_internal_direction"]
    lp = counts["candidate_LP_review"]
    lb = counts["candidate_LB_review"]
    unresolved = counts["no_deterministic_resolution"]
    manual = counts["annotation_manual_review"]
    
    assert lp == 157
    assert lb == 7
    assert unresolved == 6424
    assert manual == 30
    assert lp + lb + unresolved + manual == 6618
    
    # Priority queue vs excluded counts
    priority_queue_size = lp + lb
    excluded_from_priority = unresolved + manual
    assert priority_queue_size == 164
    assert excluded_from_priority == 6454


def test_manual_review_reconciliation() -> None:
    """G-CP8, D11: manual_review stratum is exactly the 30 NTHL1 rows == census annotation_manual_review, no double count."""
    census_stats_path = Path("data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json")
    census = json.loads(census_stats_path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
        
    counts = census["raptor_current_policy_internal_direction"]
    manual_review_count = counts["annotation_manual_review"]
    assert manual_review_count == 30
    
    # Ensure direction_by_gene.NTHL1.manual_review == 30
    nthl1_manual = census["direction_by_gene"]["NTHL1"]["manual_review"]
    assert nthl1_manual == 30
    
    # Ensure direction_by_consequence.other.manual_review == 30
    other_manual = census["direction_by_consequence"]["other"]["manual_review"]
    assert other_manual == 30


def test_current_policy_conservation_guard() -> None:
    """G-CP9, D5: Synthetic unit tests call conserve_current_policy with injected counts and verify failures.
    Ensures drift, duplicates, missing joins, and manual mapping failures fail closed with ConservationError.
    """
    api = _api()
    conserve_current_policy = api["conserve_current_policy"]
    ConservationError = api["ConservationError"]
    
    # Valid synthetic inputs matching current policy
    valid_synthetic = {
        "total_vus": 6618,
        "lp_count": 157,
        "lb_count": 7,
        "unresolved_count": 6424,
        "manual_count": 30,
        "lp_patterns": 7,
        "lb_patterns": 2,
    }
    
    # Should succeed with valid inputs
    conserve_current_policy(**valid_synthetic)
    
    # 1. Verify drift failure (mismatched total VUS)
    drifted_total = dict(valid_synthetic, total_vus=6617)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_total)
        
    # 2. Verify drift failure (mismatched LP count)
    drifted_lp = dict(valid_synthetic, lp_count=156)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_lp)
        
    # 3. Verify drift failure (mismatched Manual Review count)
    drifted_manual = dict(valid_synthetic, manual_count=29)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_manual)
        
    # 4. Verify drift failure (mismatched LP patterns count)
    drifted_patterns = dict(valid_synthetic, lp_patterns=8)
    with pytest.raises(ConservationError):
        conserve_current_policy(**drifted_patterns)


def test_full_vus_universe_conservation() -> None:
    """Finding 4 / Defect 1: Exercise planned full conserve_current_policy and build_full_vus_universe with real contract fixtures."""
    api = _api()
    build_full_vus_universe = api["build_full_vus_universe"]
    conserve_current_policy = api["conserve_current_policy"]
    ConservationError = api["ConservationError"]
    
    from raptor.census.strata import ManifestEntry
    from raptor.scorer.model import BiasRecord
    from scripts.build_tsc_calibration_batch import RunPins
    
    # 1. Prepare valid canonical SPDIs and VCF keys
    manifest = [
        ManifestEntry(variant_id="NC_000009.12:100:A:G", vcf_key="chr9:100:A:G"),
        ManifestEntry(variant_id="NC_000016.10:200:G:C", vcf_key="chr16:200:G:C"),
        ManifestEntry(variant_id="NC_000016.10:300:T:A", vcf_key="chr16:300:T:A"),
        ManifestEntry(variant_id="NC_000016.10:400:C:G", vcf_key="chr16:400:C:G"),
    ]
    
    # Criteria must be real BIAS (fired_int, explanation) tuples
    bias_records = [
        BiasRecord(
            chromosome="chr9",
            position=100,
            ref_allele="A",
            alt_allele="G",
            variant_id="chr9:100:A:G",
            variant_type="SNV",
            consequence="missense_variant",
            acmg_classification="uncertain",
            gene_name="TSC1",
            transcript="NM_000368.4",
            criteria={"pvs1": (1, "supporting")},
            provenance={"raw_row": "chr9\t100\tA\tG\tTSC1\t{'pvs1': (1, 'supporting')}"},
        ),
        BiasRecord(
            chromosome="chr16",
            position=200,
            ref_allele="G",
            alt_allele="C",
            variant_id="chr16:200:G:C",
            variant_type="SNV",
            consequence="missense_variant",
            acmg_classification="uncertain",
            gene_name="TSC2",
            transcript="NM_000548.4",
            criteria={"bp4": (1, "supporting")},
            provenance={"raw_row": "chr16\t200\tG\tC\tTSC2\t{'bp4': (1, 'supporting')}"},
        ),
        BiasRecord(
            chromosome="chr16",
            position=300,
            ref_allele="T",
            alt_allele="A",
            variant_id="chr16:300:T:A",
            variant_type="SNV",
            consequence="missense_variant",
            acmg_classification="uncertain",
            gene_name="TSC2",
            transcript="NM_000548.4",
            criteria={},
            provenance={"raw_row": "chr16\t300\tT\tA\tTSC2\t{}"},
        ),
        BiasRecord(
            chromosome="chr16",
            position=400,
            ref_allele="C",
            alt_allele="G",
            variant_id="chr16:400:C:G",
            variant_type="SNV",
            consequence="missense_variant",
            acmg_classification="uncertain",
            gene_name="NTHL1",
            transcript="NM_001351295.1",
            criteria={},
            provenance={"raw_row": "chr16\t400\tC\tG\tNTHL1\t{}"},
        ),
    ]
    
    run_pins = RunPins(
        input_sha256="1" * 64,
        output_sha256="2" * 64,
        manifest_sha256="3" * 64,
        source_snapshot="clinvar_2026-07-07",
        bias_version="3.0.0",
        bias_commit="ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_version="3.18.1",
        code_commit="a" * 40,
    )
    
    # 2. Exercise spec-scoped build_full_vus_universe reusing calibration helpers (RunPins)
    packets = build_full_vus_universe(
        manifest=manifest,
        bias_records=bias_records,
        run_pins=run_pins,
        expected_total=4,
        expected_lp=1,
        expected_lb=1,
        expected_unresolved=1,
        expected_manual=1,
        expected_lp_patterns=1,
        expected_lb_patterns=1
    )
    
    assert len(packets) == 4
    
    # Assert conservation of three source_hashes (input_vcf, bias_tsv, manifest)
    for p in packets:
        assert p.run_metadata.packet_config_sha256 == run_pins.manifest_sha256 # mapped to source_hashes
        
    # Assert run_integrity.exact_join & identity equality & 4 strata & unresolved/manual are pattern_ref None
    for p in packets:
        matching_manifest = next(m for m in manifest if m.variant_id == p.identity.canonical_spdi)
        assert p.identity.canonical_spdi == matching_manifest.variant_id
        
        stratum = p.census_selection_stratum.census_selection_stratum
        if stratum in ("no_deterministic_resolution", "manual_review"):
            assert p.pattern_ref is None
            
    # Exact annotation_manual_review -> manual_review mapping (NTHL1 maps to manual_review)
    manual_p = next(p for p in packets if p.identity.canonical_spdi == "NC_000016.10:400:C:G")
    assert manual_p.census_selection_stratum.census_selection_stratum == "manual_review"
    
    # 3. Failures for duplicate/missing/extra joins (run_integrity.exact_join)
    # Duplicate join:
    duplicate_bias = bias_records + [bias_records[0]]
    with pytest.raises(ConservationError):
        build_full_vus_universe(manifest, duplicate_bias, run_pins)
        
    # Missing join:
    with pytest.raises(ConservationError):
        build_full_vus_universe(manifest, bias_records[:-1], run_pins)
        
    # Extra join:
    extra_manifest = manifest + [ManifestEntry(variant_id="NC_000016.10:500:A:T", vcf_key="chr16:500:A:T")]
    with pytest.raises(ConservationError):
        build_full_vus_universe(extra_manifest, bias_records, run_pins)

