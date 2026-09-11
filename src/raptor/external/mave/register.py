"""Fail-closed registration/verification for external MAVE sources.

A `SourceRegisterEntry` is a PINNED claim about one external scoreset (e.g.
MaveDB `urn:mavedb:00001201-a-1`): its gene, transcript, license, sha256 and
variant count. `verify_registered_source` re-checks an observed fetch against
that pin and fails loud (never silently accepts drift) on any mismatch. It
refuses to treat either an unconfirmed entry or a released source whose
metadata is verified but whose content/licence review is incomplete as a
content-verified source.
"""
from __future__ import annotations

from dataclasses import dataclass

_VALID_VERIFICATIONS = frozenset(
    {"verified", "confirm_pending", "released_metadata_verified"}
)


class SourceVerificationError(ValueError):
    """Raised when an observed fetch does not match its pinned register entry."""


class ConfirmationPendingError(RuntimeError):
    """Raised when a source is not yet eligible for content verification.

    This includes an unconfirmed source and a released/public source whose
    metadata has been verified but whose raw content hash and permitted-use
    review are not yet pinned. Neither state is silently treated as a verified
    score source.
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
    if entry.verification in {"confirm_pending", "released_metadata_verified"}:
        raise ConfirmationPendingError(
            f"{entry.urn} is {entry.verification} -- content and permitted-use "
            "verification are incomplete; refusing to treat it as a verified source"
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
