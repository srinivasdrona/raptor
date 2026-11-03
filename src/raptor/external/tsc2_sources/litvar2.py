"""NCBI LitVar2 line-delimited mapping-record parsing.

LitVar2's gene-search endpoint returns one Python-literal `dict` per line
(e.g. `{'_id': 'litvar@rs121907954##', 'pmids_count': 3, 'rsid':
'rs121907954'}`), not JSON and not one JSON array. `parse_gene_mappings`
decodes each line with `ast.literal_eval` ONLY -- it never calls `eval`/
`exec`, and `ast.literal_eval` itself refuses to construct anything beyond
literal strings/numbers/containers, so an arbitrary-code-execution payload
(e.g. a `__import__(...)` call expression) raises instead of running.

Every record is required to carry `_id` and `pmids_count`. `rsid` and
`clingen_id` are OPTIONAL; any other field is an unknown extra and is a hard
parse failure -- even when `clingen_id` itself is present and valid. When
present, `rsid` must match `rs\\d+`; an explicit `rsid: None` is treated the
same as an absent `rsid`. When present, `clingen_id` must be a nonblank
string. A record's OUTPUT is always projected down to exactly `{"_id",
"rsid", "pmids_count"}`, with `rsid` set to `None` when absent
(`clingen_id`, when present on input, is never propagated to the returned
record).

Identity resolution (LitVar2 emits the same underlying variant under several
`_id` shapes):

* Records without an `rsid` are retained by their unique `_id`. Multiple
  input lines sharing the same `_id` (and no `rsid`) may be deduplicated only
  when every one of them projects to the exact same `{"_id", "rsid",
  "pmids_count"}` value; any disagreement (e.g. a conflicting `pmids_count`)
  fails closed rather than silently picking one side.
* Records that share an `rsid` form one alias group. If the group contains a
  unique canonical aggregate record -- `_id == f"litvar@{rsid}##"` with no
  `clingen_id` -- that record is retained and every other ("alias") record in
  the group must have `pmids_count <= canonical pmids_count`; a larger alias
  count fails closed. Multiple candidate canonical records are only
  tolerated when they are exact duplicates (identical `pmids_count`); any
  disagreement between them fails closed rather than arbitrarily picking
  one.
* If no canonical record exists and the group has exactly one member, that
  sole record is retained. If no canonical record exists and multiple
  records compete, the group is ambiguous and parsing fails closed.

The first-seen order of identity groups (whether a rsid-less `_id` or an
`rsid` alias group) is preserved in the returned list.
"""
from __future__ import annotations

import ast
import re
from typing import Any

_RSID_PATTERN = re.compile(r"^rs\d+$")
_REQUIRED_FIELDS = frozenset({"_id", "pmids_count"})
_OPTIONAL_FIELDS = frozenset({"rsid", "clingen_id"})
_ALLOWED_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS


class LitVarParseError(ValueError):
    """Raised when a LitVar2 line-delimited mapping record cannot be safely
    parsed, is missing a required field or carries an unknown extra field
    (beyond the optional `rsid`/`clingen_id`), has a malformed value, or
    conflicts with another record in the same identity group (duplicate
    `_id` with disagreeing projected values, a malformed/ambiguous `rsid`
    alias group, or a conflicting canonical aggregate record)."""


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

    record_keys = set(record)
    missing = _REQUIRED_FIELDS - record_keys
    extra = record_keys - _ALLOWED_FIELDS
    if missing or extra:
        raise LitVarParseError(
            f"line {line_number} does not have the exact required fields "
            f"{sorted(_REQUIRED_FIELDS)!r} (optional: {sorted(_OPTIONAL_FIELDS)!r}): "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r} got={sorted(record_keys)!r}"
        )

    record_id = record["_id"]
    pmids_count = record["pmids_count"]

    if not isinstance(record_id, str) or not record_id.strip():
        raise LitVarParseError(f"line {line_number} has a malformed '_id' value: {record_id!r}")
    if not isinstance(pmids_count, int) or isinstance(pmids_count, bool):
        raise LitVarParseError(
            f"line {line_number} has a malformed pmids_count value: {pmids_count!r}"
        )
    if pmids_count < 0:
        raise LitVarParseError(
            f"line {line_number} has a negative pmids_count value: {pmids_count!r}"
        )

    rsid: str | None = None
    if "rsid" in record and record["rsid"] is not None:
        candidate_rsid = record["rsid"]
        if not isinstance(candidate_rsid, str) or not _RSID_PATTERN.match(candidate_rsid):
            raise LitVarParseError(
                f"line {line_number} has a malformed rsid value: {candidate_rsid!r}"
            )
        rsid = candidate_rsid

    has_clingen_id = False
    if "clingen_id" in record:
        candidate_clingen_id = record["clingen_id"]
        if not isinstance(candidate_clingen_id, str) or not candidate_clingen_id.strip():
            raise LitVarParseError(
                f"line {line_number} has a malformed clingen_id value: {candidate_clingen_id!r}"
            )
        has_clingen_id = True

    # Project the parsed record down to exactly the three committed fields --
    # an accepted optional clingen_id is validated above but never bundled.
    # `has_clingen_id` is carried alongside for canonical-aggregate identity
    # resolution and is never part of the returned projection.
    return {
        "_id": record_id,
        "rsid": rsid,
        "pmids_count": pmids_count,
        "has_clingen_id": has_clingen_id,
    }


def _project(record: dict[str, Any]) -> dict[str, Any]:
    return {"_id": record["_id"], "rsid": record["rsid"], "pmids_count": record["pmids_count"]}


def _resolve_rsidless_group(record_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    projected = [_project(record) for record in records]
    first = projected[0]
    for other in projected[1:]:
        if other != first:
            raise LitVarParseError(
                f"duplicate rsid-less _id {record_id!r} has conflicting projected values: "
                f"{first!r} vs {other!r}"
            )
    return first


def _resolve_rsid_group(rsid: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    canonical_id = f"litvar@{rsid}##"
    canonical_indices = [
        index
        for index, record in enumerate(records)
        if record["_id"] == canonical_id and not record["has_clingen_id"]
    ]

    if canonical_indices:
        canonical = records[canonical_indices[0]]
        for index in canonical_indices[1:]:
            duplicate = records[index]
            if duplicate["pmids_count"] != canonical["pmids_count"]:
                raise LitVarParseError(
                    f"rsid {rsid!r} has multiple conflicting canonical aggregate records: "
                    f"pmids_count {canonical['pmids_count']!r} vs {duplicate['pmids_count']!r}"
                )

        canonical_index_set = set(canonical_indices)
        for index, alias in enumerate(records):
            if index in canonical_index_set:
                continue
            if alias["pmids_count"] > canonical["pmids_count"]:
                raise LitVarParseError(
                    f"rsid {rsid!r} alias pmids_count {alias['pmids_count']!r} exceeds "
                    f"canonical pmids_count {canonical['pmids_count']!r}"
                )
        return _project(canonical)

    if len(records) == 1:
        return _project(records[0])

    raise LitVarParseError(
        f"rsid {rsid!r} has multiple ambiguous non-canonical records with no unique "
        "canonical aggregate record to prefer"
    )


def parse_gene_mappings(payload: str) -> list[dict[str, Any]]:
    """Parse a LitVar2 gene-search line-delimited payload into a stable list
    of `{"_id", "rsid", "pmids_count"}` records, with identity groups (a
    rsid-less `_id` or a shared `rsid` alias group) resolved per the module
    docstring rules and returned in first-seen group order. Raises
    `LitVarParseError` on any unsafe/malformed line, an unknown field, a
    malformed `rsid`/`clingen_id`, a conflicting duplicate `_id`, or an
    unresolved/ambiguous `rsid` alias group."""
    order: list[tuple[str, str]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        record = _parse_line(line, line_number=line_number)
        key = ("rsid", record["rsid"]) if record["rsid"] is not None else ("id", record["_id"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(record)

    results: list[dict[str, Any]] = []
    for kind, ident in order:
        records = groups[(kind, ident)]
        if kind == "id":
            results.append(_resolve_rsidless_group(ident, records))
        else:
            results.append(_resolve_rsid_group(ident, records))
    return results


__all__ = [
    "LitVarParseError",
    "parse_gene_mappings",
]
