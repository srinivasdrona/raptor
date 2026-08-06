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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple, runtime_checkable


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


class AtlasCatalogError(AtlasError):
    """Base for the offline citation-catalog/resolver subsystem (sibling of
    :class:`AtlasPackError`). Raised ONLY by ``raptor.atlas.citation``
    catalog/resolver operations (``load_catalog``, ``catalog_content_hash``,
    ``normalize_identifier``, ``resolve``, ``verify_content``,
    ``verify_span``); it is not a blanket type for every Atlas failure."""


class AtlasCatalogSchemaError(AtlasCatalogError):
    """A citation catalog manifest failed structural validation: malformed
    schema/field/enum, duplicate ``source_id``, duplicate/cross-source
    identifier alias, or an ineligible role/source_type leaf pairing."""


class AtlasCatalogHashError(AtlasCatalogError):
    """A citation catalog's declared ``catalog_content_hash`` does not match
    the recomputed digest of its own content (self-hash drift)."""


class AtlasCatalogPathError(AtlasCatalogError):
    """A citation catalog manifest or content-root artifact path failed
    safety checks: traversal, symlink/junction escape, drive/UNC/absolute
    path where a relative one is required, or a missing/non-regular file."""


class AtlasCitationResolutionError(AtlasCatalogError):
    """Identifier normalization failed, or resolution failed: unknown
    scheme, unresolved/ambiguous/cross-alias identifier, or a structurally
    valid catalog source that is not grounding-eligible (fails the full
    grounding predicate) or whose declared source_type disagrees."""


class AtlasContentDriftError(AtlasCatalogError):
    """A raw or extracted-text artifact's recomputed sha256/byte-length
    disagrees with the catalog-declared value, or the extracted-text
    artifact is not valid UTF-8. Declared hashes are never trusted."""


class AtlasSpanMismatchError(AtlasCatalogError):
    """A claim span failed exact verification: invalid locator grammar or
    out-of-range offsets, a missing extracted-text artifact, or an
    ``exact_quote`` that does not equal the normalized text slice exactly."""


class AtlasIdentityMapError(AtlasError):
    """Base for the offline raw-identity replay mapper subsystem (sibling
    of :class:`AtlasPackError`/:class:`AtlasCatalogError`). Raised ONLY by
    ``raptor.atlas.identity_map`` (``load_identity_map``,
    ``identity_map_content_hash``, ``identity_map_lock_content_hash``,
    :class:`OfflineRawIdentityMapper`) and by the out-of-process acquisition
    adapter (``scripts/build_atlas_raw_identity_map.py``); it is not a
    blanket type for every Atlas failure."""


class AtlasIdentityMapSchemaError(AtlasIdentityMapError):
    """A raw identity map, lock, raw inventory, or replay record failed
    structural validation: malformed schema/field/type, a missing required
    field, an invalid enum value, a record/row count mismatch, or a raw
    identity string that is not a recognized protein-change notation."""


class AtlasIdentityMapHashError(AtlasIdentityMapError):
    """A raw identity map's or lock's declared self-hash, a lock-to-map
    binding, a pack binding, a raw-inventory binding, a response file hash,
    a response bundle hash, or an acquisition-tool hash disagrees with the
    recomputed value. Declared hashes are never trusted."""


class AtlasIdentityMapPathError(AtlasIdentityMapError):
    """A raw identity map or lock artifact path failed safety checks:
    traversal, symlink/junction escape, drive/UNC/absolute path where a
    relative one is required, a missing/non-regular file, or an attempted
    publish over an existing (colliding) path."""


class AtlasIdentityMapResponseError(AtlasIdentityMapError):
    """An official response artifact is not valid UTF-8/JSON, is missing an
    expected ESearch/ESummary field, or its content does not permit a
    deterministic consequence/scope classification."""


class AtlasIdentityMapAmbiguityError(AtlasIdentityMapError):
    """A record's independently recomputed resolution classification (or
    identity/consequence/scope derivation) disagrees with its declared
    value, or a replay lookup does not exactly match a pinned
    raw_record_id/raw_identity_string/source_reported_consequence_hint."""


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
# Citation resolver: frozen value/result types, typed errors' companion
# dataclasses, and the CitationResolver protocol.
#
# These are the frozen VALUE/RESULT types shared by the offline citation
# catalog + resolver (``raptor.atlas.citation``, which owns the loader and
# verification LOGIC) and by promotion (``raptor.atlas.promote``, which
# consumes them through ``PromotionContext.citation_resolver``). Neither
# this module nor any type below imports ``raptor.atlas.citation`` --
# import direction stays acyclic (citation.py -> model.py).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class CitationIdentifier:
    """A normalized, canonical citation identifier (PMID/PMCID/DOI/
    ACCESSION), as returned by ``normalize_identifier``."""

    scheme: str
    value: str
    canonical: str


@dataclass(frozen=True, eq=True)
class CatalogSource:
    """A flattened, frozen projection of one validated catalog source
    entry. ``identifiers`` is a normalized, order-stable tuple of
    :class:`CitationIdentifier`. The ``extracted_*``/``extraction_*``/
    ``text_normalization`` fields default to ``None`` because a
    provenance/context-only source, or a leaf with no extracted-text
    artifact, structurally loads without one -- only a span verification
    requires it (see ``verify_span``)."""

    source_id: str
    source_type: str
    role: str
    identifiers: Tuple["CitationIdentifier", ...]
    license: Optional[str]
    permitted_use: str
    verification: str
    authoritative_url: Optional[str]
    document_date: Optional[str]
    document_version: Optional[str]
    raw_relative_path: Optional[str]
    raw_declared_sha256: Optional[str]
    raw_declared_byte_length: Optional[int]
    raw_media_type: Optional[str]
    extracted_relative_path: Optional[str] = None
    extracted_declared_sha256: Optional[str] = None
    extracted_declared_byte_length: Optional[int] = None
    extraction_method: Optional[str] = None
    extraction_version: Optional[str] = None
    text_normalization: Optional[str] = None


@dataclass(frozen=True, eq=True)
class ContentVerification:
    """The RECOMPUTED (from-disk) content verification result. Declared
    catalog hashes/byte-lengths are never trusted -- only this recomputed
    result is authoritative."""

    raw_sha256: str
    raw_byte_length: int
    extracted_text_sha256: Optional[str]
    extracted_text_byte_length: Optional[int]


@dataclass(frozen=True, eq=True)
class ResolvedCitation:
    """The result of a successful, content-verified grounding resolution.
    Carries no text payload (kept lightweight) -- ``verify_span``
    re-reads and re-verifies the extracted-text artifact as
    defense-in-depth."""

    identifier: CitationIdentifier
    source: CatalogSource
    content: ContentVerification
    content_verified: bool


@dataclass(frozen=True, eq=True)
class VerifiedSpan:
    """The result of a successful exact-span verification. Returned ONLY
    on success -- any mismatch raises :class:`AtlasSpanMismatchError`."""

    source_id: str
    locator: str
    start: int
    end: int
    exact_quote: str
    extracted_text_sha256: str


@runtime_checkable
class CitationResolver(Protocol):
    """The minimal production interface :class:`PromotionContext` requires.
    Promotion Gate 3 calls ``resolve``; Gate 4 calls ``verify_span``. A
    strict test fake need implement exactly these two methods -- this
    Protocol is ``runtime_checkable`` so ``isinstance(obj, CitationResolver)``
    performs a structural (duck-typed) check and rejects a bare boolean or
    callable that lacks both methods."""

    def resolve(self, identifier: "CitationIdentifier | str") -> "ResolvedCitation":
        ...

    def verify_span(self, resolved: "ResolvedCitation", span: "Span") -> "VerifiedSpan":
        ...


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
    citation_resolver: CitationResolver
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


# ---------------------------------------------------------------------------
# Offline raw-identity replay mapper (RP1-RP7 replay tuple)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class RawIdentityReplay:
    """The full RP1-RP7 replay tuple for one raw identity, independently
    recomputed from immutable, hash-verified official response bytes by
    :func:`raptor.atlas.identity_map.load_identity_map`. Never constructed
    directly from untrusted/declared input -- only by a verified mapper."""

    normalization_outcome: str
    universe_key: str
    identity_state: str
    spdi_canonical: Optional[str]
    hgvs_c: Optional[str]
    hgvs_p: Optional[str]
    transcript_pin: Optional[str]
    residue_index: Optional[int]
    codon_index: Optional[int]
    consequence_class: Optional[str]
    scope_decision: str
    exclusion_code: Optional[str]

    def __post_init__(self) -> None:
        _require(
            self.identity_state in IDENTITY_STATES,
            f"RawIdentityReplay.identity_state must be one of {IDENTITY_STATES}, "
            f"got {self.identity_state!r}",
        )
        if self.identity_state == "resolved":
            _require(
                self.spdi_canonical is not None and self.hgvs_c is not None,
                "RawIdentityReplay: a 'resolved' identity_state requires a non-null "
                "spdi_canonical and hgvs_c",
            )
            _require(
                self.exclusion_code is None,
                "RawIdentityReplay: a 'resolved' identity_state must not carry an "
                "exclusion_code",
            )
        else:
            _require(
                self.spdi_canonical is None and self.hgvs_c is None,
                "RawIdentityReplay: an 'unresolved' identity_state must not carry a "
                "spdi_canonical or hgvs_c",
            )


@runtime_checkable
class RawIdentityMapper(Protocol):
    """The minimal offline replay interface the Atlas panel selector requires
    to independently replay a raw discovered identity against the pinned
    official response bundle. ``runtime_checkable`` so
    ``isinstance(obj, RawIdentityMapper)`` performs a structural check."""

    def replay(
        self,
        raw_record_id: str,
        raw_identity_string: str,
        source_reported_consequence_hint: str,
    ) -> RawIdentityReplay:
        ...


# ---------------------------------------------------------------------------
# Atlas Phase-2 contrast-panel selector: typed errors
# ---------------------------------------------------------------------------
#
# These are raised ONLY by ``raptor.atlas.panel``. ``AtlasPanelError`` is a
# new sibling of ``AtlasPackError``/``AtlasCatalogError``/
# ``AtlasIdentityMapError`` (it is not a supertype of any of them). Terminal
# selection outcomes (SOLUTION/INFEASIBLE_COMPLETE/UNDETERMINED per attempt;
# PANEL_SELECTED/INFEASIBLE_PANEL/UNDETERMINED_SEARCH_INCOMPLETE overall) are
# ordinary return values, never exceptions -- only a precondition/protocol
# fault raises one of the classes below.


class AtlasPanelError(AtlasError):
    """Base of the Atlas Phase-2 contrast-panel selector error family.

    Every instance carries a ``code`` (a string drawn from a closed enum of
    protocol-failure/input-fault names), an optional ``check_id`` (e.g.
    ``"V1"``, ``"K5"``, ``"U3"``, ``"RP4"``, ``"IM2"``, ``"E6"``) naming the
    specific rule that failed, and an optional ``locus`` describing where in
    the input the fault was found.
    """

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        check_id: Optional[str] = None,
        locus: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.check_id = check_id
        self.locus = locus


class AtlasPanelInputError(AtlasPanelError):
    """A caller/argument fault before any protocol check: a missing or
    unreadable path, a non-regular file, a symlink/junction or a '..'
    escape, malformed YAML, a wrong schema id, an absent required argument,
    or a timestamp that ``yaml.safe_load`` coerced into a ``date``/
    ``datetime`` instead of leaving as a quoted string."""


class AtlasPanelRegistrationError(AtlasPanelError):
    """A V1/V2/V3 failure (protocol digest mismatch, registration self-hash
    mismatch, seed literal mismatch), or a registration parameter this
    implementation cannot honour soundly (an unsupported ``search_scope`` or
    a non-null ``stratum_shortlist_size``)."""


class AtlasPanelPackDriftError(AtlasPanelError):
    """A V4 failure (``PACK_DRIFT``): the live disease-pack content hash
    does not equal one (or more) of the three required comparands (the
    registration's freeze-time snapshot, the candidate universe's pack
    binding, and the universe lock's pack binding)."""


class AtlasUniverseLockError(AtlasPanelError):
    """A V5 failure via K1/K2/K3/K4/K6: the registration-active universe
    lock is missing, corrupt, mismatched against the universe/raw
    inventory/ledger/discovery-set, duplicated, invalid-binding, of an
    unknown protocol version, or future-dated relative to the run."""


class AtlasLockDeltaError(AtlasPanelError):
    """A V5 failure via K5: the mandatory ``lock_protocol_version_delta`` is
    missing, partial, free-text, or its protocol/registration digests are
    not reconcilable to the registration's amendment log (a gap in the
    amendment chain, or reconciliation against a rejected/invalid-binding
    digest)."""


class AtlasUniverseContractError(AtlasPanelError):
    """A V6 failure: U1-U7 candidate-universe conservation, RP1-RP7
    normalization replay disagreement, prohibited universe content, a
    strata/lineage/support-class recomputation disagreement, or a
    contradictory recomputed-derivation crosswalk cell."""


class AtlasIdentityMapBindingError(AtlasPanelError):
    """A V7 failure via IM1-IM6: the active identity-map lock is absent,
    corrupt, stale-versioned, or fails to bind the map manifest, response
    bundle, acquisition tool, raw inventory, disease pack, or the universe
    lock's own ``identity_map_binding``.

    Deliberately distinct from :class:`AtlasIdentityMapError` (which
    ``raptor.atlas.identity_map`` raises for its own artifact-level faults):
    the selector catches that error and re-raises it as this class, tagged
    with the offending IM check id, so a mapper fault always stays
    attributable to a protocol rule and is NEVER downgraded to an unresolved
    identity, an out-of-scope row, an eligibility failure, or a partial
    result. A mapper fault stops the run with no run record.
    """


# ---------------------------------------------------------------------------
# Atlas Phase-2 contrast-panel selector: frozen result types
# ---------------------------------------------------------------------------
#
# Every mapping/sequence loaded from disk that ends up on one of these
# dataclasses is deep-frozen (``MappingProxyType``/``tuple``), mirroring the
# same deep-freeze principle already used by ``pack.py``/``citation.py``.


@dataclass(frozen=True, eq=True)
class AnchorSpec:
    """The caller-supplied anchor used by E3 (anchor residue/identity
    collision). Never a literal baked into core; always injected by the
    caller (CLI or test) via :class:`SelectionInputs`."""

    spdi_canonical: str
    residue_index: int


@dataclass(frozen=True, eq=True)
class SelectionInputs:
    """The complete, explicit input surface to :func:`select_panel`. No
    field has a default sourced from an environment variable, a wall clock
    read (other than the caller-supplied ``run_started_at``), or a global --
    every path is explicit and caller-supplied."""

    repo_root: Path
    protocol_path: Path
    registration_path: Path
    pack_path: Path
    universe_path: Path
    raw_inventory_path: Path
    anchor: AnchorSpec
    run_started_at: datetime
    executor_identity: str
    identity_map_path: Path
    identity_map_response_root: Path
    node_budget_override: Optional[int] = None


@dataclass(frozen=True, eq=True)
class LockProtocolVersionDelta:
    """The mandatory K5 protocol-version delta, always fully populated even
    when ``differs`` is ``False`` (never pruned/omitted on a match)."""

    lock_protocol_version: str
    lock_protocol_doc_hash: str
    lock_registration_content_hash: str
    current_protocol_version: str
    current_protocol_doc_hash: str
    current_registration_content_hash: str
    differs: bool
    reconciled_via_amendment_log_versions: tuple[str, ...]


@dataclass(frozen=True, eq=True)
class PreconditionReport:
    """The complete V1-V7 precondition attestation. Constructed only when
    every check has passed; there is no partial/default-filled construction
    path."""

    verified_protocol_doc_hash: str
    verified_registration_content_hash: str
    verified_live_pack_content_hash: str
    active_universe_lock: Mapping[str, Any]
    verified_lock_content_hash: str
    verified_universe_content_hash: str
    verified_raw_inventory_hash: str
    verified_raw_inventory_record_count: int
    verified_normalization_ledger_hash: str
    verified_normalization_ledger_row_count: int
    verified_discovery_set_hash: str
    verified_discovery_set_count: int
    lock_protocol_version_delta: LockProtocolVersionDelta
    identity_map: "IdentityMapAttestation"
    checks_passed: tuple[str, ...]


@dataclass(frozen=True, eq=True)
class NormalizationReplay:
    """The U7/RP1-RP7 normalization replay result, recomputed end-to-end
    from the raw inventory through the verified identity-map mapper."""

    replayed_row_count: int
    outcome_counts: Mapping[str, int]
    unresolved_confirmed_count: int
    checks_passed: tuple[str, ...]


@dataclass(frozen=True, eq=True)
class LineageIndex:
    """The recomputed source-lineage grouping over the candidate universe.
    Unknown lineage is always pooled into the single
    ``"LG:UNKNOWN-POOL"`` group -- never split, never relaxed."""

    group_of_observation: Mapping[str, str]
    group_confidence: Mapping[str, str]
    unknown_observation_count: int
    unknown_record_count: int


@dataclass(frozen=True, eq=True)
class RecordDisposition:
    """One row of the mandatory, one-row-per-universe-record disposition
    table (protocol Section 18)."""

    record_id: str
    universe_key: str
    identity_state: str
    all_matched_strata: tuple[str, ...]
    primary_stratum: Optional[str]
    spec_stratum: str
    spec_stratum_derivation: str
    support_class: str
    source_group_keys: tuple[str, ...]
    draw_key: Optional[str]
    disposition: str
    rule_id: str
    allocation_slot: Optional[str]
    label_function_discordant: bool
    stale_label_discordant: bool


@dataclass(frozen=True, eq=True)
class AttemptOutcome:
    """One relaxation-level/panel-size attempt in the exhaustive search."""

    level: str
    n: int
    status: str
    nodes_expanded: int
    solution: Optional[tuple[str, ...]]


@dataclass(frozen=True, eq=True)
class SelectionRun:
    """The complete, pure result of :func:`select_panel`. Nothing is
    written to disk or mutated by producing this object."""

    terminal_outcome: str
    preconditions: PreconditionReport
    replay: NormalizationReplay
    n_target: int
    n_selected: Optional[int]
    selected_record_ids: tuple[str, ...]
    attempts: tuple[AttemptOutcome, ...]
    applied_relaxation_steps: tuple[str, ...]
    independence_status: str
    dispositions: tuple[RecordDisposition, ...]
    flags: Mapping[str, Any]


@dataclass(frozen=True, eq=True)
class IdentityMapAttestation:
    """The V7/IM1-IM6 identity-map attestation. ``mapper`` is the ONLY
    channel by which a verified :class:`RawIdentityMapper` reaches the
    RP1-RP7 replay -- there is no injectable mapper argument anywhere in
    :class:`SelectionInputs`, and ``mapper`` is never itself compared,
    hashed, or rendered (it is dropped before anything is written to a
    run record)."""

    lock_path: Path
    lock_version: str
    map_version: str
    lock_content_hash: str
    map_content_hash: str
    map_record_count: int
    response_bundle_hash: str
    response_file_count: int
    response_byte_count: int
    acquisition_tool_sha256: str
    reference_assembly: str
    reference_transcript: str
    reference_protein: str
    reference_page_count: int
    checks_passed: tuple[str, ...]
    mapper: RawIdentityMapper
