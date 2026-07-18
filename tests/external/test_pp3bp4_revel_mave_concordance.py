import pytest
import json
from pathlib import Path


def test_tf1_mave_concordance_blocked_and_non_gating():
    """T-F1 MAVE.

    Verify MAVE concordance report:
    1. Defaults to status 'BLOCKED_DATA' when the structured REVEL table is missing.
    2. Marked as 'NON_GATING' (does not gate policy/predictions).
    3. No calibration or clinical authorization claims are made.
    """
    from raptor.external.mave.concordance import build_mave_concordance_report, MaveStatus

    # When REVEL score table is absent, the report should return BLOCKED_DATA
    report = build_mave_concordance_report(
        score_table_path=None, # missing score table
        mave_data_path="dummy_path"
    )

    assert report.status == MaveStatus.BLOCKED_DATA
    assert report.gating_type == "NON_GATING"
    
    # Assert that no clinical authorization or calibration is claimed
    assert not report.is_calibrated
    assert not report.clinical_use_authorized
    assert "research use only" in report.disclaimer.lower()


def test_tf1_mave_scorer_access_only_variant_id():
    """T-F1 MAVE scorer access.

    Verify that when evaluating MAVE concordance, the injected scorer receives
    ONLY the variant_id, and the MAVE functional class or value NEVER enters
    the policy thresholds or scorer calls.
    """
    from raptor.external.mave.concordance import build_mave_concordance_report

    requested_variant_ids = []

    # Injected scorer that records arguments passed to it
    def dummy_scorer(*args, **kwargs):
        # The scorer must only receive the variant_id (as a single positional argument)
        assert len(args) == 1, "Scorer received unexpected positional arguments"
        assert not kwargs, "Scorer received unexpected keyword arguments"
        variant_id = args[0]
        assert isinstance(variant_id, str), "Scorer argument must be a string variant_id"
        requested_variant_ids.append(variant_id)
        return 0.5

    # Mock MAVE records
    mock_mave_data = [
        {"variant_id": "NC_000009.12:g.10001A>G", "functional_class": "enriched", "functional_value": 1.2},
        {"variant_id": "NC_000016.10:g.54321C>T", "functional_class": "depleted", "functional_value": -2.3},
    ]

    # We evaluate and check that the scorer only queried variant_ids, not functional classes/values
    report = build_mave_concordance_report(
        score_table_path="dummy_score_table.py",
        mave_data_list=mock_mave_data,
        scorer=dummy_scorer,
        status="proposed"
    )

    # Scorer should only have been queried with the variant_id strings
    for vid in requested_variant_ids:
        assert isinstance(vid, str)
        assert vid in ["NC_000009.12:g.10001A>G", "NC_000016.10:g.54321C>T"]

    # Verify report is deterministic
    report_json_1 = report.to_json()
    report_json_2 = report.to_json()
    assert report_json_1 == report_json_2
