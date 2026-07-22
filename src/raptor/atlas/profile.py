"""Public profile assembly for the Mechanism Atlas.

``build_mechanism_profile`` is the single public builder function. Its
positional/keyword-only signature is exact and fixed by the frozen test
contract -- no extra public keyword arguments are accepted. The builder
performs existence-only resolution of claim source references against the
supplied ``sources`` registry; it deliberately does NOT enforce
leaf-grounding role/type/verification rules (that is the separate,
explicitly-invoked responsibility of :func:`raptor.atlas.registry.validate_claim_grounding`).
"""

from __future__ import annotations

from typing import Any, Sequence

from raptor.atlas import ontology
from raptor.atlas.hashing import evidence_core_hash, profile_envelope_hash
from raptor.atlas.model import (
    AtlasIdentityError,
    AtlasProvenanceError,
    EvidenceAssessment,
    MechanismProfile,
    PackBinding,
    Provenance,
)


def build_mechanism_profile(
    identity: Any,
    claims: Sequence[Any],
    contexts: Sequence[Any],
    edges: Sequence[Any],
    sources: Sequence[Any],
    *,
    pack: Any,
) -> MechanismProfile:
    """Build a frozen :class:`MechanismProfile` bound to ``pack``.

    Parameters are exactly positional (``identity``, ``claims``,
    ``contexts``, ``edges``, ``sources``) plus the keyword-only ``pack``.
    ``sources`` is a sequence of :class:`~raptor.atlas.model.SourceRegisterEntry`
    (the source register), not raw :class:`~raptor.atlas.model.EntryRef`.
    """

    if identity.gene not in pack.allowed_genes:
        raise AtlasIdentityError(
            f"identity gene {identity.gene!r} is not in the bound disease pack's allowed_genes"
        )

    registry = {source.entry_id: source for source in sources}

    claims_tuple = tuple(claims)
    for claim in claims_tuple:
        if claim.source_ref.entry_id not in registry:
            raise AtlasProvenanceError(
                f"claim {claim.claim_id!r} references unresolved source register "
                f"entry {claim.source_ref.entry_id!r}"
            )
        ontology.validate_claim_kind(claim.claim_kind, pack=pack)

    for context in contexts:
        ontology.validate_context_vocabulary("tissue", context.tissue, pack=pack)

    edges_tuple = tuple(edges)
    for edge in edges_tuple:
        ontology.validate_node_layer(edge.from_layer, pack=pack)
        ontology.validate_node_layer(edge.to_layer, pack=pack)
        if edge.context is not None:
            ontology.validate_context_vocabulary("tissue", edge.context.tissue, pack=pack)

    verified_claim_ids = tuple(c.claim_id for c in claims_tuple if c.verification == "verified")
    unverified_claim_ids = tuple(c.claim_id for c in claims_tuple if c.verification != "verified")
    edge_supporting = tuple(cid for edge in edges_tuple for cid in edge.supporting_claims)
    edge_contradicting = tuple(cid for edge in edges_tuple for cid in edge.contradicting_claims)

    evidence = EvidenceAssessment(
        supporting=tuple(dict.fromkeys(verified_claim_ids + edge_supporting)),
        contradicting=tuple(dict.fromkeys(edge_contradicting)),
        missing_evidence=(),
        unknowns=tuple(dict.fromkeys(unverified_claim_ids)),
    )

    source_pins = tuple(dict.fromkeys(claim.source_ref for claim in claims_tuple))

    pack_binding = PackBinding(
        pack_id=pack.pack_id,
        pack_version=pack.pack_version,
        pack_content_hash=pack.pack_content_hash,
    )

    draft_profile = MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=claims_tuple,
        candidate_classes=(),
        edges=edges_tuple,
        evidence=evidence,
        provenance=Provenance(source_pins=source_pins, version_pins=(), content_hashes={}),
        run_metadata=None,
    )

    content_hashes = {
        "evidence_core_hash": evidence_core_hash(draft_profile),
        "profile_envelope_hash": profile_envelope_hash(draft_profile),
    }

    return MechanismProfile(
        identity=identity,
        pack_binding=pack_binding,
        claims=claims_tuple,
        candidate_classes=(),
        edges=edges_tuple,
        evidence=evidence,
        provenance=Provenance(source_pins=source_pins, version_pins=(), content_hashes=content_hashes),
        run_metadata=None,
    )
