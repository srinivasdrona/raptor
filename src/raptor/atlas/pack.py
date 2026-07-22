"""Disease pack manifest loading, structural validation, and canonical hashing.

The canonical hash algorithm (``atlas.pack_content_hash.v1``) is exact:
parse YAML with ``yaml.safe_load``, validate the resulting mapping first,
strip only the top-level ``pack_content_hash`` key, then serialize the
remaining mapping as canonical JSON (``sort_keys=True``,
``separators=(",", ":")``, ``ensure_ascii=False``, sequence order
preserved) and take the lowercase SHA-256 hex digest. Every other
present field -- including explicit ``null`` values -- participates in
the hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from raptor.atlas.model import (
    AtlasPackError,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
    DiseasePack,
    SourceRegisterEntry,
)

REQUIRED_PACK_FIELDS = (
    "schema",
    "pack_id",
    "pack_version",
    "allowed_genes",
    "assembly_pins",
    "transcript_pins",
    "reconciliation_policy",
    "ontology_extensions",
    "source_register_pins",
    "prohibitions",
    "pilot_eval_metadata",
)

_ONTOLOGY_EXTENSION_KEYS = ("claim_kinds", "node_layers", "mechanism_classes")

PACKS_ROOT = Path("configs/atlas/packs")


def validate_disease_pack(manifest: Mapping[str, Any]) -> None:
    """Structurally validate a disease pack manifest mapping.

    Deliberately does NOT check ``pack_content_hash`` -- hash verification
    is the sole responsibility of :func:`load_disease_pack`. Raises
    :class:`AtlasPackError` fail-closed on any structural violation.
    """

    for field_name in REQUIRED_PACK_FIELDS:
        if field_name not in manifest:
            raise AtlasPackError(f"disease pack manifest is missing required field {field_name!r}")

    pack_id = manifest["pack_id"]
    ontology_extensions = manifest["ontology_extensions"]
    if not isinstance(ontology_extensions, dict):
        raise AtlasPackError("disease pack manifest field 'ontology_extensions' must be a mapping")

    for key in _ONTOLOGY_EXTENSION_KEYS:
        entries = ontology_extensions.get(key) or []
        for entry in entries:
            entry_id = entry.get("id") if isinstance(entry, dict) else None
            if not entry_id or not str(entry_id).startswith(f"{pack_id}:"):
                raise AtlasPackError(
                    f"ontology_extensions.{key} entry {entry!r} must have an id namespaced "
                    f"as '{pack_id}:<name>'"
                )
            if not entry.get("parent"):
                raise AtlasPackError(
                    f"ontology_extensions.{key} entry {entry_id!r} must declare a parent"
                )

    source_register_pins = manifest["source_register_pins"]
    if not isinstance(source_register_pins, list):
        raise AtlasPackError("disease pack manifest field 'source_register_pins' must be a list")

    for pin in source_register_pins:
        if pin.get("role") == "direct_evidence_leaf" and pin.get("source_type") not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasPackError(
                f"source_register_pins entry {pin.get('entry_id')!r} cannot ground a direct "
                f"evidence leaf with source_type {pin.get('source_type')!r}"
            )


def pack_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the canonical ``atlas.pack_content_hash.v1`` digest of
    ``manifest``, excluding only the top-level ``pack_content_hash`` key."""

    payload = {key: value for key, value in manifest.items() if key != "pack_content_hash"}
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def _build_source_register_entry(pin: Mapping[str, Any]) -> SourceRegisterEntry:
    return SourceRegisterEntry(
        entry_id=pin["entry_id"],
        source_type=pin["source_type"],
        role=pin["role"],
        urn_or_ids=pin.get("urn_or_ids", {}),
        verification=pin["verification"],
        transcript=pin.get("transcript"),
        license=pin.get("license"),
        sha256=pin.get("sha256"),
        variant_count=pin.get("variant_count"),
    )


def _resolve_pack_path(path_or_pack_id: str) -> Path:
    candidate = Path(path_or_pack_id)
    if candidate.exists():
        return candidate
    return PACKS_ROOT / str(path_or_pack_id) / "pack.yaml"


def load_disease_pack(path_or_pack_id: str) -> DiseasePack:
    """Load, validate, and hash-check a disease pack manifest from a
    literal path or a bare pack id resolved under ``configs/atlas/packs``.

    Fails closed with :class:`AtlasPackError` on any structural violation
    or content-hash mismatch.
    """

    pack_path = _resolve_pack_path(path_or_pack_id)
    if not pack_path.exists():
        raise AtlasPackError(f"disease pack manifest not found at {pack_path}")

    with pack_path.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)

    if not isinstance(manifest, dict):
        raise AtlasPackError(f"disease pack manifest at {pack_path} did not parse to a mapping")

    validate_disease_pack(manifest)

    stored_hash = manifest.get("pack_content_hash")
    computed_hash = pack_content_hash(manifest)
    if stored_hash != computed_hash:
        raise AtlasPackError(
            f"disease pack manifest at {pack_path} has pack_content_hash {stored_hash!r} "
            f"but recomputes to {computed_hash!r}"
        )

    return DiseasePack(
        schema=manifest["schema"],
        pack_id=manifest["pack_id"],
        pack_version=manifest["pack_version"],
        pack_content_hash=stored_hash,
        allowed_genes=tuple(manifest["allowed_genes"]),
        assembly_pins=tuple(manifest["assembly_pins"]),
        transcript_pins=tuple(manifest["transcript_pins"]),
        reconciliation_policy=manifest["reconciliation_policy"],
        ontology_extensions=manifest["ontology_extensions"],
        source_register_pins=tuple(
            _build_source_register_entry(pin) for pin in manifest["source_register_pins"]
        ),
        prohibitions=manifest["prohibitions"],
        pilot_eval_metadata=manifest["pilot_eval_metadata"],
    )
