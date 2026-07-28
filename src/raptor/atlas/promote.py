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
from pathlib import Path
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

# Grounding-predicate constants (grounding_eligibility in the spec). These
# MIRROR (never import) citation.py's own values -- promote.py depends only
# on model.py and the injected resolver (import_independence) -- so Gate 3
# / Gate 4 can independently re-derive the FULL grounding predicate from a
# resolved CatalogSource/ContentVerification/VerifiedSpan rather than
# trusting the resolver's own content_verified=True/success signal.
_GROUNDING_PERMITTED_USE = "grounding_and_quote"
_GROUNDING_VERIFICATION = "verified"
# Exact mirror of citation.py's own ``_SHA256_HEX_RE`` -- a lowercase
# 64-hex digest, never uppercase/short/invalid-char.
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# Exact mirror of citation.py's own ``_TEXT_NORMALIZATION_ID``.
_GROUNDING_TEXT_NORMALIZATION_ID = "atlas.text_norm.v1"
# A path segment consisting solely of one-or-more '.' characters ("." /
# ".." / "..." / ...) is never a real relative file name -- reject any of
# them, not merely the classic ".." traversal segment.
_ALL_DOTS_PATH_SEGMENT_RE = re.compile(r"^\.+$")


def _is_int_not_bool(value: Any) -> bool:
    """``bool`` is an ``int`` subclass in Python -- a byte_length of
    ``True`` must never be silently accepted as ``1``."""

    return isinstance(value, int) and not isinstance(value, bool)


def _is_safe_relative_path(value: Any) -> bool:
    """Structural (no filesystem I/O) plausibility check mirroring
    citation.py's ``_resolve_content_artifact`` path-safety rules:
    promote.py has no ``content_root`` and never touches the filesystem
    itself, but a resolver-declared ``raw_relative_path``/
    ``extracted_relative_path`` must at least be a nonblank,
    non-drive-qualified, non-absolute, traversal-free relative path
    string before its declared content pin is trusted as complete.
    Also rejects ``.``, ``..``, ``...`` (and any other all-dots segment,
    including a bare all-dots ``value`` that normalizes to zero path
    ``parts`` under ``pathlib``) -- none of these are real file names."""

    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/") or value.startswith("\\"):
        return False
    candidate = Path(value)
    if candidate.drive or candidate.is_absolute():
        return False
    parts = candidate.parts
    if not parts:
        # e.g. "." alone normalizes away to zero parts under pathlib and
        # would resolve to content_root itself -- never a real file.
        return False
    if any(_ALL_DOTS_PATH_SEGMENT_RE.match(part) for part in parts):
        return False
    return True


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
    requested identifier: ``resolved.source.identifiers`` must be a
    NON-EMPTY tuple of properly-typed :class:`CitationIdentifier` values
    (never trust an untyped/garbage entry merely because the outer
    ``CatalogSource`` dataclass instance passed ``isinstance``), and the
    exact requested ``canonical_string`` must be one of the source's own
    declared identifiers. This defeats a spoofing resolver that returns
    ``identifier.canonical`` matching what was requested while attaching
    it to a ``source`` that itself advertises a DIFFERENT identifier (e.g.
    requested ``PMID:12345`` bound to a source whose own ``identifiers``
    only contains ``PMID:99999``). An EMPTY identifiers tuple is ALWAYS
    rejected -- there is no compatibility exception: a real catalog load
    never produces an empty identifiers tuple for a grounding-eligible
    ``direct_evidence_leaf`` source (enforced at ``load_catalog`` time),
    so a resolver that omits them entirely is treated exactly like one
    that fails to corroborate the requested identifier.

    Finally, independently re-derives the FULL spec ``grounding_predicate``
    from the resolved ``CatalogSource``/``ContentVerification`` -- never
    trusting the resolver's bare ``content_verified=True`` claim alone --
    exactly mirroring (never importing) citation.py's own catalog-schema
    validation (``_validate_artifact_pin``) and
    ``LocalCitationResolver.resolve()``'s predicate:
    ``permitted_use == 'grounding_and_quote'``, ``verification ==
    'verified'``, a complete/valid ``raw_artifact`` pin (nonblank safe
    relative path -- rejecting ``.``/``..``/``...``/any all-dots segment
    and absolute/drive/UNC/backslash traversal, a lowercase 64-hex
    ``sha256``, a non-negative (zero IS valid, per the catalog schema)
    ``int`` ``byte_length`` that is not a ``bool``, and a nonblank
    media_type string), and a ``ContentVerification`` whose own
    ``raw_sha256``/``raw_byte_length`` match the source's DECLARED raw pin
    exactly (both are separately format/type-checked, not merely compared
    for equality), and whose ``extracted_text_sha256``/
    ``extracted_text_byte_length`` match the source's declared extracted
    pin exactly whenever the source declares one (extracted-text pins
    remain OPTIONAL at resolve/grounding time per spec -- a claim SPAN
    additionally REQUIRES a complete one, enforced independently by Gate
    4's own extracted-pin completeness check, not here). Any missing/
    malformed/inconsistent field fails closed with
    :class:`AtlasProvenanceError`, never a raw ``TypeError``/
    ``AttributeError``."""

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
    if not isinstance(source_identifiers, tuple) or not source_identifiers:
        raise AtlasProvenanceError(
            f"citation resolver returned a source with a non-tuple or empty identifiers "
            f"field for proposed source {entry_id!r} identifier {canonical_string!r}; a "
            "resolved source must itself declare at least one typed identifier"
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
    if canonical_string not in source_canonicals:
        raise AtlasProvenanceError(
            f"citation resolver resolved identifier {canonical_string!r} for proposed "
            f"source {entry_id!r} to a source that does not itself declare that "
            f"identifier among its own identifiers {tuple(source_canonicals)!r}"
        )

    # --- Independent grounding-predicate re-derivation ------------------
    # Never trust the resolver's bare content_verified=True claim: re-check
    # every clause of the spec's grounding_predicate directly against the
    # resolved CatalogSource/ContentVerification fields themselves, exactly
    # as LocalCitationResolver.resolve() itself would (mirrored, never
    # imported), so a spoofing/buggy resolver cannot claim success for a
    # source that is not actually grounding-admissible.
    source = resolved.source
    if source.permitted_use != _GROUNDING_PERMITTED_USE:
        raise AtlasProvenanceError(
            f"citation resolver returned a source with permitted_use "
            f"{source.permitted_use!r} for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}; grounding requires {_GROUNDING_PERMITTED_USE!r}"
        )
    if source.verification != _GROUNDING_VERIFICATION:
        raise AtlasProvenanceError(
            f"citation resolver returned a source with verification "
            f"{source.verification!r} for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}; grounding requires {_GROUNDING_VERIFICATION!r}"
        )
    if not _is_safe_relative_path(source.raw_relative_path):
        raise AtlasProvenanceError(
            f"citation resolver returned a source with an invalid or unsafe "
            f"raw_relative_path {source.raw_relative_path!r} for proposed source "
            f"{entry_id!r} identifier {canonical_string!r}"
        )
    if (
        not isinstance(source.raw_declared_sha256, str)
        or not _SHA256_HEX_RE.match(source.raw_declared_sha256)
    ):
        raise AtlasProvenanceError(
            f"citation resolver returned a source with an invalid raw_declared_sha256 "
            f"{source.raw_declared_sha256!r} for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}; expected a lowercase 64-hex sha256 digest"
        )
    if (
        not _is_int_not_bool(source.raw_declared_byte_length)
        or source.raw_declared_byte_length < 0
    ):
        raise AtlasProvenanceError(
            f"citation resolver returned a source with an invalid "
            f"raw_declared_byte_length {source.raw_declared_byte_length!r} for proposed "
            f"source {entry_id!r} identifier {canonical_string!r}; a grounding-eligible "
            "raw artifact must declare a non-negative int byte length (zero is valid)"
        )
    if not isinstance(source.raw_media_type, str) or not source.raw_media_type:
        raise AtlasProvenanceError(
            f"citation resolver returned a source with an invalid raw_media_type "
            f"{source.raw_media_type!r} for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}"
        )

    content = resolved.content
    if (
        not isinstance(content.raw_sha256, str)
        or not _SHA256_HEX_RE.match(content.raw_sha256)
        or content.raw_sha256 != source.raw_declared_sha256
        or not _is_int_not_bool(content.raw_byte_length)
        or content.raw_byte_length != source.raw_declared_byte_length
    ):
        raise AtlasProvenanceError(
            f"citation resolver's ContentVerification does not corroborate the declared "
            f"raw content pin for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}"
        )
    # extracted-text pins remain OPTIONAL at resolve()/grounding time (only
    # required to additionally satisfy a claim SPAN, independently enforced
    # by Gate 4's own extracted-pin completeness check), but whenever the
    # source itself DECLARES an extracted pin, the resolver's own
    # ContentVerification must agree with it exactly -- a resolver may not
    # silently drift the two apart.
    if source.extracted_declared_sha256 is not None and (
        content.extracted_text_sha256 != source.extracted_declared_sha256
    ):
        raise AtlasProvenanceError(
            f"citation resolver's ContentVerification does not corroborate the declared "
            f"extracted_text sha256 pin for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}"
        )
    if source.extracted_declared_byte_length is not None and (
        content.extracted_text_byte_length != source.extracted_declared_byte_length
    ):
        raise AtlasProvenanceError(
            f"citation resolver's ContentVerification does not corroborate the declared "
            f"extracted_text byte_length pin for proposed source {entry_id!r} identifier "
            f"{canonical_string!r}"
        )

    return resolved


def _require_extracted_pin_complete_for_span(
    entry_id: Any, resolved: ResolvedCitation, span: Span
) -> None:
    """Independently re-derive completeness of the resolved source's
    extracted-text pin BEFORE trusting ``verify_span()``'s result --
    extracted-text pins are OPTIONAL at Gate 3/``resolve()`` time (a
    direct_evidence_leaf source may ground claims that carry no textual
    span), but THIS claim's ``text-char`` span requires an exact slice of
    extracted text, so its source must declare a COMPLETE, internally
    consistent extracted-text artifact pin. Mirrors (never imports)
    citation.py's catalog-load-time ``_validate_extracted_text`` (all six
    sub-fields required together) plus its ``verify_span``/
    ``verify_content`` content-drift re-checks. Any missing, malformed, or
    inconsistent field fails closed with :class:`AtlasProvenanceError`
    before the resolver's ``verify_span`` is ever called."""

    source = resolved.source
    if not _is_safe_relative_path(source.extracted_relative_path):
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            "but the resolved source has no complete/safe extracted_relative_path "
            f"({source.extracted_relative_path!r})"
        )
    if (
        not isinstance(source.extracted_declared_sha256, str)
        or not _SHA256_HEX_RE.match(source.extracted_declared_sha256)
    ):
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            "but the resolved source has an invalid extracted_declared_sha256 "
            f"({source.extracted_declared_sha256!r})"
        )
    if (
        not _is_int_not_bool(source.extracted_declared_byte_length)
        or source.extracted_declared_byte_length < 0
    ):
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            "but the resolved source has an invalid extracted_declared_byte_length "
            f"({source.extracted_declared_byte_length!r})"
        )
    quote_length = len(span.exact_quote or "")
    if quote_length > 0 and source.extracted_declared_byte_length == 0:
        # Zero extracted bytes is structurally VALID on its own (matches
        # the catalog loader's non-negative rule), but this claim's
        # nonblank exact_quote/offset span logically cannot be sliced out
        # of a zero-byte extracted-text artifact.
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} pins a zero-byte "
            "extracted-text artifact, which cannot contain the claim's nonblank "
            "exact_quote/offset span"
        )
    if not isinstance(source.extraction_method, str) or not source.extraction_method:
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            f"but the resolved source has an invalid extraction_method "
            f"({source.extraction_method!r})"
        )
    if not isinstance(source.extraction_version, str) or not source.extraction_version:
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            f"but the resolved source has an invalid extraction_version "
            f"({source.extraction_version!r})"
        )
    if source.text_normalization != _GROUNDING_TEXT_NORMALIZATION_ID:
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r} requires a text-char span, "
            f"but the resolved source's text_normalization "
            f"{source.text_normalization!r} is not exactly "
            f"{_GROUNDING_TEXT_NORMALIZATION_ID!r}"
        )

    content = resolved.content
    if (
        not isinstance(content.extracted_text_sha256, str)
        or not _SHA256_HEX_RE.match(content.extracted_text_sha256)
        or content.extracted_text_sha256 != source.extracted_declared_sha256
    ):
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r}: resolved "
            "ContentVerification.extracted_text_sha256 does not corroborate the source's "
            "declared extracted-text pin"
        )
    if (
        not _is_int_not_bool(content.extracted_text_byte_length)
        or content.extracted_text_byte_length != source.extracted_declared_byte_length
    ):
        raise AtlasProvenanceError(
            f"proposed claim referencing source {entry_id!r}: resolved "
            "ContentVerification.extracted_text_byte_length does not corroborate the "
            "source's declared extracted-text pin"
        )


def _validate_verified_span_shape(
    entry_id: Any, resolved: ResolvedCitation, span: Span, verified: Any
) -> VerifiedSpan:
    """Defense-in-depth against a malicious/buggy resolver: validate the
    EXACT result type of ``verify_span()`` and assert it is bound to the
    EXACT resolved source and the EXACT span that was requested -- a
    resolver that verifies a DIFFERENT source/locator/quote than the one
    Gate 4 asked about must not be trusted. Also validates the ONE
    extracted-artifact binding field ``VerifiedSpan`` itself carries
    (``extracted_text_sha256``) against the resolved ``ContentVerification``
    (already independently corroborated against the source's own declared
    extracted pin by ``_require_extracted_pin_complete_for_span``), and the
    internal ``start``/``end``/``exact_quote`` offset consistency -- never
    a raw ``TypeError``/``AttributeError`` on a malformed field."""

    if not isinstance(verified, VerifiedSpan):
        raise AtlasProvenanceError(
            f"citation resolver verify_span returned {type(verified)!r} for proposed claim "
            f"referencing {entry_id!r}; expected VerifiedSpan"
        )
    if (
        not isinstance(verified.source_id, str)
        or verified.source_id != resolved.source.source_id
        or not isinstance(verified.locator, str)
        or verified.locator != span.locator
        or not isinstance(verified.exact_quote, str)
        or verified.exact_quote != span.exact_quote
    ):
        raise AtlasProvenanceError(
            f"citation resolver verify_span result is not bound to the exact resolved "
            f"source/span requested for proposed claim referencing {entry_id!r}"
        )
    if (
        not _is_int_not_bool(verified.start)
        or not _is_int_not_bool(verified.end)
        or verified.start < 0
        or verified.end < verified.start
        or (verified.end - verified.start) != len(verified.exact_quote)
    ):
        raise AtlasProvenanceError(
            f"citation resolver verify_span returned an internally inconsistent "
            f"start/end/exact_quote offset for proposed claim referencing {entry_id!r}"
        )
    if (
        not isinstance(verified.extracted_text_sha256, str)
        or not _SHA256_HEX_RE.match(verified.extracted_text_sha256)
        or verified.extracted_text_sha256 != resolved.content.extracted_text_sha256
    ):
        raise AtlasProvenanceError(
            f"citation resolver verify_span result's extracted_text_sha256 does not "
            f"corroborate the resolved source's own verified content for proposed claim "
            f"referencing {entry_id!r}"
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
    (threaded explicitly to Gate 4 -- no globals, no cross-candidate state).

    "Agree" means FULL frozen ``CatalogSource`` equality (every field --
    ``identifiers``, ``license``, ``permitted_use``, ``verification``, raw/
    extracted content pins, extraction metadata -- not merely matching
    ``source_id``/``source_type``): a resolver that returns a split
    ``identifiers`` tuple (each alias's own subset individually contains
    the alias it was asked to resolve) or that varies any other field
    across aliases of the SAME proposed source is a resolution failure,
    since it means the aliases do not actually corroborate a single,
    internally-consistent catalog source declaration."""

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

        # Full CatalogSource equality (frozen dataclass field-wise ==, not
        # merely source_id/source_type): a resolver that returns a source
        # whose identifiers tuple is split across aliases (each alias's own
        # membership check individually passes, per
        # _validate_resolved_citation_shape) or that differs in ANY other
        # field -- license, permitted_use, verification, content/path/hash
        # pins, extraction metadata -- across aliases of the SAME proposed
        # source is rejected here. Comparing every alias's resolved source
        # to resolved_aliases[0] is order-independent: if all N sources are
        # pairwise equal, the choice of reference element does not change
        # the accept/reject outcome.
        for identifier, resolved in resolved_aliases[1:]:
            if resolved.source != first_resolved.source:
                raise AtlasProvenanceError(
                    f"proposed source {entry_id!r} bib aliases resolve to inconsistent "
                    f"CatalogSource declarations: alias {first_identifier!r} resolved to "
                    f"{first_resolved.source!r} but alias {identifier!r} resolved to "
                    f"{resolved.source!r} (full CatalogSource equality is required across "
                    "all aliases of one proposed source, not merely matching "
                    "source_id/source_type)"
                )

        # Equivalent restatement of the same invariant: once every alias's
        # resolved source is confirmed identical, there is exactly ONE
        # common identifiers tuple, and it must itself declare every
        # canonical alias that was actually requested for this proposed
        # source (each alias resolved exactly once, above).
        common_source_canonicals = {
            source_identifier.canonical for source_identifier in first_resolved.source.identifiers
        }
        for identifier, _resolved in resolved_aliases:
            if identifier not in common_source_canonicals:
                raise AtlasProvenanceError(
                    f"proposed source {entry_id!r} common resolved CatalogSource identifiers "
                    f"{tuple(sorted(common_source_canonicals))!r} do not include requested "
                    f"alias {identifier!r}"
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
        # This claim's text-char span requires a COMPLETE, internally
        # consistent extracted-text pin on the resolved source -- checked
        # independently BEFORE ever calling the resolver's verify_span, so
        # an incomplete/malformed pin fails closed without depending on
        # the resolver's own (possibly buggy/malicious) behavior.
        _require_extracted_pin_complete_for_span(source_ref, resolved, span)
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
