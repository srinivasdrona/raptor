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
    CensusSelectionMetadata,
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
    allow_empty_criteria: bool = False,
) -> CandidateEvidencePacket:
    """Validate `packet_input`, build immutable `CriterionEntry` rows by
    resolving each criterion through `config.lineage_policy.records`, derive
    contradiction/direction/state, compute all three packet hashes, and
    return the frozen packet. `config=None` is invalid.

    `allow_empty_criteria=True` (corrected all-VUS track, D12) permits a
    packet with zero `criterion_inputs` -- used only by
    `raptor.packet.corrected_universe.build_evidence_absent_packet` for a
    BIAS row that fired no criteria at all; every other caller keeps the
    default (fail loud on empty criteria).
    """
    if config is None:
        raise PacketValidationError("build_packet requires a PacketConfig; got None")
    if packet_input is None:
        raise PacketValidationError("build_packet requires a PacketInput; got None")

    _validate_packet_input(packet_input, allow_empty_criteria=allow_empty_criteria)
    _validate_selection_metadata(packet_input)

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
        census_selection_stratum=packet_input.census_selection_stratum,
    )

    core_hash = evidence_core_hash(draft)
    plan_hash = narrative_plan_hash(narrative_plan)
    draft = replace(draft, evidence_core_hash=core_hash, narrative_plan_hash=plan_hash)

    envelope_hash = packet_envelope_hash(draft)
    final = replace(draft, packet_envelope_hash=envelope_hash, packet_id=envelope_hash)
    # `census_selection_stratum` is a real, declared field supplied at
    # construction above, so both hash domains already reflect it -- no
    # post-hoc rebind/rehash needed on this path (unlike
    # `bind_census_selection_metadata`, which attaches metadata onto an
    # ALREADY-BUILT packet from a reused calibration helper).
    return final


_VALID_GENES = frozenset({"TSC1", "TSC2", "NTHL1"})
_VALID_VARIANT_CLASSES = frozenset({"missense", "truncating", "other"})

# PRD FR2: canonical GRCh38 SPDI syntax --
# NC_######.<version>:<0-based nonnegative position>:<deleted DNA or empty>:<inserted DNA or empty>
_CANONICAL_SPDI_RE = re.compile(r"^NC_[0-9]{6}\.[0-9]+:[0-9]+:([ACGTN]*):([ACGTN]*)$")

# PRD FR2: consequence must be one or more safe comma-separated
# alphanumeric/underscore tokens (syntax
# only -- no invented closed consequence vocabulary, no re-encoding). This
# accepts every official Sequence Ontology term verbatim, including terms
# with a leading digit or embedded uppercase acronym (e.g.
# `3_prime_UTR_variant`, `5_prime_UTR_variant`), while still rejecting
# punctuation and blank strings.
_CONSEQUENCE_RE = re.compile(r"^[A-Za-z0-9_]+(?:,[A-Za-z0-9_]+)*$")

# PRD FR2: per-gene canonical GRCh38 accession + MANE transcript pin.
# NTHL1 (added for the corrected all-VUS track, D2/D11): BIAS-annotated TSC2
# rows misannotated to NTHL1 are pre-routed to `manual_review` by
# `raptor.census.strata.reproduce_census_strata` and still need a real,
# validated `CanonicalVariantIdentity` to build a packet.
_GENE_ACCESSIONS = {
    "TSC1": "NC_000009.12",
    "TSC2": "NC_000016.10",
    "NTHL1": "NC_000016.10",
}
_GENE_MANE_TRANSCRIPTS = {
    "TSC1": "NM_000368.5",
    "TSC2": "NM_000548.5",
    "NTHL1": "NM_002528.7",
}


def _validate_packet_input(packet_input: PacketInput, *, allow_empty_criteria: bool = False) -> None:
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
            "PacketInput.identity.consequence must be one or more comma-separated "
            "safe alphanumeric/underscore tokens; "
            f"got {identity.consequence!r}"
        )

    if not packet_input.criterion_inputs and not allow_empty_criteria:
        raise PacketValidationError("PacketInput.criterion_inputs must be non-empty")


def _validate_pattern_ref_stratum(
    metadata: CensusSelectionMetadata, pattern_ref: Optional[object]
) -> None:
    """Shared PatternRef/`CensusSelectionMetadata` cross-field invariant
    (corrected all-VUS track, D13): a present `pattern_ref` must name the
    same stratum, and `no_deterministic_resolution`/`manual_review` never
    carry a `pattern_ref` at all."""
    if pattern_ref is not None and pattern_ref.census_selection_stratum != metadata.census_selection_stratum:
        raise PacketValidationError(
            "pattern_ref.census_selection_stratum "
            f"{pattern_ref.census_selection_stratum!r} does not match "
            f"census_selection_stratum {metadata.census_selection_stratum!r}"
        )
    if (
        metadata.census_selection_stratum in ("no_deterministic_resolution", "manual_review")
        and pattern_ref is not None
    ):
        raise PacketValidationError(
            "pattern_ref must be None when census_selection_stratum is "
            f"{metadata.census_selection_stratum!r}"
        )


def _validate_selection_metadata(packet_input: PacketInput) -> None:
    metadata = packet_input.census_selection_stratum
    if metadata is None:
        return
    _validate_pattern_ref_stratum(metadata, packet_input.pattern_ref)


def _rebind_with_metadata(
    packet: CandidateEvidencePacket, metadata: Optional[CensusSelectionMetadata]
) -> CandidateEvidencePacket:
    """Bind `metadata` onto the real, declared `census_selection_stratum`
    field (via `dataclasses.replace`, which preserves every other field
    unchanged) and recompute the two hash domains it is bound into. A
    `None` metadata is a no-op."""
    if metadata is None:
        return packet
    packet = replace(packet, census_selection_stratum=metadata)
    core_hash = evidence_core_hash(packet)
    packet = replace(packet, evidence_core_hash=core_hash)
    envelope_hash = packet_envelope_hash(packet)
    packet = replace(packet, packet_envelope_hash=envelope_hash, packet_id=envelope_hash)
    return packet


def bind_census_selection_metadata(
    packet: CandidateEvidencePacket, metadata: Optional[CensusSelectionMetadata]
) -> CandidateEvidencePacket:
    """Public seam (reused by `raptor.packet.corrected_universe`) to bind
    `metadata` onto an ALREADY-BUILT `CandidateEvidencePacket` -- e.g. one
    produced by the unchanged `build_candidate_universe` calibration helper,
    which never threads `PacketInput.census_selection_stratum`. Validates
    the same PatternRef/stratum invariant `build_packet` enforces, then
    rebinds + rehashes via `_rebind_with_metadata`."""
    if metadata is not None:
        _validate_pattern_ref_stratum(metadata, packet.pattern_ref)
    return _rebind_with_metadata(packet, metadata)


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
