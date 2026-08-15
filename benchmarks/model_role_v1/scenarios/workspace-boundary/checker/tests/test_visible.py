from solution import build_disposition_audit, resolve_workspace_path


def test_simple_path(tmp_path):
    assert resolve_workspace_path(tmp_path, "reports/a.json") == tmp_path / "reports/a.json"


def test_counts_only(tmp_path):
    audit = build_disposition_audit(tmp_path, ["a.json", "../outside.json"])
    assert audit["total"] == 2
    assert audit["accepted"] + audit["rejected"] == 2
