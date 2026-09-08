"""NCBI LitVar2 line-delimited mapping-record parsing.

LitVar2's gene-search endpoint returns one Python-literal `dict` per line
(e.g. `{'_id': 'litvar@rs121907954##', 'pmids_count': 3, 'rsid':
'rs121907954'}`), not JSON and not one JSON array. `parse_gene_mappings`
decodes each line with `ast.literal_eval` ONLY -- it never calls `eval`/
`exec`, and `ast.literal_eval` itself refuses to construct anything beyond
literal strings/numbers/containers, so an arbitrary-code-execution payload
(e.g. a `__import__(...)` call expression) raises instead of running.

Every record is required to carry exactly `{"_id", "rsid", "pmids_count"}`
with the right types; `rsid` must match `rs\\d+`. Records are deduplicated
by `rsid`, keeping the first occurrence, PROVIDED every duplicate agrees on
`pmids_count`; a duplicate `rsid` with a conflicting `pmids_count` is a hard
parse failure, never silently resolved by picking one side.
"""
from __future__ import annotations

import ast
import re
from typing import Any

_RSID_PATTERN = re.compile(r"^rs\d+$")
_REQUIRED_FIELDS = frozenset({"_id", "rsid", "pmids_count"})


class LitVarParseError(ValueError):
    """Raised when a LitVar2 line-delimited mapping record cannot be safely
    parsed, is missing/has extra fields, has a malformed value, or conflicts
    with an already-seen record for the same `rsid`."""


def _parse_line(line: str, *, line_number: int) -> dict[str, Any]:
    try:
        record = ast.literal_eval(line)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
        raise LitVarParseError(
            f"line {line_number} is not a safe Python literal mapping: {exc}"
        ) from exc

    if not isinstance(record, dict):
        raise LitVarParseError(
            f"line {line_number} does not decode to a mapping record; got "
            f"{type(record).__name__}"
        )
    if set(record) != _REQUIRED_FIELDS:
        raise LitVarParseError(
            f"line {line_number} does not have the exact required fields "
            f"{sorted(_REQUIRED_FIELDS)!r}: got {sorted(record)!r}"
        )

    record_id = record["_id"]
    rsid = record["rsid"]
    pmids_count = record["pmids_count"]

    if not isinstance(record_id, str) or not record_id:
        raise LitVarParseError(f"line {line_number} has a malformed '_id' value: {record_id!r}")
    if not isinstance(rsid, str) or not _RSID_PATTERN.match(rsid):
        raise LitVarParseError(f"line {line_number} has a malformed rsid value: {rsid!r}")
    if not isinstance(pmids_count, int) or isinstance(pmids_count, bool):
        raise LitVarParseError(
            f"line {line_number} has a malformed pmids_count value: {pmids_count!r}"
        )

    return {"_id": record_id, "rsid": rsid, "pmids_count": pmids_count}


def parse_gene_mappings(payload: str) -> list[dict[str, Any]]:
    """Parse a LitVar2 gene-search line-delimited payload into a stable,
    rsid-deduplicated list of `{"_id", "rsid", "pmids_count"}` records
    (original first-seen order preserved). Raises `LitVarParseError` on any
    unsafe/malformed line, a malformed `rsid`, or a duplicate `rsid` whose
    `pmids_count` disagrees with the first occurrence."""
    rows_by_rsid: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        record = _parse_line(line, line_number=line_number)
        rsid = record["rsid"]

        existing = rows_by_rsid.get(rsid)
        if existing is not None:
            if existing["pmids_count"] != record["pmids_count"]:
                raise LitVarParseError(
                    f"duplicate rsid {rsid!r} has conflicting pmids_count values: "
                    f"{existing['pmids_count']!r} vs {record['pmids_count']!r}"
                )
            continue  # stable dedupe: keep the first occurrence

        rows_by_rsid[rsid] = record
        order.append(rsid)

    return [rows_by_rsid[rsid] for rsid in order]


__all__ = [
    "LitVarParseError",
    "parse_gene_mappings",
]
