"""Tests for the real, committed `configs/acmg/strength_policy.yaml` --
the (deliberately unapproved) owner-decision policy for track
`strength-policy-2026-07`. Confirms the file loads against the real
ladder + real scorer vocab, stays fail-closed end-to-end, and never
inflates a strength via `cap`.
"""
from __future__ import annotations

from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.strength_policy import (
    STRENGTH_RANK,
    apply_strength_policy,
    load_strength_ladder,
    load_strength_policy,
)

LADDER_PATH = "configs/eval/bias_strength_ladder.yaml"
POLICY_PATH = "configs/acmg/strength_policy.yaml"
SCORER_CONFIG_PATH = "configs/acmg/tsc.yaml"


def _load_real_policy():
    ladder = load_strength_ladder(LADDER_PATH)
    scorer_config = load_scorer_config(SCORER_CONFIG_PATH)
    scorer_strength_vocab = {
        criterion: tuple(spec["strength_vocab"])
        for criterion, spec in scorer_config.acmg_criteria.items()
        if criterion in ladder.criteria
    }
    policy = load_strength_policy(POLICY_PATH, ladder=ladder, scorer_strength_vocab=scorer_strength_vocab)
    return ladder, policy


def test_real_strength_policy_is_unapproved_and_fail_closed():
    _, policy = _load_real_policy()
    assert policy.status == "unapproved"
    assert policy.owner_approved is False
    assert policy.is_active is False
    assert policy.default_disposition == "manual"


def test_real_strength_policy_exhaustively_covers_the_real_ladder():
    ladder, policy = _load_real_policy()
    for criterion, strengths in ladder.criteria.items():
        assert set(policy.records[criterion]) == set(strengths)


def test_real_strength_policy_cap_never_inflates():
    ladder, policy = _load_real_policy()
    for criterion, per_strength in policy.records.items():
        for strength, record in per_strength.items():
            if record.disposition == "cap":
                assert record.emit is not None
                assert STRENGTH_RANK[record.emit] < STRENGTH_RANK[strength]
            if record.disposition == "accept":
                assert record.emit == strength
            if record.disposition in ("manual", "forbid"):
                assert record.emit is None


def test_real_strength_policy_every_call_routes_manual_while_unapproved():
    """End-to-end fail-closed confirmation: no matter what disposition a
    real record configures, an unapproved policy must force `manual` for
    every (criterion, strength) pair on the ladder."""
    ladder, policy = _load_real_policy()
    record = {"variant_id": "17:1:A:G", "gene_name": "TSC2"}
    for criterion, strengths in ladder.criteria.items():
        for strength in strengths:
            call = {"criterion": criterion, "strength": strength, "direction": "pathogenic", "rationale": ""}
            decision = apply_strength_policy(record=record, call=call, policy=policy)
            assert decision.disposition == "manual"
            assert decision.emitted_call is None
            assert decision.manual_record == record


def test_real_strength_policy_ps1_and_bs1_supporting_have_no_accept_target():
    """Corrections vs. the planner's card text (see
    docs/reference/acmg-strength-policy-2026-07.md §6): PS1-moderate and
    BS1-supporting have no schema-valid `accept`/`cap` target under the
    current vocab -- both must be configured `manual`, never `accept`."""
    _, policy = _load_real_policy()
    assert policy.records["PS1"]["moderate"].disposition == "manual"
    assert policy.records["BS1"]["supporting"].disposition == "manual"


def test_real_strength_policy_open_owner_forks_stay_neutral_manual():
    """Checker finding (2026-07-13, gpt-5.6-sol code-review, strength-policy
    track): both flagged owner forks -- PM4 supporting
    (`pm4-supporting-vocab-widening-or-forbid`) and BP4 strong/very_strong
    (`bp4-elevated-cap-vs-forbid`) -- must resolve to the SAME neutral
    `manual` disposition with `recommended_disposition == "manual"`. Neither
    may pre-select one side of its fork (e.g. BP4 must not silently default
    to `cap`), since that would let a blanket-approval of this file activate
    an outcome the owner never explicitly chose."""
    _, policy = _load_real_policy()
    fork_records = [
        policy.records["PM4"]["supporting"],
        policy.records["BP4"]["strong"],
        policy.records["BP4"]["very_strong"],
    ]
    for record in fork_records:
        assert record.disposition == "manual"
        assert record.recommended_disposition == "manual"


def test_real_strength_policy_pm2_strong_caps_to_moderate_not_supporting():
    _, policy = _load_real_policy()
    record = policy.records["PM2"]["strong"]
    assert record.disposition == "cap"
    assert record.emit == "moderate"
