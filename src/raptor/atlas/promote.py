"""Discovery candidate import validation and promotion (8 ordered gates).

``validate_candidate_import`` enforces, in strict order, the eight
promotion gates defined by the spec. Each gate short-circuits on failure
-- no later gate's collaborators are invoked once an earlier gate raises.
``promote_candidate`` re-validates and then builds a frozen tuple of
:class:`~raptor.atlas.model.ObservedClaim` without ever mutating the
input candidate.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from raptor.atlas.guards import scan_for_classification_leakage
from raptor.atlas.identity import validate_canonical_spdi_shape
from raptor.atlas.model import (
    AtlasCandidateImport,
    AtlasCatalogError,
    AtlasIdentityError,
    AtlasProvenanceError,
    AtlasSchemaError,
    CatalogSource,
    CitationIdentifier,
    CitationResolver,
    ContentVerification,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
    EntryRef,
    ObservedClaim,
    PromotionContext,
    ResolvedCitation,
    Span,
    VerifiedSpan,
)

#: Raw, scheme-less bib field -> ("prefix used to construct the canonical
#: identifier string", "the already-prefixed/URL forms rejected structurally
#: BEFORE the resolver is ever invoked").
_BIB_SCHEME_PREFIXES = (
    ("pmid", "PMID"),
    ("pmcid", "PMCID"),
    ("doi", "DOI"),
    ("accession", "ACCESSION"),
)

_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)

# The FULL raw-payload grammar per scheme (bib_mapping.bib_field_grammar).
# These constants intentionally MIRROR (never import) the equivalent
# grammar in citation.py -- promote.py depends only on model.py and the
# injected resolver (import_independence) -- so that a grammatically
# invalid candidate bib value fails Gate 3's OWN structural pre-check
# (AtlasSchemaError, zero resolver calls) rather than being passed through
# to the resolver as a "resolution failure" (AtlasProvenanceError).
_PMID_RAW_VALUE_RE = re.compile(r"^[1-9][0-9]*$")
_PMCID_RAW_VALUE_RE = re.compile(r"^PMC[0-9]+$")
_DOI_RAW_VALUE_RE = re.compile(r"^10\.[0-9]{4,9}/[^\s%]+$")
_ACCESSION_NAMESPACE_RAW_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
_ACCESSION_OPAQUE_RAW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_DOI_TRAILING_PUNCTUATION = (".", ",", ";", ":", ")", "\u2014")


def _bib_declares_any_identifier(bib: Any) -> bool:
    if not isinstance(bib, dict):
        return False
    return any(isinstance(bib.get(scheme_key), str) and bib.get(scheme_key) for scheme_key, _ in _BIB_SCHEME_PREFIXES)


def _validate_bib_raw_payload(entry_id: Any, scheme_key: str, prefix: str, raw_value: Any) -> None:
    """Gate 3's OWN structural pre-check -- the FULL raw, scheme-less bib
    grammar (``bib_mapping.bib_field_grammar``). ``proposed_sources[].bib``
    values are RAW and SCHEME-LESS ONLY. Reject -- with
    :class:`AtlasSchemaError`, BEFORE constructing the prefixed identifier
    string or touching the resolver -- any value that is already
    scheme-prefixed, a URL, whitespace-bearing, percent-encoded, or (per
    scheme) grammatically malformed. This is intentionally FULL grammar
    validation (not just prefix/URL/whitespace rejection): a value like a
    leading-zero PMID or a malformed DOI/accession fails HERE with zero
    resolver calls, not as a deferred resolver-side provenance failure.
    Never strips/rewrites the raw value first."""

    if not isinstance(raw_value, str) or not raw_value:
        raise AtlasSchemaError(
            f"proposed source {entry_id!r} bib.{scheme_key} must be a nonblank raw string"
        )
    if any(ch.isspace() for ch in raw_value):
        raise AtlasSchemaError(
            f"proposed source {entry_id!r} bib.{scheme_key} value {raw_value!r} must not "
            "contain whitespace (raw, scheme-less payload only)"
        )
    if raw_value.lower().startswith(prefix.lower() + ":"):
        raise AtlasSchemaError(
            f"proposed source {entry_id!r} bib.{scheme_key} value {raw_value!r} is already "
            "scheme-prefixed; bib values must be raw and scheme-less"
        )

    if scheme_key == "pmid":
        if not _PMID_RAW_VALUE_RE.match(raw_value):
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.pmid value {raw_value!r} must be positive "
                "decimal digits with no leading zero"
            )
        return

    if scheme_key == "pmcid":
        if not _PMCID_RAW_VALUE_RE.match(raw_value):
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.pmcid value {raw_value!r} must be exactly "
                "'PMC' followed by digits, with no wrapper"
            )
        return

    if scheme_key == "doi":
        for url_prefix in _DOI_URL_PREFIXES:
            if raw_value.lower().startswith(url_prefix):
                raise AtlasSchemaError(
                    f"proposed source {entry_id!r} bib.doi value {raw_value!r} must not be "
                    "a URL form; bib values must be raw and scheme-less"
                )
        if "%" in raw_value:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.doi value {raw_value!r} must not contain "
                "percent-encoding"
            )
        if raw_value[-1] in _DOI_TRAILING_PUNCTUATION:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.doi value {raw_value!r} must not end in "
                "trailing sentence punctuation"
            )
        if not _DOI_RAW_VALUE_RE.match(raw_value.lower()):
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.doi value {raw_value!r} must be a bare "
                "'10.<4-9 digits>/...' payload"
            )
        return

    if scheme_key == "accession":
        if ":" not in raw_value:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.accession value {raw_value!r} must be "
                "'<namespace>:<opaque>' (unqualified accessions are rejected)"
            )
        namespace, _sep, opaque = raw_value.partition(":")
        if not namespace or not _ACCESSION_NAMESPACE_RAW_RE.match(namespace.lower()):
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.accession value {raw_value!r} has an "
                "invalid namespace"
            )
        if not opaque or not _ACCESSION_OPAQUE_RAW_RE.match(opaque):
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} bib.accession value {raw_value!r} has an "
                "invalid opaque identifier"
            )
        return


def _canonical_bib_identifier(scheme_key: str, prefix: str, raw_value: str) -> str:
    """Compute the EXACT canonical identifier string that
    ``normalize_identifier`` would produce for this already
    grammar-validated (:func:`_validate_bib_raw_payload`) raw bib value --
    WITHOUT importing/calling ``normalize_identifier`` itself
    (import_independence: promote.py depends only on model.py and the
    injected resolver). PMID/PMCID payloads have no case ambiguity once
    grammar-valid; DOI lowercases the WHOLE payload; ACCESSION lowercases
    ONLY the namespace, preserving the opaque part's case -- exactly
    mirroring citation.py's ``_normalize_doi_payload``/``normalize_identifier``
    per-scheme canonicalization. Used both as the string passed to
    ``CitationResolver.resolve()`` and for an EXACT (not case-insensitive)
    identity comparison against the resolver's return value in
    :func:`_validate_resolved_citation_shape`."""

    if scheme_key == "doi":
        return f"{prefix}:{raw_value.lower()}"
    if scheme_key == "accession":
        namespace, _sep, opaque = raw_value.partition(":")
        return f"{prefix}:{namespace.lower()}:{opaque}"
    return f"{prefix}:{raw_value}"


def _is_conforming_citation_resolver(candidate: Any) -> bool:
    """isinstance(candidate, CitationResolver) alone is NOT sufficient: a
    ``runtime_checkable`` Protocol's ``isinstance`` check only confirms
    that attributes NAMED ``resolve``/``verify_span`` are PRESENT -- it
    does not confirm they are callable. A spoofed object with
    ``resolve = "not callable"`` passes ``isinstance`` but must still be
    rejected here, before any call is attempted."""

    return (
        isinstance(candidate, CitationResolver)
        and callable(getattr(candidate, "resolve", None))
        and callable(getattr(candidate, "verify_span", None))
    )


def _validate_resolved_citation_shape(
    entry_id: Any, canonical_string: str, resolved: Any
) -> ResolvedCitation:
    """Defense-in-depth against a malicious/buggy resolver: validate the
    EXACT result type/shape of ``resolve()``'s return value (never trust a
    duck-typed or partially-shaped object) and assert that the resolution
    actually corresponds to the identifier that was requested. A resolver
    that returns the wrong type, an internally inconsistent
    ``ResolvedCitation`` (e.g. a ``source``/``identifier``/``content`` of
    the wrong type), or a citation for a DIFFERENT identifier than the one
    requested is a resolution failure (:class:`AtlasProvenanceError`), not
    a raw ``TypeError``/``AttributeError`` escaping to the caller.

    ``canonical_string`` is ALREADY canonicalized exactly as
    ``normalize_identifier`` would (see ``_canonical_bib_identifier``), so
    the comparison against ``resolved.identifier.canonical`` is an EXACT
    (not case-insensitive) string comparison -- a resolver that echoes
    back a differently-cased identifier is itself non-conforming and must
    fail, not be silently tolerated by a fuzzy comparison.

    Beyond the standalone ``identifier.canonical`` echo, this also
    validates that the resolved SOURCE itself internally corroborates the
    requested identifier: ``resolved.source.identifiers`` must be a tuple
    of properly-typed :class:`CitationIdentifier` values (never trust an
    untyped/garbage entry merely because the outer ``CatalogSource``
    dataclass instance passed ``isinstance``), and -- whenever that tuple
    is non-empty -- the exact requested ``canonical_string`` must be one
    of the source's own declared identifiers. This defeats a spoofing
    resolver that returns ``identifier.canonical`` matching what was
    requested while attaching it to a ``source`` that itself advertises a
    DIFFERENT identifier (e.g. requested ``PMID:12345`` bound to a source
    whose own ``identifiers`` only contains ``PMID:99999``). A source that
    declares an EMPTY identifiers tuple is tolerated (this defense
    degrades to the standalone ``identifier.canonical`` check alone in
    that case): a real catalog load never produces an empty identifiers
    tuple for a grounding-eligible ``direct_evidence_leaf`` source
    (enforced at ``load_catalog`` time), so this only relaxes for a
    minimal resolver double that does not populate that field, not for a
    real catalog-backed resolver."""

    if not isinstance(resolved, ResolvedCitation):
        raise AtlasProvenanceError(
            f"citation resolver returned {type(resolved)!r} for proposed source "
            f"{entry_id!r} identifier {canonical_string!r}; expected ResolvedCitation"
        )
    if (
        not isinstance(resolved.identifier, CitationIdentifier)
        or not isinstance(resolved.source, CatalogSource)
        or not isinstance(resolved.content, ContentVerification)
        or resolved.content_verified is not True
    ):
        raise AtlasProvenanceError(
            f"citation resolver returned a malformed ResolvedCitation for proposed source "
            f"{entry_id!r} identifier {canonical_string!r}"
        )
    if (
        not isinstance(resolved.identifier.canonical, str)
        or resolved.identifier.canonical != canonical_string
    ):
        raise AtlasProvenanceError(
            f"citation resolver returned a citation for identifier "
            f"{resolved.identifier.canonical!r} but {canonical_string!r} was requested "
            f"for proposed source {entry_id!r} (resolver identity mismatch)"
        )
    if not isinstance(resolved.source.source_id, str) or not resolved.source.source_id:
        raise AtlasProvenanceError(
            f"citation resolver returned a ResolvedCitation with an invalid source_id for "
            f"proposed source {entry_id!r} identifier {canonical_string!r}"
        )

    source_identifiers = resolved.source.identifiers
    if not isinstance(source_identifiers, tuple):
        raise AtlasProvenanceError(
            f"citation resolver returned a source with a non-tuple identifiers field for "
            f"proposed source {entry_id!r} identifier {canonical_string!r}"
        )
    source_canonicals = []
    for source_identifier in source_identifiers:
        if (
            not isinstance(source_identifier, CitationIdentifier)
            or not isinstance(source_identifier.canonical, str)
            or not source_identifier.canonical
        ):
            raise AtlasProvenanceError(
                f"citation resolver returned a source with a malformed identifier entry "
                f"{source_identifier!r} for proposed source {entry_id!r} identifier "
                f"{canonical_string!r}"
            )
        source_canonicals.append(source_identifier.canonical)
    if source_canonicals and canonical_string not in source_canonicals:
        raise AtlasProvenanceError(
            f"citation resolver resolved identifier {canonical_string!r} for proposed "
            f"source {entry_id!r} to a source that does not itself declare that "
            f"identifier among its own identifiers {tuple(source_canonicals)!r}"
        )
    return resolved


def _validate_verified_span_shape(
    entry_id: Any, resolved: ResolvedCitation, span: Span, verified: Any
) -> VerifiedSpan:
    """Defense-in-depth against a malicious/buggy resolver: validate the
    EXACT result type of ``verify_span()`` and assert it is bound to the
    EXACT resolved source and the EXACT span that was requested -- a
    resolver that verifies a DIFFERENT source/locator/quote than the one
    Gate 4 asked about must not be trusted."""

    if not isinstance(verified, VerifiedSpan):
        raise AtlasProvenanceError(
            f"citation resolver verify_span returned {type(verified)!r} for proposed claim "
            f"referencing {entry_id!r}; expected VerifiedSpan"
        )
    if (
        verified.source_id != resolved.source.source_id
        or verified.locator != span.locator
        or verified.exact_quote != span.exact_quote
    ):
        raise AtlasProvenanceError(
            f"citation resolver verify_span result is not bound to the exact resolved "
            f"source/span requested for proposed claim referencing {entry_id!r}"
        )
    return verified


def _is_valid_named_signoff(signoff: Any) -> bool:
    """A valid Gate 8 signoff is either a nonblank named string (the
    Phase-1 synthetic signoff shape used by every frozen fixture) or an
    explicitly structured mapping carrying a nonblank ``reviewer_id`` or
    ``name`` AND an ``accepted`` flag that is exactly ``True``. Booleans
    and any other generic truthy object (e.g. ``1``, arbitrary objects,
    or a bare ``True`` returned by an adversarial ``lambda``) are
    rejected -- a NAMED signoff is required, not mere truthiness."""

    if isinstance(signoff, bool):
        return False
    if isinstance(signoff, str):
        return bool(signoff.strip())
    if isinstance(signoff, dict):
        reviewer = signoff.get("reviewer_id") or signoff.get("name")
        return (
            isinstance(reviewer, str)
            and bool(reviewer.strip())
            and signoff.get("accepted") is True
        )
    return False


def _gate1_canonical_spdi_readmission(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    variant = candidate.candidate_variant
    provenance = candidate.retrieval_provenance
    pack = context.disease_pack

    declared_binding = provenance.get("pack_binding") or {}
    actual_binding = {
        "pack_id": pack.pack_id,
        "pack_version": pack.pack_version,
        "pack_content_hash": pack.pack_content_hash,
    }
    if declared_binding != actual_binding:
        raise AtlasSchemaError(
            "candidate retrieval_provenance.pack_binding does not match the "
            "promotion context's bound disease pack"
        )

    spdi_proposed = variant.get("spdi_proposed")
    if not spdi_proposed:
        raise AtlasIdentityError("candidate_variant.spdi_proposed is required for readmission")
    # Reuse the SOLE shared canonical SPDI shape validator (also used by
    # admit_identity) -- readmission is never a bare presence check or an
    # alias-equality shortcut.
    validate_canonical_spdi_shape(spdi_proposed)

    gene_proposed = variant.get("gene_proposed")
    if gene_proposed not in pack.allowed_genes:
        raise AtlasIdentityError(
            f"candidate_variant.gene_proposed {gene_proposed!r} is not in the bound "
            "disease pack's allowed_genes"
        )


def _gate2_source_type_role_validation(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    sources_by_id: dict = {}
    for source in candidate.proposed_sources:
        entry_id = source.get("entry_id")
        if entry_id in sources_by_id:
            raise AtlasSchemaError(
                f"candidate.proposed_sources contains a duplicate entry_id {entry_id!r}"
            )
        sources_by_id[entry_id] = source
        if source.get("role") == "direct_evidence_leaf" and source.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} cannot ground a direct "
                f"evidence leaf with source_type {source.get('source_type')!r}"
            )

    # Every proposed claim is unconditionally promoted to verification="verified"
    # by promote_candidate, so the source it will be grounded against must
    # resolve exactly (not by bare alias/id equality against an unrelated
    # register) to a direct_evidence_leaf-role, PRIMARY-LIT/DATASET-typed
    # source carrying a resolvable bibliographic proposal. A provenance_only,
    # context, or crosswalk source can never ground a verified claim.
    for claim in candidate.proposed_claims:
        source_ref = claim.get("source_ref_proposed")
        linked_source = sources_by_id.get(source_ref)
        if linked_source is None:
            raise AtlasSchemaError(
                f"proposed claim references source_ref_proposed {source_ref!r} which is "
                "missing from candidate.proposed_sources"
            )
        if linked_source.get("role") != "direct_evidence_leaf":
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} has role "
                f"{linked_source.get('role')!r}; only a direct_evidence_leaf source can "
                "ground a claim that will become verified"
            )
        if linked_source.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} has source_type "
                f"{linked_source.get('source_type')!r}, which is not one of "
                f"{DIRECT_EVIDENCE_LEAF_SOURCE_TYPES}"
            )
        if _bib_declares_any_identifier(linked_source.get("bib")) is False:
            raise AtlasSchemaError(
                f"proposed claim's linked source {source_ref!r} lacks a resolvable "
                "bibliographic proposal (pmid/pmcid/doi/accession)"
            )


def _gate3_citation_resolution(
    candidate: AtlasCandidateImport, context: PromotionContext
) -> Dict[str, ResolvedCitation]:
    """Reject a non-conforming resolver, then resolve every raw bib alias of
    every ``direct_evidence_leaf`` proposed source, requiring all aliases of
    a given source to agree, and return a LOCAL ``resolved_by_source`` map
    (threaded explicitly to Gate 4 -- no globals, no cross-candidate state)."""

    if not _is_conforming_citation_resolver(context.citation_resolver):
        raise AtlasSchemaError(
            "PromotionContext.citation_resolver must implement the CitationResolver "
            "protocol with CALLABLE resolve + verify_span; a bare boolean/callable (or an "
            "object exposing non-callable resolve/verify_span attributes) is not a "
            "citation resolver"
        )

    resolved_by_source: Dict[str, ResolvedCitation] = {}

    for source in candidate.proposed_sources:
        if not isinstance(source, dict):
            raise AtlasSchemaError(f"candidate.proposed_sources entry {source!r} must be a mapping")
        if source.get("role") != "direct_evidence_leaf":
            # provenance_only/context/crosswalk sources never ground; they are
            # not resolved here (Gate 2 already enforces their structural role/type).
            continue

        entry_id = source.get("entry_id")
        bib = source.get("bib")
        if not isinstance(bib, dict) or not bib:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} has role='direct_evidence_leaf' but its "
                "bib mapping is missing or empty"
            )

        resolved_aliases = []
        for scheme_key, prefix in _BIB_SCHEME_PREFIXES:
            if scheme_key not in bib:
                continue
            raw_value = bib[scheme_key]
            _validate_bib_raw_payload(entry_id, scheme_key, prefix, raw_value)

            # Construct the canonical identifier string by mirroring
            # citation.py's per-scheme canonicalization LOCALLY
            # (_canonical_bib_identifier); promote.py never imports/calls
            # normalize_identifier itself (import-independence: promote.py
            # depends only on model.py and the injected resolver). The
            # resolver is still independently responsible for validating
            # this string via its own CitationResolver.resolve()
            # implementation -- this local canonicalization only ensures
            # Gate 3's own identity checks compare like-for-like forms.
            canonical_string = _canonical_bib_identifier(scheme_key, prefix, raw_value)

            try:
                resolved = context.citation_resolver.resolve(canonical_string)
            except AtlasCatalogError as exc:
                raise AtlasProvenanceError(
                    f"citation resolver failed to resolve proposed source {entry_id!r} "
                    f"identifier {canonical_string!r}"
                ) from exc

            resolved = _validate_resolved_citation_shape(entry_id, canonical_string, resolved)

            resolved_aliases.append((canonical_string, resolved))

        if not resolved_aliases:
            raise AtlasSchemaError(
                f"proposed source {entry_id!r} has role='direct_evidence_leaf' but its bib "
                "declares zero supported identifiers (pmid/pmcid/doi/accession)"
            )

        first_identifier, first_resolved = resolved_aliases[0]
        for identifier, resolved in resolved_aliases[1:]:
            if (
                resolved.source.source_id != first_resolved.source.source_id
                or resolved.source.source_type != first_resolved.source.source_type
            ):
                raise AtlasProvenanceError(
                    f"proposed source {entry_id!r} bib aliases disagree on resolved source: "
                    f"{first_identifier!r} -> {first_resolved.source.source_id!r} "
                    f"but {identifier!r} -> {resolved.source.source_id!r}"
                )

        if (
            first_resolved.source.source_type != source.get("source_type")
            or first_resolved.source.role != "direct_evidence_leaf"
        ):
            raise AtlasProvenanceError(
                f"proposed source {entry_id!r} resolved catalog source_type/role "
                f"({first_resolved.source.source_type!r}/{first_resolved.source.role!r}) "
                f"does not match the candidate-declared source_type "
                f"{source.get('source_type')!r}"
            )

        resolved_by_source[entry_id] = first_resolved

    return resolved_by_source


def _gate4_exact_span_resolution(
    candidate: AtlasCandidateImport,
    context: PromotionContext,
    resolved_by_source: Dict[str, ResolvedCitation],
) -> None:
    for claim in candidate.proposed_claims:
        source_ref = claim.get("source_ref_proposed")
        span_proposed = claim.get("span_proposed")
        if (
            not isinstance(span_proposed, dict)
            or not span_proposed.get("locator")
            or not span_proposed.get("exact_quote")
        ):
            raise AtlasSchemaError(
                f"proposed claim referencing {source_ref!r} lacks a complete span_proposed "
                "(both a nonblank locator AND a nonblank exact_quote are required)"
            )

        resolved = resolved_by_source.get(source_ref)
        if resolved is None:
            raise AtlasProvenanceError(
                f"proposed claim references source_ref_proposed {source_ref!r} which was "
                "not resolved by Gate 3 (defense-in-depth; Gate 2 guarantees a resolved leaf)"
            )

        span = Span(
            locator=span_proposed.get("locator"),
            exact_quote=span_proposed.get("exact_quote"),
            page_or_figure=span_proposed.get("page_or_figure"),
        )
        try:
            verified = context.citation_resolver.verify_span(resolved, span)
        except AtlasCatalogError as exc:
            raise AtlasProvenanceError(
                f"exact span verification failed for proposed claim referencing "
                f"{source_ref!r}"
            ) from exc

        _validate_verified_span_shape(source_ref, resolved, span, verified)


def _gate5_context_ontology_pack_validation(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for claim in candidate.proposed_claims:
        claim_kind = claim.get("claim_kind_proposed")
        context_name = claim.get("context_proposed")
        if not context.context_validator(claim_kind, context_name):
            raise AtlasSchemaError(
                f"context validator rejected proposed claim kind {claim_kind!r} "
                f"in context {context_name!r}"
            )


def _gate6_duplicate_conflict_rules(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    duplicate_index = context.duplicate_index or {}
    for value in duplicate_index.values():
        if "conflict" in str(value):
            raise AtlasProvenanceError(
                "duplicate/conflict register indicates an unresolved conflict for this candidate"
            )


def _gate7_no_classification_leakage(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    scan_for_classification_leakage(candidate.proposed_claims, _path="proposed_claims")
    scan_for_classification_leakage(candidate.proposed_sources, _path="proposed_sources")
    scan_for_classification_leakage(candidate.candidate_variant, _path="candidate_variant")
    scan_for_classification_leakage(candidate.retrieval_provenance, _path="retrieval_provenance")


def _gate8_named_human_oracle_span_review(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    for claim in candidate.proposed_claims:
        signoff = context.human_oracle_reviewer(claim.get("source_ref_proposed"))
        if not _is_valid_named_signoff(signoff):
            raise AtlasProvenanceError(
                f"human oracle reviewer did not provide a valid NAMED signoff for "
                f"proposed claim referencing {claim.get('source_ref_proposed')!r}"
            )


def validate_candidate_import(candidate: AtlasCandidateImport, context: PromotionContext) -> None:
    """Run all eight promotion gates, in exact order, short-circuiting on
    the first failure. Gate 3's resolved-source map is a LOCAL variable
    threaded explicitly to Gate 4 -- no module global, no hidden cache, no
    cross-candidate leakage."""

    _gate1_canonical_spdi_readmission(candidate, context)
    _gate2_source_type_role_validation(candidate, context)
    resolved_by_source = _gate3_citation_resolution(candidate, context)
    _gate4_exact_span_resolution(candidate, context, resolved_by_source)
    _gate5_context_ontology_pack_validation(candidate, context)
    _gate6_duplicate_conflict_rules(candidate, context)
    _gate7_no_classification_leakage(candidate, context)
    _gate8_named_human_oracle_span_review(candidate, context)


def promote_candidate(candidate: AtlasCandidateImport, context: PromotionContext) -> tuple:
    """Validate ``candidate`` against ``context`` and, only if every gate
    passes, return a frozen tuple of newly-admitted :class:`ObservedClaim`
    objects. Never mutates ``candidate``."""

    validate_candidate_import(candidate, context)

    accepted = []
    for index, claim in enumerate(candidate.proposed_claims):
        span_proposed = claim.get("span_proposed") or {}
        span = Span(
            locator=span_proposed.get("locator"),
            exact_quote=span_proposed.get("exact_quote"),
            page_or_figure=span_proposed.get("page_or_figure"),
        )
        source_ref = EntryRef(entry_id=claim.get("source_ref_proposed"), span=span)
        accepted.append(
            ObservedClaim(
                claim_id=f"promoted-{index}",
                claim_text=claim.get("claim_text"),
                claim_kind=claim.get("claim_kind_proposed"),
                source_ref=source_ref,
                verification="verified",
                directionality=claim.get("directionality", "unknown"),
            )
        )

    return tuple(accepted)
