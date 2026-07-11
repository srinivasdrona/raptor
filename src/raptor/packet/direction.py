"""PRD-04 Task A `direction.py` — the production candidate-direction policy.

`compute_candidate_direction` is a **review** direction, never a
classification, and never the eval-only Tavtigian combiner: it sums signed
points over `included` criteria under the injected, config-pinned
`CandidateDirectionPolicy` (FR5). An unapproved policy always yields a null
direction (`null_reason="production_policy_unapproved"`) -- the eval combiner
never becomes a production oracle (Slot-3 failure mode 6). This module
imports no `raptor.eval.combine`.
"""
from __future__ import annotations

from typing import Sequence

from .config import CandidateDirectionPolicy
from .model import (
    CandidateDirection,
    DirectionPolicyError,
    PacketPolicyDisposition,
    PointContribution,
)

_UNAPPROVED_NULL_REASON = "production_policy_unapproved"
_LP_REVIEW = "candidate_LP_review"
_LB_REVIEW = "candidate_LB_review"
_NO_DETERMINISTIC_RESOLUTION = "no_deterministic_resolution"


def compute_candidate_direction(
    entries: Sequence, policy: CandidateDirectionPolicy
) -> CandidateDirection:
    """Signed sum under the **production** policy, scoring only `included`
    entries whose criterion+strength pair exists in
    `criterion_strength_points`; an included unknown pair raises
    `DirectionPolicyError`. Returns `null`/`null_reason` when the policy is
    unapproved. Sum `>= candidate_lp_min` -> `candidate_LP_review`; sum
    `<= candidate_lb_max` -> `candidate_LB_review`; otherwise
    `no_deterministic_resolution`."""
    if policy is None:
        raise DirectionPolicyError("compute_candidate_direction requires a CandidateDirectionPolicy")

    if policy.approval_status != "approved":
        return CandidateDirection(
            direction=None,
            null_reason=_UNAPPROVED_NULL_REASON,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            approval_status=policy.approval_status,
            signed_points=None,
            per_criterion_points=(),
        )

    included = [
        entry for entry in entries
        if entry.packet_policy_disposition is PacketPolicyDisposition.INCLUDED
    ]

    contributions = []
    total = 0
    for entry in included:
        strength_points = policy.criterion_strength_points.get(entry.criterion)
        points = strength_points.get(entry.strength) if strength_points is not None else None
        if points is None:
            raise DirectionPolicyError(
                f"no candidate-direction points configured for included criterion "
                f"{entry.criterion!r}/strength {entry.strength!r}"
            )
        total += points
        contributions.append(
            PointContribution(criterion=entry.criterion, strength=entry.strength, points=points)
        )

    contributions.sort(key=lambda c: (c.criterion, c.strength))

    if policy.candidate_lp_min is not None and total >= policy.candidate_lp_min:
        direction = _LP_REVIEW
    elif policy.candidate_lb_max is not None and total <= policy.candidate_lb_max:
        direction = _LB_REVIEW
    else:
        direction = _NO_DETERMINISTIC_RESOLUTION

    return CandidateDirection(
        direction=direction,
        null_reason=None,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        approval_status=policy.approval_status,
        signed_points=total,
        per_criterion_points=tuple(contributions),
    )
