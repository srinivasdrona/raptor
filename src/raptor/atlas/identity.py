"""Variant identity admission and transcript reconciliation.

A canonical, GRCh38-shaped SPDI string is the sole admission and
reconciliation key for variant identity in the Mechanism Atlas. Gene,
assembly, and transcript pins are always resolved against the bound
disease pack -- nothing here fabricates or infers identity from bare
HGVS-c equality or any other heuristic.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from raptor.atlas.model import AtlasIdentity, AtlasIdentityError


def _pack_transcript_aliases(pack: Any) -> set[str]:
    aliases: set[str] = set()
    for pin in pack.transcript_pins or ():
        if isinstance(pin, dict):
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
