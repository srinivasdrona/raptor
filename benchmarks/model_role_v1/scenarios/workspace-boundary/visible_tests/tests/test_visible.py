from pathlib import Path

import pytest

from solution import (
    WorkspaceBoundaryError,
    build_disposition_audit,
    resolve_workspace_path,
)


def test_simple_relative_path_is_accepted(tmp_path):
    resolved = resolve_workspace_path(tmp_path, "reports/summary.json")
    assert resolved == (tmp_path / "reports/summary.json").resolve(strict=False)


def test_parent_segment_is_rejected(tmp_path):
    with pytest.raises(WorkspaceBoundaryError) as caught:
        resolve_workspace_path(tmp_path, "../outside.json")
    assert caught.value.code == "PARENT_SEGMENT"


def test_audit_counts_all_requests(tmp_path):
    audit = build_disposition_audit(
        tmp_path, ["reports/a.json", "../outside.json"]
    )
    assert audit["total"] == 2
    assert audit["accepted"] + audit["rejected"] == 2
