"""PRD-04 Task B `render.py` — deterministic Markdown packet rendering.

`render_markdown(packet, config, *, view)` (FR10) is a pure function of the
JSON packet + the requested `PacketView`: a given packet/config/view always
renders byte-identical Markdown. The narrative section is a deterministic
template expansion of the packet's `NarrativePlan` (FR7): every
`template_id` must exist in `config.narrative_catalog`, every plan entry
must bind **exactly** the template's `required_bindings` (no more, no
fewer), and every bound `field_path` must resolve against the packet field
tree via a safe dot/index resolver (`entries.0.criterion`) — **never**
`eval`/`exec`. Any violation raises `PacketValidationError` (AC9) — the
renderer never emits a freeform fact it did not mechanically resolve.

The `FIRST_PASS` view resolves field paths **only** against
`redact_for_first_pass(packet)` (`FirstPassPacketView`) — never the full
packet — so a plan cannot smuggle a candidate-direction/comparator/pattern
field into a first-pass render (FR14.1/AC4/AC20): a path that only exists on
the full packet (e.g. `candidate_direction.direction`) fails to resolve
against the redacted view and raises loud, exactly like an unknown field.

`OPERATOR`/`RECONCILIATION` render the full packet and always place the
candidate direction (including the `null` + `null_reason` state) directly
adjacent to the configured `non_authoritative_marker`, the packet
`review_state`, and `gate_status` (FR14) — the direction is never a
standalone "LP"/"LB" classification token (AC4).

When a `RECONCILIATION` render's packet carries `external_comparators`
(FR27), the comparator machine fields are reveal-gated: the caller must pass
a `decision_history` (a replayed `DecisionHistory`, never a bare boolean)
whose own hash chain independently re-verifies and which carries a
`COMPARATOR_REVEAL` record bound to this exact canonical variant, `packet_id`,
and `evidence_core_hash` -- see `comparator.comparator_reveal_verified`. A
missing, non-matching, or forged/tampered history raises
`PacketValidationError` before any comparator field is emitted (AC17/AC20);
`FIRST_PASS`/`OPERATOR` renders are entirely unaffected by `decision_history`.
"""
from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Optional

from .config import NarrativeCatalog, RenderConfig
from .model import (
    CandidateEvidencePacket,
    NarrativePlanEntry,
    PacketValidationError,
    PacketView,
    redact_for_first_pass,
)

if TYPE_CHECKING:  # pragma: no cover - type-checking only, avoids a hard
    # module-level dependency of render.py (used by every view) on
    # comparator.py's decision-log machinery (only needed by RECONCILIATION
    # renders of packets carrying external comparators).
    from .decisions import DecisionHistory

# Exact `{name}` placeholder tokens only -- no dotted/indexed/format-spec
# access inside a template body, so template expansion can never traverse
# into arbitrary attributes via a format-string side channel (no eval).
_TOKEN_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_field_path(root: Any, path: str) -> Any:
    """Safe dot/index field resolver (FR7): `path` segments split on `.`;
    a pure-digit segment indexes into a tuple/list only, any other segment
    accesses a *declared dataclass field* on a dataclass instance only --
    never an arbitrary attribute. This rejects primitive methods (e.g.
    `str.upper`), dunder attributes, and any non-field attribute, so a
    template can never smuggle a bound method or private/internal state
    into rendered text. Never calls `eval`/`exec`. Raises
    `PacketValidationError` on any missing/non-field attribute,
    non-sequence index, or out-of-range index -- an unresolved path always
    fails loud (AC9)."""
    if not isinstance(path, str) or not path.strip():
        raise PacketValidationError("narrative field_path must be a non-blank string")
    current = root
    for segment in path.split("."):
        if segment == "":
            raise PacketValidationError(f"narrative field_path {path!r} has an empty segment")
        if segment.isdigit():
            index = int(segment)
            if not isinstance(current, (tuple, list)):
                raise PacketValidationError(
                    f"narrative field_path {path!r} indexes into a non-sequence at {segment!r}"
                )
            if index >= len(current):
                raise PacketValidationError(
                    f"narrative field_path {path!r} index {segment!r} is out of range"
                )
            current = current[index]
        else:
            if not is_dataclass(current) or isinstance(current, type):
                raise PacketValidationError(
                    f"narrative field_path {path!r} does not resolve: {segment!r} is not a "
                    f"declared field on {type(current).__name__} (not a dataclass instance)"
                )
            field_names = {field.name for field in fields(current)}
            if segment not in field_names:
                raise PacketValidationError(
                    f"narrative field_path {path!r} does not resolve: no declared field "
                    f"{segment!r} on {type(current).__name__}"
                )
            current = getattr(current, segment)
    return current


def _render_template_body(template_id: str, body: str, resolved: Mapping[str, Any]) -> str:
    def _substitute(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in resolved:
            raise PacketValidationError(
                f"template {template_id!r} body references unbound placeholder {{{name}}}"
            )
        value = resolved[name]
        return str(value.value) if isinstance(value, Enum) else str(value)

    return _TOKEN_RE.sub(_substitute, body)


def _expand_entry(entry: NarrativePlanEntry, catalog: NarrativeCatalog, root: Any) -> str:
    template = catalog.templates.get(entry.template_id)
    if template is None:
        raise PacketValidationError(
            f"narrative plan references unknown template_id {entry.template_id!r}"
        )

    bound_names = tuple(binding.name for binding in entry.field_bindings)
    if len(set(bound_names)) != len(bound_names):
        raise PacketValidationError(
            f"narrative plan entry for template {entry.template_id!r} has duplicate "
            f"binding name(s): {bound_names!r}"
        )
    if set(bound_names) != set(template.required_bindings):
        raise PacketValidationError(
            f"narrative plan entry for template {entry.template_id!r} must bind exactly "
            f"{sorted(template.required_bindings)!r}; got {sorted(bound_names)!r}"
        )

    resolved: dict[str, Any] = {}
    for binding in entry.field_bindings:
        value = _resolve_field_path(root, binding.field_path)
        resolved[binding.name] = value.value if isinstance(value, Enum) else value

    return _render_template_body(entry.template_id, template.body, resolved)


def _require_verified_comparator_reveal(
    packet: CandidateEvidencePacket, decision_history: Optional["DecisionHistory"]
) -> None:
    """Gate the `RECONCILIATION` comparator reveal on a verified recorded
    decision (FR27/AC17/AC20), never a caller-supplied boolean: `decision_history`
    must be an actual `DecisionHistory` (produced by `decisions.replay`, not a
    bare truthy value), its own hash chain must independently re-verify
    (rejecting a hand-built/forged history), and it must carry a
    `COMPARATOR_REVEAL` record bound to this exact canonical variant,
    `packet_id`, and `evidence_core_hash`. Local import: only a
    `RECONCILIATION` render of a packet with `external_comparators` needs
    `comparator.py`'s decision-log machinery, and this keeps that dependency
    out of every `FIRST_PASS`/`OPERATOR` render (and off render.py's module
    surface) while still avoiding any risk of a render/comparator import
    cycle."""
    from .comparator import ComparatorRevealError, comparator_reveal_verified
    from .decisions import DecisionHistory

    if not isinstance(decision_history, DecisionHistory):
        raise PacketValidationError(
            "render_markdown RECONCILIATION view of a packet with attached external_comparators "
            "requires decision_history to be a verified DecisionHistory (e.g. from "
            "decisions.replay(...)); a missing value or a caller-supplied boolean is not accepted"
        )
    try:
        verified = comparator_reveal_verified(packet, decision_history)
    except ComparatorRevealError as exc:
        raise PacketValidationError(
            f"render_markdown RECONCILIATION view: decision_history failed verification: {exc}"
        ) from exc
    if not verified:
        raise PacketValidationError(
            "render_markdown RECONCILIATION view requires decision_history to carry a verified "
            "COMPARATOR_REVEAL record for this exact canonical variant, packet_id, and "
            "evidence_core_hash before any comparator field may render"
        )


def render_markdown(
    packet: CandidateEvidencePacket,
    config: RenderConfig,
    *,
    view: PacketView,
    decision_history: Optional["DecisionHistory"] = None,
) -> str:
    """Deterministic Markdown render (FR10). `FIRST_PASS` resolves the
    narrative plan and evidence trail against `redact_for_first_pass(packet)`
    only and never touches `packet.candidate_direction` /
    `packet.pattern_ref` / `packet.external_comparators` (FR14.1/AC20).
    `OPERATOR`/`RECONCILIATION` render the full packet with the
    non-authoritative marker + review state + gate status unavoidably
    adjacent to the candidate direction (FR14/AC4). `decision_history` is
    only consulted for `RECONCILIATION` renders of a packet carrying
    `external_comparators`, and only a verified `DecisionHistory` with a
    matching `COMPARATOR_REVEAL` record unlocks the comparator fields --
    see the module docstring and `comparator.comparator_reveal_verified`;
    `FIRST_PASS`/`OPERATOR` behavior is unaffected by this parameter."""
    if not isinstance(packet, CandidateEvidencePacket):
        raise PacketValidationError("render_markdown requires a CandidateEvidencePacket")
    if not isinstance(config, RenderConfig):
        raise PacketValidationError("render_markdown requires a RenderConfig")
    if not isinstance(view, PacketView):
        raise PacketValidationError(f"render_markdown requires a PacketView; got {view!r}")

    if view is PacketView.FIRST_PASS:
        root: Any = redact_for_first_pass(packet)
        heading = config.first_pass_heading
    elif view is PacketView.OPERATOR:
        root = packet
        heading = config.operator_heading
    elif view is PacketView.RECONCILIATION:
        root = packet
        heading = config.reconciliation_heading
    else:  # pragma: no cover -- PacketView is exhaustive above
        raise PacketValidationError(f"render_markdown: unhandled PacketView {view!r}")

    if view is PacketView.RECONCILIATION and packet.external_comparators:
        _require_verified_comparator_reveal(packet, decision_history)

    lines: list[str] = [f"# {heading}", ""]

    if root.narrative_plan is not None:
        lines.append("## Narrative")
        for entry in root.narrative_plan.entries:
            lines.append(_expand_entry(entry, config.narrative_catalog, root))
        lines.append("")

    lines.append("## Evidence entries")
    for entry in root.entries:
        lines.append(
            f"- criterion={entry.criterion} strength={entry.strength} "
            f"direction={entry.direction} disposition={entry.packet_policy_disposition.value}"
        )
    lines.append("")

    lines.append(f"Contradiction: {root.contradiction}")
    lines.append(
        "Quality flags: " + (", ".join(root.quality_flags) if root.quality_flags else "none")
    )
    if root.missing_evidence:
        lines.append("")
        lines.append("## Missing evidence")
        for item in root.missing_evidence:
            lines.append(f"- {item.category}: {item.next_action}")
    lines.append("")
    lines.append(f"Review state: {root.review_state.value}")
    lines.append(f"Gate status: {root.gate_status.value}")

    if view in (PacketView.OPERATOR, PacketView.RECONCILIATION):
        direction = packet.candidate_direction
        lines.append("")
        lines.append(config.non_authoritative_marker)
        if direction.direction is None:
            lines.append(
                f"Candidate direction (non-authoritative, review-only): null "
                f"(null_reason={direction.null_reason})"
            )
        else:
            lines.append(
                f"Candidate direction (non-authoritative, review-only): "
                f"{direction.direction} (signed_points={direction.signed_points})"
            )
        lines.append(f"Review state: {packet.review_state.value}")
        lines.append(f"Gate status: {packet.gate_status.value}")
        if packet.pattern_ref is not None:
            lines.append(
                f"Census selection metadata: stratum={packet.pattern_ref.census_selection_stratum} "
                f"pattern_id={packet.pattern_ref.pattern_id} "
                f"snapshot={packet.pattern_ref.census_snapshot_id}"
            )
        if view is PacketView.RECONCILIATION and packet.external_comparators:
            lines.append("")
            lines.append("## External comparator (reveal)")
            for comparator in packet.external_comparators:
                lines.append(
                    f"- source={comparator.source_name} class={comparator.machine_class} "
                    f"criteria={','.join(comparator.criteria)}"
                )

    return "\n".join(lines) + "\n"
