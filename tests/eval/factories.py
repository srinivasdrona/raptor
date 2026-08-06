"""Stable shared constructors for eval tests.

Unlike pytest's specially loaded ``conftest`` modules, this module has one
package-qualified identity regardless of collection order.
"""

from __future__ import annotations

from raptor.eval.config import EvalConfig
from raptor.eval.model import Metrics


def make_eval_config(**overrides) -> EvalConfig:
    base = dict(
        automatable_criteria=["PVS1", "PS3", "PM1", "PM2", "PP3", "BA1", "BS1", "BS2", "BP4", "BP7"],
        tavtigian_points={
            "supporting": 1, "moderate": 2, "strong": 4, "very_strong": 8, "stand_alone": 8,
        },
        tavtigian_cutoffs={
            "pathogenic_min": 10, "likely_pathogenic_min": 6,
            "vus_min": 0, "vus_max": 5,
            "likely_benign_max": -1, "benign_max": -7,
        },
        min_count_per_class=10,
        split={"seed": 42, "holdout_fraction": 0.3},
        oracle_thresholds={},
        labels_snapshot="clinvar_2026-07-01",
    )
    base.update(overrides)
    return EvalConfig(**base)


def make_v2_auth_config() -> dict:
    return {
        "schema_version": 2,
        "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
        "full_spectrum": {
            "requires": ["missense:pathogenic", "missense:benign", "truncating:pathogenic"]
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"]
            }
        },
        "governance_statements": {
            "FULL_SPECTRUM": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
            "TRUNCATING_PATHOGENIC_ONLY": "Full-spectrum VUS automation is not authorized. Evidence supports only the validated truncating-pathogenic scope; missense remains unvalidated.",
            "NONE_VALIDATED": "Full-spectrum VUS automation is not authorized; no pre-registered research scope is currently validated."
        },
    }


def make_oracle_thresholds() -> dict:
    return {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"],
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"],
            },
        },
    }


__all__ = [
    "Metrics",
    "make_eval_config",
    "make_v2_auth_config",
    "make_oracle_thresholds",
]
