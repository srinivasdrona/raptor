import pytest

@pytest.mark.blocked_ac1
def test_ac1_accuracy_metrics_blocked():
    """
    AC1a/AC1b - Trust gate blocked on Oracle
    The validation is blocked until the benchmark is frozen and the Oracle sets thresholds.
    We do NOT invent target numbers. (GP-9/H13).
    """
    pytest.skip("BLOCKED: AC1 accuracy metrics and trust gate depend on Oracle pre-registered thresholds.")
