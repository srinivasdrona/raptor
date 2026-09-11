"""Fail-closed registration/verification for external MAVE sources.

A `SourceRegisterEntry` is a PINNED claim about one external scoreset (e.g.
MaveDB `urn:mavedb:00001201-a-1`): its gene, transcript, license, sha256 and
variant count. `verify_registered_source` re-checks an observed fetch against
that pin and fails loud (never silently accepts drift) on any mismatch, and
refuses to treat a `confirm_pending` entry (e.g. an IGVF/CAGI7 accession we
do not yet hold access to) as verified.
"""
from __future__ import annotations

from dataclasses import dataclass

_VALID_VERIFICATIONS = frozenset({"verified", "confirm_pending"})


class SourceVerificationError(ValueError):
    """Raised when an observed fetch does not match its pinned register entry."""


class ConfirmationPendingError(RuntimeError):
    """Raised when a source is registered but not yet confirmed/accessible.

    E.g. 2026 IGVF VAMP-seq/SGE accessions and CAGI7 challenge data that are
    registered (so the source register documents their existence and pins)
    but for which RAPTOR does not hold verified access -- never claimed as
    fetched/verified, never silently treated as available.
    """


@dataclass(frozen=True)
class SourceRegisterEntry:
    """One pinned external MAVE source-register row (config-driven, never
    invented at call sites -- see `configs/external/mave_sources.yaml`)."""

    urn: str
    gene: str
    transcript: str
    license: str
    sha256: str
    variant_count: int
    verification: str = "verified"

    def __post_init__(self) -> None:
        if self.verification not in _VALID_VERIFICATIONS:
            raise SourceVerificationError(
                f"unknown verification state {self.verification!r} for {self.urn!r} "
                f"(expected one of {sorted(_VALID_VERIFICATIONS)!r})"
            )


def verify_registered_source(
    entry: SourceRegisterEntry,
    *,
    observed_transcript: str,
    observed_license: str,
    observed_sha256: str,
    observed_variant_count: int,
) -> None:
    """Fail-closed verification: raises on ANY drift between the pinned
    register entry and what was actually observed/fetched. Returns `None`
    (no value) on success -- callers only care whether this raised."""
    if entry.verification == "confirm_pending":
        raise ConfirmationPendingError(
            f"{entry.urn} is confirm_pending -- RAPTOR does not hold verified access; "
            "refusing to treat it as a validated source"
        )

    if not entry.sha256 or len(entry.sha256) != 64:
        raise SourceVerificationError(
            f"{entry.urn} has no pinned (or non-hex) sha256 -- refusing to verify an "
            "unpinned/unpinned-length sha value"
        )

    if entry.transcript != observed_transcript:
        raise SourceVerificationError(
            f"{entry.urn} transcript mismatch: pinned {entry.transcript!r} != "
            f"observed {observed_transcript!r}"
        )

    if entry.license != observed_license:
        raise SourceVerificationError(
            f"{entry.urn} license mismatch: pinned {entry.license!r} != "
            f"observed {observed_license!r}"
        )

    if entry.sha256.lower() != observed_sha256.lower():
        raise SourceVerificationError(
            f"{entry.urn} sha256 hash mismatch: pinned {entry.sha256!r} != "
            f"observed {observed_sha256!r}"
        )

    if entry.variant_count != observed_variant_count:
        raise SourceVerificationError(
            f"{entry.urn} variant_count mismatch: pinned {entry.variant_count!r} != "
            f"observed {observed_variant_count!r}"
        )
