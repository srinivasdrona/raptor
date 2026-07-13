"""Exact-match SPDI/hgvsc identity join for MAVE overlap sets.

Two identity operations only, both fail-loud:

* `join_exact_overlap` -- exact `variant_id` (canonical SPDI) matching
  between an expected set (e.g. the label-free heldout manifest / an
  already-verified overlap) and an observed set (parsed `MaveScoreRecord`s
  that already carry a resolved `variant_id`). Any unknown/missing id or a
  reference-allele mismatch raises -- never silently dropped.

* `map_cdna_to_spdi` -- full hgvs_c -> genomic SPDI projection. This
  REQUIRES an injected `projector` (e.g. a UTA-backed HGVS projector); with
  no projector, it raises `ProjectionUnavailableError` rather than guessing
  a genomic position from a bare `c.` string. Deterministic: the output is
  sorted by `variant_id` regardless of input row order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

from .source import MaveScoreRecord


class ProjectionUnavailableError(RuntimeError):
    """Raised when a full cDNA->genomic projection is requested but no
    projector was injected. RAPTOR never guesses a genomic position from a
    bare `c.` HGVS string -- projection is either done by a real projector
    (UTA/hgvs-backed) or refused outright."""


class ReferenceMismatchError(ValueError):
    """Raised when a matched variant's observed reference allele does not
    equal the expected canonical reference allele."""


@dataclass(frozen=True)
class CanonicalVariant:
    """One expected variant identity: a canonical SPDI `variant_id` plus its
    reference allele, sourced from a label-free manifest or an
    already-verified overlap -- never derived by guessing inside this
    module."""

    variant_id: str
    reference: str


class ExactOverlapMismatchError(ValueError):
    """Raised when the observed variant_id set does not exactly equal the
    expected variant_id set. Carries both offending sets so callers can
    report precisely what drifted."""

    def __init__(self, unknown_variant_ids: set[str], missing_variant_ids: set[str]):
        self.unknown_variant_ids = unknown_variant_ids
        self.missing_variant_ids = missing_variant_ids
        super().__init__(
            f"exact overlap mismatch: unknown={sorted(unknown_variant_ids)!r} "
            f"missing={sorted(missing_variant_ids)!r}"
        )


def join_exact_overlap(
    expected: Iterable[CanonicalVariant],
    observed: Iterable[MaveScoreRecord],
) -> list[tuple[CanonicalVariant, MaveScoreRecord]]:
    """Exact `variant_id` join. Fails loud with `ExactOverlapMismatchError`
    if the observed set contains any id not in `expected` (unknown) or is
    missing any id from `expected` (missing) -- a partial/best-effort join
    is never returned silently. Fails loud with `ReferenceMismatchError` if
    a joined pair's reference alleles disagree."""
    expected_by_id = {variant.variant_id: variant for variant in expected}
    observed_by_id = {record.variant_id: record for record in observed}

    unknown = set(observed_by_id) - set(expected_by_id)
    missing = set(expected_by_id) - set(observed_by_id)
    if unknown or missing:
        raise ExactOverlapMismatchError(unknown_variant_ids=unknown, missing_variant_ids=missing)

    joined: list[tuple[CanonicalVariant, MaveScoreRecord]] = []
    for variant_id in sorted(expected_by_id):
        variant = expected_by_id[variant_id]
        record = observed_by_id[variant_id]
        if record.reference is not None and record.reference != variant.reference:
            raise ReferenceMismatchError(
                f"{variant_id}: reference allele mismatch (expected {variant.reference!r}, "
                f"observed {record.reference!r})"
            )
        joined.append((variant, record))
    return joined


@runtime_checkable
class CdnaProjector(Protocol):
    """Port: anything that can project a transcript-relative HGVS `c.`
    change to a genomic SPDI string. Real impl deferred (UTA-backed, PRD-08
    scope); tests/scripts inject a fake/real projector explicitly."""

    def project(self, transcript: str, hgvs_c: str) -> str: ...


def map_cdna_to_spdi(
    rows: Iterable[MaveScoreRecord],
    *,
    transcript: str,
    projector: CdnaProjector | None = None,
) -> list[MaveScoreRecord]:
    """Project every row's `hgvs_c` to a genomic SPDI `variant_id` via
    `projector.project(transcript, hgvs_c)`. Raises
    `ProjectionUnavailableError` if no projector is supplied -- this module
    never fabricates a genomic position from a bare cDNA change. Output is
    sorted by the resulting `variant_id` so the result is independent of
    input row order (determinism, R-A11-style)."""
    if projector is None:
        raise ProjectionUnavailableError(
            f"full cDNA->SPDI projection for transcript {transcript!r} requires an "
            "injected projector (e.g. UTA-backed); none was supplied"
        )

    projected: list[MaveScoreRecord] = []
    for row in rows:
        if row.hgvs_c is None:
            raise ProjectionUnavailableError(
                f"row has no hgvs_c to project (variant_id={row.variant_id!r})"
            )
        variant_id = projector.project(transcript, row.hgvs_c)
        projected.append(
            MaveScoreRecord(
                variant_id=variant_id,
                hgvs_c=row.hgvs_c,
                score=row.score,
                reference=row.reference,
            )
        )
    return sorted(projected, key=lambda record: record.variant_id)


__all__ = [
    "CanonicalVariant",
    "CdnaProjector",
    "ExactOverlapMismatchError",
    "ProjectionUnavailableError",
    "ReferenceMismatchError",
    "join_exact_overlap",
    "map_cdna_to_spdi",
]
