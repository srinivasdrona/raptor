"""Registry-aware claim grounding checks and fail-closed source verification.

This module is deliberately independent from :mod:`raptor.atlas.profile`.
``build_mechanism_profile`` only checks that a claim's source reference
*resolves* to a known registry entry; it never enforces leaf-grounding
(role/type/verification) rules. Those stronger checks live here and must be
invoked explicitly wherever a "verified grounding" guarantee is required.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from raptor.atlas.model import (
    AtlasProvenanceError,
    AtlasSourceVerificationError,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_claim_grounding(claim: Any, registry: Mapping[str, Any], *, pack: Any) -> None:
    """Verify that ``claim`` is grounded by a resolvable, direct-evidence-leaf
    source register entry with a non-empty span and verified state.

    Checks are applied in order (entry resolution, span presence, role/type
    pairing, verification state) so that failures are diagnosable and
    fail closed at the first violated invariant.
    """

    entry_id = claim.source_ref.entry_id
    entry = registry.get(entry_id)
    if entry is None:
        raise AtlasProvenanceError(
            f"claim {claim.claim_id!r} references unresolved source register entry {entry_id!r}"
        )

    span = claim.source_ref.span
    if span is None or not span.locator:
        raise AtlasProvenanceError(
            f"claim {claim.claim_id!r} has no non-empty span on its source reference"
        )

    if entry.role != "direct_evidence_leaf" or entry.source_type not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
        raise AtlasProvenanceError(
            f"source register entry {entry_id!r} cannot ground a direct evidence leaf "
            f"(role={entry.role!r}, source_type={entry.source_type!r})"
        )

    if entry.verification != "verified":
        raise AtlasProvenanceError(
            f"source register entry {entry_id!r} is not verified (state={entry.verification!r})"
        )


def verify_source(entry: Any) -> bool:
    """Fail-closed verification of a single :class:`SourceRegisterEntry`.

    Raises :class:`AtlasSourceVerificationError` if the entry is not in a
    ``verified`` state, if a present ``sha256`` is not a well-formed
    64-character lowercase hex digest, or if ``license`` metadata is
    missing. Returns ``True`` when the entry passes all checks.
    """

    if entry.verification != "verified":
        raise AtlasSourceVerificationError(
            f"source register entry {entry.entry_id!r} is not verified (state={entry.verification!r})"
        )

    if entry.sha256 is not None and not _SHA256_RE.match(entry.sha256):
        raise AtlasSourceVerificationError(
            f"source register entry {entry.entry_id!r} has a malformed sha256 pin"
        )

    if entry.license is None:
        raise AtlasSourceVerificationError(
            f"source register entry {entry.entry_id!r} is verified but missing license metadata"
        )

    return True
