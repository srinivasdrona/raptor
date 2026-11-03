"""RAPTOR v2 TSC2 functional-identity promotion -- pure SPDI/hgvs_g helper.

``spdi_to_hgvs_g`` deterministically derives the genomic HGVS string for an
already-verified GRCh38 SPDI coordinate (spec
``row_contract_amendment.spdi_to_hgvs_g``): a one-base substitution uses
``g.<pos><ref>><alt>``; a multi-base EQUAL-LENGTH replacement uses
``g.<start>_<end>delins<inserted>``. This is a pure, offline function --
it never calls a network service -- and is the single source of truth
this package's join logic (``ingest.promote_functional_identities``) uses
to derive ``hgvs_g`` from a mapping/crosswalk row's already-verified
``genomic_spdi``; the row is then independently re-verified by
``raptor.external.tsc2_functional.model.NormalizedFunctionalRow``.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import re

#: The fixed genomic accession pin for this entire slice (spec
#: ``inputs.identity_pins.genomic_accession``) -- never configurable per
#: call.
GENOMIC_ACCESSION = "NC_000016.10"

#: A canonical SPDI string: ``<accession>:<position0>:<deleted>:<inserted>``.
#: ``deleted``/``inserted`` must be non-empty ACGT strings (spec
#: ``row_contract_amendment.verified_spdi.invariants``); equal-length
#: checking is performed separately below since a regex alone cannot
#: express a cross-group length equality.
_SPDI_RE = re.compile(r"^(?P<accession>[A-Za-z0-9_.]+):(?P<position>-?\d+):(?P<deleted>[ACGT]+):(?P<inserted>[ACGT]+)$")


class PromotionModelError(ValueError):
    """Raised when an ``spdi`` string is not a canonical
    ``<accession>:<position>:<deleted>:<inserted>`` string, does not carry
    the pinned ``NC_000016.10`` accession, has a negative position, has
    non-ACGT or empty deleted/inserted sequences, or has unequal deleted/
    inserted lengths (only an exact SNV or an equal-length multi-base
    delins is ever derivable into a genomic HGVS string by this slice)."""


def spdi_to_hgvs_g(spdi: str) -> str:
    """Deterministically derive a genomic HGVS string from an already-
    verified ``NC_000016.10`` SPDI coordinate.

    A one-base substitution (``len(deleted) == len(inserted) == 1``)
    yields ``NC_000016.10:g.<pos1><ref>><alt>`` where ``pos1 = position0 +
    1``. A multi-base EQUAL-LENGTH replacement yields
    ``NC_000016.10:g.<start1>_<end1>delins<inserted>`` where ``start1 =
    position0 + 1`` and ``end1 = start1 + len(deleted) - 1``.

    Raises ``PromotionModelError`` for any SPDI string that is not a
    canonical ``<accession>:<position>:<deleted>:<inserted>`` string with
    non-empty ACGT deleted/inserted sequences, does not carry the pinned
    ``NC_000016.10`` accession, has a negative position, or has unequal
    deleted/inserted lengths (an indel/MNV shape is never accepted here)."""
    if not isinstance(spdi, str) or not spdi:
        raise PromotionModelError(f"spdi must be a non-empty string, got {spdi!r}")
    match = _SPDI_RE.match(spdi)
    if match is None:
        raise PromotionModelError(
            f"spdi {spdi!r} is not a canonical <accession>:<position>:<deleted>:<inserted> string "
            "with non-empty ACGT deleted/inserted sequences"
        )
    accession = match["accession"]
    if accession != GENOMIC_ACCESSION:
        raise PromotionModelError(f"spdi {spdi!r} accession must be {GENOMIC_ACCESSION!r}, got {accession!r}")
    position0 = int(match["position"])
    if position0 < 0:
        raise PromotionModelError(f"spdi {spdi!r} position must be non-negative, got {position0!r}")
    deleted = match["deleted"]
    inserted = match["inserted"]
    if len(deleted) != len(inserted):
        raise PromotionModelError(
            f"spdi {spdi!r} deleted/inserted lengths must be equal (only an exact SNV or an "
            f"equal-length delins is derivable), got deleted={deleted!r} inserted={inserted!r}"
        )
    start1 = position0 + 1
    if len(deleted) == 1:
        return f"{accession}:g.{start1}{deleted}>{inserted}"
    end1 = start1 + len(deleted) - 1
    return f"{accession}:g.{start1}_{end1}delins{inserted}"


__all__ = [
    "GENOMIC_ACCESSION",
    "PromotionModelError",
    "spdi_to_hgvs_g",
]
