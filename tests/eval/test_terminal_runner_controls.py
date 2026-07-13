from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_masked_holdout_eval import (
    _require_verified_return_artifact,
    _verify_return_control_files,
)


def test_return_controls_require_scored_status_and_manifest_bound_skip_list(
    tmp_path: Path,
) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    skip.write_text("PM1\nPS4\nPP5\nBP6\n", encoding="utf-8")
    verified = {status.name: "a" * 64, skip.name: "b" * 64}

    operational, evaluation = _verify_return_control_files(
        verified,
        tmp_path,
        automatable_criteria={"PM1", "PP3"},
        declared_skips={"PM1"},
    )
    assert operational == {"PM1", "PS4", "PP5", "BP6"}
    assert evaluation == {"PM1"}


def test_return_controls_reject_blocked_status_or_unattested_skip(tmp_path: Path) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("BLOCKED_MASK_CONSERVATION\n", encoding="utf-8")
    skip.write_text("PM1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SCORED_MASKED"):
        _verify_return_control_files(
            {status.name: "a" * 64, skip.name: "b" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips={"PM1"},
        )

    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    with pytest.raises(ValueError, match="return manifest"):
        _verify_return_control_files(
            {status.name: "a" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips={"PM1"},
        )


def test_return_controls_require_operator_skip_declaration(tmp_path: Path) -> None:
    status = tmp_path / "TERMINAL_STATUS.txt"
    skip = tmp_path / "evaluation_skip_list.txt"
    status.write_text("SCORED_MASKED\n", encoding="utf-8")
    skip.write_text("PM1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="declared skipped criteria"):
        _verify_return_control_files(
            {status.name: "a" * 64, skip.name: "b" * 64},
            tmp_path,
            automatable_criteria={"PM1"},
            declared_skips=set(),
        )


def test_consumed_scoring_artifact_must_be_the_manifest_bound_file(tmp_path: Path) -> None:
    artifact = tmp_path / "holdout.tsv"
    artifact.write_text("scored", encoding="utf-8")
    verified = {artifact.name: "a" * 64}
    _require_verified_return_artifact(verified, tmp_path, artifact, label="BIAS TSV")

    other = tmp_path / "other"
    other.mkdir()
    outside = other / artifact.name
    outside.write_text("different", encoding="utf-8")
    with pytest.raises(ValueError, match="verified return directory"):
        _require_verified_return_artifact(
            verified,
            tmp_path,
            outside,
            label="BIAS TSV",
        )
