"""PRD-04 Task C executable contract: states, decisions, and comparator reveal."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import uuid

import pytest
import yaml

import test_packet_core as core


def _api():
    api = core._api()
    try:
        from raptor.packet.comparator import (
            ComparatorConfig,
            ComparatorConfigError,
            ComparatorRevealError,
            attach_comparator,
            load_comparator_config,
            reveal,
            reveal_allowed,
        )
        from raptor.packet.config import NarrativeCatalog, NarrativeTemplate, RenderConfig
        from raptor.packet.model import PacketView
        from raptor.packet.decisions import (
            ActorRole,
            DecisionDraft,
            DecisionEventType,
            DecisionHistory,
            DecisionLogConflictError,
            DecisionLogError,
            DecisionLogRecord,
            DecisionLogTamperError,
            append_decision,
            decision_log_path,
            replay,
        )
        from raptor.packet.state import (
            PacketStateMachine,
            ReviewerSignoff,
            StateTransitionError,
            TransitionContext,
            can_promote,
        )
        from raptor.packet.render import render_markdown
    except ImportError as exc:
        pytest.fail(f"PRD-04 Task C workflow is not implemented: {exc}")
    api.update(locals())
    return api


def _approved_packet(api):
    return api["build_packet"](
        core._packet_input(api),
        core._packet_config(api, approved=True),
    )


def _blocked_packet(api):
    return api["build_packet"](
        core._packet_input(api),
        core._packet_config(api, approved=False),
    )


def _signoff(api, packet, reviewer_id: str, decision: str = "accept"):
    return api["ReviewerSignoff"](
        reviewer_id=reviewer_id,
        role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
        decision=decision,
        packet_id=packet.packet_id,
    )


def _context(
    api,
    packet,
    *,
    role=None,
    gate=None,
    mask=True,
    primary=True,
    approved=True,
    reviewers=(),
    successor=None,
):
    return api["TransitionContext"](
        actor_id="actor-1",
        actor_role=role or api["ActorRole"].OPERATOR,
        gate_status=gate or api["GateStatus"].UNVERIFIED,
        mask_ruling_complete=mask,
        primary_grounding_complete=primary,
        production_policy_approved=approved,
        reviewers=tuple(reviewers),
        successor_packet_id=successor.packet_id if successor else None,
        successor_envelope_hash=successor.packet_envelope_hash if successor else None,
    )


def _draft(
    api,
    packet,
    *,
    event=None,
    actor_role=None,
    confidence=0.9,
    decision="accept",
    supersedes=None,
):
    return api["DecisionDraft"](
        variant_id=packet.identity.canonical_spdi,
        packet_id=packet.packet_id,
        evidence_core_hash=packet.evidence_core_hash,
        event_type=event or api["DecisionEventType"].INDEPENDENT_DECISION,
        actor_id="reviewer-1",
        actor_role=actor_role or api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
        timestamp="2026-07-11T12:00:00Z",
        decision=decision,
        rationale="independent evidence review",
        confidence=confidence,
        supersedes_packet_id=supersedes.packet_id if supersedes else None,
        supersedes_envelope_hash=supersedes.packet_envelope_hash if supersedes else None,
    )


def _record_id(number: int) -> str:
    return str(uuid.UUID(int=number))


def test_ac10_exact_state_transitions_and_reviewer_guards() -> None:
    api = _api()
    machine = api["PacketStateMachine"]()
    approved = _approved_packet(api)
    blocked = _blocked_packet(api)

    assert approved.review_state is api["ReviewState"].DRAFT_PROVISIONAL
    assert blocked.review_state is api["ReviewState"].POLICY_BLOCKED
    assert not machine.can_transition(
        blocked,
        api["ReviewState"].READY_FOR_EXPERT_REVIEW,
        _context(api, blocked, approved=True),
    )

    masked_input = replace(
        core._packet_input(api),
        criterion_inputs=(
            core._criterion_input(
                api,
                "PS1",
                "strong",
                "pathogenic",
                key="masked-ps1",
            ),
        ),
    )
    masked = api["build_packet"](
        masked_input,
        core._packet_config(api, approved=True),
    )
    assert machine.can_transition(
        masked,
        api["ReviewState"].POLICY_BLOCKED,
        _context(api, masked),
    )

    null_ready = replace(
        blocked,
        review_state=api["ReviewState"].READY_FOR_EXPERT_REVIEW,
    )
    assert not machine.can_transition(
        null_ready,
        api["ReviewState"].EXPERT_APPROVED_INTERNAL,
        _context(
            api,
            null_ready,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=(_signoff(api, null_ready, "qmg-null"),),
        ),
    )
    null_first = replace(
        blocked,
        review_state=api["ReviewState"].EXPERT_APPROVED_INTERNAL,
    )
    assert not machine.can_transition(
        null_first,
        api["ReviewState"].SECOND_REVIEW_APPROVED,
        _context(
            api,
            null_first,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=(
                _signoff(api, null_first, "qmg-null-1"),
                _signoff(api, null_first, "qmg-null-2"),
            ),
        ),
    )

    ready = machine.transition(
        approved,
        api["ReviewState"].READY_FOR_EXPERT_REVIEW,
        _context(api, approved),
    )
    assert ready.review_state is api["ReviewState"].READY_FOR_EXPERT_REVIEW
    assert ready.packet_id != approved.packet_id
    assert ready.predecessor_packet_id == approved.packet_id
    assert approved.review_state is api["ReviewState"].DRAFT_PROVISIONAL

    with pytest.raises(api["StateTransitionError"]):
        machine.transition(
            ready,
            api["ReviewState"].EXPERT_APPROVED_INTERNAL,
            _context(api, ready, role=api["ActorRole"].OPERATOR),
        )

    changes = machine.transition(
        ready,
        api["ReviewState"].EXPERT_CHANGES_REQUESTED,
        _context(
            api,
            ready,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=(_signoff(api, ready, "qmg-1", "adjust"),),
        ),
    )
    assert changes.review_state is api["ReviewState"].EXPERT_CHANGES_REQUESTED

    resubmitted_source = replace(
        approved,
        review_state=api["ReviewState"].EXPERT_CHANGES_REQUESTED,
    )
    resubmitted = machine.transition(
        resubmitted_source,
        api["ReviewState"].READY_FOR_EXPERT_REVIEW,
        _context(api, resubmitted_source, successor=approved),
    )
    assert resubmitted.review_state is api["ReviewState"].READY_FOR_EXPERT_REVIEW

    first = machine.transition(
        ready,
        api["ReviewState"].EXPERT_APPROVED_INTERNAL,
        _context(
            api,
            ready,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=(_signoff(api, ready, "qmg-1"),),
        ),
    )
    same_reviewer = (
        _signoff(api, first, "qmg-1"),
        _signoff(api, first, "qmg-1"),
    )
    assert not machine.can_transition(
        first,
        api["ReviewState"].SECOND_REVIEW_APPROVED,
        _context(
            api,
            first,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=same_reviewer,
        ),
    )
    second = machine.transition(
        first,
        api["ReviewState"].SECOND_REVIEW_APPROVED,
        _context(
            api,
            first,
            role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            reviewers=(
                _signoff(api, first, "qmg-1"),
                _signoff(api, first, "qmg-2"),
            ),
        ),
    )
    assert second.review_state is api["ReviewState"].SECOND_REVIEW_APPROVED

    successor = replace(approved, packet_id="d" * 64, packet_envelope_hash="d" * 64)
    superseded = machine.transition(
        ready,
        api["ReviewState"].SUPERSEDED,
        _context(api, ready, successor=successor),
    )
    assert superseded.review_state is api["ReviewState"].SUPERSEDED
    assert superseded.predecessor_packet_id == ready.packet_id


@pytest.mark.parametrize(
    "gate",
    ["FAIL", "UNDERPOWERED", "UNVERIFIED"],
)
def test_ac15_external_ready_rejects_every_nonpass_gate(gate: str) -> None:
    api = _api()
    packet = replace(
        _approved_packet(api),
        review_state=api["ReviewState"].SECOND_REVIEW_APPROVED,
    )
    reviewers = (_signoff(api, packet, "qmg-1"), _signoff(api, packet, "qmg-2"))
    context = _context(
        api,
        packet,
        gate=api["GateStatus"][gate],
        reviewers=reviewers,
    )

    assert not api["can_promote"](packet, context.gate_status, reviewers)
    with pytest.raises(api["StateTransitionError"]):
        api["PacketStateMachine"]().transition(
            packet,
            api["ReviewState"].EXTERNAL_SUBMISSION_READY,
            context,
        )


def test_ac15_ac18_external_ready_requires_all_independent_guards() -> None:
    api = _api()
    packet = replace(
        _approved_packet(api),
        review_state=api["ReviewState"].SECOND_REVIEW_APPROVED,
    )
    reviewers = (_signoff(api, packet, "qmg-1"), _signoff(api, packet, "qmg-2"))
    valid = _context(
        api,
        packet,
        gate=api["GateStatus"].PASS,
        reviewers=reviewers,
    )

    for changes in (
        {"mask_ruling_complete": False},
        {"primary_grounding_complete": False},
        {"production_policy_approved": False},
        {"reviewers": reviewers[:1]},
        {"reviewers": (reviewers[0], reviewers[0])},
    ):
        context = replace(valid, **changes)
        assert not api["PacketStateMachine"]().can_transition(
            packet,
            api["ReviewState"].EXTERNAL_SUBMISSION_READY,
            context,
        )

    unapproved = replace(
        _blocked_packet(api),
        review_state=api["ReviewState"].SECOND_REVIEW_APPROVED,
    )
    assert not api["PacketStateMachine"]().can_transition(
        unapproved,
        api["ReviewState"].EXTERNAL_SUBMISSION_READY,
        replace(valid, reviewers=(
            _signoff(api, unapproved, "qmg-1"),
            _signoff(api, unapproved, "qmg-2"),
        )),
    )

    external = api["PacketStateMachine"]().transition(
        packet,
        api["ReviewState"].EXTERNAL_SUBMISSION_READY,
        valid,
    )
    assert external.review_state is api["ReviewState"].EXTERNAL_SUBMISSION_READY
    assert external.gate_status is api["GateStatus"].PASS


def test_ac11_ac23_variant_log_idempotency_and_versions(tmp_path: Path) -> None:
    api = _api()
    first_packet = _approved_packet(api)
    second_packet = replace(
        first_packet,
        packet_id="e" * 64,
        packet_envelope_hash="e" * 64,
        predecessor_packet_id=first_packet.packet_id,
        predecessor_envelope_hash=first_packet.packet_envelope_hash,
    )
    log = api["decision_log_path"](
        tmp_path,
        first_packet.identity.canonical_spdi,
    )
    assert log == tmp_path / (
        hashlib.sha256(first_packet.identity.canonical_spdi.encode()).hexdigest()
        + ".jsonl"
    )

    first = api["append_decision"](
        log,
        _draft(api, first_packet),
        record_id=_record_id(1),
    )
    assert first.prev_hash == "0" * 64
    line_count = len(log.read_text(encoding="utf-8").splitlines())
    assert api["append_decision"](
        log,
        _draft(api, first_packet),
        record_id=_record_id(1),
    ) == first
    assert len(log.read_text(encoding="utf-8").splitlines()) == line_count

    with pytest.raises(api["DecisionLogConflictError"]):
        api["append_decision"](
            log,
            replace(_draft(api, first_packet), rationale="different"),
            record_id=_record_id(1),
        )

    second = api["append_decision"](
        log,
        _draft(
            api,
            second_packet,
            event=api["DecisionEventType"].SUPERSESSION,
            actor_role=api["ActorRole"].SYSTEM,
            confidence=None,
            decision="supersede",
            supersedes=first_packet,
        ),
        record_id=_record_id(2),
    )
    assert second.prev_hash == first.record_hash
    history = api["replay"](log)
    assert history.variant_id == first_packet.identity.canonical_spdi
    assert tuple(record.packet_id for record in history.records) == (
        first_packet.packet_id,
        second_packet.packet_id,
    )


def test_ac23_append_rejects_cross_variant_path_before_write(tmp_path: Path) -> None:
    api = _api()
    packet = _approved_packet(api)
    variant_a_log = api["decision_log_path"](
        tmp_path,
        packet.identity.canonical_spdi,
    )
    api["append_decision"](
        variant_a_log,
        _draft(api, packet),
        record_id=_record_id(3),
    )
    before = variant_a_log.read_bytes()
    variant_b_draft = replace(
        _draft(api, packet),
        variant_id="NC_000016.10:1:A:G",
    )

    with pytest.raises(api["DecisionLogError"]):
        api["append_decision"](
            variant_a_log,
            variant_b_draft,
            record_id=_record_id(4),
        )
    assert variant_a_log.read_bytes() == before


def test_ac23_replay_detects_tamper_reorder_gap_cross_variant_and_bad_path(
    tmp_path: Path,
) -> None:
    api = _api()
    packet = _approved_packet(api)

    def valid_two_record_log(name: str) -> Path:
        root = tmp_path / name
        log = api["decision_log_path"](root, packet.identity.canonical_spdi)
        api["append_decision"](log, _draft(api, packet), record_id=_record_id(10))
        api["append_decision"](
            log,
            replace(_draft(api, packet), decision="retain-VUS"),
            record_id=_record_id(11),
        )
        return log

    tampered = valid_two_record_log("tampered")
    rows = [json.loads(line) for line in tampered.read_text(encoding="utf-8").splitlines()]
    rows[0]["decision"] = "tampered"
    tampered.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(api["DecisionLogTamperError"]):
        api["replay"](tampered)

    reordered = valid_two_record_log("reordered")
    lines = reordered.read_text(encoding="utf-8").splitlines()
    reordered.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
    with pytest.raises(api["DecisionLogTamperError"]):
        api["replay"](reordered)

    gap = valid_two_record_log("gap")
    rows = [json.loads(line) for line in gap.read_text(encoding="utf-8").splitlines()]
    rows[1]["prev_hash"] = "f" * 64
    payload = {key: value for key, value in rows[1].items() if key not in {"prev_hash", "record_hash"}}
    rows[1]["record_hash"] = api["decision_record_hash"]("f" * 64, payload)
    gap.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    with pytest.raises(api["DecisionLogTamperError"]):
        api["replay"](gap)

    cross_variant = valid_two_record_log("cross")
    rows = [
        json.loads(line)
        for line in cross_variant.read_text(encoding="utf-8").splitlines()
    ]
    rows[1]["variant_id"] = "NC_000016.10:1:A:G"
    payload = {key: value for key, value in rows[1].items() if key not in {"prev_hash", "record_hash"}}
    rows[1]["record_hash"] = api["decision_record_hash"](rows[1]["prev_hash"], payload)
    cross_variant.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(api["DecisionLogTamperError"]):
        api["replay"](cross_variant)

    valid = valid_two_record_log("path")
    wrong = valid.with_name("0" * 64 + ".jsonl")
    valid.replace(wrong)
    with pytest.raises(api["DecisionLogTamperError"]):
        api["replay"](wrong)


def test_ac11_ac23_decision_module_uses_lock_flush_fsync_and_no_kb() -> None:
    path = Path("src/raptor/packet/decisions.py")
    if not path.is_file():
        pytest.fail("decision workflow implementation is missing")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    imported = set()
    attributes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)
    assert "raptor.kb.store" not in imported
    assert "classification_versions" not in text
    assert "fsync" in attributes
    assert "flush" in attributes
    assert "fcntl" in imported or "msvcrt" in imported


def test_ac16_pattern_approval_is_log_only_and_advances_zero_packets(
    tmp_path: Path,
) -> None:
    api = _api()
    packets = (_approved_packet(api), _approved_packet(api))
    before = tuple(packet.review_state for packet in packets)
    log = api["decision_log_path"](tmp_path, packets[0].identity.canonical_spdi)
    record = api["append_decision"](
        log,
        _draft(
            api,
            packets[0],
            event=api["DecisionEventType"].PATTERN_POLICY_APPROVAL,
            actor_role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            decision="approve-pattern-policy",
        ),
        record_id=_record_id(20),
    )

    assert record.event_type is api["DecisionEventType"].PATTERN_POLICY_APPROVAL
    assert tuple(packet.review_state for packet in packets) == before
    assert not hasattr(api["PacketStateMachine"], "approve_pattern")


def test_ac17_ac20_comparator_is_reveal_only_and_decision_precedes_reveal(
    tmp_path: Path,
) -> None:
    api = _api()
    packet = _approved_packet(api)
    comparator = core._api()["ExternalComparator"](
        comparator_id="aavc-2024",
        source_name="AAVC",
        source_snapshot="ClinVar September 2024",
        source_doi="10.5281/zenodo.17201194",
        source_archive_sha256="c" * 64,
        source_commit="8da2b5a",
        match_method="exact_vcf_key",
        machine_class="LIKELY_BENIGN",
        criteria=("BS1_S",),
        flags=("EXTERNAL_MACHINE_OUTPUT",),
    )
    attached = api["attach_comparator"](packet, comparator)
    assert attached.evidence_core_hash == packet.evidence_core_hash
    assert attached.entries == packet.entries
    assert attached.candidate_direction == packet.candidate_direction
    assert attached.packet_id != packet.packet_id
    assert not hasattr(api["redact_for_first_pass"](attached), "external_comparators")
    assert api["attach_comparator"](attached, comparator) == attached
    with pytest.raises(api["ComparatorRevealError"]):
        api["attach_comparator"](
            attached,
            replace(comparator, machine_class="LIKELY_PATHOGENIC"),
        )

    log = api["decision_log_path"](tmp_path, attached.identity.canonical_spdi)
    empty_history = api["replay"](log)
    assert not api["reveal_allowed"](attached, empty_history)
    render_config = api["RenderConfig"](
        config_version="1",
        non_authoritative_marker="NON-AUTHORITATIVE",
        first_pass_heading="FIRST PASS",
        operator_heading="OPERATOR",
        reconciliation_heading="RECONCILIATION",
        narrative_catalog=api["NarrativeCatalog"](
            config_version="1",
            templates={
                "criterion_summary": api["NarrativeTemplate"](
                    template_id="criterion_summary",
                    body="Criterion {criterion}.",
                    required_bindings=("criterion",),
                ),
            },
        ),
    )
    with pytest.raises(api["PacketValidationError"]):
        api["render_markdown"](
            attached,
            render_config,
            view=api["PacketView"].RECONCILIATION,
            decision_history=empty_history,
        )
    with pytest.raises(api["ComparatorRevealError"]):
        api["reveal"](
            log,
            attached,
            actor_id="reviewer-1",
            actor_role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            timestamp="2026-07-11T12:01:00Z",
            record_id=_record_id(31),
        )
    direct_reveal = _draft(
        api,
        attached,
        event=api["DecisionEventType"].COMPARATOR_REVEAL,
        confidence=None,
        decision="reveal",
    )
    with pytest.raises(api["DecisionLogError"]):
        api["append_decision"](
            log,
            direct_reveal,
            record_id=_record_id(29),
        )
    with pytest.raises(api["DecisionLogError"]):
        api["append_decision"](
            log,
            _draft(
                api,
                attached,
                event=api["DecisionEventType"].RECONCILIATION,
                confidence=None,
                decision="reconcile",
            ),
            record_id=_record_id(28),
        )

    api["append_decision"](
        log,
        _draft(api, attached, confidence=0.8),
        record_id=_record_id(30),
    )
    assert api["reveal_allowed"](attached, api["replay"](log))
    revealed = api["reveal"](
        log,
        attached,
        actor_id="reviewer-1",
        actor_role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
        timestamp="2026-07-11T12:01:00Z",
        record_id=_record_id(31),
    )
    assert revealed.event_type is api["DecisionEventType"].COMPARATOR_REVEAL
    revealed_history = api["replay"](log)
    assert not api["reveal_allowed"](attached, revealed_history)
    reconciliation = api["render_markdown"](
        attached,
        render_config,
        view=api["PacketView"].RECONCILIATION,
        decision_history=revealed_history,
    )
    assert comparator.machine_class in reconciliation
    reconciled = api["append_decision"](
        log,
        _draft(
            api,
            attached,
            event=api["DecisionEventType"].RECONCILIATION,
            confidence=None,
            decision="reconcile",
        ),
        record_id=_record_id(32),
    )
    assert reconciled.event_type is api["DecisionEventType"].RECONCILIATION
    with pytest.raises(api["ComparatorRevealError"]):
        api["reveal"](
            log,
            attached,
            actor_id="reviewer-1",
            actor_role=api["ActorRole"].QUALIFIED_MOLECULAR_GENETICIST,
            timestamp="2026-07-11T12:02:00Z",
            record_id=_record_id(33),
        )


def test_ac17_strict_comparator_config_loader(tmp_path: Path) -> None:
    api = _api()
    config_path = tmp_path / "comparator.yaml"
    config_path.write_text(
        "config_version: '1'\n"
        "source_name: AAVC\n"
        "source_snapshot: 'ClinVar September 2024'\n"
        "source_doi: '10.5281/zenodo.17201194'\n"
        f"source_archive_sha256: '{'c' * 64}'\n"
        "source_commit: 8da2b5a\n"
        "match_methods: [exact_vcf_key, common_trim_equivalent]\n",
        encoding="utf-8",
    )
    config = api["load_comparator_config"](config_path)
    assert config.source_name == "AAVC"
    assert config.match_methods == ("exact_vcf_key", "common_trim_equivalent")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["unknown"] = True
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(api["ComparatorConfigError"]):
        api["load_comparator_config"](bad)
