"""Tests for PRD-04 Task A production candidate-direction policy."""

from pathlib import Path
import pytest
import yaml

from raptor.eval.config import load_config as load_eval_config, FORBIDDEN_CRITERIA
from raptor.eval.lineage_policy import load_lineage_policy
from raptor.packet.config import (
    load_candidate_direction_policy,
    load_packet_config,
    CandidateDirectionPolicy,
    PacketConfigError
)

def test_ac_d1_dependency_readiness():
    """AC-D1: Prerequisite surfaces (A, B, C) are present."""
    base_dir = Path("docs/prompts/policy-blockers")
    assert (base_dir / "A-bp4-pp3-aggregation/manifest.json").exists()
    assert (base_dir / "B-bs2-policy/manifest.json").exists()
    assert (base_dir / "C-transcript-nthl1/manifest.json").exists()
    assert Path("src/raptor/eval/predictor_aggregation.py").exists()
    assert Path("data/census/tsc_predictor_aggregation_report_2026-07-12.json").exists()
    assert Path("docs/reference/bs2-tsc-penetrance-mosaicism-review.md").exists()
    assert Path("src/raptor/ingest/transcript_reconcile.py").exists()

def test_ac_d2_criteria_parity():
    """AC-D2: criterion_strength_points keys == the derived candidate_set {PVS1,PM2,PM4,BA1,BS1,BP3,BP7}."""
    eval_config = load_eval_config("configs/eval/tsc2.yaml")
    lineage_policy = load_lineage_policy("configs/eval/bias_lineage.yaml")

    # unruled transitive are those that require heldout mask
    unruled_transitive = {
        crit for crit, rec in lineage_policy.records.items()
        if rec.validation_disposition == "requires_heldout_mask"
    }

    candidate_set = (
        set(eval_config.automatable_criteria)
        - {"BS2"}
        - FORBIDDEN_CRITERIA
        - unruled_transitive
    )

    policy = load_candidate_direction_policy("configs/packet/candidate_direction.yaml")

    # The policy should be populated regardless of unapproved status (per D contract)
    expected_set = {"PVS1", "PM2", "PM4", "BA1", "BS1", "BP3", "BP7"}
    assert set(policy.criterion_strength_points.keys()) == expected_set
    assert candidate_set == expected_set

    # Record excluded set + reasons
    excluded = {
        "BS2": "deferred",
        "PP3": "deferred",
        "BP4": "deferred",
    }
    for crit in FORBIDDEN_CRITERIA:
        excluded[crit] = "forbidden"
    for crit in unruled_transitive:
        excluded[crit] = "unruled_transitive"

    # Ensure no forbidden/unruled in points
    for crit in policy.criterion_strength_points.keys():
        assert crit not in excluded

def test_ac_d3_corrected_strengths():
    """AC-D3: PP3/BP4 are excluded; PM2, PM4, BP3, etc. point contributions are correct."""
    policy = load_candidate_direction_policy("configs/packet/candidate_direction.yaml")
    assert "PP3" not in policy.criterion_strength_points
    assert "BP4" not in policy.criterion_strength_points
    assert policy.criterion_strength_points["PM2"] == {
        "supporting": 1,
        "moderate": 2,
        "strong": 4,
    }
    assert policy.criterion_strength_points["PM4"] == {
        "supporting": 1,
        "moderate": 2,
        "strong": 4,
    }
    assert policy.criterion_strength_points["BP3"] == {
        "supporting": -1,
        "moderate": -2,
        "strong": -4,
    }

def test_ac_d4_scope():
    """AC-D4: scope NTHL1/base-mismatch out-of-scope excluded upstream."""
    acmg = yaml.safe_load(Path("configs/acmg/tsc.yaml").read_text())
    assert acmg["genes"] == {
        "TSC1": "NM_000368.5",
        "TSC2": "NM_000548.5",
    }
    report = yaml.safe_load(
        Path("data/census/tsc_transcript_reconciliation_report_2026-07-12.json").read_text()
    )
    assert (
        report["probe1_census_arithmetic_and_version_facts"]["bias_gene_transcript"][
            "NTHL1|NM_002528.6"
        ]
        == 30
    )
    assert report["probe2_nthl1_locus_characterization"]["nthl1_row_count"] == 30
    assert (
        report["probe3_spdi_version_invariance"][
            "direct_bias_tsv_source_disposition_counts"
        ]["out_of_scope_gene"]
        == 1
    )

def test_ac_d5_unapproved_null():
    """AC-D5: approval_status stays unapproved; compute_candidate_direction returns null."""
    from raptor.packet.direction import compute_candidate_direction
    policy = load_candidate_direction_policy("configs/packet/candidate_direction.yaml")
    assert policy.approval_status == "unapproved"

    # Values SHOULD be populated per contract
    assert policy.criterion_strength_points
    # Prompt explicitly says "null cutoffs" for unapproved
    assert policy.candidate_lp_min is None
    assert policy.candidate_lb_max is None

    # Try computing direction for an empty variant
    direction = compute_candidate_direction([], policy)
    assert direction.direction is None
    assert direction.null_reason == "production_policy_unapproved"

def test_ac_d6_strict_schema():
    """AC-D6: strict 8-key schema is preserved."""
    raw = yaml.safe_load(Path("configs/packet/candidate_direction.yaml").read_text())
    expected_keys = {
        "policy_id",
        "version",
        "approval_status",
        "approved_by",
        "approval_ref",
        "criterion_strength_points",
        "candidate_lp_min",
        "candidate_lb_max",
    }
    assert set(raw.keys()) == expected_keys
