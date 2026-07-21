from __future__ import annotations

import json
from pathlib import Path
import pytest

from raptor.scorer.model import BiasRecord
from raptor.scorer.config import load_config as load_scorer_config
from raptor.eval.config import load_config as load_eval_config

# Import from the planned module with lazy fallback to allow clean collection
try:
    from raptor.census.strata import (
        ManifestEntry,
        StratumEntry,
        ConservationError,
        ManifestError,
        STRENGTH_MAP,
        load_manifest,
        reproduce_census_strata,
        _split_consequence_terms,
        _variant_class_for,
    )
    HAS_STRATA = True
except ImportError:
    from scripts.build_tsc_calibration_batch import (
        ManifestEntry,
        StratumEntry,
        ConservationError,
        ManifestError,
        STRENGTH_MAP,
        load_manifest,
        reproduce_census_strata,
        _split_consequence_terms,
        _variant_class_for,
    )
    HAS_STRATA = False


def check_strata_implemented() -> None:
    if not HAS_STRATA:
        pytest.fail("Missing planned implementation: raptor.census.strata")


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
def scorer_config():
    return load_scorer_config("configs/acmg/tsc.yaml")


@pytest.fixture
def eval_config():
    return load_eval_config("configs/eval/tsc2.yaml")


def test_g_vc1_pp3_bp4_suppression(scorer_config, eval_config) -> None:
    """G-VC1 PP3/BP4 suppression — a synthetic variant that would be LP with PP3 (or LB with BP4) but abstains without it routes to no_deterministic_resolution; the scored automatable set excludes PP3/BP4."""
    check_strata_implemented()

    # Create a row that has pm2 (strong) and pp3 (moderate).
    # Under standard rules, pm2 (strong) + pp3 (moderate/supporting) might trigger LP.
    # But because pp3 is not in eval_config.automatable_criteria, it is not scored.
    # Therefore, it should remain no_deterministic_resolution.
    row = _row(1, {"pm2": (3, "strong"), "pp3": (2, "moderate")})
    manifest = {
        row.variant_id: ManifestEntry(
            variant_id="NC_000016.10:999:A:G",
            vcf_key=row.variant_id,
        )
    }

    strata = reproduce_census_strata([row], manifest, scorer_config, eval_config)
    assert len(strata) == 1
    assert strata[0].stratum == "no_deterministic_resolution"


def test_g_vc2_nthl1_prerouting(scorer_config, eval_config) -> None:
    """G-VC2 NTHL1 pre-routing — an NTHL1-gene row goes to manual_review, never LP/LB."""
    check_strata_implemented()

    # NTHL1-gene row with high-scoring criteria (pvs1 very strong)
    row = _row(2, {"pvs1": (4, "very_strong")}, gene="NTHL1")
    manifest = {
        row.variant_id: ManifestEntry(
            variant_id="NC_000016.10:1000:A:G",
            vcf_key=row.variant_id,
        )
    }

    strata = reproduce_census_strata([row], manifest, scorer_config, eval_config)
    assert len(strata) == 1
    assert strata[0].stratum == "manual_review"
    assert strata[0].signed_points == 0
    assert strata[0].pattern_id == ""
    assert strata[0].pattern_signature == ()


def test_g_vc3_manifest_duplicate(tmp_path: Path) -> None:
    """G-VC3 manifest duplicate variant_id/vcf_key fails loud (ManifestError)."""
    check_strata_implemented()

    # Duplicate variant_id
    dup_var_id_path = tmp_path / "dup_var_id.jsonl"
    dup_var_id_path.write_text(
        json.dumps({"variant_id": "VAR1", "vcf_key": "KEY1"}) + "\n" +
        json.dumps({"variant_id": "VAR1", "vcf_key": "KEY2"}) + "\n",
        encoding="utf-8"
    )

    with pytest.raises(ManifestError) as exc_info:
        load_manifest(dup_var_id_path)
    assert "duplicate variant_id" in str(exc_info.value)

    # Duplicate vcf_key
    dup_vcf_key_path = tmp_path / "dup_vcf_key.jsonl"
    dup_vcf_key_path.write_text(
        json.dumps({"variant_id": "VAR1", "vcf_key": "KEY1"}) + "\n" +
        json.dumps({"variant_id": "VAR2", "vcf_key": "KEY1"}) + "\n",
        encoding="utf-8"
    )

    with pytest.raises(ManifestError) as exc_info:
        load_manifest(dup_vcf_key_path)
    assert "duplicate vcf_key" in str(exc_info.value)


def test_g_vc4_exact_one_to_one_join(scorer_config, eval_config) -> None:
    """G-VC4 exact one-to-one join — a BIAS row with no manifest entry fails loud (ConservationError)."""
    check_strata_implemented()

    row = _row(3, {"pm2": (1, "supporting")})
    # Empty manifest => join miss
    manifest = {}

    with pytest.raises(ConservationError) as exc_info:
        reproduce_census_strata([row], manifest, scorer_config, eval_config)
    assert "has no manifest entry" in str(exc_info.value)


def test_g_vc5_strength_map_drift(scorer_config, eval_config) -> None:
    """G-VC5 strength_map drift raises ConservationError (no silent re-label)."""
    check_strata_implemented()

    row = _row(4, {"pm2": (1, "supporting")})
    manifest = {
        row.variant_id: ManifestEntry(
            variant_id="NC_000016.10:1002:A:G",
            vcf_key=row.variant_id,
        )
    }

    # Create a drifted scorer config with altered strength_map
    import dataclasses
    drifted_scorer = dataclasses.replace(
        scorer_config,
        strength_map=frozenset([("1", "drifted_supporting")]),
    )

    with pytest.raises(ConservationError) as exc_info:
        reproduce_census_strata([row], manifest, drifted_scorer, eval_config)
    assert "strength_map" in str(exc_info.value)


def test_g_vc6_pattern_signature_compress(scorer_config, eval_config) -> None:
    """G-VC6 pattern signature is the sorted automatable-call catalog; identical patterns compress."""
    check_strata_implemented()

    # Two distinct variants with same criteria => should have identical pattern_id
    row1 = _row(5, {"pvs1": (4, "very_strong")})
    row2 = _row(6, {"pvs1": (4, "very_strong")})
    manifest = {
        row1.variant_id: ManifestEntry(variant_id="VAR1", vcf_key=row1.variant_id),
        row2.variant_id: ManifestEntry(variant_id="VAR2", vcf_key=row2.variant_id),
    }

    strata = reproduce_census_strata([row1, row2], manifest, scorer_config, eval_config)
    assert len(strata) == 2
    assert strata[0].stratum == "candidate_LP_review"
    assert strata[1].stratum == "candidate_LP_review"
    assert strata[0].pattern_id == strata[1].pattern_id
    assert strata[0].pattern_signature == strata[1].pattern_signature
    assert strata[0].pattern_id == "PVS1 Very Strong"
