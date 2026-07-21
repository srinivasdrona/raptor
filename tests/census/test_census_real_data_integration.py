from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import os
import json
import hashlib
import subprocess
import pytest

try:
    from raptor.census.strata import (
        ManifestEntry,
        StratumEntry,
        load_manifest,
        reproduce_census_strata,
        _variant_class_for,
    )
    from raptor.census.aggregate import build_census_record
    from scripts.build_tsc_calibration_batch import RunPins
    HAS_ALL = True
except ImportError:
    from scripts.build_tsc_calibration_batch import (
        ManifestEntry,
        StratumEntry,
        load_manifest,
        reproduce_census_strata,
        RunPins,
        _variant_class_for,
    )
    build_census_record = None
    HAS_ALL = False


def check_all_implemented() -> None:
    if not HAS_ALL or build_census_record is None:
        pytest.fail("Missing planned implementation: raptor.census modules")


def _get_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(
    os.environ.get("RAPTOR_VUS_REAL_DATA") != "1",
    reason="RAPTOR_VUS_REAL_DATA env var is not set to 1",
)
def test_g_vc15_real_data_integration() -> None:
    """G-VC15 opt-in (env-gated, e.g. RAPTOR_VUS_REAL_DATA=1) run over the immutable manifest + BIAS TSV + current configs asserts the binding oracles."""
    check_all_implemented()

    # Paths to real, immutable inputs
    manifest_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.manifest.jsonl")
    bias_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/tsc-vus-2026-07-07/tsc_vus_input.bias_output.tsv")
    provenance_path = Path("D:/AIProjects/raptor-data/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.provenance.json")

    # Verify input existence
    if not manifest_path.is_file() or not bias_path.is_file() or not provenance_path.is_file():
        pytest.fail("Real data inputs are missing or inaccessible")

    # Verify provenance source/hash
    provenance_data = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert provenance_data["vcf_hash"] == "3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09"
    assert provenance_data["source_snapshot"] == "clinvar_2026-07-07"

    # Load real manifest
    manifest_entries = load_manifest(manifest_path)
    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest_entries}

    # Load configs
    from raptor.scorer.config import load_config as load_scorer_config
    from raptor.eval.config import load_config as load_eval_config
    from raptor.scorer.bias_source import BiasTsvSource

    scorer_config = load_scorer_config("configs/acmg/tsc.yaml")
    eval_config = load_eval_config("configs/eval/tsc2.yaml")

    # Load bias rows directly via BiasTsvSource (reused public API)
    bias_rows = tuple(BiasTsvSource(bias_path).records())

    # 1. Assert row & manifest counts match oracle (6618)
    assert len(manifest_entries) == 6618
    assert len(bias_rows) == 6618

    # Run strata reproduction
    strata = reproduce_census_strata(
        bias_rows,
        manifest_by_vcf_key,
        scorer_config,
        eval_config,
    )

    # Derive current Git commit rather than stale 7e03ca4
    repo_root = Path(__file__).resolve().parents[2]
    res = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root
    )
    current_commit = res.stdout.strip()

    # Build the record with Derived current Git commit and exact Nirvana version
    run_pins = RunPins(
        input_sha256="3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
        output_sha256="0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e",
        manifest_sha256="7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba",
        source_snapshot="clinvar_2026-07-07",
        bias_version="3.0.0",
        bias_commit="ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_version="3.18.1-0-g05f88047",
        code_commit=current_commit,
    )

    # Derive actual bound path hashes at runtime (including all 5 spec-bound surfaces)
    bound_hashes = {
        "approved_predictor_policy": _get_sha256(repo_root / "configs/eval/bp4pp3_predictor_policy.json"),
        "acmg_scorer_policy": _get_sha256(repo_root / "configs/acmg/tsc.yaml"),
        "eval_config": _get_sha256(repo_root / "configs/eval/tsc2.yaml"),
        "bias_lineage_policy": _get_sha256(repo_root / "configs/eval/bias_lineage.yaml"),
        "packet_candidate_direction": _get_sha256(repo_root / "configs/packet/candidate_direction.yaml"),
    }

    with open("data/census/tsc_vus_clinvar_2026-07-07_stats.json", "r", encoding="utf-8") as h:
        historical_stats = json.load(h)

    # Build the final census record from computed objects -- never read from the new final aggregate
    record = build_census_record(
        strata=strata,
        bias_rows=bias_rows,
        manifest=manifest_entries,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
        automatable_criteria=eval_config.automatable_criteria,
    )

    # 1.1 Assert additional schema/integrity metrics
    consumed_inc = record["consumed_automated_criterion_incidence"]
    for crit in eval_config.automatable_criteria:
        assert crit in consumed_inc
    assert consumed_inc["PP3"] == 0
    assert consumed_inc["BP4"] == 0

    assert sum(record["bias_gene_transcript"].values()) == 6618

    shares = record["raptor_current_policy_internal_direction_shares"]
    assert sum(shares.values()) == pytest.approx(1.0)

    run_integrity = record["run_integrity"]
    assert run_integrity["parser_records"] == 6618
    assert run_integrity["parser_contract_errors"] == 0
    assert run_integrity["exact_join"] is True
    assert run_integrity["duplicate_manifest_ids"] == 0
    assert run_integrity["duplicate_manifest_keys"] == 0
    assert run_integrity["duplicate_bias_keys"] == 0

    # 2. Assert direction totals (157 / 7 / 6424 / 30)
    directions = record["raptor_current_policy_internal_direction"]
    assert directions["candidate_LP_review"] == 157
    assert directions["candidate_LB_review"] == 7
    assert directions["no_deterministic_resolution"] == 6424
    assert directions["annotation_manual_review"] == 30

    # 3. Assert exact pattern counts (7 LP / 2 LB)
    assert record["candidate_pattern_compression"]["candidate_LP_review"]["exact_strength_patterns"] == 7
    assert record["candidate_pattern_compression"]["candidate_LB_review"]["exact_strength_patterns"] == 2

    # 4. Assert suppression counts (2226 / 3696 / 5474 / 0)
    supp = record["pp3bp4_suppression"]
    assert supp["raw_pp3"] == 2226
    assert supp["raw_bp4"] == 3696
    assert supp["affected_union"] == 5474
    assert supp["scored_calls"] == 0

    # 5. Assert point distribution summing to 6618 & signed_points == 0 is exactly 149
    dist = record["point_distribution"]
    assert sum(dist.values()) == 6618
    assert dist["0"] == 149

    # Check other point bands
    assert dist["-8"] == 1
    assert dist["-3"] == 6
    assert dist["1"] == 5651
    assert dist["2"] == 61
    assert dist["3"] == 172
    assert dist["4"] == 395
    assert dist["5"] == 26
    assert dist["6"] == 2
    assert dist["7"] == 5
    assert dist["9"] == 143
    assert dist["11"] == 1
    assert dist["12"] == 6

    # 6. Assert per-gene/per-consequence breakdowns named in the spec
    corpus = record["corpus"]
    assert corpus["TSC1"] == 2249
    assert corpus["TSC2"] == 4369
    assert corpus["missense"] == 5645
    assert corpus["other"] == 893
    assert corpus["truncating"] == 80

    # Assert direction-by-gene and direction-by-consequence maps equal independently-derived Counters in the test
    from collections import Counter
    expected_direction_by_gene: dict[str, Counter[str]] = {}
    expected_direction_by_consequence: dict[str, Counter[str]] = {}
    
    strata_by_var_id = {s.variant_id: s for s in strata}
    for row in bias_rows:
        m_entry = manifest_by_vcf_key[row.variant_id]
        stratum = strata_by_var_id[m_entry.variant_id]
        direction = stratum.stratum
        
        gene = row.gene_name
        expected_direction_by_gene.setdefault(gene, Counter())[direction] += 1
        
        conseq_class = _variant_class_for(row.consequence)
        expected_direction_by_consequence.setdefault(conseq_class, Counter())[direction] += 1

    # Ensure direction-by-gene in record matches our independently derived expected Counters
    for gene, counter in expected_direction_by_gene.items():
        assert dict(record["direction_by_gene"][gene]) == dict(counter)

    # Ensure direction-by-consequence in record matches our independently derived expected Counters
    for conseq_class, counter in expected_direction_by_consequence.items():
        assert dict(record["direction_by_consequence"][conseq_class]) == dict(counter)

    # 7. Assert privacy of the record (strictly contains NO SPDI, VCF keys, or raw rationale/patient identifiers)
    sample_manifest_spdis = [entry.variant_id for entry in manifest_entries[:20]]
    sample_manifest_vcf_keys = [entry.vcf_key for entry in manifest_entries[:20]]

    def assert_privacy_recursive(val: any) -> None:
        if isinstance(val, str):
            for forbidden_spdi in sample_manifest_spdis:
                assert forbidden_spdi not in val, f"Leaked variant SPDI {forbidden_spdi!r} in record"
            for forbidden_key in sample_manifest_vcf_keys:
                assert forbidden_key not in val, f"Leaked variant vcf_key {forbidden_key!r} in record"
        elif isinstance(val, dict):
            for k, v in val.items():
                for forbidden_key_name in ("variant_id", "vcf_key", "spdi", "hgvs", "rationale", "packet_id"):
                    assert forbidden_key_name not in str(k).lower(), f"Leaked schema/identity key name {k!r} in record"
                assert_privacy_recursive(v)
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                assert_privacy_recursive(item)

    assert_privacy_recursive(record)

