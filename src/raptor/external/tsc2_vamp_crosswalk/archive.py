"""Zenodo TSC2 analysis V1 archive validation and GMM identity-table
parsing for the VAMP-seq genomic crosswalk.

``validate_zenodo_archive_and_extract_members`` verifies the ENTIRE
downloaded archive's byte length/sha256/md5 against ``expected_archive``
BEFORE ever attempting to open it as a zip (a corrupted/substituted
archive fails fast on its raw bytes, never on a zip-parsing exception).
Every zip member name is then swept for path-traversal/absolute-path/
drive-qualified unsafety and for a symlink entry (an ``external_attr``
Unix file-mode with the ``S_IFLNK`` bit set) BEFORE any member is read --
this sweep runs across the WHOLE archive, not merely the required
members, so a decoy/malicious entry sitting alongside the two real GMM
tables is rejected outright. A duplicate member name anywhere in the
archive is likewise rejected. Only the exact ``required_members`` paths
are then extracted, each independently byte-length/sha256/md5-verified
against its own pin.

``parse_gmm_identity_rows`` parses the two extracted GMM TSV members
(library1 then library2, in that fixed order, regardless of the input
mapping's own key order) into a flat list of identity records: only
``required_columns`` are ever read (every other column -- abundance, GMM
density, clinical, population, predictor, evidence-code -- is completely
ignored and never enters the returned rows or any downstream artifact),
every ``required_values`` pin (gene/chromosome/RefSeq transcript/Ensembl
transcript) must match exactly, real CRLF line endings are handled via
``str.splitlines()`` (never left embedded in a value), a numeric
``hg38_start``/``hg38_end`` coordinate carrying a trailing ``.0`` (a
common TSV float-serialization artifact) is truncated to its integer
value, and ``hgvs_p``/``hgvs_c`` must be unique across BOTH members
combined -- a duplicate of either is a fatal archive-integrity violation,
never silently deduplicated.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

#: Canonical, fixed member processing order -- archive-file ordering never
#: controls output row ordering beyond this fixed library1-then-library2
#: sequence (spec ``join_contract.source_order`` governs the FINAL
#: crosswalk row order, which follows the frozen SCORE file, not this).
_MEMBER_ORDER = ("library1", "library2")


class ArchiveValidationError(ValueError):
    """Raised for any Zenodo-archive or GMM-member integrity violation:
    a byte-length/sha256/md5 mismatch (archive or member), a zip
    traversal/absolute/drive-qualified member name, a symlink entry, a
    duplicate member name, a missing/misnamed required member, a missing
    required GMM column, a required-value (gene/chromosome/transcript)
    mismatch, or a duplicate ``hgvs_p``/``hgvs_c`` across the two GMM
    members."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _md5(payload: bytes) -> str:
    return hashlib.md5(payload).hexdigest()  # nosec B303 - matching pinned upstream MD5


def _assert_safe_zip_member_name(name: str) -> None:
    if not isinstance(name, str) or not name or name.startswith("/") or name.startswith("\\"):
        raise ArchiveValidationError(f"unsafe zip member name (blank/absolute path): {name!r}")
    posix = PurePosixPath(name)
    if posix.is_absolute() or any(part in (".", "..") for part in posix.parts):
        raise ArchiveValidationError(f"unsafe zip member name (path traversal): {name!r}")
    if PureWindowsPath(name).drive:
        raise ArchiveValidationError(f"unsafe zip member name (drive-qualified path): {name!r}")


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """A Unix zip entry's external_attr packs the file mode into its high
    16 bits (the same layout ``os.stat().st_mode`` uses) -- ``S_IFLNK``
    (``0o120000``) there marks a symlink whose "content" is an arbitrary
    (attacker-controlled) target path, never a real GMM TSV payload."""
    unix_mode = info.external_attr >> 16
    return (unix_mode & 0o170000) == 0o120000


def validate_zenodo_archive_and_extract_members(
    *,
    archive_bytes: bytes,
    expected_archive: dict[str, Any],
    required_members: dict[str, dict[str, Any]],
) -> dict[str, bytes]:
    """Verify ``archive_bytes`` against ``expected_archive``'s
    ``byte_length``/``sha256``/``md5`` pins, sweep every zip member name
    for path-traversal/symlink/duplicate unsafety, then extract and
    independently verify each ``required_members`` entry's own
    ``byte_length``/``sha256``/``md5`` pin. Returns ``{member_key:
    extracted_bytes}`` (e.g. ``{"library1": ..., "library2": ...}``).
    Raises ``ArchiveValidationError`` on any violation; the archive is
    NEVER opened as a zip if its own raw-byte pins do not already match."""
    if not isinstance(archive_bytes, bytes):
        raise ArchiveValidationError(f"archive_bytes must be bytes, got {type(archive_bytes).__name__}")
    if len(archive_bytes) != expected_archive["byte_length"]:
        raise ArchiveValidationError(
            f"archive byte_length mismatch: expected {expected_archive['byte_length']!r}, observed "
            f"{len(archive_bytes)!r}"
        )
    actual_sha256 = _sha256(archive_bytes)
    if actual_sha256.lower() != str(expected_archive["sha256"]).lower():
        raise ArchiveValidationError(
            f"archive sha256 mismatch: expected {expected_archive['sha256']!r}, observed {actual_sha256!r}"
        )
    actual_md5 = _md5(archive_bytes)
    if actual_md5.lower() != str(expected_archive["md5"]).lower():
        raise ArchiveValidationError(
            f"archive md5 mismatch: expected {expected_archive['md5']!r}, observed {actual_md5!r}"
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ArchiveValidationError(f"archive is not a valid zip file: {exc}") from exc

    with zf:
        infolist = zf.infolist()
        seen_names: set[str] = set()
        for info in infolist:
            _assert_safe_zip_member_name(info.filename)
            if _is_symlink_entry(info):
                raise ArchiveValidationError(f"archive member is a symlink entry, refusing: {info.filename!r}")
            if info.filename in seen_names:
                raise ArchiveValidationError(f"archive contains a duplicate member name: {info.filename!r}")
            seen_names.add(info.filename)

        extracted: dict[str, bytes] = {}
        for member_key, member_pin in required_members.items():
            member_path = member_pin["path"]
            if member_path not in seen_names:
                raise ArchiveValidationError(
                    f"required member {member_key!r} not found at pinned path {member_path!r}"
                )
            payload = zf.read(member_path)
            if len(payload) != member_pin["byte_length"]:
                raise ArchiveValidationError(
                    f"required member {member_key!r} byte_length mismatch: expected "
                    f"{member_pin['byte_length']!r}, observed {len(payload)!r}"
                )
            member_sha256 = _sha256(payload)
            if member_sha256.lower() != str(member_pin["sha256"]).lower():
                raise ArchiveValidationError(
                    f"required member {member_key!r} sha256 mismatch: expected {member_pin['sha256']!r}, "
                    f"observed {member_sha256!r}"
                )
            member_md5 = _md5(payload)
            if member_md5.lower() != str(member_pin["md5"]).lower():
                raise ArchiveValidationError(
                    f"required member {member_key!r} md5 mismatch: expected {member_pin['md5']!r}, "
                    f"observed {member_md5!r}"
                )
            extracted[member_key] = payload

    return extracted


def _parse_coordinate(value: str, *, member_key: str, row_index: int, column: str) -> int:
    """Parse a GMM ``hg38_start``/``hg38_end`` value -- a bare integer
    string OR a numeric string carrying a trailing ``.0`` float-
    serialization artifact -- into a real 1-based int coordinate."""
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise ArchiveValidationError(
            f"{member_key} row {row_index}: {column} {value!r} is not numeric"
        ) from exc
    as_int = int(as_float)
    if as_int != as_float:
        raise ArchiveValidationError(
            f"{member_key} row {row_index}: {column} {value!r} is not an integral coordinate"
        )
    return as_int


def parse_gmm_identity_rows(
    *,
    members: dict[str, bytes],
    required_columns: list[str],
    required_values: dict[str, str],
) -> list[dict[str, Any]]:
    """Parse the ``library1``/``library2`` GMM TSV members (in that FIXED
    order) into identity records: ``{"archive_member", "archive_row",
    "protein_variant" (bare ``hgvs_p``), "hgvs_c" (bare), "ref_allele",
    "alt_allele", "source_start", "source_end"}``. Every non-required
    column is ignored entirely. Raises ``ArchiveValidationError`` on a
    missing required column, a ``required_values`` mismatch, or a
    duplicate ``hgvs_p``/``hgvs_c`` anywhere across both members."""
    all_rows: list[dict[str, Any]] = []
    seen_hgvs_p: set[str] = set()
    seen_hgvs_c: set[str] = set()

    for member_key in _MEMBER_ORDER:
        if member_key not in members:
            continue
        payload = members[member_key]
        text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        # str.splitlines() normalizes \n/\r\n/\r uniformly and never
        # leaves a stray \r embedded in any parsed value.
        lines = [line for line in text.splitlines() if line != ""]
        if not lines:
            raise ArchiveValidationError(f"{member_key}: GMM member is empty")
        header = lines[0].split("\t")
        missing_columns = [column for column in required_columns if column not in header]
        if missing_columns:
            raise ArchiveValidationError(f"{member_key}: missing required column(s) {missing_columns!r}")

        for row_index, line in enumerate(lines[1:], start=1):
            values = line.split("\t")
            if len(values) != len(header):
                raise ArchiveValidationError(
                    f"{member_key} row {row_index}: has {len(values)} fields, expected {len(header)}"
                )
            record = dict(zip(header, values))
            for column, expected_value in required_values.items():
                if record.get(column) != expected_value:
                    raise ArchiveValidationError(
                        f"{member_key} row {row_index}: {column} {record.get(column)!r} does not match "
                        f"the pinned expectation {expected_value!r}"
                    )

            hgvs_p = record["hgvs_p"]
            hgvs_c = record["hgvs_c"]
            if hgvs_p in seen_hgvs_p:
                raise ArchiveValidationError(f"duplicate hgvs_p across GMM members: {hgvs_p!r}")
            seen_hgvs_p.add(hgvs_p)
            if hgvs_c in seen_hgvs_c:
                raise ArchiveValidationError(f"duplicate hgvs_c across GMM members: {hgvs_c!r}")
            seen_hgvs_c.add(hgvs_c)

            source_start = _parse_coordinate(record["hg38_start"], member_key=member_key, row_index=row_index, column="hg38_start")
            source_end = _parse_coordinate(record["hg38_end"], member_key=member_key, row_index=row_index, column="hg38_end")

            all_rows.append(
                {
                    "archive_member": member_key,
                    "archive_row": row_index,
                    "protein_variant": hgvs_p,
                    "hgvs_c": hgvs_c,
                    "ref_allele": record["ref_allele"],
                    "alt_allele": record["alt_allele"],
                    "source_start": source_start,
                    "source_end": source_end,
                }
            )

    return all_rows


__all__ = [
    "ArchiveValidationError",
    "validate_zenodo_archive_and_extract_members",
    "parse_gmm_identity_rows",
]
