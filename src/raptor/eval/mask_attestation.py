"""Fail-closed verification of the held-out ClinVar source-mask ledgers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MaskAttestationError(ValueError):
    """Raised when the mask/remask ledgers do not prove exact conservation."""


@dataclass(frozen=True)
class MaskAttestation:
    holdout_count: int
    removed_count: int
    zero_survivors: bool
    manifest_sha256: str
    ledger_sha256: str
    remask_audit_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, *, name: str) -> dict[str, Any]:
    if not path.is_file():
        raise MaskAttestationError(f"{name} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MaskAttestationError(f"{name} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise MaskAttestationError(f"{name} root must be a JSON object: {path}")
    return payload


def _manifest_ids(path: Path) -> frozenset[str]:
    if not path.is_file():
        raise MaskAttestationError(f"holdout manifest does not exist: {path}")
    identities: list[str] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise MaskAttestationError(f"holdout manifest line {line_no} is invalid JSON") from exc
        identity = row.get("variant_id") if isinstance(row, dict) else None
        if not isinstance(identity, str) or not identity:
            raise MaskAttestationError(
                f"holdout manifest line {line_no} lacks a non-blank variant_id"
            )
        identities.append(identity)
    if len(identities) != len(set(identities)):
        raise MaskAttestationError("holdout manifest contains duplicate variant_id values")
    if not identities:
        raise MaskAttestationError("holdout manifest is empty")
    return frozenset(identities)


def _int_field(payload: dict[str, Any], field: str, *, name: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MaskAttestationError(f"{name}.{field} must be a non-negative integer")
    return value


def _identity_set(payload: dict[str, Any], field: str, *, name: str) -> frozenset[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise MaskAttestationError(f"{name}.{field} must be a list of non-blank strings")
    if len(value) != len(set(value)):
        raise MaskAttestationError(f"{name}.{field} contains duplicate identities")
    return frozenset(value)


def verify_mask_attestation(
    manifest_path: str | Path,
    ledger_path: str | Path,
    remask_audit_path: str | Path,
) -> MaskAttestation:
    """Prove exact first-pass removal and zero held-out survivors on re-mask."""
    manifest = Path(manifest_path)
    ledger_file = Path(ledger_path)
    remask_file = Path(remask_audit_path)
    holdout_ids = _manifest_ids(manifest)
    ledger = _load_json_object(ledger_file, name="mask ledger")
    remask = _load_json_object(remask_file, name="remask audit")

    input_records = _int_field(ledger, "input_records", name="mask ledger")
    output_records = _int_field(ledger, "output_records", name="mask ledger")
    removed_count = _int_field(ledger, "matched_records_removed", name="mask ledger")
    removed_ids = _identity_set(
        ledger, "matched_holdout_identities", name="mask ledger"
    )
    absent_ids = _identity_set(
        ledger, "holdout_identities_not_present", name="mask ledger"
    )
    if absent_ids:
        raise MaskAttestationError(
            f"mask ledger did not find {len(absent_ids)} held-out identities"
        )
    if removed_ids != holdout_ids or removed_count != len(holdout_ids):
        raise MaskAttestationError(
            "mask ledger removed identities/count do not exactly equal the holdout manifest"
        )
    if output_records != input_records - removed_count:
        raise MaskAttestationError("mask ledger row conservation failed")

    remask_input = _int_field(remask, "input_records", name="remask audit")
    remask_output = _int_field(remask, "output_records", name="remask audit")
    remask_removed = _int_field(remask, "matched_records_removed", name="remask audit")
    remask_removed_ids = _identity_set(
        remask, "matched_holdout_identities", name="remask audit"
    )
    remask_absent_ids = _identity_set(
        remask, "holdout_identities_not_present", name="remask audit"
    )
    if remask_input != output_records or remask_output != remask_input:
        raise MaskAttestationError("remask audit row conservation/input continuity failed")
    if remask_removed != 0 or remask_removed_ids:
        raise MaskAttestationError("remask audit found held-out survivor rows")
    if remask_absent_ids != holdout_ids:
        raise MaskAttestationError(
            "remask audit absent-identity set does not exactly equal the holdout manifest"
        )

    return MaskAttestation(
        holdout_count=len(holdout_ids),
        removed_count=removed_count,
        zero_survivors=True,
        manifest_sha256=_sha256(manifest),
        ledger_sha256=_sha256(ledger_file),
        remask_audit_sha256=_sha256(remask_file),
    )
