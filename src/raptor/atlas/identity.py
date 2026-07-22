"""Variant identity admission and transcript reconciliation.

A canonical, GRCh38-shaped SPDI string is the sole admission and
reconciliation key for variant identity in the Mechanism Atlas. Gene,
assembly, and transcript pins are always resolved against the bound
disease pack -- nothing here fabricates or infers identity from bare
HGVS-c equality or any other heuristic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping as MappingABC
from typing import Any, Callable, Mapping

from raptor.atlas.model import AtlasIdentity, AtlasIdentityError

#: A canonical SPDI accession/version component is shaped like a RefSeq
#: accession -- one to four letters, an underscore, digits, a dot, and a
#: version number (e.g. ``NC_000000.0``). This is a SHAPE check only; it
#: never hardcodes a specific real accession.
_SPDI_ACCESSION_RE = re.compile(r"^[A-Za-z]{1,4}_[0-9]+\.[0-9]+$")
#: A deletion/insertion component is an uppercase nucleotide sequence
#: (empty allowed, per canonical SPDI grammar, for pure insertions/
#: deletions).
_SPDI_BASE_RE = re.compile(r"^[ACGTN]*$")


def validate_canonical_spdi_shape(spdi: Any) -> str:
    """Validate that ``spdi`` is a syntactically well-formed canonical
    (RefSeq-accession-shaped) SPDI string: exactly four colon-separated
    components -- ``<accession>.<version>:<position>:<deletion>:<insertion>``
    -- with a zero-based non-negative integer position and uppercase
    nucleotide (A/C/G/T/N, empty allowed) deletion/insertion sequences.

    This is the SOLE shared shape validator for canonical SPDI admission;
    it is reused by both :func:`admit_identity` and the promotion pipeline's
    canonical-SPDI-readmission gate so neither performs a bare
    presence-only or alias-equality check. Returns ``spdi`` unchanged on
    success; raises :class:`AtlasIdentityError` fail-closed on any
    malformed shape (whitespace, HGVS-style punctuation, wrong colon
    count, negative/non-integer position, or non-nucleotide bases).
    """

    if not isinstance(spdi, str) or not spdi:
        raise AtlasIdentityError("canonical SPDI must be a non-empty string")
    if any(ch.isspace() for ch in spdi):
        raise AtlasIdentityError(f"canonical SPDI {spdi!r} must not contain whitespace")

    parts = spdi.split(":")
    if len(parts) != 4:
        raise AtlasIdentityError(
            f"canonical SPDI {spdi!r} must have exactly 4 colon-separated components "
            f"(accession.version:position:deletion:insertion), got {len(parts)}"
        )

    accession, position, deletion, insertion = parts
    if not _SPDI_ACCESSION_RE.match(accession):
        raise AtlasIdentityError(
            f"canonical SPDI {spdi!r} has a malformed accession.version component {accession!r}"
        )
    if not position.isdigit():
        raise AtlasIdentityError(
            f"canonical SPDI {spdi!r} position component {position!r} must be a "
            "non-negative zero-based integer"
        )
    if not _SPDI_BASE_RE.match(deletion):
        raise AtlasIdentityError(
            f"canonical SPDI {spdi!r} deletion component {deletion!r} must be an "
            "uppercase nucleotide sequence (A/C/G/T/N), empty allowed"
        )
    if not _SPDI_BASE_RE.match(insertion):
        raise AtlasIdentityError(
            f"canonical SPDI {spdi!r} insertion component {insertion!r} must be an "
            "uppercase nucleotide sequence (A/C/G/T/N), empty allowed"
        )
    return spdi


def _pack_transcript_aliases(pack: Any) -> set[str]:
    aliases: set[str] = set()
    for pin in pack.transcript_pins or ():
        if isinstance(pin, MappingABC):
            transcript = pin.get("transcript")
        else:
            transcript = pin
        if transcript:
            aliases.add(transcript)
    return aliases


def admit_identity(record: Mapping[str, Any], *, pack: Any) -> AtlasIdentity:
    """Admit a candidate identity record into an :class:`AtlasIdentity`.

    Admission requires a non-empty canonical SPDI, a gene present in the
    pack's ``allowed_genes``, and an assembly present in the pack's
    ``assembly_pins``. If a ``transcript_pin`` is supplied it must be one
    of the pack's pinned transcript aliases. Any violation raises
    :class:`AtlasIdentityError`.
    """

    spdi_canonical = record.get("spdi_canonical")
    if not spdi_canonical:
        raise AtlasIdentityError("admit_identity requires a non-empty canonical SPDI string")
    validate_canonical_spdi_shape(spdi_canonical)

    gene = record.get("gene")
    if gene not in pack.allowed_genes:
        raise AtlasIdentityError(
            f"gene {gene!r} is not in the bound disease pack's allowed_genes"
        )

    assembly = record.get("assembly")
    if assembly not in pack.assembly_pins:
        raise AtlasIdentityError(
            f"assembly {assembly!r} is not in the bound disease pack's assembly_pins"
        )

    transcript_pin = record.get("transcript_pin")
    if transcript_pin is not None:
        allowed_transcripts = _pack_transcript_aliases(pack)
        if transcript_pin not in allowed_transcripts:
            raise AtlasIdentityError(
                f"transcript_pin {transcript_pin!r} is not pinned by the bound disease pack"
            )

    return AtlasIdentity(
        spdi_canonical=spdi_canonical,
        gene=gene,
        assembly=assembly,
        transcript_pin=transcript_pin,
        hgvs_c=record.get("hgvs_c"),
        hgvs_p=record.get("hgvs_p"),
        hgvs_g=record.get("hgvs_g"),
        identity_state=record.get("identity_state", "resolved"),
    )


def reconcile_transcript(
    identity: AtlasIdentity,
    alias: str,
    *,
    pack: Any,
    resolver: Callable[[str, str], bool],
) -> bool:
    """Reconcile a transcript alias against ``identity`` via an injected
    ``resolver`` callable. The alias must first be one of the pack's pinned
    transcript aliases; the resolver is then the sole source of truth for
    whether the alias resolves to the identity's canonical SPDI. Never
    fabricates a match from bare string equality."""

    allowed_transcripts = _pack_transcript_aliases(pack)
    if alias not in allowed_transcripts:
        raise AtlasIdentityError(
            f"transcript alias {alias!r} is not pinned by the bound disease pack"
        )

    resolved = resolver(identity.spdi_canonical, alias)
    if not resolved:
        raise AtlasIdentityError(
            f"resolver could not reconcile transcript alias {alias!r} against "
            f"{identity.spdi_canonical!r}"
        )
    return True
