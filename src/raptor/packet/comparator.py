"""PRD-04 Task C `comparator.py` — the reveal-only AAVC comparator envelope
(sec 4.11 FR27, AC17/AC20).

`attach_comparator` appends an `ExternalComparator` to a packet's envelope
(never its evidence core -- `evidence_core_hash` is unchanged) and returns a
new immutable packet version; the same comparator id attached twice is a
no-op, a different comparator payload under the same id fails loud. AAVC is
already stripped from the `FIRST_PASS` view by Task-A's
`redact_for_first_pass`. `reveal_allowed`/`reveal` enforce decision-before-
reveal: a reviewer (QMG/VCEP) must record an `independent_decision` with a
non-null confidence, bound to this exact packet/evidence-core, before any
`comparator_reveal` -- and a reveal never fires twice. AAVC never enters
criteria, the candidate-direction policy, or grounding; this module only
reveals a comparator already bound to the full packet. `comparator_reveal_verified`
is the read-side counterpart `render.py` uses to gate the RECONCILIATION
view's comparator fields on a hash-chain-verified `DecisionHistory` carrying
a matching `COMPARATOR_REVEAL` record, rather than trusting a caller-supplied
boolean.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Tuple

import yaml

from .decisions import (
    ActorRole,
    DecisionDraft,
    DecisionEventType,
    DecisionHistory,
    DecisionLogRecord,
    append_decision,
    replay,
)
from .hashing import decision_record_hash, packet_envelope_hash
from .model import CandidateEvidencePacket, ExternalComparator

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_DECISION_GENESIS_HASH = "0" * 64


class ComparatorConfigError(ValueError):
    """A malformed/unknown-field `configs/packet/comparator.yaml`, or an
    internally inconsistent `ComparatorConfig`."""


class ComparatorRevealError(ValueError):
    """A comparator was attached/revealed in violation of FR27: a
    conflicting duplicate `comparator_id`, or a reveal attempted without a
    prior qualifying independent decision (or after one already occurred)."""


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


@dataclass(frozen=True)
class ComparatorConfig:
    """The pinned AAVC source envelope (FR27): DOI + archive checksum +
    repository commit + the match-method vocabulary this deployment
    accepts."""

    config_version: str
    source_name: str
    source_snapshot: str
    source_doi: str
    source_archive_sha256: str
    source_commit: str
    match_methods: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "config_version", "source_name", "source_snapshot", "source_doi", "source_commit",
        ):
            if not _non_blank(getattr(self, name)):
                raise ComparatorConfigError(f"ComparatorConfig.{name} must be non-blank")
        if not _is_hex64(self.source_archive_sha256):
            raise ComparatorConfigError("ComparatorConfig.source_archive_sha256 must be lowercase hex-64")
        object.__setattr__(self, "match_methods", tuple(self.match_methods))
        if not self.match_methods:
            raise ComparatorConfigError("ComparatorConfig.match_methods must be non-empty")
        seen = set()
        for method in self.match_methods:
            if not _non_blank(method):
                raise ComparatorConfigError(f"ComparatorConfig.match_methods entries must be non-blank; got {method!r}")
            if method in seen:
                raise ComparatorConfigError(f"ComparatorConfig.match_methods has a duplicate entry: {method!r}")
            seen.add(method)


_COMPARATOR_REQUIRED_KEYS = frozenset({
    "config_version",
    "source_name",
    "source_snapshot",
    "source_doi",
    "source_archive_sha256",
    "source_commit",
    "match_methods",
})


def _require_str(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ComparatorConfigError(f"comparator config {key!r} must be a non-blank string, got {value!r}")
    return value


def load_comparator_config(path: "str | Path") -> ComparatorConfig:
    """Strictly load + schema-validate `configs/packet/comparator.yaml`
    (exactly the seven `ComparatorConfig` keys; unknown/missing keys fail
    loud)."""
    raw_path = Path(path)
    if not raw_path.is_file():
        raise ComparatorConfigError(f"comparator config not found: {raw_path}")
    raw = yaml.safe_load(raw_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ComparatorConfigError(f"comparator config root must be a mapping, got {type(raw).__name__}")
    keys = set(raw.keys())
    unknown = keys - _COMPARATOR_REQUIRED_KEYS
    if unknown:
        raise ComparatorConfigError(f"comparator config has unknown key(s): {sorted(unknown)!r}")
    missing = _COMPARATOR_REQUIRED_KEYS - keys
    if missing:
        raise ComparatorConfigError(f"comparator config is missing key(s): {sorted(missing)!r}")

    raw_methods = raw.get("match_methods")
    if not isinstance(raw_methods, (list, tuple)) or not raw_methods:
        raise ComparatorConfigError("comparator config 'match_methods' must be a non-empty list")
    methods = []
    for item in raw_methods:
        if not isinstance(item, str) or not item.strip():
            raise ComparatorConfigError(f"comparator config match_methods entries must be non-blank strings, got {item!r}")
        methods.append(item)

    return ComparatorConfig(
        config_version=_require_str(raw, "config_version"),
        source_name=_require_str(raw, "source_name"),
        source_snapshot=_require_str(raw, "source_snapshot"),
        source_doi=_require_str(raw, "source_doi"),
        source_archive_sha256=_require_str(raw, "source_archive_sha256"),
        source_commit=_require_str(raw, "source_commit"),
        match_methods=tuple(methods),
    )


def attach_comparator(
    packet: CandidateEvidencePacket, comparator: ExternalComparator
) -> CandidateEvidencePacket:
    """Return a new immutable packet version carrying `comparator` in its
    envelope; `evidence_core_hash` and every evidence-core field (`entries`,
    `candidate_direction`, ...) are unchanged. Attaching an already-present,
    identical comparator is a no-op; a different payload under the same
    `comparator_id` fails loud."""
    if not isinstance(packet, CandidateEvidencePacket):
        raise ComparatorRevealError(f"attach_comparator requires a CandidateEvidencePacket; got {packet!r}")
    if not isinstance(comparator, ExternalComparator):
        raise ComparatorRevealError(f"attach_comparator requires an ExternalComparator; got {comparator!r}")

    for existing in packet.external_comparators:
        if existing.comparator_id == comparator.comparator_id:
            if existing == comparator:
                return packet
            raise ComparatorRevealError(
                f"comparator_id {comparator.comparator_id!r} is already attached with a different payload"
            )

    draft = replace(
        packet,
        external_comparators=packet.external_comparators + (comparator,),
        predecessor_packet_id=packet.packet_id,
        predecessor_envelope_hash=packet.packet_envelope_hash,
        packet_id="",
        packet_envelope_hash="",
    )
    new_hash = packet_envelope_hash(draft)
    return replace(draft, packet_id=new_hash, packet_envelope_hash=new_hash)


_QUALIFYING_REVEAL_ROLES = frozenset({ActorRole.QUALIFIED_MOLECULAR_GENETICIST, ActorRole.VCEP_CURATOR})


def reveal_allowed(packet: CandidateEvidencePacket, history: DecisionHistory) -> bool:
    """True iff `history` carries an `independent_decision` for this exact
    `packet_id`/`evidence_core_hash`, by a QMG/VCEP, with a non-null
    confidence, and carries **no** prior `comparator_reveal` for the same
    packet/core (FR27 decision-before-reveal, at most once)."""
    if not isinstance(packet, CandidateEvidencePacket) or not isinstance(history, DecisionHistory):
        return False

    has_qualifying_decision = False
    for record in history.records:
        if (
            record.packet_id == packet.packet_id
            and record.evidence_core_hash == packet.evidence_core_hash
        ):
            if record.event_type is DecisionEventType.COMPARATOR_REVEAL:
                return False
            if (
                record.event_type is DecisionEventType.INDEPENDENT_DECISION
                and record.actor_role in _QUALIFYING_REVEAL_ROLES
                and record.confidence is not None
            ):
                has_qualifying_decision = True
    return has_qualifying_decision


def _decision_record_payload(record: DecisionLogRecord) -> dict:
    """Reconstruct the exact canonical JSON payload `decisions.py` hashed for
    `record` -- every field except `prev_hash`/`record_hash` -- so a
    `record_hash` can be independently recomputed from an already-parsed
    `DecisionLogRecord`. `decisions.py`'s own row-hash verifier
    (`_verify_replayed_rows`) is private and only operates on raw JSON rows,
    not on already-constructed `DecisionHistory`/`DecisionLogRecord`
    instances, so `render.py`'s reveal gate needs this reconstruction to
    re-verify a `DecisionHistory` handed to it by a caller."""
    return {
        "record_id": record.record_id,
        "variant_id": record.variant_id,
        "packet_id": record.packet_id,
        "evidence_core_hash": record.evidence_core_hash,
        "event_type": record.event_type.value,
        "actor_id": record.actor_id,
        "actor_role": record.actor_role.value,
        "timestamp": record.timestamp,
        "decision": record.decision,
        "rationale": record.rationale,
        "confidence": record.confidence,
        "supersedes_packet_id": record.supersedes_packet_id,
        "supersedes_envelope_hash": record.supersedes_envelope_hash,
    }


def _verify_decision_history_chain(history: DecisionHistory) -> None:
    """Independently recompute `history.records`' linear
    prev_hash/record_hash chain from genesis (FR25/AC23), regardless of how
    `history` was constructed. `DecisionHistory.__post_init__` only checks
    shape (one shared `variant_id`, `DecisionLogRecord` element types) -- a
    hand-built history with individually well-formed records but a
    fabricated or discontinuous hash chain (e.g. a forged `COMPARATOR_REVEAL`
    row) passes that shape check but is rejected here. Raises
    `ComparatorRevealError` on any break."""
    prev_hash = _DECISION_GENESIS_HASH
    for index, record in enumerate(history.records):
        if record.prev_hash != prev_hash:
            raise ComparatorRevealError(
                f"decision history record {index} breaks the linear prev_hash chain"
            )
        expected_hash = decision_record_hash(prev_hash, _decision_record_payload(record))
        if record.record_hash != expected_hash:
            raise ComparatorRevealError(
                f"decision history record {index} record_hash does not match its recomputed payload hash"
            )
        prev_hash = record.record_hash


def comparator_reveal_verified(packet: CandidateEvidencePacket, history: DecisionHistory) -> bool:
    """True iff `history` is a hash-chain-verified `DecisionHistory` (its
    linear prev_hash/record_hash chain independently re-verified by
    `_verify_decision_history_chain`, so a hand-built/forged history cannot
    pass) for this exact canonical variant (`packet.identity.canonical_spdi`)
    and it carries a `COMPARATOR_REVEAL` record bound to this exact
    `packet_id` and `evidence_core_hash` (FR27). Used by `render.py` to gate
    the RECONCILIATION comparator reveal on a verified recorded decision
    rather than a caller-supplied boolean. Raises `ComparatorRevealError` if
    the history's own hash chain does not verify (forged/tampered); returns
    `False` for a merely missing, empty, or non-matching (but internally
    consistent) history."""
    if not isinstance(packet, CandidateEvidencePacket) or not isinstance(history, DecisionHistory):
        return False
    if not history.records or history.variant_id != packet.identity.canonical_spdi:
        return False

    _verify_decision_history_chain(history)

    qualifying_roles = {
        ActorRole.QUALIFIED_MOLECULAR_GENETICIST,
        ActorRole.VCEP_CURATOR,
    }
    independent_decision_seen = False
    for record in history.records:
        same_packet = (
            record.packet_id == packet.packet_id
            and record.evidence_core_hash == packet.evidence_core_hash
            and record.variant_id == packet.identity.canonical_spdi
        )
        if (
            same_packet
            and record.event_type is DecisionEventType.INDEPENDENT_DECISION
            and record.actor_role in qualifying_roles
            and record.confidence is not None
        ):
            independent_decision_seen = True
        if same_packet and record.event_type is DecisionEventType.COMPARATOR_REVEAL:
            return independent_decision_seen
    return False


def reveal(
    log_path: "str | Path",
    packet: CandidateEvidencePacket,
    *,
    actor_id: str,
    actor_role: ActorRole,
    timestamp: str,
    record_id: str,
) -> DecisionLogRecord:
    """Replay `log_path`, require `reveal_allowed`, and append a
    `comparator_reveal` record for `packet`; raises `ComparatorRevealError`
    when decision-before-reveal is not satisfied (no qualifying decision, or
    an existing reveal already fired)."""
    history = replay(log_path)
    if not reveal_allowed(packet, history):
        raise ComparatorRevealError(
            "comparator reveal requires a prior independent decision with confidence and no existing reveal"
        )

    draft = DecisionDraft(
        variant_id=packet.identity.canonical_spdi,
        packet_id=packet.packet_id,
        evidence_core_hash=packet.evidence_core_hash,
        event_type=DecisionEventType.COMPARATOR_REVEAL,
        actor_id=actor_id,
        actor_role=actor_role,
        timestamp=timestamp,
        decision="reveal",
        rationale="AAVC comparator reveal following a qualifying independent decision",
        confidence=None,
        supersedes_packet_id=None,
        supersedes_envelope_hash=None,
    )
    return append_decision(log_path, draft, record_id=record_id)
