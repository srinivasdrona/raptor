from __future__ import annotations

import os
from pathlib import Path
import pytest

try:
    from raptor.census.strata import (
        ManifestEntry,
        StratumEntry,
        load_manifest,
        reproduce_census_strata,
    )
    from raptor.census.aggregate import build_census_record
    from scripts.build_tsc_calibration_batch import RunPins
    HAS_ALL = True
except ImportError:
    HAS_ALL = False


def check_all_implemented() -> None:
    if not HAS_ALL:
        pytest.fail("Missing planned implementation: raptor.census modules")


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
    if not manifest_path.is_file() or not bias_path.is_file():
        pytest.fail("Real data inputs are missing or inaccessible")

    # Load real manifest
    manifest_entries = load_manifest(manifest_path)
    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest_entries}

    # Load configs
    from raptor.scorer.config import load_config as load_scorer_config
    from raptor.eval.config import load_config as load_eval_config
    from scripts.build_tsc_calibration_batch import load_bias_rows

    scorer_config = load_scorer_config("configs/acmg/tsc.yaml")
    eval_config = load_eval_config("configs/eval/tsc2.yaml")

    # Load bias rows
    bias_rows = load_bias_rows(bias_path)

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

    # Build the record
    run_pins = RunPins(
        input_sha256="3fff6de7ae9b2b202642e498c4c49532cf1aaf5c2734f0e8341d5ace88fa3a09",
        output_sha256="0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e",
        manifest_sha256="7f9937521a425e73b31422fa9191c90e67fa80cc58f351517ac732b1d32fcbba",
        source_snapshot="clinvar_2026-07-07",
        bias_version="3.0.0",
        bias_commit="ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_version="3.18.1",
        code_commit="7e03ca4",
    )

    bound_hashes = {
        "approved_predictor_policy": "ac9d361aa57686c736a527a9256ea7fd22c4292709f5e6b3482e1c3c4546c72b",
        "acmg_scorer_policy": "1ba8066accd8eda16e20518abbeaedb61247fea372675f519f02a8574ff9350e",
        "eval_config": "ea4ff684bdc2ae6b079f352816b3993ac813af0e2654b851c30c1f4ef577a293",
        "bias_lineage_policy": "d2312b2c74f125204ababe9731fc4e37a8e0f30d1608b75f8457aae6591689df",
    }

    import json
    with open("data/census/tsc_vus_clinvar_2026-07-07_stats.json", "r", encoding="utf-8") as h:
        historical_stats = json.load(h)

    record = build_census_record(
        strata=strata,
        bias_rows=bias_rows,
        manifest=manifest_entries,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

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
    assert dist["0"] == 149  # 119 unresolved with 0 points + 30 manual rows carrying 0 points

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
