from __future__ import annotations

import json
from pathlib import Path

import pytest

from raptor.eval.mask_attestation import MaskAttestationError, verify_mask_attestation


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_mask_attestation_requires_exact_removal_and_zero_survivors(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            [
                json.dumps({"variant_id": "NC_1:1:A:G"}),
                json.dumps({"variant_id": "NC_1:2:C:T"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.json"
    _write_json(
        ledger,
        {
            "input_records": 10,
            "output_records": 8,
            "matched_records_removed": 2,
            "matched_holdout_identities": ["NC_1:1:A:G", "NC_1:2:C:T"],
            "holdout_identities_not_present": [],
        },
    )
    remask = tmp_path / "remask.json"
    _write_json(
        remask,
        {
            "input_records": 8,
            "output_records": 8,
            "matched_records_removed": 0,
            "matched_holdout_identities": [],
            "holdout_identities_not_present": ["NC_1:1:A:G", "NC_1:2:C:T"],
        },
    )

    attestation = verify_mask_attestation(manifest, ledger, remask)
    assert attestation.holdout_count == 2
    assert attestation.removed_count == 2
    assert attestation.zero_survivors is True


def test_mask_attestation_fails_on_missing_removal_or_survivor(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"variant_id": "NC_1:1:A:G"}) + "\n", encoding="utf-8")
    ledger = tmp_path / "ledger.json"
    remask = tmp_path / "remask.json"
    _write_json(
        ledger,
        {
            "input_records": 2,
            "output_records": 2,
            "matched_records_removed": 0,
            "matched_holdout_identities": [],
            "holdout_identities_not_present": ["NC_1:1:A:G"],
        },
    )
    _write_json(
        remask,
        {
            "input_records": 2,
            "output_records": 1,
            "matched_records_removed": 1,
            "matched_holdout_identities": ["NC_1:1:A:G"],
            "holdout_identities_not_present": [],
        },
    )

    with pytest.raises(MaskAttestationError):
        verify_mask_attestation(manifest, ledger, remask)
