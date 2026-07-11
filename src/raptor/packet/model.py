"""PRD-04 Task A `model.py` — the candidate-evidence-packet core schema.

`CandidateEvidencePacket` (PRD-04 sec 4.1) is assembled by `build.py` from an
injected `PacketInput` (sec 4.10): a `PacketInput` carries the raw per-criterion
scorer output + two-level provenance but NO caller-supplied lineage or
disposition -- those are resolved during `build_packet` from the injected
`PacketConfig.lineage_policy` (ADR-0009) via `resolve_packet_policy_disposition`
(FR4.1, this module). `CriterionEntry` is the immutable, packet-scoped result:
both raw dispositions are preserved verbatim alongside the derived
`packet_policy_disposition` so a downstream reviewer/auditor can always see
what the lineage policy said versus how the packet resolved it.

Two-level provenance (FR4.2): every entry carries exactly one `ScorerProvenance`
(the BIAS raw row -- never a `PrimaryEvidenceRef`) plus zero-or-more
`PrimaryEvidenceRef` (independently sourced literature/functional/clinical/
population/predictor evidence, each either `resolved` or `unresolved` per a
strict predicate). `CandidateDirection` (FR5) is nullable: an unapproved
production candidate-direction policy always yields
`direction=None, null_reason="production_policy_unapproved"`.

All dataclasses are `frozen=True`. Ordered collections are tuples; mappings
handed to a dataclass are copied to read-only values at construction. Typed
failures (`PacketSchemaError`, `PacketValidationError`, `ProvenanceValidationError`,
`DispositionMappingError`, `DirectionPolicyError`, `PacketHashError`) are raised
instead of catch-all `Exception` so callers can discriminate a schema-shape
bug from a content/business-rule violation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_DNA_RE = re.compile(r"^[ACGTN]+$")
_BIAS_VERSION = "3.0.0"


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _is_hex40(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX40_RE.fullmatch(value))


def _is_dna(value: object) -> bool:
    return isinstance(value, str) and bool(_DNA_RE.fullmatch(value))


def _non_blank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# --------------------------------------------------------------------------
# Typed failures (never a catch-all `Exception`)
# --------------------------------------------------------------------------


class PacketSchemaError(ValueError):
    """A packet-core schema shape does not match the pinned Task-A contract
    (e.g. an unknown/missing field on a schema-validated surface)."""


class PacketValidationError(ValueError):
    """An injected `PacketInput` (or one of its value objects) fails
    packet-build content validation (never a silent default)."""


class ProvenanceValidationError(ValueError):
    """`ScorerProvenance`/`PrimaryEvidenceRef` violates its pinned schema or
    resolved/unresolved predicate (FR4.2)."""


class DispositionMappingError(ValueError):
    """`resolve_packet_policy_disposition` saw an unmapped
    validation/production disposition pairing -- never silently `included`."""


class DirectionPolicyError(ValueError):
    """The candidate-direction policy cannot score an entry/points
    combination (e.g. an included criterion+strength pair with no configured
    points)."""


class PacketHashError(ValueError):
    """A canonical packet hash cannot be computed (e.g. a malformed
    `prev_hash` handed to `decision_record_hash`)."""


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class PacketPolicyDisposition(Enum):
    INCLUDED = "included"
    MASKED = "masked"
    EXCLUDED = "excluded"
    DEFERRED = "deferred"


class PrimaryGrounding(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_REQUIRED = "not_required"


class ResolutionStatus(Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class ReviewState(Enum):
    DRAFT_PROVISIONAL = "DRAFT_PROVISIONAL"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    READY_FOR_EXPERT_REVIEW = "READY_FOR_EXPERT_REVIEW"
    EXPERT_CHANGES_REQUESTED = "EXPERT_CHANGES_REQUESTED"
    EXPERT_APPROVED_INTERNAL = "EXPERT_APPROVED_INTERNAL"
    SECOND_REVIEW_APPROVED = "SECOND_REVIEW_APPROVED"
    EXTERNAL_SUBMISSION_READY = "EXTERNAL_SUBMISSION_READY"
    SUPERSEDED = "SUPERSEDED"


class GateStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNDERPOWERED = "UNDERPOWERED"
    UNVERIFIED = "UNVERIFIED"


class PacketView(Enum):
    FIRST_PASS = "FIRST_PASS"
    OPERATOR = "OPERATOR"
    RECONCILIATION = "RECONCILIATION"


# --------------------------------------------------------------------------
# Core value objects (exact fields -- slot2 "Core value objects")
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalVariantIdentity:
    """The canonical variant identity (PRD-04 sec 4.1). Content (e.g. a blank
    `canonical_spdi`) is validated by `build_packet`, not here, so a caller
    can freely construct/`dataclasses.replace` an identity for negative-path
    fixtures without an unrelated constructor raising."""

    canonical_spdi: str
    gene: str
    transcript: str
    consequence: str
    variant_class: str


@dataclass(frozen=True)
class RunMetadata:
    """`run_id`/`generated_at` are recorded but excluded from every packet
    hash; the other four fields are envelope pins (§4.2)."""

    run_id: str
    generated_at: str
    code_commit: str
    packet_config_sha256: str
    lineage_policy_sha256: str
    candidate_policy_sha256: str

    def __post_init__(self) -> None:
        for name in ("run_id", "generated_at", "code_commit"):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"RunMetadata.{name} must be non-blank")
        for name in ("packet_config_sha256", "lineage_policy_sha256", "candidate_policy_sha256"):
            if not _is_hex64(getattr(self, name)):
                raise PacketValidationError(f"RunMetadata.{name} must be lowercase hex-64")


@dataclass(frozen=True)
class SourceSnapshotPins:
    """All three hashes are lowercase hex-64."""

    snapshot_id: str
    snapshot_date: str
    clinvar_sha256: str
    bias_output_sha256: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        if not _non_blank(self.snapshot_id):
            raise PacketValidationError("SourceSnapshotPins.snapshot_id must be non-blank")
        if not _non_blank(self.snapshot_date):
            raise PacketValidationError("SourceSnapshotPins.snapshot_date must be non-blank")
        for name in ("clinvar_sha256", "bias_output_sha256", "manifest_sha256"):
            if not _is_hex64(getattr(self, name)):
                raise PacketValidationError(f"SourceSnapshotPins.{name} must be lowercase hex-64")


@dataclass(frozen=True)
class ScorerProvenance:
    """Resolves to a BIAS raw row; is **never** a `PrimaryEvidenceRef` (FR4.2).
    All fields are required (no defaults); strict formats on the three
    checksum fields."""

    bias_row_key: str
    chromosome: str
    position: int
    ref: str
    alt: str
    scorer_run_id: str
    input_sha256: str
    output_sha256: str
    raw_row_sha256: str
    bias_version: str
    bias_commit: str
    nirvana_version: str
    transcript: str

    def __post_init__(self) -> None:
        for name in (
            "bias_row_key", "chromosome", "ref", "alt", "scorer_run_id",
            "bias_version", "bias_commit", "nirvana_version", "transcript",
        ):
            if not _non_blank(getattr(self, name)):
                raise ProvenanceValidationError(f"ScorerProvenance.{name} must be non-blank")
        if isinstance(self.position, bool) or not isinstance(self.position, int) or self.position < 1:
            raise ProvenanceValidationError("ScorerProvenance.position must be a positive int (>= 1)")
        for name in ("ref", "alt"):
            if not _is_dna(getattr(self, name)):
                raise ProvenanceValidationError(
                    f"ScorerProvenance.{name} must be uppercase DNA matching ^[ACGTN]+$"
                )
        if self.bias_version != _BIAS_VERSION:
            raise ProvenanceValidationError(
                f"ScorerProvenance.bias_version must be exactly {_BIAS_VERSION!r}; got {self.bias_version!r}"
            )
        if not _is_hex40(self.bias_commit):
            raise ProvenanceValidationError("ScorerProvenance.bias_commit must be lowercase hex-40")
        for name in ("input_sha256", "output_sha256", "raw_row_sha256"):
            if not _is_hex64(getattr(self, name)):
                raise ProvenanceValidationError(f"ScorerProvenance.{name} must be lowercase hex-64")


_PRIMARY_SOURCE_TYPES = frozenset({
    "literature",
    "functional_assay",
    "clingen_guidance",
    "database_record",
})


@dataclass(frozen=True)
class PrimaryEvidenceRef:
    """`source_type` is never `bias_row` (a BIAS row is a `ScorerProvenance`,
    never a primary ref). A `resolved` ref requires all identity/locator/
    snapshot/version fields and exactly one of checksum or
    checksum-null-reason; an `unresolved` ref requires `unresolved_reason`."""

    ref_id: str
    source_type: str
    source_id: str
    locator: str
    source_snapshot: str
    source_version: str
    source_sha256: Optional[str]
    source_sha256_null_reason: Optional[str]
    supports_criterion: str
    resolution_status: ResolutionStatus
    unresolved_reason: Optional[str]

    def __post_init__(self) -> None:
        if not _non_blank(self.ref_id):
            raise ProvenanceValidationError("PrimaryEvidenceRef.ref_id must be non-blank")
        if self.source_type not in _PRIMARY_SOURCE_TYPES:
            raise ProvenanceValidationError(
                f"PrimaryEvidenceRef.source_type must be one of {sorted(_PRIMARY_SOURCE_TYPES)!r}; "
                f"got {self.source_type!r} (a BIAS row is never a PrimaryEvidenceRef)"
            )
        if not _non_blank(self.supports_criterion):
            raise ProvenanceValidationError("PrimaryEvidenceRef.supports_criterion must be non-blank")
        if not isinstance(self.resolution_status, ResolutionStatus):
            raise ProvenanceValidationError(
                "PrimaryEvidenceRef.resolution_status must be a ResolutionStatus"
            )
        if self.source_sha256 is not None and not _is_hex64(self.source_sha256):
            raise ProvenanceValidationError(
                "PrimaryEvidenceRef.source_sha256 must be lowercase hex-64 when set"
            )

        if self.resolution_status is ResolutionStatus.RESOLVED:
            for name in ("source_id", "locator", "source_snapshot", "source_version"):
                if not _non_blank(getattr(self, name)):
                    raise ProvenanceValidationError(
                        f"a resolved PrimaryEvidenceRef requires non-blank {name}"
                    )
            has_checksum = self.source_sha256 is not None
            has_null_reason = _non_blank(self.source_sha256_null_reason)
            if has_checksum == has_null_reason:
                raise ProvenanceValidationError(
                    "a resolved PrimaryEvidenceRef requires exactly one of source_sha256 or "
                    "source_sha256_null_reason"
                )
            if self.unresolved_reason is not None:
                raise ProvenanceValidationError(
                    "a resolved PrimaryEvidenceRef must not carry an unresolved_reason"
                )
        else:
            if not _non_blank(self.unresolved_reason):
                raise ProvenanceValidationError(
                    "an unresolved PrimaryEvidenceRef requires a non-blank unresolved_reason"
                )


@dataclass(frozen=True)
class PacketCriterionInput:
    """One caller-supplied criterion call + its two-level provenance. Carries
    **no** caller-supplied lineage or disposition -- those are resolved by
    `build_packet` from the injected `PacketConfig.lineage_policy`."""

    criterion: str
    strength: str
    direction: str
    rationale: str
    scorer_provenance: ScorerProvenance
    primary_evidence_refs: Tuple[PrimaryEvidenceRef, ...]
    primary_grounding: PrimaryGrounding
    primary_grounding_reason: str

    def __post_init__(self) -> None:
        """`primary_grounding_reason` content (e.g. required-when-ABSENT) is
        validated by `build_packet` against the build-computed
        `primary_required`, not here -- a caller can freely construct/
        `dataclasses.replace` an input for negative-path fixtures without an
        unrelated constructor raising."""
        for name in ("criterion", "strength", "direction", "rationale"):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"PacketCriterionInput.{name} must be non-blank")
        if not isinstance(self.scorer_provenance, ScorerProvenance):
            raise PacketValidationError(
                "PacketCriterionInput.scorer_provenance must be a ScorerProvenance"
            )
        object.__setattr__(self, "primary_evidence_refs", tuple(self.primary_evidence_refs))
        for ref in self.primary_evidence_refs:
            if not isinstance(ref, PrimaryEvidenceRef):
                raise PacketValidationError(
                    "PacketCriterionInput.primary_evidence_refs must contain only PrimaryEvidenceRef"
                )
        if not isinstance(self.primary_grounding, PrimaryGrounding):
            raise PacketValidationError(
                "PacketCriterionInput.primary_grounding must be a PrimaryGrounding"
            )


@dataclass(frozen=True)
class MissingEvidence:
    category: str
    next_action: str
    supporting_field_paths: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not _non_blank(self.category):
            raise PacketValidationError("MissingEvidence.category must be non-blank")
        if not _non_blank(self.next_action):
            raise PacketValidationError("MissingEvidence.next_action must be non-blank")
        object.__setattr__(self, "supporting_field_paths", tuple(self.supporting_field_paths))


@dataclass(frozen=True)
class PatternRef:
    """The selection stratum is never a production direction (census
    selection-metadata only)."""

    census_snapshot_id: str
    pattern_id: str
    census_selection_stratum: str
    pattern_signature: Tuple[str, ...]
    member_count: int

    def __post_init__(self) -> None:
        for name in ("census_snapshot_id", "pattern_id", "census_selection_stratum"):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"PatternRef.{name} must be non-blank")
        object.__setattr__(self, "pattern_signature", tuple(self.pattern_signature))
        if (
            isinstance(self.member_count, bool)
            or not isinstance(self.member_count, int)
            or self.member_count < 0
        ):
            raise PacketValidationError("PatternRef.member_count must be a non-negative int")


@dataclass(frozen=True)
class ExternalComparator:
    """The AAVC envelope. Attached to the packet but excluded from the
    evidence core and the first-pass view."""

    comparator_id: str
    source_name: str
    source_snapshot: str
    source_doi: str
    source_archive_sha256: str
    source_commit: str
    match_method: str
    machine_class: str
    criteria: Tuple[str, ...]
    flags: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "comparator_id", "source_name", "source_snapshot", "source_doi",
            "source_commit", "match_method", "machine_class",
        ):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"ExternalComparator.{name} must be non-blank")
        if not _is_hex64(self.source_archive_sha256):
            raise PacketValidationError(
                "ExternalComparator.source_archive_sha256 must be lowercase hex-64"
            )
        object.__setattr__(self, "criteria", tuple(self.criteria))
        object.__setattr__(self, "flags", tuple(self.flags))


@dataclass(frozen=True)
class PacketInput:
    """The injected packet-build input (PRD-04 sec 4.10, FR24). Carries no
    lineage -- `build_packet` resolves every criterion's disposition from the
    injected `PacketConfig.lineage_policy`."""

    identity: CanonicalVariantIdentity
    criterion_inputs: Tuple[PacketCriterionInput, ...]
    run_metadata: RunMetadata
    source_snapshot: SourceSnapshotPins
    quality_flags: Tuple[str, ...]
    missing_evidence: Tuple[MissingEvidence, ...]
    pattern_ref: Optional[PatternRef]
    external_comparators: Tuple[ExternalComparator, ...]
    predecessor_packet_id: Optional[str]
    predecessor_envelope_hash: Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CanonicalVariantIdentity):
            raise PacketValidationError("PacketInput.identity must be a CanonicalVariantIdentity")
        object.__setattr__(self, "criterion_inputs", tuple(self.criterion_inputs))
        for item in self.criterion_inputs:
            if not isinstance(item, PacketCriterionInput):
                raise PacketValidationError(
                    "PacketInput.criterion_inputs must contain only PacketCriterionInput"
                )
        if not isinstance(self.run_metadata, RunMetadata):
            raise PacketValidationError("PacketInput.run_metadata must be a RunMetadata")
        if not isinstance(self.source_snapshot, SourceSnapshotPins):
            raise PacketValidationError("PacketInput.source_snapshot must be a SourceSnapshotPins")
        if not isinstance(self.quality_flags, (list, tuple)):
            raise PacketValidationError("PacketInput.quality_flags must be a list or tuple of non-blank strings")
        for item in self.quality_flags:
            if not _non_blank(item):
                raise PacketValidationError("PacketInput.quality_flags must contain only non-blank strings")
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))
        object.__setattr__(self, "missing_evidence", tuple(self.missing_evidence))
        for item in self.missing_evidence:
            if not isinstance(item, MissingEvidence):
                raise PacketValidationError(
                    "PacketInput.missing_evidence must contain only MissingEvidence"
                )
        if self.pattern_ref is not None and not isinstance(self.pattern_ref, PatternRef):
            raise PacketValidationError("PacketInput.pattern_ref must be a PatternRef or None")
        object.__setattr__(self, "external_comparators", tuple(self.external_comparators))
        for item in self.external_comparators:
            if not isinstance(item, ExternalComparator):
                raise PacketValidationError(
                    "PacketInput.external_comparators must contain only ExternalComparator"
                )


@dataclass(frozen=True)
class CriterionEntry:
    """The immutable, packet-scoped result of resolving one
    `PacketCriterionInput` against the injected lineage policy (FR4.1/FR4.2).
    Both raw dispositions are preserved verbatim alongside the derived
    `packet_policy_disposition`."""

    criterion: str
    strength: str
    direction: str
    rationale: str
    lineage_class: str
    validation_disposition: str
    production_disposition: str
    decision_dependency: str
    packet_policy_disposition: PacketPolicyDisposition
    exclusion_reason: Optional[str]
    scorer_provenance: ScorerProvenance
    primary_evidence_refs: Tuple[PrimaryEvidenceRef, ...]
    primary_grounding: PrimaryGrounding
    primary_grounding_reason: str
    primary_required: bool

    def __post_init__(self) -> None:
        for name in ("criterion", "strength", "direction", "rationale"):
            if not _non_blank(getattr(self, name)):
                raise PacketValidationError(f"CriterionEntry.{name} must be non-blank")
        if not isinstance(self.packet_policy_disposition, PacketPolicyDisposition):
            raise PacketValidationError(
                "CriterionEntry.packet_policy_disposition must be a PacketPolicyDisposition"
            )
        if not isinstance(self.scorer_provenance, ScorerProvenance):
            raise PacketValidationError("CriterionEntry.scorer_provenance must be a ScorerProvenance")
        object.__setattr__(self, "primary_evidence_refs", tuple(self.primary_evidence_refs))
        for ref in self.primary_evidence_refs:
            if not isinstance(ref, PrimaryEvidenceRef):
                raise PacketValidationError(
                    "CriterionEntry.primary_evidence_refs must contain only PrimaryEvidenceRef"
                )
        if not isinstance(self.primary_grounding, PrimaryGrounding):
            raise PacketValidationError("CriterionEntry.primary_grounding must be a PrimaryGrounding")
        if not isinstance(self.primary_required, bool):
            raise PacketValidationError("CriterionEntry.primary_required must be a bool")
        self._validate_primary_grounding_consistency()
        if (
            self.packet_policy_disposition is PacketPolicyDisposition.EXCLUDED
            and not _non_blank(self.exclusion_reason)
        ):
            raise PacketValidationError("an excluded CriterionEntry requires a non-blank exclusion_reason")
        if (
            self.packet_policy_disposition is not PacketPolicyDisposition.EXCLUDED
            and self.exclusion_reason is not None
        ):
            raise PacketValidationError("only an excluded CriterionEntry may carry an exclusion_reason")

    def _validate_primary_grounding_consistency(self) -> None:
        """Reject any `primary_required`/`PrimaryGrounding` combination that
        contradicts the resolved primary evidence (never a silent pass):

        - `NOT_REQUIRED` is only valid when `primary_required` is `False`.
        - `ABSENT` requires a non-blank `primary_grounding_reason` and no
          *resolved* `PrimaryEvidenceRef` (an absent claim cannot also carry
          a resolved primary ref).
        - `PRESENT` requires at least one *resolved* `PrimaryEvidenceRef` whose
          `supports_criterion` exactly equals this entry's `criterion`,
          regardless of `primary_required` (a claim of presence must be
          backed by a resolved ref for *this* criterion -- a resolved ref
          that supports a different criterion does not count)."""
        resolved_count = sum(
            1 for ref in self.primary_evidence_refs
            if ref.resolution_status is ResolutionStatus.RESOLVED
        )
        matching_resolved_count = sum(
            1 for ref in self.primary_evidence_refs
            if ref.resolution_status is ResolutionStatus.RESOLVED
            and ref.supports_criterion == self.criterion
        )
        if self.primary_grounding is PrimaryGrounding.NOT_REQUIRED:
            if self.primary_required:
                raise PacketValidationError(
                    f"criterion {self.criterion!r} has primary_required=True; "
                    "PrimaryGrounding.NOT_REQUIRED is invalid"
                )
        elif self.primary_grounding is PrimaryGrounding.ABSENT:
            if not _non_blank(self.primary_grounding_reason):
                raise PacketValidationError(
                    f"criterion {self.criterion!r} PrimaryGrounding.ABSENT requires a "
                    "non-blank primary_grounding_reason"
                )
            if resolved_count > 0:
                raise PacketValidationError(
                    f"criterion {self.criterion!r} PrimaryGrounding.ABSENT must have no "
                    "resolved PrimaryEvidenceRef"
                )
        elif self.primary_grounding is PrimaryGrounding.PRESENT:
            if matching_resolved_count < 1:
                raise PacketValidationError(
                    f"criterion {self.criterion!r} PrimaryGrounding.PRESENT requires at "
                    "least one resolved PrimaryEvidenceRef whose supports_criterion "
                    f"exactly equals {self.criterion!r}"
                )


@dataclass(frozen=True)
class PointContribution:
    criterion: str
    strength: str
    points: int

    def __post_init__(self) -> None:
        if not _non_blank(self.criterion):
            raise DirectionPolicyError("PointContribution.criterion must be non-blank")
        if not _non_blank(self.strength):
            raise DirectionPolicyError("PointContribution.strength must be non-blank")
        if isinstance(self.points, bool) or not isinstance(self.points, int):
            raise DirectionPolicyError("PointContribution.points must be an int")


@dataclass(frozen=True)
class CandidateDirection:
    """Nullable production candidate-direction (FR5). Unapproved means
    `direction=None, null_reason="production_policy_unapproved",
    signed_points=None`, no contributions. Approved means a non-null
    direction, null `null_reason`, and an integer score."""

    direction: Optional[str]
    null_reason: Optional[str]
    policy_id: str
    policy_version: str
    approval_status: str
    signed_points: Optional[int]
    per_criterion_points: Tuple[PointContribution, ...]

    def __post_init__(self) -> None:
        if not _non_blank(self.policy_id):
            raise DirectionPolicyError("CandidateDirection.policy_id must be non-blank")
        if not _non_blank(self.policy_version):
            raise DirectionPolicyError("CandidateDirection.policy_version must be non-blank")
        object.__setattr__(self, "per_criterion_points", tuple(self.per_criterion_points))
        for item in self.per_criterion_points:
            if not isinstance(item, PointContribution):
                raise DirectionPolicyError(
                    "CandidateDirection.per_criterion_points must contain only PointContribution"
                )
        if self.direction is None:
            if self.null_reason != "production_policy_unapproved":
                raise DirectionPolicyError(
                    "a null CandidateDirection.direction requires "
                    "null_reason='production_policy_unapproved'"
                )
            if self.signed_points is not None:
                raise DirectionPolicyError("a null CandidateDirection must have signed_points=None")
            if self.per_criterion_points:
                raise DirectionPolicyError("a null CandidateDirection must have no per_criterion_points")
        else:
            if self.null_reason is not None:
                raise DirectionPolicyError("a non-null CandidateDirection.direction requires null_reason=None")
            if isinstance(self.signed_points, bool) or not isinstance(self.signed_points, int):
                raise DirectionPolicyError(
                    "a non-null CandidateDirection requires an integer signed_points"
                )


@dataclass(frozen=True)
class FieldBinding:
    name: str
    field_path: str

    def __post_init__(self) -> None:
        if not _non_blank(self.name):
            raise PacketValidationError("FieldBinding.name must be non-blank")
        if not _non_blank(self.field_path):
            raise PacketValidationError("FieldBinding.field_path must be non-blank")


@dataclass(frozen=True)
class NarrativePlanEntry:
    template_id: str
    field_bindings: Tuple[FieldBinding, ...]

    def __post_init__(self) -> None:
        if not _non_blank(self.template_id):
            raise PacketValidationError("NarrativePlanEntry.template_id must be non-blank")
        object.__setattr__(self, "field_bindings", tuple(self.field_bindings))
        for binding in self.field_bindings:
            if not isinstance(binding, FieldBinding):
                raise PacketValidationError(
                    "NarrativePlanEntry.field_bindings must contain only FieldBinding"
                )


@dataclass(frozen=True)
class NarrativePlan:
    entries: Tuple[NarrativePlanEntry, ...]
    model: str
    prompt_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        for entry in self.entries:
            if not isinstance(entry, NarrativePlanEntry):
                raise PacketValidationError("NarrativePlan.entries must contain only NarrativePlanEntry")
        if not _non_blank(self.model):
            raise PacketValidationError("NarrativePlan.model must be non-blank")
        if not _is_hex64(self.prompt_hash):
            raise PacketValidationError("NarrativePlan.prompt_hash must be lowercase hex-64")


@dataclass(frozen=True)
class CandidateEvidencePacket:
    """The frozen packet (PRD-04 sec 4.1). `packet_id == packet_envelope_hash`.
    Later state/reviewer actions create a new packet or decision record; they
    never mutate this object."""

    packet_schema_version: str
    packet_id: str
    evidence_core_hash: str
    narrative_plan_hash: str
    packet_envelope_hash: str
    identity: CanonicalVariantIdentity
    entries: Tuple[CriterionEntry, ...]
    candidate_direction: CandidateDirection
    exclusions: Tuple[str, ...]
    contradiction: bool
    quality_flags: Tuple[str, ...]
    missing_evidence: Tuple[MissingEvidence, ...]
    narrative_plan: Optional[NarrativePlan]
    external_comparators: Tuple[ExternalComparator, ...]
    review_state: ReviewState
    gate_status: GateStatus
    pattern_ref: Optional[PatternRef]
    run_metadata: RunMetadata
    source_snapshot: SourceSnapshotPins
    predecessor_packet_id: Optional[str]
    predecessor_envelope_hash: Optional[str]


@dataclass(frozen=True)
class FirstPassPacketView:
    """Direction-blinded projection of a `CandidateEvidencePacket` (PRD-04 FR14/FR14.1,
    AC20). The only view a first-pass reviewer may consume; carries no candidate
    direction, external comparator envelope, pattern reference, run metadata, null
    reasons, points, or policy ids."""

    packet_id: str
    evidence_core_hash: str
    identity: CanonicalVariantIdentity
    entries: Tuple[CriterionEntry, ...]
    exclusions: Tuple[str, ...]
    contradiction: bool
    quality_flags: Tuple[str, ...]
    missing_evidence: Tuple[MissingEvidence, ...]
    narrative_plan: Optional[NarrativePlan]
    review_state: ReviewState
    gate_status: GateStatus


def redact_for_first_pass(packet: CandidateEvidencePacket) -> FirstPassPacketView:
    """Pure projection (PRD-04 FR14.1, AC20) that strips `candidate_direction`,
    `external_comparators`, `pattern_ref`, `run_metadata`, `source_snapshot`,
    predecessor linkage, and hash/version fields not part of the first-pass
    schema, retaining only the fields blinded reviewers are permitted to see."""
    return FirstPassPacketView(
        packet_id=packet.packet_id,
        evidence_core_hash=packet.evidence_core_hash,
        identity=packet.identity,
        entries=packet.entries,
        exclusions=packet.exclusions,
        contradiction=packet.contradiction,
        quality_flags=packet.quality_flags,
        missing_evidence=packet.missing_evidence,
        narrative_plan=packet.narrative_plan,
        review_state=packet.review_state,
        gate_status=packet.gate_status,
    )


# --------------------------------------------------------------------------
# Disposition precedence (PRD sec 4.1 FR4.1 -- exhaustive, first match wins)
# --------------------------------------------------------------------------

_KNOWN_DISPOSITIONS = frozenset({"allowed", "requires_heldout_mask", "forbidden", "deferred"})
_DEFERRABLE = frozenset({"allowed", "deferred"})


def resolve_packet_policy_disposition(validation: str, production: str) -> PacketPolicyDisposition:
    """FR4.1 precedence, implemented exactly (validation dominates):

    1. ``validation == forbidden`` -> excluded, regardless of production
       (PP5/BP6/PS4).
    2. ``validation == requires_heldout_mask`` -> masked, regardless of
       production (PS1/PM5/PM1/PP2/BP1).
    3. both validation and production are in ``{allowed, deferred}`` and at
       least one of them is ``deferred`` -> deferred (PS3, BS2).
    4. ``validation == allowed`` and ``production == allowed`` -> included.
    5. any other (incl. unknown) pairing -> fail loud, never silently
       ``included`` (r3-1).
    """
    if validation not in _KNOWN_DISPOSITIONS or production not in _KNOWN_DISPOSITIONS:
        raise DispositionMappingError(
            f"unknown disposition pairing: validation={validation!r}, production={production!r}"
        )
    if validation == "forbidden":
        return PacketPolicyDisposition.EXCLUDED
    if validation == "requires_heldout_mask":
        return PacketPolicyDisposition.MASKED
    if validation in _DEFERRABLE and production in _DEFERRABLE:
        if validation == "allowed" and production == "allowed":
            return PacketPolicyDisposition.INCLUDED
        return PacketPolicyDisposition.DEFERRED
    raise DispositionMappingError(
        f"unmapped disposition pairing: validation={validation!r}, production={production!r} "
        "-- never silently `included`"
    )
