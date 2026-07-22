"""Disease pack manifest loading, structural validation, and canonical hashing.

The canonical hash algorithm (``atlas.pack_content_hash.v1``) is exact:
parse YAML with ``yaml.safe_load``, validate the resulting mapping first,
strip only the top-level ``pack_content_hash`` key, then serialize the
remaining mapping as canonical JSON (``sort_keys=True``,
``separators=(",", ":")``, ``ensure_ascii=False``, sequence order
preserved) and take the lowercase SHA-256 hex digest. Every other
present field -- including explicit ``null`` values -- participates in
the hash.

Once a manifest's stored hash has been verified against its actual
content, every nested mutable structure (mappings and sequences) is
deep-frozen (``types.MappingProxyType`` / ``tuple``, recursively, never
retaining a reference to the original mutable object) before building the
:class:`~raptor.atlas.model.DiseasePack`, so no caller -- including one
holding the original raw YAML dict -- can mutate a loaded pack after its
hash has been checked.
"""

from __future__ import annotations

import hashlib
import json
import re
import types
from pathlib import Path
from typing import Any, Mapping

import yaml

from raptor.atlas.model import (
    AtlasPackError,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
    DiseasePack,
    SOURCE_REGISTER_ENTRY_ROLES,
    SOURCE_REGISTER_ENTRY_SOURCE_TYPES,
    SOURCE_REGISTER_ENTRY_VERIFICATION_STATES,
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

_ONTOLOGY_EXTENSION_LIST_KEYS = ("claim_kinds", "node_layers", "mechanism_classes")
_ONTOLOGY_EXTENSION_KEYS = _ONTOLOGY_EXTENSION_LIST_KEYS + ("context_vocabularies",)

_PACK_SCHEMA_ID = "atlas.disease_pack.v1"
#: Bare pack id / pack version must be nonblank, path-safe tokens -- no
#: path separators, traversal, drive letters, or whitespace.
_SAFE_PACK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_PACK_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_SOURCE_PIN_FIELDS = ("entry_id", "source_type", "role", "urn_or_ids", "verification")

#: Repo root anchored two levels above ``src/raptor/atlas`` (this file's
#: directory) -- never dependent on the process's current working
#: directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS_ROOT = _REPO_ROOT / "configs" / "atlas" / "packs"


def _is_nonblank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_pack(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasPackError(message)


def validate_disease_pack(manifest: Mapping[str, Any]) -> None:
    """Structurally validate a disease pack manifest mapping.

    Deliberately does NOT check ``pack_content_hash`` -- hash verification
    is the sole responsibility of :func:`load_disease_pack`. Raises
    :class:`AtlasPackError` fail-closed on any structural violation,
    including malformed schema/id/version, wrong field container types,
    missing ontology extension keys, non-unique ids, malformed source pin
    fields, and mis-paired source role/type.
    """

    _require_pack(isinstance(manifest, dict), "disease pack manifest must be a mapping")

    for field_name in REQUIRED_PACK_FIELDS:
        if field_name not in manifest:
            raise AtlasPackError(f"disease pack manifest is missing required field {field_name!r}")

    _require_pack(
        manifest["schema"] == _PACK_SCHEMA_ID,
        f"disease pack manifest 'schema' must be exactly {_PACK_SCHEMA_ID!r}, "
        f"got {manifest['schema']!r}",
    )

    pack_id = manifest["pack_id"]
    _require_pack(
        _is_nonblank_str(pack_id) and bool(_SAFE_PACK_ID_RE.match(pack_id)),
        f"disease pack manifest 'pack_id' must be a nonblank path-safe token, got {pack_id!r}",
    )

    pack_version = manifest["pack_version"]
    _require_pack(
        _is_nonblank_str(pack_version) and bool(_SAFE_PACK_VERSION_RE.match(pack_version)),
        f"disease pack manifest 'pack_version' must be a nonblank version-safe token, "
        f"got {pack_version!r}",
    )

    allowed_genes = manifest["allowed_genes"]
    _require_pack(
        isinstance(allowed_genes, list) and allowed_genes and all(_is_nonblank_str(g) for g in allowed_genes),
        "disease pack manifest field 'allowed_genes' must be a non-empty list of nonblank strings",
    )
    _require_pack(
        len(set(allowed_genes)) == len(allowed_genes),
        "disease pack manifest field 'allowed_genes' must contain unique entries",
    )

    assembly_pins = manifest["assembly_pins"]
    _require_pack(
        isinstance(assembly_pins, list) and assembly_pins and all(_is_nonblank_str(a) for a in assembly_pins),
        "disease pack manifest field 'assembly_pins' must be a non-empty list of nonblank strings",
    )
    _require_pack(
        len(set(assembly_pins)) == len(assembly_pins),
        "disease pack manifest field 'assembly_pins' must contain unique entries",
    )

    transcript_pins = manifest["transcript_pins"]
    _require_pack(isinstance(transcript_pins, list), "disease pack manifest field 'transcript_pins' must be a list")
    for pin in transcript_pins:
        if isinstance(pin, dict):
            _require_pack(
                _is_nonblank_str(pin.get("transcript")),
                f"transcript_pins entry {pin!r} must have a nonblank 'transcript' key",
            )
        else:
            _require_pack(
                _is_nonblank_str(pin),
                f"transcript_pins entry {pin!r} must be a nonblank string or a mapping with a "
                "'transcript' key",
            )

    _require_pack(
        isinstance(manifest["reconciliation_policy"], dict),
        "disease pack manifest field 'reconciliation_policy' must be a mapping",
    )
    _require_pack(
        isinstance(manifest["prohibitions"], dict),
        "disease pack manifest field 'prohibitions' must be a mapping",
    )
    _require_pack(
        isinstance(manifest["pilot_eval_metadata"], dict),
        "disease pack manifest field 'pilot_eval_metadata' must be a mapping",
    )

    ontology_extensions = manifest["ontology_extensions"]
    _require_pack(
        isinstance(ontology_extensions, dict),
        "disease pack manifest field 'ontology_extensions' must be a mapping",
    )
    for required_key in _ONTOLOGY_EXTENSION_KEYS:
        _require_pack(
            required_key in ontology_extensions,
            f"disease pack manifest field 'ontology_extensions' is missing required key {required_key!r}",
        )

    context_vocabularies = ontology_extensions.get("context_vocabularies")
    _require_pack(
        isinstance(context_vocabularies, dict),
        "disease pack manifest field 'ontology_extensions.context_vocabularies' must be a mapping",
    )
    for vocab_name, vocab_values in context_vocabularies.items():
        _require_pack(
            isinstance(vocab_values, list) and all(_is_nonblank_str(v) for v in vocab_values),
            f"ontology_extensions.context_vocabularies[{vocab_name!r}] must be a list of "
            "nonblank strings",
        )

    all_extension_ids: set[str] = set()
    for key in _ONTOLOGY_EXTENSION_LIST_KEYS:
        entries = ontology_extensions.get(key)
        _require_pack(
            isinstance(entries, list),
            f"disease pack manifest field 'ontology_extensions.{key}' must be a list",
        )
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
            _require_pack(
                entry_id not in all_extension_ids,
                f"ontology_extensions.{key} entry id {entry_id!r} is not unique across "
                "claim_kinds/node_layers/mechanism_classes",
            )
            all_extension_ids.add(entry_id)

    source_register_pins = manifest["source_register_pins"]
    if not isinstance(source_register_pins, list):
        raise AtlasPackError("disease pack manifest field 'source_register_pins' must be a list")

    seen_entry_ids: set[str] = set()
    for pin in source_register_pins:
        _require_pack(isinstance(pin, dict), f"source_register_pins entry {pin!r} must be a mapping")
        for required_field in _REQUIRED_SOURCE_PIN_FIELDS:
            _require_pack(
                required_field in pin,
                f"source_register_pins entry {pin!r} is missing required field {required_field!r}",
            )

        entry_id = pin["entry_id"]
        _require_pack(
            _is_nonblank_str(entry_id),
            f"source_register_pins entry_id {entry_id!r} must be a nonblank string",
        )
        _require_pack(
            entry_id not in seen_entry_ids,
            f"source_register_pins entry_id {entry_id!r} is not unique",
        )
        seen_entry_ids.add(entry_id)

        source_type = pin["source_type"]
        _require_pack(
            source_type in SOURCE_REGISTER_ENTRY_SOURCE_TYPES,
            f"source_register_pins entry {entry_id!r} has invalid source_type {source_type!r}",
        )

        role = pin["role"]
        _require_pack(
            role in SOURCE_REGISTER_ENTRY_ROLES,
            f"source_register_pins entry {entry_id!r} has invalid role {role!r}",
        )

        urn_or_ids = pin["urn_or_ids"]
        _require_pack(
            isinstance(urn_or_ids, dict) and bool(urn_or_ids),
            f"source_register_pins entry {entry_id!r} field 'urn_or_ids' must be a non-empty mapping",
        )

        verification = pin["verification"]
        _require_pack(
            verification in SOURCE_REGISTER_ENTRY_VERIFICATION_STATES,
            f"source_register_pins entry {entry_id!r} has invalid verification {verification!r}",
        )

        sha256 = pin.get("sha256")
        if sha256 is not None:
            _require_pack(
                isinstance(sha256, str) and bool(_SHA256_HEX_RE.match(sha256)),
                f"source_register_pins entry {entry_id!r} field 'sha256' must be a lowercase "
                f"64-character hex digest, got {sha256!r}",
            )

        variant_count = pin.get("variant_count")
        if variant_count is not None:
            _require_pack(
                _is_int_not_bool(variant_count),
                f"source_register_pins entry {entry_id!r} field 'variant_count' must be an "
                f"int (not bool), got {variant_count!r}",
            )

        if role == "direct_evidence_leaf" and source_type not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasPackError(
                f"source_register_pins entry {entry_id!r} cannot ground a direct "
                f"evidence leaf with source_type {source_type!r}"
            )


def pack_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the canonical ``atlas.pack_content_hash.v1`` digest of
    ``manifest``, excluding only the top-level ``pack_content_hash`` key."""

    payload = {key: value for key, value in manifest.items() if key != "pack_content_hash"}
    canonical_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze ``value`` into an immutable structure: every
    ``dict`` becomes a ``types.MappingProxyType`` wrapping a rebuilt dict
    of already-frozen children, and every ``list``/``tuple`` becomes a
    ``tuple`` of already-frozen elements. Scalars pass through unchanged.
    Never retains a reference to any original mutable container, so
    mutating the raw YAML-parsed object after loading cannot affect the
    frozen result."""

    if isinstance(value, dict):
        return types.MappingProxyType({key: _deep_freeze(v) for key, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


def _build_source_register_entry(pin: Mapping[str, Any]) -> SourceRegisterEntry:
    return SourceRegisterEntry(
        entry_id=pin["entry_id"],
        source_type=pin["source_type"],
        role=pin["role"],
        urn_or_ids=_deep_freeze(pin.get("urn_or_ids", {})),
        verification=pin["verification"],
        transcript=pin.get("transcript"),
        license=pin.get("license"),
        sha256=pin.get("sha256"),
        variant_count=pin.get("variant_count"),
    )


def _resolve_pack_path(path_or_pack_id: str) -> Path:
    """Resolve ``path_or_pack_id`` to a concrete pack manifest path.

    A value that syntactically LOOKS like an explicit path (contains a
    path separator, is ``.``/``..``, or ends in ``.yaml``/``.yml``) is
    used as a literal, caller-supplied path (fail-closed at the
    ``load_disease_pack`` file-existence check if it turns out not to be
    a real manifest file). Anything else is treated as a BARE pack id and
    resolved ONLY under the repo-root-anchored :data:`PACKS_ROOT` -- it
    must be a single path-safe token with no path separators, drive
    markers, ``.``/``..`` traversal segments, colons, or whitespace, so it
    can never escape ``PACKS_ROOT`` regardless of the current working
    directory. Deliberately does NOT use bare filesystem existence to
    decide the branch (a bare id such as ``"."``/``".."`` can trivially
    "exist" as an ambient directory and must never be treated as an
    explicit path)."""

    text = str(path_or_pack_id)
    looks_like_explicit_path = (
        "/" in text or "\\" in text or text in (".", "..") or text.lower().endswith((".yaml", ".yml"))
    )
    if looks_like_explicit_path:
        return Path(text)

    if not _SAFE_PACK_ID_RE.match(text):
        raise AtlasPackError(
            f"bare disease pack id {text!r} is not a safe path token (no separators, "
            "traversal, drive markers, or whitespace allowed)"
        )
    return PACKS_ROOT / text / "pack.yaml"


def load_disease_pack(path_or_pack_id: str) -> DiseasePack:
    """Load, validate, and hash-check a disease pack manifest from a
    literal path or a bare pack id resolved under the repo-root-anchored
    ``configs/atlas/packs`` directory.

    Fails closed with :class:`AtlasPackError` on any structural violation
    or content-hash mismatch. Once the stored hash has been verified
    against the manifest's actual content, every nested mutable field is
    deep-frozen before constructing the returned :class:`DiseasePack`, so
    neither the caller's raw manifest dict nor any reference obtained from
    the returned pack can mutate its validated content.
    """

    pack_path = _resolve_pack_path(path_or_pack_id)
    if not pack_path.is_file():
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
        transcript_pins=_deep_freeze(manifest["transcript_pins"]),
        reconciliation_policy=_deep_freeze(manifest["reconciliation_policy"]),
        ontology_extensions=_deep_freeze(manifest["ontology_extensions"]),
        source_register_pins=tuple(
            _build_source_register_entry(pin) for pin in manifest["source_register_pins"]
        ),
        prohibitions=_deep_freeze(manifest["prohibitions"]),
        pilot_eval_metadata=_deep_freeze(manifest["pilot_eval_metadata"]),
    )
