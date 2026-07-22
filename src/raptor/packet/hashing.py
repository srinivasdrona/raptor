"""PRD-04 Task A `hashing.py` — the four canonical packet hash domains (sec 4.2/FR8).

Mirrors `scorer/report.py`'s deterministic-content-hash pattern: canonical
JSON is UTF-8, `sort_keys=True`, `separators=(",", ":")`; tuple members
serialize as lists. `evidence_core_hash` excludes narrative, comparators, and
run metadata (R-A11); `packet_envelope_hash` excludes only `run_id` and
`generated_at`. Genesis `prev_hash = "0" * 64` (FR25) for the decision-log
chain (`decision_record_hash`); Task C owns the exact record payload shape --
this module only supplies the hashing primitive.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Mapping

from .model import PacketHashError

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize(value: Any) -> Any:
    """Canonicalize a packet value object into JSON-serializable data: enums
    become their `.value`, dataclasses become field-name-keyed dicts, and
    tuple/list/frozenset collections become lists (order preserved -- callers
    are responsible for canonical ordering before this step)."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _normalize(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, frozenset)):
        return [_normalize(v) for v in value]
    return value


def _canonical_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def evidence_core_hash(packet: Any) -> str:
    """Over the immutable evidence core: identity + sorted criterion trail +
    lineage + disposition + strengths/directions + two-level provenance refs
    + direction/null_reason + signed points + exclusions/contradictions/
    missing-evidence. **Excludes** narrative, comparators, run metadata,
    review state, decisions. A corrected-track packet's real, declared
    `census_selection_stratum` field (see `raptor.packet.model`) is bound in
    only when present (non-`None`), so pre-existing (non-corrected) packets
    with `census_selection_stratum=None` hash byte-identically to before."""
    payload = {
        "identity": _normalize(packet.identity),
        "entries": _normalize(packet.entries),
        "candidate_direction": _normalize(packet.candidate_direction),
        "exclusions": _normalize(packet.exclusions),
        "contradiction": packet.contradiction,
        "quality_flags": sorted(packet.quality_flags),
        "missing_evidence": _normalize(packet.missing_evidence),
    }
    if packet.census_selection_stratum is not None:
        payload["census_selection_stratum"] = _normalize(packet.census_selection_stratum)
    return _canonical_hash(payload)


def narrative_plan_hash(plan: Any) -> str:
    """Over the canonical narrative plan (template ids + bindings) + `model`
    + `prompt_hash`. Hashes `null` when there is no plan."""
    if plan is None:
        return _canonical_hash(None)
    payload = _normalize(plan)
    for entry in payload["entries"]:
        entry["field_bindings"].sort(key=lambda b: (b["name"], b["field_path"]))
    return _canonical_hash(payload)


def packet_envelope_hash(packet: Any) -> str:
    """Over `evidence_core_hash` + `narrative_plan_hash` + the enumerated
    run-metadata pins (schema version, config/policy versions, source
    snapshot). **Excludes** only `run_id` and `generated_at` -- comparator/
    pattern/state changes create a new immutable envelope while leaving the
    evidence core unchanged. A corrected-track packet's real, declared
    `census_selection_stratum` field is bound in only when present (see
    `evidence_core_hash`)."""
    payload = {
        "evidence_core_hash": packet.evidence_core_hash,
        "narrative_plan_hash": packet.narrative_plan_hash,
        "packet_schema_version": packet.packet_schema_version,
        "run_pins": {
            "code_commit": packet.run_metadata.code_commit,
            "packet_config_sha256": packet.run_metadata.packet_config_sha256,
            "lineage_policy_sha256": packet.run_metadata.lineage_policy_sha256,
            "candidate_policy_sha256": packet.run_metadata.candidate_policy_sha256,
        },
        "source_snapshot": _normalize(packet.source_snapshot),
        "pattern_ref": _normalize(packet.pattern_ref) if packet.pattern_ref is not None else None,
        "external_comparators": _normalize(packet.external_comparators),
        "review_state": packet.review_state.value,
        "gate_status": packet.gate_status.value,
        "predecessor_packet_id": packet.predecessor_packet_id,
        "predecessor_envelope_hash": packet.predecessor_envelope_hash,
    }
    if packet.census_selection_stratum is not None:
        payload["census_selection_stratum"] = _normalize(packet.census_selection_stratum)
    return _canonical_hash(payload)


def decision_record_hash(prev_hash: str, record_payload: Mapping[str, object]) -> str:
    """`sha256(prev_hash + canonical(record_payload))`; `prev_hash` must be
    lowercase hex-64 (genesis `"0" * 64`, FR25). Task C owns the exact record
    payload shape -- this accepts any canonical mapping so it does not invent
    the Task-C record shape early."""
    if not isinstance(prev_hash, str) or not _HEX64_RE.fullmatch(prev_hash):
        raise PacketHashError(f"decision_record_hash: prev_hash must be lowercase hex-64, got {prev_hash!r}")
    blob = prev_hash + json.dumps(record_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
