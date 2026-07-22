"""Frozen structural dataclasses and typed errors for the RAPTOR Mechanism Atlas.

This module defines the condition-agnostic data model shared by every
downstream Atlas module (pack loading, identity admission, ontology
validation, source grounding, profile assembly, candidate promotion and
export). Nothing in this module (or any other module under
``src/raptor/atlas``) may reference a concrete disease, gene symbol,
transcript accession, or mechanistic claim. Those specifics live only in
versioned disease packs under ``configs/atlas/packs/``.

All dataclasses below are ``frozen=True`` (immutable, value-equality). Core
collections (claims, edges, evidence, source pins) use ``tuple`` so profile
objects are order-stable and hashable-by-value. Raw candidate JSON payloads
staged from an out-of-process discovery pipeline (``AtlasCandidateImport``)
deliberately keep native ``list``/``dict`` shapes because they represent
unvalidated, untrusted input that has not yet been admitted into the frozen
core model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class AtlasError(Exception):
    """Private base class for all Mechanism Atlas typed errors."""


class AtlasSchemaError(AtlasError):
    """A structural/schema invariant of the Atlas data model was violated."""


class AtlasIdentityError(AtlasError):
    """Variant identity admission or transcript reconciliation failed."""


class AtlasProvenanceError(AtlasError):
    """A claim, source, or promotion step failed a provenance requirement."""


class AtlasSourceVerificationError(AtlasError):
    """A source register entry failed fail-closed verification checks."""


class AtlasLeakageError(AtlasError):
    """A module-boundary or classification-leakage guard was violated."""


class AtlasExportError(AtlasError):
    """A one-way external export could not be produced from a profile."""


class AtlasPackError(AtlasError):
    """A disease pack manifest failed structural validation or hash checks."""


# ---------------------------------------------------------------------------
# Core structural vocabulary (condition-agnostic state enumerations)
# ---------------------------------------------------------------------------

IDENTITY_STATES = ("resolved", "unresolved")
CLAIM_VERIFICATION_STATES = ("verified", "unverified")
DIRECTIONALITY_STATES = ("increase", "decrease", "none", "unknown")
EDGE_EFFECT_STATES = ("increase", "decrease", "disrupt", "none", "unknown")
MECHANISM_STATES = ("supported", "contradicted", "conflicting", "unknown", "unverified")
ZYGOSITY_STATES = ("germline", "somatic", "mosaic", "inferred", "unknown")
CONFIDENCE_STATES = ("low", "moderate", "high", "na")
DIRECT_EVIDENCE_LEAF_SOURCE_TYPES = ("PRIMARY-LIT", "DATASET")
SOURCE_REGISTER_ENTRY_SOURCE_TYPES = (
    "PRIMARY-OFFICIAL", "PRIMARY-DOC", "PRIMARY-LIT", "SECONDARY-SYNTH",
    "DATASET", "CROSSWALK", "UNVERIFIED",
)
SOURCE_REGISTER_ENTRY_ROLES = ("direct_evidence_leaf", "provenance_only", "context", "crosswalk")
SOURCE_REGISTER_ENTRY_VERIFICATION_STATES = ("verified", "confirm_pending", "unverified")


def _require(condition: bool, message: str, error_type: type = AtlasSchemaError) -> None:
    if not condition:
        raise error_type(message)


# ---------------------------------------------------------------------------
# Disease pack binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class PackBinding:
    """Identifies exactly which disease pack (id/version/hash) a profile is
    bound to. This is the sole authoritative, hash-participating pack
    reference in the frozen model."""

    pack_id: str
    pack_version: str
    pack_content_hash: str


@dataclass(frozen=True, eq=True)
class DiseasePack:
    """In-memory representation of a loaded, validated disease pack manifest.

    Construction performs no validation itself -- validation and hashing are
    the responsibility of :mod:`raptor.atlas.pack`. This keeps the dataclass
    usable for pure fixture construction in tests.
    """

    schema: str
    pack_id: str
    pack_version: str
    pack_content_hash: str
    allowed_genes: tuple[str, ...]
    assembly_pins: tuple[str, ...]
    transcript_pins: tuple[str, ...]
    reconciliation_policy: Mapping[str, Any]
    ontology_extensions: Mapping[str, Any]
    source_register_pins: tuple["SourceRegisterEntry", ...]
    prohibitions: Mapping[str, Any]
    pilot_eval_metadata: Mapping[str, Any]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class AtlasIdentity:
    """Canonical variant identity. A GRCh38-shaped SPDI string is the sole
    admission/reconciliation key; all other fields are descriptive."""

    spdi_canonical: str
    gene: str
    assembly: str
    transcript_pin: Optional[str]
    hgvs_c: Optional[str]
    hgvs_p: Optional[str]
    hgvs_g: Optional[str]
    identity_state: str

    def __post_init__(self) -> None:
        _require(
            bool(self.spdi_canonical),
            "AtlasIdentity.spdi_canonical must be a non-empty canonical SPDI string",
        )
        _require(
            self.identity_state in IDENTITY_STATES,
            f"AtlasIdentity.identity_state must be one of {IDENTITY_STATES!r}, got {self.identity_state!r}",
        )


# ---------------------------------------------------------------------------
# Source grounding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class Span:
    """A locator into a source artifact (page/figure/table/coordinate)."""

    locator: str
    exact_quote: Optional[str] = None
    page_or_figure: Optional[str] = None


@dataclass(frozen=True, eq=True)
class EntryRef:
    """A reference from a claim to a source register entry. ``span`` is
    owned solely by ``EntryRef`` -- no other structure carries a span."""

    entry_id: str
    span: Optional[Span] = None


@dataclass(frozen=True, eq=True)
class SourceRegisterEntry:
    """A single registered source (bibliographic record or dataset) that may
    ground observed claims. ``role``/``source_type`` pairing is enforced at
    construction: only ``PRIMARY-LIT``/``DATASET`` source types may serve as
    a ``direct_evidence_leaf``."""

    entry_id: str
    source_type: str
    role: str
    urn_or_ids: Mapping[str, str]
    verification: str
    transcript: Optional[str] = None
    license: Optional[str] = None
    sha256: Optional[str] = None
    variant_count: Optional[int] = None

    def __post_init__(self) -> None:
        if self.role == "direct_evidence_leaf":
            _require(
                self.source_type in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
                "SourceRegisterEntry with role='direct_evidence_leaf' must have "
                f"source_type in {DIRECT_EVIDENCE_LEAF_SOURCE_TYPES!r}, got {self.source_type!r}",
            )


@dataclass(frozen=True, eq=True)
class ObservedClaim:
    """A single mechanistic claim, grounded via ``source_ref`` only. No
    span/variant/statement fields live directly on the claim -- span
    ownership belongs solely to ``EntryRef``."""

    claim_id: str
    claim_text: str
    claim_kind: str
    source_ref: EntryRef
    verification: str
    directionality: str

    def __post_init__(self) -> None:
        _require(
            self.verification in CLAIM_VERIFICATION_STATES,
            f"ObservedClaim.verification must be one of {CLAIM_VERIFICATION_STATES!r}",
        )
        _require(
            self.directionality in DIRECTIONALITY_STATES,
            f"ObservedClaim.directionality must be one of {DIRECTIONALITY_STATES!r}",
        )


# ---------------------------------------------------------------------------
# Context / mechanism graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class ContextRecord:
    """Experimental context under which claims/edges were observed."""

    assay: str
    model_system: str
    cell_type: Optional[str]
    tissue: Optional[str]
    zygosity_context: str
    assay_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(
            self.zygosity_context in ZYGOSITY_STATES,
            f"ContextRecord.zygosity_context must be one of {ZYGOSITY_STATES!r}",
        )


@dataclass(frozen=True, eq=True)
class CandidateClass:
    """A candidate mechanism classification with a supporting confidence."""

    class_id: str
    state: str
    confidence: str

    def __post_init__(self) -> None:
        _require(
            self.state in MECHANISM_STATES,
            f"CandidateClass.state must be one of {MECHANISM_STATES!r}",
        )
        _require(
            self.confidence in CONFIDENCE_STATES,
            f"CandidateClass.confidence must be one of {CONFIDENCE_STATES!r}",
        )


@dataclass(frozen=True, eq=True)
class MechanismEdge:
    """A directed edge in the mechanism graph between two node layers."""

    from_layer: str
    to_layer: str
    effect: str
    supporting_claims: tuple[str, ...]
    contradicting_claims: tuple[str, ...]
    context: Optional[ContextRecord]
    edge_state: str

    def __post_init__(self) -> None:
        _require(
            self.effect in EDGE_EFFECT_STATES,
            f"MechanismEdge.effect must be one of {EDGE_EFFECT_STATES!r}",
        )
        _require(
            self.edge_state in MECHANISM_STATES,
            f"MechanismEdge.edge_state must be one of {MECHANISM_STATES!r}",
        )
        if self.supporting_claims and self.contradicting_claims:
            _require(
                self.edge_state == "conflicting",
                "MechanismEdge with both supporting and contradicting claims "
                "must have edge_state='conflicting'",
            )


@dataclass(frozen=True, eq=True)
class EvidenceAssessment:
    """Aggregate evidence-state summary derived from claims and edges."""

    supporting: tuple[str, ...]
    contradicting: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    unknowns: tuple[str, ...]


# ---------------------------------------------------------------------------
# Run metadata / provenance / profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class RunMetadata:
    """Non-hash-bound run bookkeeping. ``pack_binding_audit`` is an
    equality-bound (not hashed) copy checked against the profile's
    authoritative ``pack_binding`` at construction time."""

    run_id: str
    generated_at: str
    tool_versions: Mapping[str, str]
    pack_binding_audit: Optional[PackBinding] = None


@dataclass(frozen=True, eq=True)
class Provenance:
    """Audit-facing provenance snapshot. Holds no pack binding of its own --
    ``MechanismProfile.pack_binding`` is the sole authoritative/hash-bound
    binding."""

    source_pins: tuple[EntryRef, ...]
    version_pins: tuple[str, ...]
    content_hashes: Mapping[str, str]


@dataclass(frozen=True, eq=True)
class MechanismProfile:
    """The frozen, hashable Mechanism Atlas profile for a single admitted
    variant identity, bound to exactly one disease pack."""

    identity: AtlasIdentity
    pack_binding: PackBinding
    claims: tuple[ObservedClaim, ...]
    candidate_classes: tuple[CandidateClass, ...]
    edges: tuple[MechanismEdge, ...]
    evidence: EvidenceAssessment
    provenance: Provenance
    run_metadata: Optional[RunMetadata] = None

    def __post_init__(self) -> None:
        _require(
            self.pack_binding is not None,
            "MechanismProfile.pack_binding is required and must be the sole "
            "authoritative pack binding",
        )
        if self.run_metadata is not None and self.run_metadata.pack_binding_audit is not None:
            _require(
                self.run_metadata.pack_binding_audit == self.pack_binding,
                "MechanismProfile.run_metadata.pack_binding_audit must match "
                "MechanismProfile.pack_binding exactly",
            )

        known_claim_ids = {claim.claim_id for claim in self.claims}
        for edge in self.edges:
            for claim_id in (*edge.supporting_claims, *edge.contradicting_claims):
                _require(
                    claim_id in known_claim_ids,
                    f"MechanismEdge references unknown claim_id {claim_id!r}",
                )
        for claim_id in (*self.evidence.supporting, *self.evidence.contradicting):
            _require(
                claim_id in known_claim_ids,
                f"EvidenceAssessment references unknown claim_id {claim_id!r}",
            )


# ---------------------------------------------------------------------------
# Discovery candidate import / promotion (out-of-process staging)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class AtlasCandidateImport:
    """Raw, untrusted candidate payload staged from an out-of-process
    discovery pipeline. List-typed fields deliberately stay as native
    Python ``list``/``dict`` (not tuples) because this data has not yet been
    admitted into the frozen core model."""

    candidate_variant: Mapping[str, Any]
    proposed_claims: list
    proposed_sources: list
    retrieval_provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require(
            isinstance(self.candidate_variant, dict),
            "AtlasCandidateImport.candidate_variant must be a dict",
        )
        _require(
            isinstance(self.proposed_claims, list),
            "AtlasCandidateImport.proposed_claims must be a raw list",
        )
        _require(
            isinstance(self.proposed_sources, list),
            "AtlasCandidateImport.proposed_sources must be a raw list",
        )
        _require(
            isinstance(self.retrieval_provenance, dict),
            "AtlasCandidateImport.retrieval_provenance must be a dict",
        )


@dataclass(frozen=True, eq=True)
class PromotionContext:
    """Collaborators and pinned pack context needed to validate/promote a
    staged candidate into the frozen core model."""

    disease_pack: DiseasePack
    citation_resolver: Callable[[Mapping[str, Any]], bool]
    context_validator: Callable[[str, Mapping[str, Any]], bool]
    human_oracle_reviewer: Callable[[Any], bool]
    duplicate_index: Optional[Mapping[str, str]] = None


# ---------------------------------------------------------------------------
# One-way external export
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class DisMechRecord:
    """One-way export record for the external DisMech schema. Holds an
    equality-bound (not hash-participating) audit copy of provenance."""

    spdi_canonical: str
    pack_binding: PackBinding
    claims: tuple[ObservedClaim, ...]
    provenance: Mapping[str, Any]
