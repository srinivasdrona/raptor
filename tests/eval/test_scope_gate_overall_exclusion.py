"""Tests for excluding pooled overall stratum from v2 scopes.

Ensures that:
1. decide_scope_gate scopes include real class scopes only and never overall:*.
2. canonical_scope_gate_reason / report render / serialized scope_gate does not contain `overall:`.
3. build_aggregate_v2 accepts genuine envelope where report.metrics contains overall but scope table omits overall, and aggregate scopes/reason omit overall.
4. If tampered scope table adds overall:* despite pooled metrics, aggregate rejects as unexpected scope.
5. Overall metrics remain in report.metrics/aggregate metrics as descriptive aggregate but never become scopes or auth inputs.
6. Real descriptive 'other' remains admitted (both directions).
7. Unknown non-variant-class metric stratum policy: at minimum exclude exact reserved 'overall'.
"""
from __future__ import annotations

import pytest
from conftest import make_eval_config, Metrics, with_point_estimate_lb
from raptor.eval.scope_gate import decide_scope_gate, canonical_scope_gate_reason
from raptor.eval.report import EvalReport, report_to_dict
from scripts.build_masked_holdout_gate_aggregate import build_aggregate_v2, _canonical_oracle_thresholds


def make_v2_auth_config() -> dict:
    """Build the valid scope_authorization config block."""
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
        }
    }


def make_oracle_thresholds() -> dict:
    return {
        "confidence": 0.95,
        "strata": {
            "missense": {
                "precision": 0.90,
                "recall": 0.85,
                "gating": True,
                "directions": ["pathogenic", "benign"]
            },
            "truncating": {
                "precision": 0.95,
                "recall": 0.95,
                "gating": True,
                "directions": ["pathogenic"]
            }
        }
    }


def test_1_runner_metrics_overall_exclusion_from_scopes():
    """1. Runner-shaped metrics containing missense,truncating,other,overall:
    decide_scope_gate scopes must include real class scopes only and never overall:*.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    metrics = {
        "overall": with_point_estimate_lb(Metrics(
            precision=0.9, recall=0.9, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="overall", gating=False, benign_precision=0.9, benign_recall=0.9
        )),
        "missense": with_point_estimate_lb(Metrics(
            precision=0.91, recall=0.86, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=0.91, benign_recall=0.86
        )),
        "truncating": with_point_estimate_lb(Metrics(
            precision=0.96, recall=0.96, concordance=0.95,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="truncating", gating=True, benign_precision=0.96, benign_recall=0.96
        )),
        "other": with_point_estimate_lb(Metrics(
            precision=0.8, recall=0.8, concordance=0.8,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="other", gating=False, benign_precision=0.8, benign_recall=0.8
        ))
    }

    decision = decide_scope_gate(metrics, cfg)

    # Scopes keys must never contain overall:*
    assert "overall:pathogenic" not in decision.scopes
    assert "overall:benign" not in decision.scopes


def test_2_serialized_and_rendered_outputs_no_overall_mention():
    """2. canonical_scope_gate_reason/report render/serialized scope_gate must not contain `overall:`."""
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    metrics = {
        "overall": with_point_estimate_lb(Metrics(
            precision=0.9, recall=0.9, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="overall", gating=False, benign_precision=0.9, benign_recall=0.9
        )),
        "missense": with_point_estimate_lb(Metrics(
            precision=0.91, recall=0.86, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=0.91, benign_recall=0.86
        )),
        "truncating": with_point_estimate_lb(Metrics(
            precision=0.96, recall=0.96, concordance=0.95,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="truncating", gating=True, benign_precision=0.96, benign_recall=0.96
        ))
    }

    decision = decide_scope_gate(metrics, cfg)

    # canonical_scope_gate_reason must not contain overall:
    reason_text = canonical_scope_gate_reason(
        {k: v.scope_status for k, v in decision.scopes.items()},
        decision.authorization_blockers
    )
    assert "overall:" not in reason_text
    assert "overall:" not in decision.reason

    # Report render and serialized scope_gate must not contain overall:
    report = EvalReport(
        labels_snapshot="snap",
        benchmark_size=100,
        train_dev_size=50,
        holdout_size=50,
        holdout_label_counts={"P": 25, "B": 25},
        holdout_class_counts={"missense": 25, "truncating": 25},
        metrics=metrics,
        gate=None,
        config_pins={
            "bias_tsv_sha256": "bias",
            "manifest_sha256": "manifest",
            "mask_ledger_sha256": "ledger",
            "remask_audit_sha256": "remask",
            "return_manifest_sha256": "return",
            "predictor_correction_counts": {},
            "operational_skipped_criteria": [],
            "evaluation_skipped_criteria": [],
            "oracle_thresholds": make_oracle_thresholds(),
        },
        scope_gate=decision
    )

    rendered = report.render()
    assert "overall:" not in rendered

    serialized = report_to_dict(report)
    assert "overall:" not in serialized["scope_gate"]["reason"]
    for key in serialized["scope_gate"]["scopes"]:
        assert not key.startswith("overall:")


def test_3_build_aggregate_v2_accepts_metrics_overall_but_no_scopes_overall():
    """3. build_aggregate_v2 accepts genuine envelope where report.metrics contains overall
    but scope table omits overall, and aggregate scopes/reason omit overall.
    """
    envelope = {
        "content_hash": "c" * 64,
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {
            "removed_count": 0,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {},
        "report": {
            "labels_snapshot": "snap",
            "benchmark_size": 100,
            "train_dev_size": 50,
            "holdout_size": 50,
            "holdout_label_counts": {"P": 25, "B": 25},
            "holdout_class_counts": {"missense": 25, "truncating": 25},
            "metrics": {
                "overall": {"precision": 0.9, "recall": 0.9, "concordance": 0.9, "counts": {}},
                "missense": {
                    "precision": 0.9, "recall": 0.9, "concordance": 0.9,
                    "precision_lb": 0.91, "recall_lb": 0.86,
                    "benign_precision_lb": 0.91, "benign_recall_lb": 0.86,
                    "counts": {
                        "path_called": 40, "benign_called": 40,
                        "path_actual": 40, "benign_actual": 40,
                    },
                },
                "truncating": {
                    "precision": 0.95, "recall": 0.95, "concordance": 0.95,
                    "precision_lb": 0.96, "recall_lb": 0.96,
                    "benign_precision_lb": 0.96, "benign_recall_lb": 0.96,
                    "counts": {
                        "path_called": 40, "benign_called": 40,
                        "path_actual": 40, "benign_actual": 40,
                    },
                },
            },
            "gate": {
                "status": "PASS",
                "stratum": "missense",
                "reason": "ok",
                "vus_authorized": True,
                "per_stratum": {},
            },
            "config_pins": {
                "bias_tsv_sha256": "bias_sha",
                "manifest_sha256": "manifest_sha",
                "mask_ledger_sha256": "ledger_sha",
                "remask_audit_sha256": "remask_sha",
                "return_manifest_sha256": "return_sha",
                "predictor_correction_counts": {},
                "operational_skipped_criteria": [],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": _canonical_oracle_thresholds(),
            },
            "scope_gate": {
                "schema_version": "2",
                "scopes": {
                    "missense:pathogenic": {
                        "stratum": "missense",
                        "direction": "pathogenic",
                        "metric_status": "MET",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.91,
                        "recall_lb": 0.86,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "missense:benign": {
                        "stratum": "missense",
                        "direction": "benign",
                        "metric_status": "MET",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.91,
                        "recall_lb": 0.86,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "truncating:pathogenic": {
                        "stratum": "truncating",
                        "direction": "pathogenic",
                        "metric_status": "MET",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.96,
                        "recall_lb": 0.96,
                        "precision_threshold": 0.95,
                        "recall_threshold": 0.95,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "truncating:benign": {
                        "stratum": "truncating",
                        "direction": "benign",
                        "metric_status": "NO_THRESHOLD",
                        "coverage_adequate": True,
                        "scope_status": "DESCRIPTIVE",
                        "precision_lb": 0.96,
                        "recall_lb": 0.96,
                        "precision_threshold": None,
                        "recall_threshold": None,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    }
                },
                "full_spectrum_status": "PASS",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": "All pre-registered research scopes are validated for research-evidence use only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "research_use_disclaimer": "Research-evidence validation only; this authorizes no clinical classification, VUS worklist, or ClinVar submission.",
                "reason": "missense:benign=VALIDATED; missense:pathogenic=VALIDATED; truncating:benign=DESCRIPTIVE; truncating:pathogenic=VALIDATED",
                "authorization_blockers": []
            }
        }
    }

    agg = build_aggregate_v2(
        envelope,
        date="2026-07-15",
        terminal_json_hash="j",
        terminal_report_hash="t",
        published_pm1_scope={"reachable_pm1_rows": 0},
        reproduced_pm1_scope={"reachable_pm1_rows": 0},
        production_policy_status="unapproved",
    )

    assert "overall:pathogenic" not in agg["scopes"]
    assert "overall:benign" not in agg["scopes"]
    assert "overall:" not in agg["scope_gate_reason"]


def test_4_build_aggregate_v2_rejects_tampered_overall_scopes():
    """4. If tampered scope table adds overall:* despite pooled metrics, aggregate rejects as unexpected scope."""
    envelope = {
        "content_hash": "c" * 64,
        "predictor_policy": {"status": "approved"},
        "mask_attestation": {
            "removed_count": 0,
            "zero_survivors": True,
        },
        "lineage_audit": {"effective_blocking_criteria": []},
        "verified_return_artifacts": {},
        "report": {
            "labels_snapshot": "snap",
            "benchmark_size": 100,
            "train_dev_size": 50,
            "holdout_size": 50,
            "holdout_label_counts": {"P": 25, "B": 25},
            "holdout_class_counts": {"missense": 25, "truncating": 25},
            "metrics": {
                "overall": {"precision": 0.9, "recall": 0.9, "concordance": 0.9, "counts": {}},
                "missense": {"precision": 0.9, "recall": 0.9, "concordance": 0.9, "counts": {}},
                "truncating": {"precision": 0.95, "recall": 0.95, "concordance": 0.95, "counts": {}}
            },
            "gate": {
                "status": "PASS",
                "stratum": "missense",
                "reason": "ok",
                "vus_authorized": True,
                "per_stratum": {},
            },
            "config_pins": {
                "bias_tsv_sha256": "bias_sha",
                "manifest_sha256": "manifest_sha",
                "mask_ledger_sha256": "ledger_sha",
                "remask_audit_sha256": "remask_sha",
                "return_manifest_sha256": "return_sha",
                "predictor_correction_counts": {},
                "operational_skipped_criteria": [],
                "evaluation_skipped_criteria": [],
                "oracle_thresholds": _canonical_oracle_thresholds(),
            },
            "scope_gate": {
                "schema_version": "2",
                "scopes": {
                    "overall:pathogenic": {
                        "stratum": "overall",
                        "direction": "pathogenic",
                        "metric_status": "VALIDATED",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.9,
                        "recall_lb": 0.9,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "overall:benign": {
                        "stratum": "overall",
                        "direction": "benign",
                        "metric_status": "VALIDATED",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.9,
                        "recall_lb": 0.9,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "missense:pathogenic": {
                        "stratum": "missense",
                        "direction": "pathogenic",
                        "metric_status": "VALIDATED",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.91,
                        "recall_lb": 0.86,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "missense:benign": {
                        "stratum": "missense",
                        "direction": "benign",
                        "metric_status": "VALIDATED",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.91,
                        "recall_lb": 0.86,
                        "precision_threshold": 0.90,
                        "recall_threshold": 0.85,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "truncating:pathogenic": {
                        "stratum": "truncating",
                        "direction": "pathogenic",
                        "metric_status": "VALIDATED",
                        "coverage_adequate": True,
                        "scope_status": "VALIDATED",
                        "precision_lb": 0.96,
                        "recall_lb": 0.96,
                        "precision_threshold": 0.95,
                        "recall_threshold": 0.95,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    },
                    "truncating:benign": {
                        "stratum": "truncating",
                        "direction": "benign",
                        "metric_status": "NO_THRESHOLD",
                        "coverage_adequate": True,
                        "scope_status": "DESCRIPTIVE",
                        "precision_lb": 0.96,
                        "recall_lb": 0.96,
                        "precision_threshold": None,
                        "recall_threshold": None,
                        "actual_count": 40,
                        "called_count": 40,
                        "min_count": 36,
                        "reasons": [],
                    }
                },
                "full_spectrum_status": "VALIDATED",
                "full_spectrum_vus_authorized": True,
                "research_scope_flags": {"truncating_pathogenic_research_scope_validated": True},
                "governance_state": "FULL_SPECTRUM",
                "governance_statement": "statement",
                "research_use_disclaimer": "disclaimer",
                "reason": "overall:benign=VALIDATED; overall:pathogenic=VALIDATED; missense:benign=VALIDATED; missense:pathogenic=VALIDATED; truncating:benign=DESCRIPTIVE; truncating:pathogenic=VALIDATED",
                "authorization_blockers": []
            }
        }
    }

    # Aggregate must reject this as overall:pathogenic and overall:benign are no longer valid scope keys.
    with pytest.raises(ValueError, match="unexpected scope|ghost scope|key set"):
        build_aggregate_v2(
            envelope,
            date="2026-07-15",
            terminal_json_hash="j",
            terminal_report_hash="t",
            published_pm1_scope={"reachable_pm1_rows": 0},
            reproduced_pm1_scope={"reachable_pm1_rows": 0},
            production_policy_status="unapproved",
        )


def test_5_overall_metrics_retained_descriptive_but_never_scopes_or_auth():
    """5. Overall metrics remain in report.metrics/aggregate metrics as descriptive aggregate if existing
    publication keeps them, but must never become scopes or authorization inputs.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    # Suppose missense and truncating pass, but overall metrics are abysmal.
    # Since overall is NOT a scope or authorization input, the decision should still be VALIDATED / Authorized!
    metrics = {
        "overall": with_point_estimate_lb(Metrics(
            precision=0.1, recall=0.1, concordance=0.1,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="overall", gating=False, benign_precision=0.1, benign_recall=0.1
        )),
        "missense": with_point_estimate_lb(Metrics(
            precision=0.91, recall=0.86, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=0.91, benign_recall=0.86
        )),
        "truncating": with_point_estimate_lb(Metrics(
            precision=0.96, recall=0.96, concordance=0.95,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="truncating", gating=True, benign_precision=0.96, benign_recall=0.96
        ))
    }

    decision = decide_scope_gate(metrics, cfg)

    assert decision.scopes["missense:pathogenic"].scope_status == "VALIDATED"
    assert decision.scopes["missense:benign"].scope_status == "VALIDATED"
    assert decision.scopes["truncating:pathogenic"].scope_status == "VALIDATED"
    assert decision.full_spectrum_vus_authorized is True


def test_6_other_descriptive_strata_retained_both_directions():
    """6. Real descriptive `other` remains admitted (both directions) so exclusion is specific
    to pooled overall, not all nonpinned strata.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    metrics = {
        "overall": with_point_estimate_lb(Metrics(
            precision=0.9, recall=0.9, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="overall", gating=False, benign_precision=0.9, benign_recall=0.9
        )),
        "missense": with_point_estimate_lb(Metrics(
            precision=0.91, recall=0.86, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=0.91, benign_recall=0.86
        )),
        "truncating": with_point_estimate_lb(Metrics(
            precision=0.96, recall=0.96, concordance=0.95,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="truncating", gating=True, benign_precision=0.96, benign_recall=0.96
        )),
        "other": with_point_estimate_lb(Metrics(
            precision=0.8, recall=0.8, concordance=0.8,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="other", gating=False, benign_precision=0.8, benign_recall=0.8
        ))
    }

    decision = decide_scope_gate(metrics, cfg)

    assert "other:pathogenic" in decision.scopes
    assert "other:benign" in decision.scopes
    assert decision.scopes["other:pathogenic"].scope_status == "DESCRIPTIVE"
    assert decision.scopes["other:benign"].scope_status == "DESCRIPTIVE"


def test_7_exact_overall_exclusion_does_not_invent_broader_allowlist():
    """7. Unknown non-variant-class metric stratum policy: at minimum exclude exact reserved `overall`;
    do not invent broader allowlist unless repo has canonical variant-class enum. Tests should assert exact overall exclusion.
    """
    cfg = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )

    metrics = {
        "overall": with_point_estimate_lb(Metrics(
            precision=0.9, recall=0.9, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="overall", gating=False, benign_precision=0.9, benign_recall=0.9
        )),
        "missense": with_point_estimate_lb(Metrics(
            precision=0.91, recall=0.86, concordance=0.9,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="missense", gating=True, benign_precision=0.91, benign_recall=0.86
        )),
        "custom_stratum": with_point_estimate_lb(Metrics(
            precision=0.7, recall=0.7, concordance=0.7,
            counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
            stratum="custom_stratum", gating=False, benign_precision=0.7, benign_recall=0.7
        ))
    }

    decision = decide_scope_gate(metrics, cfg)

    # Assert exact overall exclusion
    assert "overall:pathogenic" not in decision.scopes
    assert "overall:benign" not in decision.scopes

    # Assert custom_stratum is preserved
    assert "custom_stratum:pathogenic" in decision.scopes
    assert "custom_stratum:benign" in decision.scopes
    assert decision.scopes["custom_stratum:pathogenic"].scope_status == "DESCRIPTIVE"
    assert decision.scopes["custom_stratum:benign"].scope_status == "DESCRIPTIVE"
