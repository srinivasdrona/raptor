from __future__ import annotations

import json
from pathlib import Path
import pytest

from raptor.scorer.model import BiasRecord

try:
    from raptor.census.strata import ManifestEntry, StratumEntry, STRENGTH_MAP
    from raptor.census.aggregate import build_census_record
    from scripts.build_tsc_calibration_batch import RunPins
    HAS_AGGREGATE = True
except ImportError:
    from scripts.build_tsc_calibration_batch import ManifestEntry, StratumEntry, STRENGTH_MAP, RunPins
    build_census_record = None
    HAS_AGGREGATE = False


def check_aggregate_implemented() -> None:
    if not HAS_AGGREGATE:
        pytest.fail("Missing planned implementation: raptor.census.aggregate")


def _row(index: int, criteria, *, gene: str = "TSC2", consequence: str = "missense_variant") -> BiasRecord:
    chromosome = "chr16"
    raw = f"{chromosome}\t{1000 + index}\tA\tG\t{gene}\t{criteria!r}"
    return BiasRecord(
        chromosome=chromosome,
        position=1000 + index,
        ref_allele="A",
        alt_allele="G",
        variant_id=f"{chromosome}:{1000 + index}:A:G",
        variant_type="SNV",
        consequence=consequence,
        acmg_classification="uncertain",
        gene_name=gene,
        transcript="NM_000548.4",
        criteria=criteria,
        provenance={"raw_row": raw},
    )


@pytest.fixture
def base_inputs():
    # Setup standard, lightweight inputs
    run_pins = RunPins(
        input_sha256="1" * 64,
        output_sha256="2" * 64,
        manifest_sha256="3" * 64,
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

    historical_stats = {
        "raptor_current_policy_internal_direction": {
            "candidate_LP_review": 10,
            "candidate_LB_review": 20,
            "no_deterministic_resolution": 30,
            "annotation_manual_review": 5,
        }
    }

    return run_pins, bound_hashes, historical_stats


def test_g_vc7_all_counts_derived(base_inputs) -> None:
    """G-VC7 all counts derived from injected inputs (change an input, count moves); no expected-count literal in production code."""
    check_aggregate_implemented()
    run_pins, bound_hashes, historical_stats = base_inputs

    # Setup base inputs
    row1 = _row(1, {"pm2": (1, "supporting")})
    manifest1 = [ManifestEntry(variant_id="V1", vcf_key=row1.variant_id)]
    stratum1 = [
        StratumEntry(
            variant_id="V1",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        )
    ]

    record1 = build_census_record(
        strata=stratum1,
        bias_rows=[row1],
        manifest=manifest1,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    # Now change/double the inputs
    row2 = _row(2, {"pm2": (1, "supporting")})
    manifest2 = [
        ManifestEntry(variant_id="V1", vcf_key=row1.variant_id),
        ManifestEntry(variant_id="V2", vcf_key=row2.variant_id),
    ]
    stratum2 = [
        StratumEntry(
            variant_id="V1",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="V2",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
    ]

    record2 = build_census_record(
        strata=stratum2,
        bias_rows=[row1, row2],
        manifest=manifest2,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    # Asserts that the corpus totals or row counts actually changed
    assert record1["corpus"]["total_vus"] == 1
    assert record2["corpus"]["total_vus"] == 2
    assert record1["run_integrity"]["bias_rows"] == 1
    assert record2["run_integrity"]["bias_rows"] == 2


def test_g_vc8_suppression_union(base_inputs) -> None:
    """G-VC8 suppression union computed as the size of (PP3 union BP4); scored PP3/BP4 == 0."""
    check_aggregate_implemented()
    run_pins, bound_hashes, historical_stats = base_inputs

    # Setup rows:
    # 1. Row firing PP3 only
    # 2. Row firing BP4 only
    # 3. Row firing both PP3 and BP4
    # 4. Row firing other criteria (not PP3 or BP4)
    rows = [
        _row(1, {"pp3": (2, "moderate")}),
        _row(2, {"bp4": (3, "strong")}),
        _row(3, {"pp3": (2, "moderate"), "bp4": (3, "strong")}),
        _row(4, {"pm2": (1, "supporting")}),
    ]

    manifest = [ManifestEntry(variant_id=f"V{i}", vcf_key=r.variant_id) for i, r in enumerate(rows, start=1)]
    strata = [
        StratumEntry(
            variant_id=entry.variant_id,
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        )
        for entry in manifest
    ]

    record = build_census_record(
        strata=strata,
        bias_rows=rows,
        manifest=manifest,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    # raw_pp3 should be 2, raw_bp4 should be 2, union size should be 3, scored should be 0
    supp = record["pp3bp4_suppression"]
    assert supp["raw_pp3"] == 2
    assert supp["raw_bp4"] == 2
    assert supp["affected_union"] == 3
    assert supp["scored_calls"] == 0


def test_g_vc9_emitted_record_privacy(base_inputs) -> None:
    """G-VC9 emitted record contains NO variant_id/vcf_key/SPDI/HGVS/rationale/label/packet_id (privacy schema assertion)."""
    check_aggregate_implemented()
    run_pins, bound_hashes, historical_stats = base_inputs

    row = _row(1, {"pm2": (1, "supporting")})
    manifest = [ManifestEntry(variant_id="V_IDENTIFIER_SPDI", vcf_key=row.variant_id)]
    strata = [
        StratumEntry(
            variant_id="V_IDENTIFIER_SPDI",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        )
    ]

    record = build_census_record(
        strata=strata,
        bias_rows=[row],
        manifest=manifest,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    # Recursively check the record to ensure no leak of identifiers or raw rationale
    def check_clean(val: any) -> None:
        if isinstance(val, str):
            for forbidden in ("V_IDENTIFIER", "SPDI", "chr16:1001", "A>G", "A:G"):
                assert forbidden not in val, f"Leaked forbidden term {forbidden!r} in string {val!r}"
        elif isinstance(val, dict):
            for k, v in val.items():
                for forbidden in ("variant_id", "vcf_key", "spdi", "hgvs", "rationale", "packet_id"):
                    assert forbidden not in str(k).lower(), f"Leaked forbidden key {k!r}"
                check_clean(v)
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                check_clean(item)

    check_clean(record)


def test_g_vc10_historical_comparison_and_point_distribution(base_inputs) -> None:
    """G-VC10 historical comparison delta computed from the historical file, not hardcoded; point distribution covering all strata."""
    check_aggregate_implemented()
    run_pins, bound_hashes, historical_stats = base_inputs

    # Setup a mock population:
    # - 1 LP stratum (points 6)
    # - 1 LB stratum (points -3)
    # - 1 unresolved stratum (points 0)
    # - 1 unresolved stratum (points 4)
    # - 1 manual stratum (points 0, stratum manual_review)
    # Total = 5 strata
    rows = [_row(i, {}) for i in range(1, 6)]
    manifest = [ManifestEntry(variant_id=f"V{i}", vcf_key=r.variant_id) for i, r in enumerate(rows, start=1)]

    strata = [
        # LP
        StratumEntry(
            variant_id="V1",
            stratum="candidate_LP_review",
            pattern_id="P1",
            pattern_signature=("PM2 Supporting",),
            signed_points=6,
            basis="eval_only_census_selection_metadata",
        ),
        # LB
        StratumEntry(
            variant_id="V2",
            stratum="candidate_LB_review",
            pattern_id="P2",
            pattern_signature=("BP4 Strong",),
            signed_points=-3,
            basis="eval_only_census_selection_metadata",
        ),
        # Unresolved 0 points
        StratumEntry(
            variant_id="V3",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
        # Unresolved 4 points
        StratumEntry(
            variant_id="V4",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=4,
            basis="eval_only_census_selection_metadata",
        ),
        # Manual (0 points)
        StratumEntry(
            variant_id="V5",
            stratum="manual_review",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
    ]

    record = build_census_record(
        strata=strata,
        bias_rows=rows,
        manifest=manifest,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
    )

    # Point distribution assertions
    dist = record["point_distribution"]
    # Total strata = 5
    assert sum(dist.values()) == 5

    # 0 band must contain BOTH the unresolved 0-points (1) and manual (1) => 2
    assert dist["0"] == 2
    assert dist["6"] == 1
    assert dist["-3"] == 1
    assert dist["4"] == 1

    # Historical comparison delta computation check
    # Historical stats: LP=10, LB=20, Unresolved=30, Manual=5
    # Actual strata: LP=1, LB=1, Unresolved=2, Manual=1
    # Deltas: LP = 1 - 10 = -9, LB = 1 - 20 = -19, Unresolved = 2 - 30 = -28, Manual = 1 - 5 = -4
    comp = record["historical_comparison_superseded"]
    assert comp["candidate_LP_review"]["historical"] == 10
    assert comp["candidate_LP_review"]["disabled_manual"] == 1
    assert comp["candidate_LP_review"]["delta"] == -9

    assert comp["candidate_LB_review"]["historical"] == 20
    assert comp["candidate_LB_review"]["disabled_manual"] == 1
    assert comp["candidate_LB_review"]["delta"] == -19

    assert comp["no_deterministic_resolution"]["historical"] == 30
    assert comp["no_deterministic_resolution"]["disabled_manual"] == 2
    assert comp["no_deterministic_resolution"]["delta"] == -28

    assert comp["annotation_manual_review"]["historical"] == 5
    assert comp["annotation_manual_review"]["disabled_manual"] == 1
    assert comp["annotation_manual_review"]["delta"] == -4
