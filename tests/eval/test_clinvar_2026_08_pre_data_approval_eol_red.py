from __future__ import annotations

import pytest

from tests.eval._clinvar_2026_08_prospective_red_helpers import (
    assert_stop_state,
    build_approval_record,
    canonical_lf_bytes,
    canonical_lf_sha256_path,
    git_blob_sha1,
    prospective_sandbox,
    require_exception,
    validate_pre_data_approval,
)


def test_validate_pre_data_approval_accepts_crlf_worktree_when_git_blob_pins_canonical_lf_blob() -> None:
    with prospective_sandbox("approval-cross-eol-crlf") as sandbox:
        lf_raw = canonical_lf_bytes(sandbox.spec_path.read_bytes())
        lf_canonical_sha = canonical_lf_sha256_path(sandbox.spec_path)
        lf_git_blob_sha = git_blob_sha1(lf_raw)
        sandbox.spec_path.write_bytes(lf_raw)
        crlf_raw = lf_raw.replace(b"\n", b"\r\n")
        sandbox.spec_path.write_bytes(crlf_raw)

        approval = build_approval_record(sandbox)
        assert approval["registration"]["git_blob_sha1"] == lf_git_blob_sha
        assert approval["registration"]["git_blob_sha1"] == git_blob_sha1(crlf_raw)
        assert approval["registration"]["canonical_lf_sha256"] == lf_canonical_sha

        validated = validate_pre_data_approval(
            sandbox,
            approval_record=approval,
            first_archive_get_at=None,
        )
        assert validated["registration"]["git_blob_sha1"] == approval["registration"]["git_blob_sha1"]
        assert validated["registration"]["canonical_lf_sha256"] == approval["registration"]["canonical_lf_sha256"]


def test_validate_pre_data_approval_rejects_semantic_drift_even_when_crlf_normalization_is_used() -> None:
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("approval-cross-eol-semantic-drift") as sandbox:
        approval = build_approval_record(sandbox)
        pinned_spec_raw = sandbox.spec_path.read_bytes()
        approval["registration"]["git_blob_sha1"] = git_blob_sha1(pinned_spec_raw)
        approval["registration"]["canonical_lf_sha256"] = canonical_lf_sha256_path(sandbox.spec_path)

        mutated = sandbox.spec_path.read_text(encoding="utf-8")
        needle = "archive_access_authorized: false"
        if needle not in mutated:
            pytest.fail(f"expected {needle!r} in sandbox spec")
        mutated = mutated.replace(needle, "archive_access_authorized: true", 1)
        sandbox.spec_path.write_bytes(mutated.replace("\n", "\r\n").encode("utf-8"))

        with pytest.raises(stop_error) as exc:
            validate_pre_data_approval(
                sandbox,
                approval_record=approval,
                first_archive_get_at=None,
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
