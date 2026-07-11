"""PRD-04 Task A `build.py` — `build_packet`, the only constructor for a
complete `CandidateEvidencePacket` (sec 4.1/4.10/FR4.1/FR4.2/FR5/FR6/FR24).

`build_packet` resolves every criterion's disposition from the injected
`PacketConfig.lineage_policy` (never inventing lineage); a criterion missing
from the lineage policy raises `PacketValidationError`. It reads **no**
KB/benchmark/label file (FR24); the AAVC comparator is attached but excluded
from the evidence core. This module imports no `raptor.eval.combine`/
`harness`/`benchmark`/`knowns` and no `raptor.kb.store`.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional

from .config import PacketConfig
from .direction import compute_candidate_direction
from .hashing import evidence_core_hash, narrative_plan_hash, packet_envelope_hash
from .model import (
    CandidateEvidencePacket,
    CriterionEntry,
    GateStatus,
    NarrativePlan,
    PacketInput,
    PacketPolicyDisposition,
    PacketValidationError,
    ReviewState,
    resolve_packet_policy_disposition,
)

_EXCLUSION_REASON = "direct_copy_forbidden"
_FUNCTIONAL_LITERATURE_LINEAGE_CLASS = "literature_unvalidated"
_UNAPPROVED_NULL_REASON = "production_policy_unapproved"
_PATHOGENIC = "pathogenic"
_BENIGN = "benign"


def build_packet(
    packet_input: PacketInput,
    config: Optional[PacketConfig],
    *,
    narrative_plan: Optional[NarrativePlan] = None,
) -> CandidateEvidencePacket:
    """Validate `packet_input`, build immutable `CriterionEntry` rows by
    resolving each criterion through `config.lineage_policy.records`, derive
    contradiction/direction/state, compute all three packet hashes, and
    return the frozen packet. `config=None` is invalid."""
    if config is None:
        raise PacketValidationError("build_packet requires a PacketConfig; got None")
    if packet_input is None:
        raise PacketValidationError("build_packet requires a PacketInput; got None")

    _validate_packet_input(packet_input)

    entries = _build_entries(packet_input, config)

    exclusions = tuple(sorted(
        entry.criterion for entry in entries
        if entry.packet_policy_disposition is PacketPolicyDisposition.EXCLUDED
    ))

    directions = {entry.direction for entry in entries}
    contradiction = _PATHOGENIC in directions and _BENIGN in directions

    missing_evidence = tuple(
        sorted(packet_input.missing_evidence, key=lambda m: (m.category, m.next_action))
    )

    candidate_direction = compute_candidate_direction(entries, config.candidate_direction_policy)

    if candidate_direction.null_reason == _UNAPPROVED_NULL_REASON:
        review_state = ReviewState.POLICY_BLOCKED
    else:
        review_state = ReviewState.DRAFT_PROVISIONAL
    gate_status = GateStatus.UNVERIFIED

    draft = CandidateEvidencePacket(
        packet_schema_version=config.packet_schema_version,
        packet_id="",
        evidence_core_hash="",
        narrative_plan_hash="",
        packet_envelope_hash="",
        identity=packet_input.identity,
        entries=entries,
        candidate_direction=candidate_direction,
        exclusions=exclusions,
        contradiction=contradiction,
        quality_flags=packet_input.quality_flags,
        missing_evidence=missing_evidence,
        narrative_plan=narrative_plan,
        external_comparators=packet_input.external_comparators,
        review_state=review_state,
        gate_status=gate_status,
        pattern_ref=packet_input.pattern_ref,
        run_metadata=packet_input.run_metadata,
        source_snapshot=packet_input.source_snapshot,
        predecessor_packet_id=packet_input.predecessor_packet_id,
        predecessor_envelope_hash=packet_input.predecessor_envelope_hash,
    )

    core_hash = evidence_core_hash(draft)
    plan_hash = narrative_plan_hash(narrative_plan)
    draft = replace(draft, evidence_core_hash=core_hash, narrative_plan_hash=plan_hash)

    envelope_hash = packet_envelope_hash(draft)
    return replace(draft, packet_envelope_hash=envelope_hash, packet_id=envelope_hash)


_VALID_GENES = frozenset({"TSC1", "TSC2"})
_VALID_VARIANT_CLASSES = frozenset({"missense", "truncating", "other"})

# PRD FR2: canonical GRCh38 SPDI syntax --
# NC_######.<version>:<0-based nonnegative position>:<deleted DNA or empty>:<inserted DNA or empty>
_CANONICAL_SPDI_RE = re.compile(r"^NC_[0-9]{6}\.[0-9]+:[0-9]+:([ACGTN]*):([ACGTN]*)$")

# PRD FR2: consequence must be a lowercase Sequence-Ontology-style token
# (syntax only -- no invented closed consequence vocabulary).
_CONSEQUENCE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# PRD FR2: per-gene canonical GRCh38 accession + MANE transcript pin.
_GENE_ACCESSIONS = {
    "TSC1": "NC_000009.12",
    "TSC2": "NC_000016.10",
}
_GENE_MANE_TRANSCRIPTS = {
    "TSC1": "NM_000368.5",
    "TSC2": "NM_000548.5",
}


def _validate_packet_input(packet_input: PacketInput) -> None:
    identity = packet_input.identity
    for name in ("canonical_spdi", "gene", "transcript", "consequence", "variant_class"):
        value = getattr(identity, name)
        if not isinstance(value, str) or not value.strip():
            raise PacketValidationError(f"PacketInput.identity.{name} must be non-blank")
    if identity.gene not in _VALID_GENES:
        raise PacketValidationError(
            f"PacketInput.identity.gene must be one of {sorted(_VALID_GENES)!r}; got {identity.gene!r}"
        )
    if identity.variant_class not in _VALID_VARIANT_CLASSES:
        raise PacketValidationError(
            "PacketInput.identity.variant_class must be one of "
            f"{sorted(_VALID_VARIANT_CLASSES)!r}; got {identity.variant_class!r}"
        )

    spdi_match = _CANONICAL_SPDI_RE.fullmatch(identity.canonical_spdi)
    if spdi_match is None:
        raise PacketValidationError(
            "PacketInput.identity.canonical_spdi must match "
            "NC_######.<version>:<0-based position>:<deleted DNA or empty>:<inserted DNA or empty> "
            f"(uppercase ACGTN only); got {identity.canonical_spdi!r}"
        )
    deleted, inserted = spdi_match.group(1), spdi_match.group(2)
    if not deleted and not inserted:
        raise PacketValidationError(
            "PacketInput.identity.canonical_spdi must not have both deleted and inserted "
            f"alleles empty; got {identity.canonical_spdi!r}"
        )

    expected_accession = _GENE_ACCESSIONS[identity.gene]
    if not identity.canonical_spdi.startswith(f"{expected_accession}:"):
        raise PacketValidationError(
            f"PacketInput.identity.canonical_spdi must be pinned to {identity.gene}'s canonical "
            f"GRCh38 accession {expected_accession!r}; got {identity.canonical_spdi!r}"
        )

    expected_transcript = _GENE_MANE_TRANSCRIPTS[identity.gene]
    if identity.transcript != expected_transcript:
        raise PacketValidationError(
            f"PacketInput.identity.transcript must be {identity.gene}'s MANE transcript "
            f"{expected_transcript!r}; got {identity.transcript!r}"
        )

    if _CONSEQUENCE_RE.fullmatch(identity.consequence) is None:
        raise PacketValidationError(
            "PacketInput.identity.consequence must be a lowercase Sequence-Ontology-style "
            f"token matching ^[a-z][a-z0-9_]*$; got {identity.consequence!r}"
        )

    if not packet_input.criterion_inputs:
        raise PacketValidationError("PacketInput.criterion_inputs must be non-empty")


def _build_entries(packet_input: PacketInput, config: PacketConfig) -> tuple:
    entries = []
    for criterion_input in packet_input.criterion_inputs:
        record = config.lineage_policy.records.get(criterion_input.criterion)
        if record is None:
            raise PacketValidationError(
                f"no lineage record for criterion {criterion_input.criterion!r} -- "
                "build_packet never invents lineage"
            )

        disposition = resolve_packet_policy_disposition(
            record.validation_disposition, record.production_disposition
        )
        exclusion_reason = _EXCLUSION_REASON if disposition is PacketPolicyDisposition.EXCLUDED else None
        primary_required = _resolve_primary_required(
            criterion_input.criterion, record.lineage_class, disposition, config
        )
        primary_refs = tuple(
            sorted(criterion_input.primary_evidence_refs, key=lambda ref: ref.ref_id)
        )

        entries.append(
            CriterionEntry(
                criterion=criterion_input.criterion,
                strength=criterion_input.strength,
                direction=criterion_input.direction,
                rationale=criterion_input.rationale,
                lineage_class=record.lineage_class,
                validation_disposition=record.validation_disposition,
                production_disposition=record.production_disposition,
                decision_dependency=record.decision_dependency,
                packet_policy_disposition=disposition,
                exclusion_reason=exclusion_reason,
                scorer_provenance=criterion_input.scorer_provenance,
                primary_evidence_refs=primary_refs,
                primary_grounding=criterion_input.primary_grounding,
                primary_grounding_reason=criterion_input.primary_grounding_reason,
                primary_required=primary_required,
            )
        )

    entries.sort(key=lambda e: (e.criterion, e.strength, e.scorer_provenance.bias_row_key))
    return tuple(entries)


def _resolve_primary_required(
    criterion: str,
    lineage_class: str,
    disposition: PacketPolicyDisposition,
    config: PacketConfig,
) -> bool:
    """`primary_required` = any included/deferred functional/literature (PS3 /
    `literature_unvalidated`) claim + every config-flagged criterion; unknown
    fails closed."""
    if criterion in config.primary_required_criteria:
        return True
    if lineage_class == "unknown":
        return True
    if lineage_class == _FUNCTIONAL_LITERATURE_LINEAGE_CLASS and disposition in (
        PacketPolicyDisposition.INCLUDED, PacketPolicyDisposition.DEFERRED,
    ):
        return True
    return False
