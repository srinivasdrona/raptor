"""PRD-04 Task C `decisions.py` — the variant-scoped append-only hash-chained
decision log (sec 4.9 FR25, AC11/AC23).

There is **exactly one** decision log per canonical variant identity, spanning
**all** packet versions of that variant. Its path is deterministic from the
canonical variant identity -- `<root>/<sha256(canonical_spdi)>.jsonl` --
**never** a raw/unsafe identity string. Every reviewer decision, independent
decision, pattern-policy approval, supersession, comparator reveal, and
reconciliation event for every version of that variant appends to this one
log. Genesis `prev_hash` is 64 lowercase zero characters; a duplicate
`record_id` with an identical payload is a no-op, a duplicate `record_id`
with a divergent payload fails loud (`DecisionLogConflictError`). A writer
holds an OS exclusive lock over a dedicated sibling lock file and performs
append -> flush -> `os.fsync` while the lock is held. `replay` reconstructs
and verifies the one linear chain; any tamper (edited payload, reordered /
inserted record, cross-variant record, or unsafe path) fails loud
(`DecisionLogTamperError`).

This module writes no PRD-03-style qualified-classification row -- that
surface is out of scope this increment; every decision-log event lands only
in this one packet-owned log.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

if sys.platform == "win32":  # pragma: no cover - platform specific
    import msvcrt
else:  # pragma: no cover - platform specific
    import fcntl

from .hashing import decision_record_hash

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
# PRD-04 sec 4.10 canonical GRCh38 SPDI syntax (mirrors build.py's identity
# check; duplicated here because build.py's regex is module-private and this
# module must not import Task-A internals).
_SPDI_RE = re.compile(r"^NC_[0-9]{6}\.[0-9]+:[0-9]+:([ACGTN]*):([ACGTN]*)$")
_GENESIS_HASH = "0" * 64


class DecisionLogError(ValueError):
    """Base error for a malformed decision-log call (bad `record_id`, bad
    `DecisionDraft`, or an unaddressable variant identity)."""


class DecisionLogConflictError(DecisionLogError):
    """Same `record_id` appended twice with a different canonical payload
    (FR25 idempotency -- fails loud rather than silently overwriting)."""


class DecisionLogTamperError(DecisionLogError):
    """`replay` detected a fork, gap, hash mismatch, reorder/insert, a
    cross-variant record, or a raw/unsafe log path (FR25/AC23)."""


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _is_canonical_spdi(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _SPDI_RE.fullmatch(value)
    if match is None:
        return False
    deleted, inserted = match.group(1), match.group(2)
    return bool(deleted or inserted)


def _valid_confidence(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool) or not isinstance(value, float):
        return False
    return 0.0 <= value <= 1.0


class DecisionEventType(Enum):
    REVIEWER_DECISION = "reviewer_decision"
    INDEPENDENT_DECISION = "independent_decision"
    PATTERN_POLICY_APPROVAL = "pattern_policy_approval"
    SUPERSESSION = "supersession"
    COMPARATOR_REVEAL = "comparator_reveal"
    RECONCILIATION = "reconciliation"


class ActorRole(Enum):
    OPERATOR = "operator"
    QUALIFIED_MOLECULAR_GENETICIST = "qualified_molecular_geneticist"
    VCEP_CURATOR = "vcep_curator"
    SYSTEM = "system"


def _validate_common_fields(
    *,
    label: str,
    variant_id: object,
    packet_id: object,
    evidence_core_hash: object,
    event_type: object,
    actor_id: object,
    actor_role: object,
    timestamp: object,
    decision: object,
    rationale: object,
    confidence: object,
    supersedes_packet_id: object,
    supersedes_envelope_hash: object,
) -> None:
    if not _is_canonical_spdi(variant_id):
        raise DecisionLogError(f"{label}.variant_id must be a canonical SPDI string; got {variant_id!r}")
    if not _is_hex64(packet_id):
        raise DecisionLogError(f"{label}.packet_id must be lowercase hex-64; got {packet_id!r}")
    if not _is_hex64(evidence_core_hash):
        raise DecisionLogError(f"{label}.evidence_core_hash must be lowercase hex-64; got {evidence_core_hash!r}")
    if not isinstance(event_type, DecisionEventType):
        raise DecisionLogError(f"{label}.event_type must be a DecisionEventType; got {event_type!r}")
    if not _non_blank(actor_id):
        raise DecisionLogError(f"{label}.actor_id must be non-blank; got {actor_id!r}")
    if not isinstance(actor_role, ActorRole):
        raise DecisionLogError(f"{label}.actor_role must be an ActorRole; got {actor_role!r}")
    if not _non_blank(timestamp):
        raise DecisionLogError(f"{label}.timestamp must be non-blank; got {timestamp!r}")
    if not _non_blank(decision):
        raise DecisionLogError(f"{label}.decision must be non-blank; got {decision!r}")
    if not _non_blank(rationale):
        raise DecisionLogError(f"{label}.rationale must be non-blank; got {rationale!r}")
    if not _valid_confidence(confidence):
        raise DecisionLogError(f"{label}.confidence must be null or a float in [0, 1]; got {confidence!r}")
    if supersedes_packet_id is not None and not _is_hex64(supersedes_packet_id):
        raise DecisionLogError(
            f"{label}.supersedes_packet_id must be null or lowercase hex-64; got {supersedes_packet_id!r}"
        )
    if supersedes_envelope_hash is not None and not _is_hex64(supersedes_envelope_hash):
        raise DecisionLogError(
            f"{label}.supersedes_envelope_hash must be null or lowercase hex-64; got {supersedes_envelope_hash!r}"
        )
    if (supersedes_packet_id is None) != (supersedes_envelope_hash is None):
        raise DecisionLogError(
            f"{label} supersedes_packet_id/supersedes_envelope_hash must both be null or both be set"
        )


@dataclass(frozen=True)
class DecisionDraft:
    """A caller-authored, not-yet-appended decision-log entry (FR25). Task C
    validates every field before it can reach the log -- never silently
    coerced, never partially filled."""

    variant_id: str
    packet_id: str
    evidence_core_hash: str
    event_type: DecisionEventType
    actor_id: str
    actor_role: ActorRole
    timestamp: str
    decision: str
    rationale: str
    confidence: Optional[float]
    supersedes_packet_id: Optional[str]
    supersedes_envelope_hash: Optional[str]

    def __post_init__(self) -> None:
        _validate_common_fields(
            label="DecisionDraft",
            variant_id=self.variant_id,
            packet_id=self.packet_id,
            evidence_core_hash=self.evidence_core_hash,
            event_type=self.event_type,
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            timestamp=self.timestamp,
            decision=self.decision,
            rationale=self.rationale,
            confidence=self.confidence,
            supersedes_packet_id=self.supersedes_packet_id,
            supersedes_envelope_hash=self.supersedes_envelope_hash,
        )


@dataclass(frozen=True)
class DecisionLogRecord:
    """One appended, hash-chained decision-log row (FR25). `record_hash =
    sha256(prev_hash + canonical(record minus prev_hash/record_hash))`."""

    record_id: str
    variant_id: str
    packet_id: str
    evidence_core_hash: str
    event_type: DecisionEventType
    actor_id: str
    actor_role: ActorRole
    timestamp: str
    decision: str
    rationale: str
    confidence: Optional[float]
    supersedes_packet_id: Optional[str]
    supersedes_envelope_hash: Optional[str]
    prev_hash: str
    record_hash: str

    def __post_init__(self) -> None:
        if not _is_canonical_uuid(self.record_id):
            raise DecisionLogError(f"DecisionLogRecord.record_id must be a canonical UUID; got {self.record_id!r}")
        _validate_common_fields(
            label="DecisionLogRecord",
            variant_id=self.variant_id,
            packet_id=self.packet_id,
            evidence_core_hash=self.evidence_core_hash,
            event_type=self.event_type,
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            timestamp=self.timestamp,
            decision=self.decision,
            rationale=self.rationale,
            confidence=self.confidence,
            supersedes_packet_id=self.supersedes_packet_id,
            supersedes_envelope_hash=self.supersedes_envelope_hash,
        )
        if not _is_hex64(self.prev_hash):
            raise DecisionLogError(f"DecisionLogRecord.prev_hash must be lowercase hex-64; got {self.prev_hash!r}")
        if not _is_hex64(self.record_hash):
            raise DecisionLogError(
                f"DecisionLogRecord.record_hash must be lowercase hex-64; got {self.record_hash!r}"
            )


@dataclass(frozen=True)
class DecisionHistory:
    """The full replayed history of one canonical variant's decision log,
    spanning every packet version (FR25)."""

    variant_id: Optional[str]
    records: Tuple[DecisionLogRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        for record in self.records:
            if not isinstance(record, DecisionLogRecord):
                raise DecisionLogError("DecisionHistory.records must contain only DecisionLogRecord")
        if not self.records:
            return
        if self.variant_id != self.records[0].variant_id:
            raise DecisionLogError("DecisionHistory.variant_id must match its records' variant_id")
        for record in self.records:
            if record.variant_id != self.variant_id:
                raise DecisionLogError("DecisionHistory.records must all share one variant_id")


def decision_log_path(root: "str | Path", variant_identity: str) -> Path:
    """`<root>/<sha256(canonical_spdi)>.jsonl` (FR25) -- never a raw/unsafe
    identity string; `variant_identity` must already be canonical SPDI."""
    if not _is_canonical_spdi(variant_identity):
        raise DecisionLogError(
            f"decision_log_path requires a canonical SPDI variant identity; got {variant_identity!r}"
        )
    digest = hashlib.sha256(variant_identity.encode("utf-8")).hexdigest()
    return Path(root) / f"{digest}.jsonl"


def _canonical_payload(record_id: str, draft: DecisionDraft) -> dict:
    return {
        "record_id": record_id,
        "variant_id": draft.variant_id,
        "packet_id": draft.packet_id,
        "evidence_core_hash": draft.evidence_core_hash,
        "event_type": draft.event_type.value,
        "actor_id": draft.actor_id,
        "actor_role": draft.actor_role.value,
        "timestamp": draft.timestamp,
        "decision": draft.decision,
        "rationale": draft.rationale,
        "confidence": draft.confidence,
        "supersedes_packet_id": draft.supersedes_packet_id,
        "supersedes_envelope_hash": draft.supersedes_envelope_hash,
    }


def _read_rows(log_path: Path) -> list:
    if not log_path.is_file():
        return []
    text = log_path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


_ROW_KEYS = frozenset({
    "record_id", "variant_id", "packet_id", "evidence_core_hash", "event_type",
    "actor_id", "actor_role", "timestamp", "decision", "rationale", "confidence",
    "supersedes_packet_id", "supersedes_envelope_hash", "prev_hash", "record_hash",
})


def _record_from_row(row: object) -> DecisionLogRecord:
    """Strictly parse one raw JSON row into a `DecisionLogRecord`; any schema
    violation is treated as tamper (used only by `replay`, which must fail
    loud rather than silently skip a malformed row)."""
    if not isinstance(row, dict) or set(row.keys()) != _ROW_KEYS:
        raise DecisionLogTamperError(f"decision log record has an invalid schema: {row!r}")
    try:
        event_type = DecisionEventType(row["event_type"])
    except ValueError as exc:
        raise DecisionLogTamperError(f"decision log record has an unknown event_type: {row['event_type']!r}") from exc
    try:
        actor_role = ActorRole(row["actor_role"])
    except ValueError as exc:
        raise DecisionLogTamperError(f"decision log record has an unknown actor_role: {row['actor_role']!r}") from exc
    try:
        return DecisionLogRecord(
            record_id=row["record_id"],
            variant_id=row["variant_id"],
            packet_id=row["packet_id"],
            evidence_core_hash=row["evidence_core_hash"],
            event_type=event_type,
            actor_id=row["actor_id"],
            actor_role=actor_role,
            timestamp=row["timestamp"],
            decision=row["decision"],
            rationale=row["rationale"],
            confidence=row["confidence"],
            supersedes_packet_id=row["supersedes_packet_id"],
            supersedes_envelope_hash=row["supersedes_envelope_hash"],
            prev_hash=row["prev_hash"],
            record_hash=row["record_hash"],
        )
    except DecisionLogError as exc:
        raise DecisionLogTamperError(str(exc)) from exc


def _lock_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.name + ".lock")


def _acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    if os.fstat(handle.fileno()).st_size == 0:
        handle.write(b"0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)
    if sys.platform == "win32":  # pragma: no cover - platform specific
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:  # pragma: no cover - platform specific
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_lock(handle) -> None:
    try:
        handle.seek(0)
        if sys.platform == "win32":  # pragma: no cover - platform specific
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - platform specific
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _validate_append_address(log_path: Path, draft: DecisionDraft) -> None:
    """Validate, under the exclusive lock and before any append/idempotency
    decision, that `draft.variant_id` is a canonical SPDI and that
    `log_path`'s filename/stem is that variant's one deterministic address
    (`sha256(variant_id)+'.jsonl'`); a caller must never be allowed to graft
    one variant's decision onto another variant's log (FR25/AC23)."""
    if not _is_canonical_spdi(draft.variant_id):
        raise DecisionLogError(
            f"append_decision requires draft.variant_id to be a canonical SPDI; got {draft.variant_id!r}"
        )
    expected_name = hashlib.sha256(draft.variant_id.encode("utf-8")).hexdigest() + ".jsonl"
    if log_path.name != expected_name:
        raise DecisionLogError(
            f"append_decision requires log_path {log_path.name!r} to be draft.variant_id's own address "
            f"{expected_name!r}"
        )


def _same_packet_record(row: dict, draft: DecisionDraft) -> bool:
    return (
        row.get("variant_id") == draft.variant_id
        and row.get("packet_id") == draft.packet_id
        and row.get("evidence_core_hash") == draft.evidence_core_hash
    )


def _validate_event_order(existing_rows: list[dict], draft: DecisionDraft) -> None:
    if draft.event_type is DecisionEventType.COMPARATOR_REVEAL:
        qualifying_roles = {
            ActorRole.QUALIFIED_MOLECULAR_GENETICIST.value,
            ActorRole.VCEP_CURATOR.value,
        }
        has_independent_decision = any(
            _same_packet_record(row, draft)
            and row.get("event_type") == DecisionEventType.INDEPENDENT_DECISION.value
            and row.get("actor_role") in qualifying_roles
            and row.get("confidence") is not None
            for row in existing_rows
        )
        has_prior_reveal = any(
            _same_packet_record(row, draft)
            and row.get("event_type") == DecisionEventType.COMPARATOR_REVEAL.value
            for row in existing_rows
        )
        if not has_independent_decision or has_prior_reveal:
            raise DecisionLogError(
                "comparator_reveal requires a prior same-packet qualified independent decision "
                "with confidence and no prior comparator reveal"
            )

    if draft.event_type is DecisionEventType.RECONCILIATION:
        has_prior_reveal = any(
            _same_packet_record(row, draft)
            and row.get("event_type") == DecisionEventType.COMPARATOR_REVEAL.value
            for row in existing_rows
        )
        if not has_prior_reveal:
            raise DecisionLogError(
                "reconciliation requires a prior same-packet comparator_reveal"
            )


def append_decision(log_path: "str | Path", draft: DecisionDraft, *, record_id: str) -> DecisionLogRecord:
    """Append `draft` under `record_id` (FR25). Idempotent: an existing
    record with the same `record_id` and an identical canonical payload is
    returned as-is (no second write); the same `record_id` with a different
    payload raises `DecisionLogConflictError`. Takes an OS exclusive lock over
    a sibling lock file and, while still holding it, validates the log's
    filename address and (if the log already exists and is non-empty) fully
    verifies its schema/hashes/linear chain/address/single-variant invariant
    via an internal no-relock verifier -- before any idempotency/conflict
    decision or write. Any address or existing-variant mismatch is rejected
    (`DecisionLogError`/`DecisionLogTamperError`) leaving the log's bytes
    unchanged; only then does it append -> flush -> `os.fsync` while the lock
    is held. This module never relies on a post-write `replay` to catch
    corruption -- verification happens before the write, not after."""
    if not isinstance(draft, DecisionDraft):
        raise DecisionLogError(f"append_decision requires a DecisionDraft; got {draft!r}")
    if not _is_canonical_uuid(record_id):
        raise DecisionLogError(f"append_decision requires a canonical UUID record_id; got {record_id!r}")

    log_path = Path(log_path)
    lock_handle = _acquire_lock(_lock_path(log_path))
    try:
        _validate_append_address(log_path, draft)
        existing_rows = _read_rows(log_path)
        if existing_rows:
            history = _verify_replayed_rows(log_path, existing_rows)
            if history.variant_id != draft.variant_id:
                raise DecisionLogError(
                    f"append_decision draft.variant_id {draft.variant_id!r} does not match the existing "
                    f"decision log's variant_id {history.variant_id!r}"
                )

        payload = _canonical_payload(record_id, draft)

        for row in existing_rows:
            if row.get("record_id") != record_id:
                continue
            existing_payload = {k: v for k, v in row.items() if k not in ("prev_hash", "record_hash")}
            if existing_payload == payload:
                return DecisionLogRecord(
                    record_id=record_id,
                    variant_id=draft.variant_id,
                    packet_id=draft.packet_id,
                    evidence_core_hash=draft.evidence_core_hash,
                    event_type=draft.event_type,
                    actor_id=draft.actor_id,
                    actor_role=draft.actor_role,
                    timestamp=draft.timestamp,
                    decision=draft.decision,
                    rationale=draft.rationale,
                    confidence=draft.confidence,
                    supersedes_packet_id=draft.supersedes_packet_id,
                    supersedes_envelope_hash=draft.supersedes_envelope_hash,
                    prev_hash=row["prev_hash"],
                    record_hash=row["record_hash"],
                )
            raise DecisionLogConflictError(
                f"record_id {record_id!r} already exists in {log_path} with a different payload"
            )

        _validate_event_order(existing_rows, draft)

        prev_hash = existing_rows[-1]["record_hash"] if existing_rows else _GENESIS_HASH
        if not isinstance(prev_hash, str) or not _HEX64_RE.fullmatch(prev_hash):
            raise DecisionLogTamperError(f"decision log {log_path} has a malformed prior record_hash")
        record_hash = decision_record_hash(prev_hash, payload)

        row = dict(payload)
        row["prev_hash"] = prev_hash
        row["record_hash"] = record_hash

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        return DecisionLogRecord(
            record_id=record_id,
            variant_id=draft.variant_id,
            packet_id=draft.packet_id,
            evidence_core_hash=draft.evidence_core_hash,
            event_type=draft.event_type,
            actor_id=draft.actor_id,
            actor_role=draft.actor_role,
            timestamp=draft.timestamp,
            decision=draft.decision,
            rationale=draft.rationale,
            confidence=draft.confidence,
            supersedes_packet_id=draft.supersedes_packet_id,
            supersedes_envelope_hash=draft.supersedes_envelope_hash,
            prev_hash=prev_hash,
            record_hash=record_hash,
        )
    finally:
        _release_lock(lock_handle)


def _verify_replayed_rows(log_path: Path, rows: list) -> DecisionHistory:
    """Fully verify already-read rows for one decision log and reconstruct
    its `DecisionHistory` (FR25/AC23). Takes no lock and re-acquires none --
    it is the internal no-relock verifier shared by `replay` (which owns no
    lock) and `append_decision` (which calls this while still holding its
    exclusive lock, avoiding deadlock). An empty row list is an empty
    history. A non-empty row list is verified: filename addressing
    (`sha256(variant_id)`), one shared `variant_id`, row schema, UUID
    `record_id`s, genesis `prev_hash`, one linear `prev_hash` chain, and
    every `record_hash` -- any violation raises `DecisionLogTamperError`."""
    if not rows:
        return DecisionHistory(variant_id=None, records=())

    variant_id = rows[0].get("variant_id") if isinstance(rows[0], dict) else None
    if not _is_canonical_spdi(variant_id):
        raise DecisionLogTamperError(f"decision log {log_path} has a malformed variant_id: {variant_id!r}")

    expected_name = hashlib.sha256(variant_id.encode("utf-8")).hexdigest() + ".jsonl"
    if log_path.name != expected_name:
        raise DecisionLogTamperError(
            f"decision log path {log_path.name!r} does not match sha256(variant_id) address {expected_name!r}"
        )

    records = []
    prev_hash = _GENESIS_HASH
    for index, row in enumerate(rows):
        record = _record_from_row(row)
        if record.variant_id != variant_id:
            raise DecisionLogTamperError(
                f"decision log record {index} binds variant_id {record.variant_id!r}, expected {variant_id!r}"
            )
        if record.prev_hash != prev_hash:
            raise DecisionLogTamperError(f"decision log record {index} breaks the linear prev_hash chain")
        payload = {k: v for k, v in row.items() if k not in ("prev_hash", "record_hash")}
        expected_hash = decision_record_hash(record.prev_hash, payload)
        if record.record_hash != expected_hash:
            raise DecisionLogTamperError(f"decision log record {index} record_hash does not match its payload")
        records.append(record)
        prev_hash = record.record_hash

    return DecisionHistory(variant_id=variant_id, records=tuple(records))


def replay(log_path: "str | Path") -> DecisionHistory:
    """Reconstruct the full decision history for one variant (FR25/AC23).
    An empty/missing log is an empty history. A non-empty log is verified:
    filename addressing (`sha256(variant_id)`), one shared `variant_id`,
    row schema, UUID `record_id`s, genesis `prev_hash`, one linear
    `prev_hash` chain, and every `record_hash` -- any violation raises
    `DecisionLogTamperError`."""
    log_path = Path(log_path)
    return _verify_replayed_rows(log_path, _read_rows(log_path))
