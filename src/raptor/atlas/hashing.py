"""Canonical, deterministic hashing for Mechanism Atlas profiles.

``evidence_core_hash`` and ``profile_envelope_hash`` build canonical JSON
payloads from a :class:`~raptor.atlas.model.MechanismProfile` and hash them
with SHA-256. Both hashes bind the top-level ``pack_binding`` (so swapping
the disease pack always changes both hashes) and both exclude
``run_metadata`` entirely (run bookkeeping never participates in content
hashing). Claims are canonically ordered and exact-duplicate claims are
collapsed to a single canonical entry before hashing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _span_payload(span: Any) -> dict | None:
    if span is None:
        return None
    return {
        "locator": span.locator,
        "exact_quote": span.exact_quote,
        "page_or_figure": span.page_or_figure,
    }


def _entry_ref_payload(ref: Any) -> dict:
    return {
        "entry_id": ref.entry_id,
        "span": _span_payload(ref.span),
    }


def _claim_payload(claim: Any) -> dict:
    return {
        "claim_id": claim.claim_id,
        "claim_text": claim.claim_text,
        "claim_kind": claim.claim_kind,
        "source_ref": _entry_ref_payload(claim.source_ref),
        "verification": claim.verification,
        "directionality": claim.directionality,
    }


def _claim_sort_key(item: dict) -> tuple:
    span = item["source_ref"]["span"]
    locator = span["locator"] if span else ""
    return (item["claim_kind"], item["source_ref"]["entry_id"], locator or "", item["claim_text"])


def _canonicalized_deduped_claims(profile: Any) -> list:
    claims_list = [_claim_payload(claim) for claim in profile.claims]
    claims_list.sort(key=_claim_sort_key)

    deduped = []
    seen = set()
    for claim_obj in claims_list:
        serialized = json.dumps(claim_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if serialized not in seen:
            seen.add(serialized)
            deduped.append(claim_obj)
    return deduped


def _candidate_classes_payload(profile: Any) -> list:
    classes_list = [
        {"class_id": cc.class_id, "state": cc.state, "confidence": cc.confidence}
        for cc in profile.candidate_classes
    ]
    classes_list.sort(key=lambda cc: (cc["class_id"], cc["state"]))
    return classes_list


def _edges_payload(profile: Any) -> list:
    edges_list = []
    for edge in profile.edges:
        edges_list.append(
            {
                "from_layer": edge.from_layer,
                "to_layer": edge.to_layer,
                "effect": edge.effect,
                "supporting_claims": list(edge.supporting_claims),
                "contradicting_claims": list(edge.contradicting_claims),
                "context": (
                    {
                        "assay": edge.context.assay,
                        "model_system": edge.context.model_system,
                        "cell_type": edge.context.cell_type,
                        "tissue": edge.context.tissue,
                        "zygosity_context": edge.context.zygosity_context,
                        "assay_limitations": list(edge.context.assay_limitations),
                    }
                    if edge.context
                    else None
                ),
                "edge_state": edge.edge_state,
            }
        )
    edges_list.sort(key=lambda e: (e["from_layer"], e["to_layer"], e["effect"]))
    return edges_list


def _canonicalize_id_tuple(values: Any) -> list:
    """Canonicalize a tuple of plain string identifiers that is
    semantically a SET (order-insensitive, exact-duplicate-collapsing) --
    ``EvidenceAssessment.supporting/contradicting/missing_evidence/unknowns``
    and ``Provenance.version_pins`` -- into a deterministically sorted,
    deduped list so two independently-constructed but semantically
    identical profiles (e.g. with claim ids/version pins listed in a
    different order) hash identically."""
    return sorted(set(values or ()))


def _evidence_payload(profile: Any) -> dict:
    evidence = profile.evidence
    if not evidence:
        return {"supporting": [], "contradicting": [], "missing_evidence": [], "unknowns": []}
    return {
        "supporting": _canonicalize_id_tuple(evidence.supporting),
        "contradicting": _canonicalize_id_tuple(evidence.contradicting),
        "missing_evidence": _canonicalize_id_tuple(evidence.missing_evidence),
        "unknowns": _canonicalize_id_tuple(evidence.unknowns),
    }


def _source_pin_sort_key(payload: dict) -> tuple:
    span = payload["span"]
    return (
        payload["entry_id"],
        (span or {}).get("locator") or "",
        (span or {}).get("exact_quote") or "",
        (span or {}).get("page_or_figure") or "",
    )


def _canonicalized_source_pins(profile: Any) -> list:
    """Canonicalize ``Provenance.source_pins`` -- a semantically unordered,
    exact-duplicate-collapsing collection -- by sorting on the FULL key
    ``(entry_id, span.locator, span.exact_quote, span.page_or_figure)``
    (not ``entry_id`` alone, which would incorrectly conflate distinct
    spans pinned against the same source entry) and deduping exact
    (entry_id, span) duplicates via canonical-JSON-string set membership,
    mirroring the claims canonicalization above."""

    pins = [_entry_ref_payload(pin) for pin in profile.provenance.source_pins]
    pins.sort(key=_source_pin_sort_key)

    deduped = []
    seen = set()
    for pin in pins:
        serialized = json.dumps(pin, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if serialized not in seen:
            seen.add(serialized)
            deduped.append(pin)
    return deduped


def _pack_binding_payload(profile: Any) -> dict:
    return {
        "pack_id": profile.pack_binding.pack_id,
        "pack_version": profile.pack_binding.pack_version,
        "pack_content_hash": profile.pack_binding.pack_content_hash,
    }


def _identity_core_payload(profile: Any) -> dict:
    return {
        "spdi_canonical": profile.identity.spdi_canonical,
        "gene": profile.identity.gene,
    }


def _identity_envelope_payload(profile: Any) -> dict:
    identity = profile.identity
    return {
        "spdi_canonical": identity.spdi_canonical,
        "gene": identity.gene,
        "assembly": identity.assembly,
        "transcript_pin": identity.transcript_pin,
        "hgvs_c": identity.hgvs_c,
        "hgvs_p": identity.hgvs_p,
        "hgvs_g": identity.hgvs_g,
        "identity_state": identity.identity_state,
    }


def _hash_canonical(payload: dict) -> str:
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def evidence_core_hash(profile: Any) -> str:
    """Canonical hash over the minimal evidence core: pack binding, minimal
    identity (spdi/gene only), deduped/ordered claims, candidate classes,
    edges, and evidence. Excludes ``run_metadata`` and full provenance."""

    payload = {
        "pack_binding": _pack_binding_payload(profile),
        "identity": _identity_core_payload(profile),
        "claims": _canonicalized_deduped_claims(profile),
        "candidate_classes": _candidate_classes_payload(profile),
        "edges": _edges_payload(profile),
        "evidence": _evidence_payload(profile),
    }
    return _hash_canonical(payload)


def profile_envelope_hash(profile: Any) -> str:
    """Canonical hash over the full profile envelope: everything in
    ``evidence_core_hash`` plus full identity fields and provenance
    (source pins + version pins). Excludes ``run_metadata`` and
    ``content_hashes`` (which would be self-referential)."""

    payload = {
        "pack_binding": _pack_binding_payload(profile),
        "identity": _identity_envelope_payload(profile),
        "claims": _canonicalized_deduped_claims(profile),
        "candidate_classes": _candidate_classes_payload(profile),
        "edges": _edges_payload(profile),
        "evidence": _evidence_payload(profile),
        "provenance": {
            "source_pins": _canonicalized_source_pins(profile),
            "version_pins": _canonicalize_id_tuple(profile.provenance.version_pins),
        },
    }
    return _hash_canonical(payload)
