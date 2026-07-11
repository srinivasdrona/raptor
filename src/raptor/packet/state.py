"""PRD-04 Task C `state.py` — the fail-closed packet review-state machine
(sec 4.5 FR15/FR15.1, AC10/AC15/AC18).

`PacketStateMachine` implements the exact §4.5 transition table (T1-T10):
every transition is mechanically decidable over the packet + a
`TransitionContext`. `production_policy_unapproved` (a null
`candidate_direction`) is a `POLICY_BLOCKED` guard; `READY_FOR_EXPERT_REVIEW`
and every later candidate-direction approval / external state (T3/T4/T6/T9)
require a non-null `candidate_direction` -- a fact read from the **packet**,
never a caller-asserted context flag (no context can launder an unapproved
packet into a promotable one). A successful transition never mutates its
source packet: it returns a **new** frozen packet version with the
predecessor bound to the old packet's id/envelope hash and a freshly
recomputed envelope hash/packet id (`hashing.packet_envelope_hash`).

Pattern-level approval has no state-machine API here: it is only a
`decisions.DecisionEventType.PATTERN_POLICY_APPROVAL` log record and executes
no transition on any member variant (FR18/AC16).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Tuple

from .decisions import ActorRole
from .hashing import packet_envelope_hash
from .model import (
    CandidateEvidencePacket,
    GateStatus,
    PacketPolicyDisposition,
    PrimaryGrounding,
    ReviewState,
)

_HEX64_LEN = 64


class StateTransitionError(ValueError):
    """No authorized §4.5 transition exists from the packet's current
    `review_state` to the requested target under the given context."""


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == _HEX64_LEN and all(
        c in "0123456789abcdef" for c in value
    )


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class ReviewerSignoff:
    """One reviewer's signed decision, bound to the exact packet version it
    was recorded against (FR15.1). Distinctness for T8/T9 is enforced by
    `reviewer_id`."""

    reviewer_id: str
    role: ActorRole
    decision: str
    packet_id: str

    def __post_init__(self) -> None:
        if not _non_blank(self.reviewer_id):
            raise StateTransitionError(f"ReviewerSignoff.reviewer_id must be non-blank; got {self.reviewer_id!r}")
        if not isinstance(self.role, ActorRole):
            raise StateTransitionError(f"ReviewerSignoff.role must be an ActorRole; got {self.role!r}")
        if not _non_blank(self.decision):
            raise StateTransitionError(f"ReviewerSignoff.decision must be non-blank; got {self.decision!r}")
        if not _is_hex64(self.packet_id):
            raise StateTransitionError(f"ReviewerSignoff.packet_id must be lowercase hex-64; got {self.packet_id!r}")


@dataclass(frozen=True)
class TransitionContext:
    """The mechanical guard inputs for one transition attempt (FR15.1).
    Every boolean here is the **operator's** assertion of an external fact
    (gate run, mask ruling, policy confirmation); guards that also have a
    packet-owned fact (candidate direction, per-criterion primary grounding)
    always additionally check the packet -- this context can never override
    a null/unapproved packet fact."""

    actor_id: str
    actor_role: ActorRole
    gate_status: GateStatus
    mask_ruling_complete: bool
    primary_grounding_complete: bool
    production_policy_approved: bool
    reviewers: Tuple[ReviewerSignoff, ...]
    successor_packet_id: Optional[str]
    successor_envelope_hash: Optional[str]

    def __post_init__(self) -> None:
        if not _non_blank(self.actor_id):
            raise StateTransitionError(f"TransitionContext.actor_id must be non-blank; got {self.actor_id!r}")
        if not isinstance(self.actor_role, ActorRole):
            raise StateTransitionError(f"TransitionContext.actor_role must be an ActorRole; got {self.actor_role!r}")
        if not isinstance(self.gate_status, GateStatus):
            raise StateTransitionError(f"TransitionContext.gate_status must be a GateStatus; got {self.gate_status!r}")
        for name in ("mask_ruling_complete", "primary_grounding_complete", "production_policy_approved"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise StateTransitionError(f"TransitionContext.{name} must be a bool; got {value!r}")
        object.__setattr__(self, "reviewers", tuple(self.reviewers))
        for reviewer in self.reviewers:
            if not isinstance(reviewer, ReviewerSignoff):
                raise StateTransitionError("TransitionContext.reviewers must contain only ReviewerSignoff")
        if self.successor_packet_id is not None and not _is_hex64(self.successor_packet_id):
            raise StateTransitionError(
                f"TransitionContext.successor_packet_id must be null or lowercase hex-64; "
                f"got {self.successor_packet_id!r}"
            )
        if self.successor_envelope_hash is not None and not _is_hex64(self.successor_envelope_hash):
            raise StateTransitionError(
                f"TransitionContext.successor_envelope_hash must be null or lowercase hex-64; "
                f"got {self.successor_envelope_hash!r}"
            )
        if (self.successor_packet_id is None) != (self.successor_envelope_hash is None):
            raise StateTransitionError(
                "TransitionContext.successor_packet_id/successor_envelope_hash must both be "
                "null or both be set"
            )


_BLOCKING_DISPOSITIONS = frozenset({PacketPolicyDisposition.MASKED, PacketPolicyDisposition.DEFERRED})


def _direction_approved(packet: CandidateEvidencePacket) -> bool:
    """Whether `packet.candidate_direction` is non-null -- a **packet**
    fact (only true when it was built under an approved production policy);
    no `TransitionContext` field may substitute for this."""
    return packet.candidate_direction.direction is not None


def _clean_scored_set(packet: CandidateEvidencePacket) -> bool:
    """No un-adjudicated `requires_heldout_mask`/`deferred` disposition
    remains among the packet's scored criteria (§4.5 T3/T4 guard)."""
    return all(entry.packet_policy_disposition not in _BLOCKING_DISPOSITIONS for entry in packet.entries)


def _primary_grounding_satisfied(packet: CandidateEvidencePacket) -> bool:
    """Every `primary_required` criterion has `primary_grounding=PRESENT` --
    a **packet** fact, checked independently of any
    `primary_grounding_complete` context assertion (FR4.2/AC18)."""
    return all(
        entry.primary_grounding is PrimaryGrounding.PRESENT
        for entry in packet.entries
        if entry.primary_required
    )


def _signoffs(
    packet: CandidateEvidencePacket,
    reviewers: Tuple[ReviewerSignoff, ...],
    *,
    decisions: frozenset,
) -> Tuple[ReviewerSignoff, ...]:
    """Reviewer sign-offs bound to *this* packet version, by a QMG, with one
    of the accepted `decisions` -- a forged/rebound signoff (wrong
    `packet_id`) never counts."""
    return tuple(
        reviewer for reviewer in reviewers
        if reviewer.role is ActorRole.QUALIFIED_MOLECULAR_GENETICIST
        and reviewer.packet_id == packet.packet_id
        and reviewer.decision in decisions
    )


def can_promote(
    packet: CandidateEvidencePacket,
    gate_status: GateStatus,
    reviewers: Tuple[ReviewerSignoff, ...],
) -> bool:
    """Convenience check for T9 only (FR15.1): approved non-null
    `candidate_direction`, gate `PASS`, every `primary_required` criterion
    grounded, and two **distinct** QMG `accept` sign-offs bound to this
    packet version. It cannot bypass the full `transition`/`can_transition`
    guard (mask ruling + production-policy confirmation are asserted only in
    a `TransitionContext`, not here)."""
    if not isinstance(gate_status, GateStatus) or gate_status is not GateStatus.PASS:
        return False
    if not _direction_approved(packet):
        return False
    if not _primary_grounding_satisfied(packet):
        return False
    matches = _signoffs(packet, tuple(reviewers), decisions=frozenset({"accept"}))
    distinct_reviewers = {reviewer.reviewer_id for reviewer in matches}
    return len(matches) >= 2 and len(distinct_reviewers) >= 2


def _guard_t2(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    return not _direction_approved(packet) or not _clean_scored_set(packet)


def _guard_t3_t4(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    return (
        context.actor_role is ActorRole.OPERATOR
        and _direction_approved(packet)
        and _clean_scored_set(packet)
    )


def _guard_t5(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    if context.actor_role is not ActorRole.QUALIFIED_MOLECULAR_GENETICIST:
        return False
    matches = _signoffs(
        packet, context.reviewers, decisions=frozenset({"reject", "adjust", "request-evidence"})
    )
    return len(matches) == 1


def _guard_t6(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    return (
        context.actor_role is ActorRole.OPERATOR
        and context.successor_packet_id is not None
        and context.successor_envelope_hash is not None
        and _direction_approved(packet)
        and _clean_scored_set(packet)
    )


def _guard_t7(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    if context.actor_role is not ActorRole.QUALIFIED_MOLECULAR_GENETICIST:
        return False
    if not _direction_approved(packet):
        return False
    matches = _signoffs(packet, context.reviewers, decisions=frozenset({"accept"}))
    return len(matches) == 1


def _guard_t8(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    if context.actor_role is not ActorRole.QUALIFIED_MOLECULAR_GENETICIST:
        return False
    if not _direction_approved(packet):
        return False
    matches = _signoffs(packet, context.reviewers, decisions=frozenset({"accept"}))
    distinct_reviewers = {reviewer.reviewer_id for reviewer in matches}
    return len(matches) >= 2 and len(distinct_reviewers) >= 2


def _guard_t9(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    if not context.production_policy_approved:
        return False
    if context.gate_status is not GateStatus.PASS:
        return False
    if not context.mask_ruling_complete:
        return False
    if not context.primary_grounding_complete:
        return False
    if not _primary_grounding_satisfied(packet):
        return False
    return can_promote(packet, context.gate_status, context.reviewers)


def _guard_t10(packet: CandidateEvidencePacket, context: TransitionContext) -> bool:
    return (
        context.actor_role is ActorRole.OPERATOR
        and context.successor_packet_id is not None
        and context.successor_envelope_hash is not None
    )


_TRANSITIONS = {
    (ReviewState.DRAFT_PROVISIONAL, ReviewState.POLICY_BLOCKED): _guard_t2,
    (ReviewState.DRAFT_PROVISIONAL, ReviewState.READY_FOR_EXPERT_REVIEW): _guard_t3_t4,
    (ReviewState.POLICY_BLOCKED, ReviewState.READY_FOR_EXPERT_REVIEW): _guard_t3_t4,
    (ReviewState.READY_FOR_EXPERT_REVIEW, ReviewState.EXPERT_CHANGES_REQUESTED): _guard_t5,
    (ReviewState.EXPERT_CHANGES_REQUESTED, ReviewState.READY_FOR_EXPERT_REVIEW): _guard_t6,
    (ReviewState.READY_FOR_EXPERT_REVIEW, ReviewState.EXPERT_APPROVED_INTERNAL): _guard_t7,
    (ReviewState.EXPERT_APPROVED_INTERNAL, ReviewState.SECOND_REVIEW_APPROVED): _guard_t8,
    (ReviewState.SECOND_REVIEW_APPROVED, ReviewState.EXTERNAL_SUBMISSION_READY): _guard_t9,
}

_SUPERSEDABLE = frozenset(ReviewState) - {ReviewState.SUPERSEDED}


class PacketStateMachine:
    """The §4.5 fail-closed packet review-state machine (T1-T10). Carries no
    mutable state of its own; every decision is a pure function of the
    packet + `TransitionContext`."""

    def can_transition(
        self,
        packet: CandidateEvidencePacket,
        target: ReviewState,
        context: TransitionContext,
    ) -> bool:
        if not isinstance(packet, CandidateEvidencePacket):
            return False
        if not isinstance(target, ReviewState):
            return False
        if not isinstance(context, TransitionContext):
            return False
        if target is ReviewState.SUPERSEDED:
            return packet.review_state in _SUPERSEDABLE and _guard_t10(packet, context)
        guard = _TRANSITIONS.get((packet.review_state, target))
        if guard is None:
            return False
        return guard(packet, context)

    def transition(
        self,
        packet: CandidateEvidencePacket,
        target: ReviewState,
        context: TransitionContext,
    ) -> CandidateEvidencePacket:
        """Return a **new** frozen packet version bound to `packet` as its
        predecessor, or raise `StateTransitionError` (never mutates
        `packet`)."""
        if not self.can_transition(packet, target, context):
            current = getattr(packet, "review_state", None)
            raise StateTransitionError(f"no authorized §4.5 transition from {current!r} to {target!r}")

        draft = replace(
            packet,
            review_state=target,
            gate_status=context.gate_status,
            predecessor_packet_id=packet.packet_id,
            predecessor_envelope_hash=packet.packet_envelope_hash,
            packet_id="",
            packet_envelope_hash="",
        )
        new_hash = packet_envelope_hash(draft)
        return replace(draft, packet_id=new_hash, packet_envelope_hash=new_hash)
