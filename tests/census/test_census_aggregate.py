from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import json
import pytest

from raptor.scorer.model import BiasRecord

try:
    from raptor.census.strata import ManifestEntry, StratumEntry, STRENGTH_MAP, ConservationError
    from raptor.census.aggregate import build_census_record
    from scripts.build_tsc_calibration_batch import RunPins
    HAS_AGGREGATE = True
except ImportError:
    from scripts.build_tsc_calibration_batch import ManifestEntry, StratumEntry, STRENGTH_MAP, RunPins
    from raptor.census.strata import ConservationError
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

    # Setup base inputs with valid identities
    row1 = _row(1, {"pm2": (1, "supporting")})
    manifest1 = [ManifestEntry(variant_id="NC_000016.10:1001:A:G", vcf_key=row1.variant_id)]
    stratum1 = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
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
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
    )

    # Now change/double the inputs with valid identities
    row2 = _row(2, {"pm2": (1, "supporting")})
    manifest2 = [
        ManifestEntry(variant_id="NC_000016.10:1001:A:G", vcf_key=row1.variant_id),
        ManifestEntry(variant_id="NC_000016.10:1002:A:G", vcf_key=row2.variant_id),
    ]
    stratum2 = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="NC_000016.10:1002:A:G",
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
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
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

    manifest = [ManifestEntry(variant_id=f"NC_000016.10:100{i}:A:G", vcf_key=r.variant_id) for i, r in enumerate(rows, start=1)]
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
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
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

    distinctive_spdi = "NC_000016.10:777777:A:G"
    distinctive_vcf_key = "chr16:777777:A:G"
    row = _row(776777, {"pm2": (1, "supporting")})
    manifest = [ManifestEntry(variant_id=distinctive_spdi, vcf_key=distinctive_vcf_key)]
    strata = [
        StratumEntry(
            variant_id=distinctive_spdi,
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
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
    )

    # Recursively check the record to ensure no leak of identifiers or raw rationale
    def check_clean(val: any) -> None:
        if isinstance(val, str):
            for forbidden in (distinctive_spdi, distinctive_vcf_key, "777777", "NC_000016.10"):
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
    manifest = [ManifestEntry(variant_id=f"NC_000016.10:100{i}:A:G", vcf_key=r.variant_id) for i, r in enumerate(rows, start=1)]

    strata = [
        # LP
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="candidate_LP_review",
            pattern_id="P1",
            pattern_signature=("PM2 Supporting",),
            signed_points=6,
            basis="eval_only_census_selection_metadata",
        ),
        # LB
        StratumEntry(
            variant_id="NC_000016.10:1002:A:G",
            stratum="candidate_LB_review",
            pattern_id="P2",
            pattern_signature=("BP4 Strong",),
            signed_points=-3,
            basis="eval_only_census_selection_metadata",
        ),
        # Unresolved 0 points
        StratumEntry(
            variant_id="NC_000016.10:1003:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
        # Unresolved 4 points
        StratumEntry(
            variant_id="NC_000016.10:1004:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=4,
            basis="eval_only_census_selection_metadata",
        ),
        # Manual (0 points)
        StratumEntry(
            variant_id="NC_000016.10:1005:A:G",
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
        automatable_criteria=["PVS1", "PS1", "PM1", "PM2", "PM4", "PM5", "PP2", "BA1", "BS1", "BP1", "BP3", "BP7"],
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

    # G-VC10 additionally assert the four aggregate direction counts come from the supplied stratum labels
    # even though the manual and unresolved rows share point 0; no inference from point bands.
    assert comp["no_deterministic_resolution"]["disabled_manual"] == 2  # unresolved 0-pts (1) + unresolved 4-pts (1) = 2
    assert comp["annotation_manual_review"]["disabled_manual"] == 1    # manual (1)

    # Asserting these are strictly derived from supplied stratum labels:
    assert comp["candidate_LP_review"]["disabled_manual"] == sum(1 for s in strata if s.stratum == "candidate_LP_review")
    assert comp["candidate_LB_review"]["disabled_manual"] == sum(1 for s in strata if s.stratum == "candidate_LB_review")
    assert comp["no_deterministic_resolution"]["disabled_manual"] == sum(1 for s in strata if s.stratum == "no_deterministic_resolution")
    assert comp["annotation_manual_review"]["disabled_manual"] == sum(1 for s in strata if s.stratum == "manual_review")
    assert sum(dist.values()) == len(strata)


def test_complete_aggregate_schema(base_inputs) -> None:
    """Complete aggregate schema validations including extended inputs and derived fields."""
    check_aggregate_implemented()
    run_pins, bound_hashes, historical_stats = base_inputs

    # Setup 4 distinct rows with PM2, PVS1, PP3, BP4
    rows = [
        _row(1, {"pm2": (1, "supporting")}),
        _row(2, {"pvs1": (4, "very_strong")}),
        _row(3, {"pp3": (2, "moderate")}),
        _row(4, {"bp4": (1, "supporting")}),
    ]
    manifest = [ManifestEntry(variant_id=f"NC_000016.10:100{i}:A:G", vcf_key=r.variant_id) for i, r in enumerate(rows, start=1)]
    strata = [
        StratumEntry(
            variant_id=manifest[0].variant_id,
            stratum="candidate_LP_review",
            pattern_id="PM2 Supporting",
            pattern_signature=("PM2 Supporting",),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id=manifest[1].variant_id,
            stratum="candidate_LP_review",
            pattern_id="PVS1 Very Strong",
            pattern_signature=("PVS1 Very Strong",),
            signed_points=4,
            basis="eval_only_census_selection_metadata",
        ),
        # PP3 unresolved (deferred)
        StratumEntry(
            variant_id=manifest[2].variant_id,
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
        # BP4 unresolved (deferred)
        StratumEntry(
            variant_id=manifest[3].variant_id,
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
    ]

    # Explicitly test build_census_record with the extended automatable_criteria input
    automatable = ["PVS1", "PM2"]
    record = build_census_record(
        strata=strata,
        bias_rows=rows,
        manifest=manifest,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
        automatable_criteria=automatable,
    )

    # 1. Assert consumed_automated_criterion_incidence
    consumed_inc = record["consumed_automated_criterion_incidence"]
    assert "PVS1" in consumed_inc
    assert "PM2" in consumed_inc
    assert consumed_inc["PVS1"] == 1
    assert consumed_inc["PM2"] == 1
    assert "PP3" in consumed_inc
    assert "BP4" in consumed_inc
    assert consumed_inc["PP3"] == 0
    assert consumed_inc["BP4"] == 0

    # 2. Assert run_integrity fields
    run_integrity = record["run_integrity"]
    assert run_integrity["parser_records"] == 4
    assert run_integrity["parser_contract_errors"] == 0
    assert run_integrity["exact_join"] is True
    assert run_integrity["duplicate_manifest_ids"] == 0
    assert run_integrity["duplicate_manifest_keys"] == 0
    assert run_integrity["duplicate_bias_keys"] == 0

    # 3. Assert raw bias_gene_transcript aggregate is derived
    assert "bias_gene_transcript" in record
    assert record["bias_gene_transcript"]["TSC2|NM_000548.4"] == 4

    # 4. Assert direction shares are derived from stratum counts/total and sum to 1.0;
    # manual/unresolved remain distinct despite shared point 0.
    shares = record["raptor_current_policy_internal_direction_shares"]
    assert sum(shares.values()) == pytest.approx(1.0)
    assert "candidate_LP_review" in shares
    assert "candidate_LB_review" in shares
    assert "no_deterministic_resolution" in shares
    assert "annotation_manual_review" in shares
    assert shares["candidate_LP_review"] == 0.5  # 2 of 4
    assert shares["candidate_LB_review"] == 0.0  # 0 of 4
    assert shares["no_deterministic_resolution"] == 0.5  # 2 of 4
    assert shares["annotation_manual_review"] == 0.0  # 0 of 4


def test_build_census_record_invalid_historical_directions(base_inputs) -> None:
    """ValueError is raised if historical stats have missing or invalid direction counts."""
    check_aggregate_implemented()
    run_pins, bound_hashes, _ = base_inputs

    row = _row(1, {"pm2": (1, "supporting")})
    manifest = [ManifestEntry(variant_id="NC_000016.10:1001:A:G", vcf_key=row.variant_id)]
    stratum = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        )
    ]

    # Case 1: missing entirely
    bad_stats_1 = {}
    with pytest.raises(ValueError):
        build_census_record(
            strata=stratum,
            bias_rows=[row],
            manifest=manifest,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=bad_stats_1,
            automatable_criteria=["PVS1", "PM2"],
        )

    # Case 2: missing one key
    bad_stats_2 = {
        "raptor_current_policy_internal_direction": {
            "candidate_LP_review": 10,
            "candidate_LB_review": 20,
            "no_deterministic_resolution": 30,
            # missing "annotation_manual_review"
        }
    }
    with pytest.raises(ValueError):
        build_census_record(
            strata=stratum,
            bias_rows=[row],
            manifest=manifest,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=bad_stats_2,
            automatable_criteria=["PVS1", "PM2"],
        )

    # Case 3: negative count
    bad_stats_3 = {
        "raptor_current_policy_internal_direction": {
            "candidate_LP_review": 10,
            "candidate_LB_review": 20,
            "no_deterministic_resolution": -1,
            "annotation_manual_review": 5,
        }
    }
    with pytest.raises(ValueError):
        build_census_record(
            strata=stratum,
            bias_rows=[row],
            manifest=manifest,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=bad_stats_3,
            automatable_criteria=["PVS1", "PM2"],
        )


def test_aggregate_stratum_identity_conservation(base_inputs) -> None:
    """Test aggregate stratum identity conservation.
    
    - Two manifest/bias rows with two strata sharing one variant_id must raise ConservationError/ValueError;
    - Missing stratum for a manifest identity and extra unknown stratum identity each fail closed;
    - A valid record asserts exact_join true and sums for top-level directions, direction_by_gene, direction_by_consequence, transcript, and corpus all cover the same total; no silent skips.
    - Explicitly require build_census_record rejects before producing a record rather than reporting exact_join=false success.
    """
    check_aggregate_implemented()
    from raptor.census.strata import ConservationError
    run_pins, bound_hashes, historical_stats = base_inputs

    # Setup base rows
    row1 = _row(1, {"pm2": (1, "supporting")})
    row2 = _row(2, {"pm2": (1, "supporting")})

    # --- Case 1: Two manifest/bias rows with two strata sharing one variant_id must raise ConservationError/ValueError ---
    # Since they share one variant_id, let's create two strata with identical variant_id
    strata_duplicate = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        )
    ]
    manifest_dup = [
        ManifestEntry(variant_id="NC_000016.10:1001:A:G", vcf_key=row1.variant_id),
        ManifestEntry(variant_id="NC_000016.10:1002:A:G", vcf_key=row2.variant_id),
    ]

    with pytest.raises((ConservationError, ValueError)):
        build_census_record(
            strata=strata_duplicate,
            bias_rows=[row1, row2],
            manifest=manifest_dup,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=historical_stats,
            automatable_criteria=["PVS1", "PM2"],
        )

    # --- Case 2: Missing stratum for a manifest identity fails closed ---
    manifest_valid = [
        ManifestEntry(variant_id="NC_000016.10:1001:A:G", vcf_key=row1.variant_id),
        ManifestEntry(variant_id="NC_000016.10:1002:A:G", vcf_key=row2.variant_id),
    ]
    # strata only contains one entry (for row1), but manifest and bias have two -> missing stratum for row2
    strata_missing = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        )
    ]

    with pytest.raises((ConservationError, ValueError)):
        build_census_record(
            strata=strata_missing,
            bias_rows=[row1, row2],
            manifest=manifest_valid,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=historical_stats,
            automatable_criteria=["PVS1", "PM2"],
        )

    # --- Case 3: Extra unknown stratum identity fails closed ---
    # Strata has extra entry that is not in manifest / bias rows
    strata_extra = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="NC_000016.10:1002:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="NC_000016.10:9999:A:G",  # Unknown extra stratum
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        )
    ]

    with pytest.raises((ConservationError, ValueError)):
        build_census_record(
            strata=strata_extra,
            bias_rows=[row1, row2],
            manifest=manifest_valid,
            run_pins=run_pins,
            bound_hashes=bound_hashes,
            historical_stats=historical_stats,
            automatable_criteria=["PVS1", "PM2"],
        )

    # --- Case 4: A valid record asserts exact_join true and sums for top-level directions, direction_by_gene, direction_by_consequence, transcript, and corpus all cover the same total ---
    strata_valid = [
        StratumEntry(
            variant_id="NC_000016.10:1001:A:G",
            stratum="candidate_LP_review",
            pattern_id="PM2",
            pattern_signature=("PM2 Supporting",),
            signed_points=1,
            basis="eval_only_census_selection_metadata",
        ),
        StratumEntry(
            variant_id="NC_000016.10:1002:A:G",
            stratum="no_deterministic_resolution",
            pattern_id="",
            pattern_signature=(),
            signed_points=0,
            basis="eval_only_census_selection_metadata",
        ),
    ]

    record = build_census_record(
        strata=strata_valid,
        bias_rows=[row1, row2],
        manifest=manifest_valid,
        run_pins=run_pins,
        bound_hashes=bound_hashes,
        historical_stats=historical_stats,
        automatable_criteria=["PVS1", "PM2"],
    )

    # Assert exact_join is true
    assert record["run_integrity"]["exact_join"] is True

    # Total number of items
    total = len(manifest_valid)
    assert total == 2

    # Corpus total
    assert record["corpus"]["total_vus"] == total

    # Sum of top-level directions
    top_level_sum = sum(record["raptor_current_policy_internal_direction"].values())
    assert top_level_sum == total

    # Sum of direction_by_gene
    gene_sum = sum(count for gene_dict in record["direction_by_gene"].values() for count in gene_dict.values())
    assert gene_sum == total

    # Sum of direction_by_consequence
    consequence_sum = sum(count for conseq_dict in record["direction_by_consequence"].values() for count in conseq_dict.values())
    assert consequence_sum == total

    # Sum of transcripts
    transcript_sum = sum(record["bias_gene_transcript"].values())
    assert transcript_sum == total

