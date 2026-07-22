"""Condition-agnostic ontology seed vocabulary and pack-extension validation.

The core seed vocabulary below is the entire fixed vocabulary available to
every disease pack. Packs may only *extend* it with additional,
namespaced (``<pack_id>:name``) claim kinds, node layers, and mechanism
classes -- there are no hardcoded pathway-specific branches in this module.
"""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from typing import Any, Optional

from raptor.atlas.model import AtlasSchemaError

CORE_CLAIM_KINDS = (
    "rna",
    "splicing",
    "abundance",
    "stability",
    "complex",
    "localization",
    "pathway",
    "phenotype",
    "other",
)

CORE_NODE_LAYERS = (
    "dna",
    "rna",
    "protein_abundance",
    "protein_stability",
    "complex",
    "localization",
    "pathway_state",
    "phenotype",
)

CORE_MECHANISM_CLASSES = (
    "rna_splicing_defect",
    "reduced_abundance_instability",
    "misfolding_residual_function",
    "complex_formation_defect",
    "mislocalization",
    "catalytic_site_impairment",
    "dominant_negative",
    "hypomorphic_partial_loss",
)


def _pack_extension_ids(pack: Optional[Any], key: str) -> set[str]:
    if pack is None:
        return set()
    extensions_root = getattr(pack, "ontology_extensions", None)
    if not isinstance(extensions_root, MappingABC):
        return set()
    entries = extensions_root.get(key) or []
    ids: set[str] = set()
    for entry in entries:
        entry_id = entry.get("id") if isinstance(entry, MappingABC) else getattr(entry, "id", None)
        if entry_id:
            ids.add(entry_id)
    return ids


def validate_claim_kind(claim_kind: str, *, pack: Optional[Any] = None) -> None:
    """Validate ``claim_kind`` against the core seed vocabulary or a
    namespaced extension declared by ``pack``."""

    if claim_kind in CORE_CLAIM_KINDS:
        return
    if claim_kind in _pack_extension_ids(pack, "claim_kinds"):
        return
    raise AtlasSchemaError(
        f"claim_kind {claim_kind!r} is not a core seed kind or a declared pack extension"
    )


def validate_node_layer(node_layer: str, *, pack: Optional[Any] = None) -> None:
    """Validate ``node_layer`` against the core seed vocabulary or a
    namespaced extension declared by ``pack``."""

    if node_layer in CORE_NODE_LAYERS:
        return
    if node_layer in _pack_extension_ids(pack, "node_layers"):
        return
    raise AtlasSchemaError(
        f"node_layer {node_layer!r} is not a core seed layer or a declared pack extension"
    )


def validate_mechanism_class(class_id: str, *, pack: Optional[Any] = None) -> None:
    """Validate ``class_id`` against the core seed vocabulary or a
    namespaced extension declared by ``pack``."""

    if class_id in CORE_MECHANISM_CLASSES:
        return
    if class_id in _pack_extension_ids(pack, "mechanism_classes"):
        return
    raise AtlasSchemaError(
        f"mechanism class {class_id!r} is not a core seed class or a declared pack extension"
    )


def validate_context_vocabulary(vocab_key: str, value: Optional[str], *, pack: Optional[Any] = None) -> None:
    """Validate a context value (e.g. ``tissue``) against a pack-declared
    context vocabulary, if the pack declares one for ``vocab_key``. Values
    with no pack-declared vocabulary are accepted without restriction."""

    if value is None or pack is None:
        return
    extensions_root = getattr(pack, "ontology_extensions", None)
    if not isinstance(extensions_root, MappingABC):
        return
    vocab = extensions_root.get("context_vocabularies") or {}
    allowed = vocab.get(vocab_key)
    if allowed and value not in allowed:
        raise AtlasSchemaError(
            f"context value {value!r} for {vocab_key!r} is not declared by the "
            "pack's context vocabulary"
        )
