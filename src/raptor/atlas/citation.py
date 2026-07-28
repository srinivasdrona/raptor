"""Offline, deterministic citation catalog loader and resolver.

Implements the Phase-2 minimal offline & fail-closed primary-source /
exact-span resolver (``docs/project/specs/atlas-citation-resolver-v1.yaml``,
ADR-0016): identifier canonicalization (:func:`normalize_identifier`),
versioned local catalog loading with self-hash verification and deep
immutability (:func:`load_catalog`), and grounding resolution + exact-span
verification (:class:`LocalCitationResolver`).

This module performs NO network access, NO source acquisition, and NO
PDF/HTML/XML parsing -- extracted-text artifacts are produced out of band
and are only verified here by recomputed hash. It imports ONLY the
standard library, ``yaml``, and :mod:`raptor.atlas.model` (never
``raptor.atlas.pack`` or any consumer package) -- see
:func:`raptor.atlas.guards.assert_no_network_imports`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import types
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

import yaml

from raptor.atlas.model import (
    AtlasCatalogHashError,
    AtlasCatalogPathError,
    AtlasCatalogSchemaError,
    AtlasCitationResolutionError,
    AtlasContentDriftError,
    AtlasSpanMismatchError,
    CatalogSource,
    CitationIdentifier,
    ContentVerification,
    DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
    ResolvedCitation,
    SOURCE_REGISTER_ENTRY_ROLES,
    SOURCE_REGISTER_ENTRY_SOURCE_TYPES,
    SOURCE_REGISTER_ENTRY_VERIFICATION_STATES,
    Span,
    VerifiedSpan,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CATALOG_SCHEMA_ID = "atlas.citation_catalog.v1"
_TEXT_NORMALIZATION_ID = "atlas.text_norm.v1"

#: Bare catalog id must be a nonblank, path-safe token -- no separators,
#: traversal, drive markers, colons, or whitespace allowed.
_SAFE_CATALOG_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_CATALOG_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_PMID_VALUE_RE = re.compile(r"^[1-9][0-9]*$")
_DOI_VALUE_RE = re.compile(r"^10\.[0-9]{4,9}/[^\s%]+$")
_ACCESSION_NAMESPACE_RE = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
_ACCESSION_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TEXT_CHAR_LOCATOR_RE = re.compile(r"^text-char:([0-9]+):([0-9]+)$")

_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)
_DOI_TRAILING_PUNCTUATION = (".", ",", ";", ":", ")", "\u2014")

_PERMITTED_USE_VALUES = ("grounding_and_quote", "provenance_only", "context_only")

#: Repo root anchored three levels above this file's directory
#: (``src/raptor/atlas/citation.py``) -- never dependent on the process's
#: current working directory. Mirrors ``pack.py``'s ``_REPO_ROOT``/
#: ``PACKS_ROOT`` anchoring principle (not identical code).
_REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOGS_ROOT = _REPO_ROOT / "configs" / "atlas" / "catalogs"


def _is_nonblank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int_not_bool(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_catalog(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasCatalogSchemaError(message)


def _require_optional_str_field(source_id: str, field_name: str, value: Any) -> Optional[str]:
    """Validate a ``str | None`` optional catalog scalar (``license``,
    ``authoritative_url``, ``document_date``, ``document_version``).
    Rejects ANY other type -- notably a YAML-auto-parsed ``bool``/``int``/
    ``date``/``datetime`` (e.g. an unquoted ``document_date: 2024-01-01``
    is parsed by ``yaml.safe_load`` as ``datetime.date``, not ``str``) or a
    ``list``/``dict`` -- with :class:`AtlasCatalogSchemaError` BEFORE this
    value ever reaches JSON serialization in :func:`catalog_content_hash`
    (which would otherwise raise a raw, untyped ``TypeError``)."""

    if value is None or isinstance(value, str):
        return value
    raise AtlasCatalogSchemaError(
        f"source {source_id!r} field {field_name!r} must be a string or null, got "
        f"{type(value).__name__} ({value!r}); note an unquoted YAML date/bareword is "
        "parsed as a non-string scalar"
    )


# ---------------------------------------------------------------------------
# Identifier normalization (PMID / PMCID / DOI / ACCESSION)
# ---------------------------------------------------------------------------


def _normalize_doi_payload(raw_payload: str) -> CitationIdentifier:
    if "%" in raw_payload:
        raise AtlasCitationResolutionError(
            f"DOI payload must not contain percent-encoding: {raw_payload!r}"
        )
    if not raw_payload or raw_payload[-1] in _DOI_TRAILING_PUNCTUATION:
        raise AtlasCitationResolutionError(
            f"DOI payload must not end in trailing sentence punctuation: {raw_payload!r}"
        )
    lowered = raw_payload.lower()
    if not _DOI_VALUE_RE.match(lowered):
        raise AtlasCitationResolutionError(f"malformed DOI payload: {raw_payload!r}")
    return CitationIdentifier(scheme="DOI", value=lowered, canonical=f"DOI:{lowered}")


def normalize_identifier(raw: str) -> CitationIdentifier:
    """Canonicalize a single raw citation identifier string.

    Accepts a single raw string. Only outer ASCII whitespace is trimmed;
    any internal whitespace is rejected. A recognized scheme prefix
    (``PMID:``, ``PMCID:``, ``DOI:``, ``ACCESSION:``) is matched
    case-insensitively and, if present, fixes the scheme; DOI additionally
    accepts ``doi:`` and ``http(s)://(dx.)doi.org/`` URL forms. If no
    scheme prefix is present the scheme is detected from the bare value:
    all-digits -> PMID; ``PMC<digits>`` (case-insensitive) -> PMCID;
    ``10.`` prefix -> DOI. A bare accession has no reliable bare form and
    must use the ``ACCESSION:`` prefix. Deterministic and pure (no I/O).
    Raises :class:`AtlasCitationResolutionError` on empty, internal
    whitespace, unknown-scheme, or malformed input.
    """

    if not isinstance(raw, str):
        raise AtlasCitationResolutionError(f"identifier must be a string, got {type(raw)!r}")

    trimmed = raw.strip()
    if not trimmed:
        raise AtlasCitationResolutionError("identifier must not be empty")
    if any(ch.isspace() for ch in trimmed):
        raise AtlasCitationResolutionError(f"identifier must not contain internal whitespace: {raw!r}")

    lowered = trimmed.lower()

    if lowered.startswith("pmid:"):
        value = trimmed[len("pmid:"):]
        if not _PMID_VALUE_RE.match(value):
            raise AtlasCitationResolutionError(
                f"PMID value must be positive digits with no leading zeros: {value!r}"
            )
        return CitationIdentifier(scheme="PMID", value=value, canonical=f"PMID:{value}")

    if lowered.startswith("pmcid:"):
        value = trimmed[len("pmcid:"):]
        if not value.upper().startswith("PMC"):
            raise AtlasCitationResolutionError(f"PMCID value must start with PMC: {value!r}")
        pmc_digits = value[3:]
        if not pmc_digits.isdigit():
            raise AtlasCitationResolutionError(f"PMCID value must be PMC followed by digits: {value!r}")
        value_upper = "PMC" + pmc_digits
        return CitationIdentifier(scheme="PMCID", value=value_upper, canonical=f"PMCID:{value_upper}")

    if lowered.startswith("doi:"):
        return _normalize_doi_payload(trimmed[len("doi:"):])

    if lowered.startswith("accession:"):
        value = trimmed[len("accession:"):]
        parts = value.split(":", 1)
        if len(parts) != 2:
            raise AtlasCitationResolutionError(
                f"ACCESSION value must be '<namespace>:<opaque>': {value!r}"
            )
        namespace, opaque = parts
        namespace_lower = namespace.lower()
        if not _ACCESSION_NAMESPACE_RE.match(namespace_lower):
            raise AtlasCitationResolutionError(f"invalid ACCESSION namespace: {namespace!r}")
        if not _ACCESSION_OPAQUE_RE.match(opaque):
            raise AtlasCitationResolutionError(f"invalid ACCESSION opaque value: {opaque!r}")
        canonical_value = f"{namespace_lower}:{opaque}"
        return CitationIdentifier(
            scheme="ACCESSION", value=canonical_value, canonical=f"ACCESSION:{canonical_value}"
        )

    # Bare (unprefixed) form detection.
    if trimmed.isdigit() and not trimmed.startswith("0"):
        return CitationIdentifier(scheme="PMID", value=trimmed, canonical=f"PMID:{trimmed}")

    if lowered.startswith("pmc"):
        pmc_digits = trimmed[3:]
        if pmc_digits.isdigit():
            value_upper = "PMC" + pmc_digits
            return CitationIdentifier(scheme="PMCID", value=value_upper, canonical=f"PMCID:{value_upper}")

    if trimmed.startswith("10."):
        return _normalize_doi_payload(trimmed)

    for url_prefix in _DOI_URL_PREFIXES:
        if lowered.startswith(url_prefix):
            return _normalize_doi_payload(trimmed[len(url_prefix):])

    raise AtlasCitationResolutionError(f"unknown or malformed citation identifier scheme: {raw!r}")


# ---------------------------------------------------------------------------
# Canonical catalog content hash (mirrors atlas.pack_content_hash.v1)
# ---------------------------------------------------------------------------


def catalog_content_hash(manifest: Mapping[str, Any]) -> str:
    """Compute the canonical ``atlas.citation_catalog_content_hash.v1``
    digest of ``manifest``, excluding ONLY the top-level
    ``catalog_content_hash`` key. Every other present field -- including
    explicit ``null`` values -- participates. Mirrors
    ``atlas.pack_content_hash.v1`` (:func:`raptor.atlas.pack.pack_content_hash`)
    exactly: canonical JSON (``sort_keys=True``, ``separators=(",", ":")``,
    ``ensure_ascii=False``, sequence order preserved), lowercase SHA-256
    hex digest.

    ``load_catalog`` always calls this AFTER structural validation (so a
    non-JSON-native scalar, e.g. a YAML-auto-parsed date, is already
    rejected by then). Because this is also a PUBLIC function callable
    directly with an arbitrary mapping, a value ``json.dumps`` cannot
    serialize (e.g. ``datetime.date``, ``set``, a custom object) is
    translated to :class:`AtlasCatalogSchemaError` here too -- never a raw
    ``TypeError``/``ValueError`` escaping to the caller."""

    payload = {key: value for key, value in manifest.items() if key != "catalog_content_hash"}
    try:
        canonical_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AtlasCatalogSchemaError(
            f"citation catalog manifest contains a value that is not JSON-native and "
            f"cannot be hashed: {exc}"
        ) from exc
    return hashlib.sha256(canonical_bytes).hexdigest().lower()


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze ``value`` (mirrors ``pack.py``'s ``_deep_freeze``,
    reimplemented locally since ``citation.py`` may not import
    ``raptor.atlas.pack``): every ``dict`` becomes a
    ``types.MappingProxyType`` wrapping a rebuilt dict of already-frozen
    children, and every ``list``/``tuple`` becomes a ``tuple`` of
    already-frozen elements. Never retains a reference to any original
    mutable container."""

    if isinstance(value, dict):
        return types.MappingProxyType({key: _deep_freeze(v) for key, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


# ---------------------------------------------------------------------------
# Catalog structural validation
# ---------------------------------------------------------------------------


def _validate_artifact_pin(source_id: str, kind: str, pin: Any, required_fields: Tuple[str, ...]) -> None:
    _require_catalog(
        isinstance(pin, dict),
        f"source {source_id!r} field {kind!r} must be a mapping",
    )
    for field_name in required_fields:
        _require_catalog(
            field_name in pin,
            f"source {source_id!r} field {kind!r} is missing required field {field_name!r}",
        )
    _require_catalog(
        _is_nonblank_str(pin["relative_path"]),
        f"source {source_id!r} field {kind!r}.relative_path must be a nonblank string",
    )
    _require_catalog(
        isinstance(pin["sha256"], str) and bool(_SHA256_HEX_RE.match(pin["sha256"])),
        f"source {source_id!r} field {kind!r}.sha256 must be a lowercase 64-hex digest",
    )
    _require_catalog(
        _is_int_not_bool(pin["byte_length"]) and pin["byte_length"] >= 0,
        f"source {source_id!r} field {kind!r}.byte_length must be a non-negative int",
    )


def _validate_raw_artifact(source_id: str, raw_artifact: Any) -> None:
    _validate_artifact_pin(
        source_id, "raw_artifact", raw_artifact, ("relative_path", "sha256", "byte_length", "media_type")
    )
    _require_catalog(
        _is_nonblank_str(raw_artifact["media_type"]),
        f"source {source_id!r} field raw_artifact.media_type must be a nonblank string",
    )


def _validate_extracted_text(source_id: str, extracted_text: Any) -> None:
    _validate_artifact_pin(
        source_id,
        "extracted_text",
        extracted_text,
        ("relative_path", "sha256", "byte_length", "extraction_method", "extraction_version", "normalization"),
    )
    _require_catalog(
        _is_nonblank_str(extracted_text["extraction_method"]),
        f"source {source_id!r} field extracted_text.extraction_method must be a nonblank string",
    )
    _require_catalog(
        _is_nonblank_str(extracted_text["extraction_version"]),
        f"source {source_id!r} field extracted_text.extraction_version must be a nonblank string",
    )
    _require_catalog(
        extracted_text["normalization"] == _TEXT_NORMALIZATION_ID,
        f"source {source_id!r} field extracted_text.normalization must be exactly "
        f"{_TEXT_NORMALIZATION_ID!r}",
    )


def _validate_and_build_sources(
    sources_raw: Any,
) -> Tuple[Tuple[CatalogSource, ...], Mapping[str, str]]:
    _require_catalog(isinstance(sources_raw, list), "citation catalog field 'sources' must be a list")

    seen_source_ids: set = set()
    alias_index: dict = {}
    built: list = []

    for entry in sources_raw:
        _require_catalog(isinstance(entry, dict), f"citation catalog source entry {entry!r} must be a mapping")
        for field_name in ("source_id", "source_type", "role", "permitted_use", "verification"):
            _require_catalog(
                field_name in entry,
                f"citation catalog source entry is missing required field {field_name!r}",
            )

        source_id = entry["source_id"]
        _require_catalog(
            _is_nonblank_str(source_id),
            f"source_id must be a nonblank string, got {source_id!r}",
        )
        _require_catalog(source_id not in seen_source_ids, f"duplicate source_id {source_id!r}")
        seen_source_ids.add(source_id)

        source_type = entry["source_type"]
        _require_catalog(
            source_type in SOURCE_REGISTER_ENTRY_SOURCE_TYPES,
            f"source {source_id!r} has invalid source_type {source_type!r}",
        )

        role = entry["role"]
        _require_catalog(
            role in SOURCE_REGISTER_ENTRY_ROLES,
            f"source {source_id!r} has invalid role {role!r}",
        )

        permitted_use = entry["permitted_use"]
        _require_catalog(
            permitted_use in _PERMITTED_USE_VALUES,
            f"source {source_id!r} has invalid permitted_use {permitted_use!r}",
        )

        verification = entry["verification"]
        _require_catalog(
            verification in SOURCE_REGISTER_ENTRY_VERIFICATION_STATES,
            f"source {source_id!r} has invalid verification {verification!r}",
        )

        identifiers_obj = entry.get("identifiers") or {}
        _require_catalog(
            isinstance(identifiers_obj, dict),
            f"source {source_id!r} field 'identifiers' must be a mapping",
        )

        normalized_identifiers = []
        for scheme_key, prefix in (("pmid", "PMID"), ("pmcid", "PMCID"), ("doi", "DOI"), ("accession", "ACCESSION")):
            raw_values = identifiers_obj.get(scheme_key) or []
            _require_catalog(
                isinstance(raw_values, list),
                f"source {source_id!r} field 'identifiers.{scheme_key}' must be a list",
            )
            for raw_value in raw_values:
                _require_catalog(
                    isinstance(raw_value, str) and raw_value,
                    f"source {source_id!r} identifiers.{scheme_key} entries must be nonblank strings",
                )
                try:
                    identifier = normalize_identifier(f"{prefix}:{raw_value}")
                except AtlasCitationResolutionError as exc:
                    raise AtlasCatalogSchemaError(
                        f"source {source_id!r} declares a malformed identifiers.{scheme_key} "
                        f"value {raw_value!r}"
                    ) from exc
                if identifier.canonical in alias_index:
                    raise AtlasCatalogSchemaError(
                        f"identifier {identifier.canonical!r} is declared more than once across "
                        "the catalog (duplicate or cross-source alias)"
                    )
                alias_index[identifier.canonical] = source_id
                normalized_identifiers.append(identifier)

        raw_artifact = entry.get("raw_artifact")
        raw_relative_path = raw_declared_sha256 = raw_media_type = None
        raw_declared_byte_length: Optional[int] = None
        if raw_artifact is not None:
            _validate_raw_artifact(source_id, raw_artifact)
            raw_relative_path = raw_artifact["relative_path"]
            raw_declared_sha256 = raw_artifact["sha256"]
            raw_declared_byte_length = raw_artifact["byte_length"]
            raw_media_type = raw_artifact["media_type"]

        extracted_text = entry.get("extracted_text")
        extracted_relative_path = extracted_declared_sha256 = None
        extraction_method = extraction_version = text_normalization = None
        extracted_declared_byte_length: Optional[int] = None
        if extracted_text is not None:
            _validate_extracted_text(source_id, extracted_text)
            extracted_relative_path = extracted_text["relative_path"]
            extracted_declared_sha256 = extracted_text["sha256"]
            extracted_declared_byte_length = extracted_text["byte_length"]
            extraction_method = extracted_text["extraction_method"]
            extraction_version = extracted_text["extraction_version"]
            text_normalization = extracted_text["normalization"]

        if role == "direct_evidence_leaf":
            _require_catalog(
                source_type in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES,
                f"source {source_id!r} has role='direct_evidence_leaf' but source_type "
                f"{source_type!r} is not one of {DIRECT_EVIDENCE_LEAF_SOURCE_TYPES!r}",
            )
            _require_catalog(
                raw_artifact is not None,
                f"source {source_id!r} has role='direct_evidence_leaf' but is missing raw_artifact",
            )
            _require_catalog(
                len(normalized_identifiers) >= 1,
                f"source {source_id!r} has role='direct_evidence_leaf' but declares zero identifiers",
            )

        # Validate the four optional str|None scalars BEFORE they are ever
        # retained on the frozen CatalogSource -- and, transitively, before
        # catalog_content_hash's JSON serialization -- so a YAML-native
        # non-string scalar (bool/int/date/list/dict) fails closed here with
        # AtlasCatalogSchemaError, never as a raw TypeError from json.dumps.
        license_value = _require_optional_str_field(source_id, "license", entry.get("license"))
        authoritative_url_value = _require_optional_str_field(
            source_id, "authoritative_url", entry.get("authoritative_url")
        )
        document_date_value = _require_optional_str_field(
            source_id, "document_date", entry.get("document_date")
        )
        document_version_value = _require_optional_str_field(
            source_id, "document_version", entry.get("document_version")
        )

        built.append(
            CatalogSource(
                source_id=source_id,
                source_type=source_type,
                role=role,
                identifiers=tuple(normalized_identifiers),
                license=license_value,
                permitted_use=permitted_use,
                verification=verification,
                authoritative_url=authoritative_url_value,
                document_date=document_date_value,
                document_version=document_version_value,
                raw_relative_path=raw_relative_path,
                raw_declared_sha256=raw_declared_sha256,
                raw_declared_byte_length=raw_declared_byte_length,
                raw_media_type=raw_media_type,
                extracted_relative_path=extracted_relative_path,
                extracted_declared_sha256=extracted_declared_sha256,
                extracted_declared_byte_length=extracted_declared_byte_length,
                extraction_method=extraction_method,
                extraction_version=extraction_version,
                text_normalization=text_normalization,
            )
        )

    return tuple(built), alias_index


def _validate_catalog_manifest(manifest: Any) -> None:
    _require_catalog(isinstance(manifest, dict), "citation catalog manifest must be a mapping")

    for field_name in (
        "schema",
        "catalog_id",
        "catalog_version",
        "catalog_content_hash",
        "disease_pack_binding",
        "content_root_policy",
        "sources",
    ):
        _require_catalog(
            field_name in manifest,
            f"citation catalog manifest is missing required field {field_name!r}",
        )

    _require_catalog(
        manifest["schema"] == _CATALOG_SCHEMA_ID,
        f"citation catalog manifest 'schema' must be exactly {_CATALOG_SCHEMA_ID!r}, "
        f"got {manifest['schema']!r}",
    )

    catalog_id = manifest["catalog_id"]
    _require_catalog(
        _is_nonblank_str(catalog_id) and bool(_SAFE_CATALOG_ID_RE.match(catalog_id)),
        f"citation catalog manifest 'catalog_id' must be a nonblank path-safe token, "
        f"got {catalog_id!r}",
    )

    catalog_version = manifest["catalog_version"]
    _require_catalog(
        _is_nonblank_str(catalog_version) and bool(_SAFE_CATALOG_VERSION_RE.match(catalog_version)),
        f"citation catalog manifest 'catalog_version' must be a nonblank version-safe "
        f"token, got {catalog_version!r}",
    )

    _require_catalog(
        isinstance(manifest["catalog_content_hash"], str),
        "citation catalog manifest 'catalog_content_hash' must be a string",
    )

    disease_pack_binding = manifest["disease_pack_binding"]
    _require_catalog(
        isinstance(disease_pack_binding, dict),
        "citation catalog manifest 'disease_pack_binding' must be a mapping",
    )
    for field_name in ("pack_id", "pack_version", "pack_content_hash"):
        _require_catalog(
            field_name in disease_pack_binding,
            f"citation catalog manifest 'disease_pack_binding' missing field {field_name!r}",
        )

    _require_catalog(
        isinstance(manifest["content_root_policy"], dict),
        "citation catalog manifest 'content_root_policy' must be a mapping",
    )


# ---------------------------------------------------------------------------
# Manifest path resolution (bare id vs. explicit path; stat-independent)
# ---------------------------------------------------------------------------


def _resolve_catalog_manifest_path(path_or_catalog_id: Union[str, "os.PathLike[str]"]) -> Path:
    """Resolve ``path_or_catalog_id`` to a concrete, verified catalog
    manifest path.

    An ``os.PathLike[str]`` argument (e.g. ``pathlib.Path``) is ALWAYS an
    explicit path, regardless of its text. A ``str`` is classified purely
    by syntax, stat-independently: it is a bare catalog id iff it matches
    ``^[A-Za-z0-9_-]+$`` (which already excludes ``.``/``..``, separators,
    drive/UNC markers, ``:``, and whitespace); otherwise it is an explicit
    path. A bare id resolves ONLY under the repo-root-anchored
    :data:`CATALOGS_ROOT`. An explicit relative path resolves against the
    caller's process CWD; an explicit absolute path is used as given.
    The resolved manifest MUST be a regular, non-symlink/junction file --
    checked via ``lstat`` on the un-resolved candidate BEFORE following
    any symlink, then confirmed to exist and be a regular file via
    ``resolve(strict=True)``.
    """

    if isinstance(path_or_catalog_id, str):
        text = path_or_catalog_id
        if _SAFE_CATALOG_ID_RE.match(text):
            candidate = CATALOGS_ROOT / text / "catalog.yaml"
        else:
            candidate = Path(text)
    elif isinstance(path_or_catalog_id, os.PathLike):
        candidate = Path(path_or_catalog_id)
    else:
        raise AtlasCatalogPathError(
            "load_catalog path_or_catalog_id must be a str or os.PathLike[str], got "
            f"{type(path_or_catalog_id)!r}"
        )

    try:
        candidate_lstat = candidate.lstat()
    except OSError as exc:
        raise AtlasCatalogPathError(f"citation catalog manifest not found at {candidate}") from exc

    if stat.S_ISLNK(candidate_lstat.st_mode):
        raise AtlasCatalogPathError(
            f"citation catalog manifest {candidate} must be a regular, non-symlink/junction file"
        )

    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AtlasCatalogPathError(f"citation catalog manifest not found at {candidate}") from exc

    if not resolved.is_file():
        raise AtlasCatalogPathError(f"citation catalog manifest {resolved} must be a regular file")

    return resolved


def _resolve_content_root(content_root: Union[str, "os.PathLike[str]"]) -> Path:
    if not isinstance(content_root, (str, os.PathLike)):
        raise AtlasCatalogPathError(
            f"content_root must be a str or os.PathLike[str], got {type(content_root)!r}"
        )
    try:
        resolved = Path(content_root).resolve(strict=True)
    except OSError as exc:
        raise AtlasCatalogPathError(f"content_root {content_root!r} does not exist") from exc
    if not resolved.is_dir():
        raise AtlasCatalogPathError(f"content_root {resolved} is not an existing directory")
    return resolved


def _resolve_content_artifact(content_root: Path, relative_path: Any) -> Path:
    """Resolve ``relative_path`` under ``content_root`` with full
    containment safety: rejects non-relative paths (drive, absolute,
    leading slash), any ``..`` traversal segment, an un-resolved symlink
    or Windows reparse point/junction AT THE CANDIDATE PATH ITSELF
    (checked via ``lstat`` BEFORE following it -- mirrors
    ``_resolve_catalog_manifest_path``'s manifest check), and -- via
    resolved realpath containment -- any symlink/junction chain that
    escapes the root."""

    _require_content_path(
        isinstance(relative_path, str) and bool(relative_path),
        "content artifact relative_path must be a nonblank string",
    )

    candidate_relative = Path(relative_path)
    _require_content_path(
        not candidate_relative.drive
        and not candidate_relative.is_absolute()
        and not relative_path.startswith("/")
        and not relative_path.startswith("\\"),
        f"content artifact relative_path {relative_path!r} must be relative "
        "(no drive, no leading slash)",
    )
    _require_content_path(
        ".." not in candidate_relative.parts,
        f"content artifact relative_path {relative_path!r} must not contain a '..' segment",
    )

    candidate = content_root / relative_path
    try:
        candidate_lstat = candidate.lstat()
    except OSError as exc:
        raise AtlasCatalogPathError(f"content artifact not found at {candidate}") from exc
    if stat.S_ISLNK(candidate_lstat.st_mode):
        raise AtlasCatalogPathError(
            f"content artifact {candidate} must be a regular, non-symlink/junction file"
        )
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_bit and (getattr(candidate_lstat, "st_file_attributes", 0) & reparse_bit):
        raise AtlasCatalogPathError(f"content artifact {candidate} must not be a reparse point/junction")

    try:
        real_file = candidate.resolve(strict=True)
    except OSError as exc:
        raise AtlasCatalogPathError(f"content artifact not found at {candidate}") from exc

    if real_file != content_root and content_root not in real_file.parents:
        raise AtlasCatalogPathError(
            f"content artifact {real_file} escapes the allowed content_root {content_root}"
        )
    if not real_file.is_file():
        raise AtlasCatalogPathError(f"content artifact {real_file} is not a regular file")

    return real_file


def _require_content_path(condition: bool, message: str) -> None:
    if not condition:
        raise AtlasCatalogPathError(message)


# ---------------------------------------------------------------------------
# TOCTOU-hardened checked-handle file reads
# ---------------------------------------------------------------------------
#
# Every security-sensitive read (the catalog manifest itself, and each raw /
# extracted-text content artifact) goes through _read_verified_file below --
# NEVER "resolve/check a Path, hand it back, and let the caller reopen it by
# name later" (that pattern is exactly the check-then-use race this closes).


def _identity(result: "os.stat_result") -> Tuple[int, int]:
    return (result.st_dev, result.st_ino)


def _reject_unsafe_stat(path: Path, result: "os.stat_result", *, what: str) -> None:
    if stat.S_ISLNK(result.st_mode):
        raise AtlasCatalogPathError(f"{what} {path} must be a regular, non-symlink/junction file")
    reparse_bit = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse_bit and (getattr(result, "st_file_attributes", 0) & reparse_bit):
        raise AtlasCatalogPathError(f"{what} {path} must not be a reparse point/junction")
    if not stat.S_ISREG(result.st_mode):
        raise AtlasCatalogPathError(f"{what} {path} must be a regular file")


def _read_verified_file(path: Path, *, content_root: Optional[Path] = None, what: str = "file") -> bytes:
    """Read the FULL contents of ``path`` through a single checked file
    descriptor -- an immediate lstat-check -> open -> fstat-identity-check
    -> read -> post-read fstat -> post-close lstat/realpath-recheck
    sequence -- rather than returning a "checked" :class:`Path` for a
    caller to reopen by name later (the classic TOCTOU anti-pattern).

    Sequence:
      1. ``lstat`` the un-opened path and reject a symlink, a Windows
         reparse point/junction (``FILE_ATTRIBUTE_REPARSE_POINT``), or any
         non-regular file BEFORE any ``open`` is attempted.
      2. ``os.open`` read-only, adding ``O_NOFOLLOW`` when the platform
         defines it (POSIX only -- Windows' ``os.open`` has no equivalent
         flag).
      3. ``os.fstat`` the just-opened descriptor and require its
         (device, inode) identity and regular-file-ness to match the
         pre-open ``lstat`` exactly. This still detects a same-name
         symlink/file swap on platforms without ``O_NOFOLLOW`` because a
         substituted target necessarily carries a different inode.
      4. Read every byte through that SAME descriptor (never a second
         open).
      5. ``fstat`` the descriptor again immediately post-read (detects a
         change during the read).
      6. After closing, ``lstat`` the path ONE more time and require the
         same identity, still a regular file, and -- if ``content_root``
         is given -- still realpath-contained under it.
    Any mismatch at any checkpoint fails closed with
    :class:`AtlasCatalogPathError` -- never a bare ``OSError``.

    Residual limitation (documented, not silently assumed away): Windows
    provides no ``os.open`` flag to refuse following a reparse point, so a
    race landing EXACTLY between step 1's ``lstat`` and step 2's ``open``
    is only CAUGHT (via the inevitable identity mismatch a substitution
    produces) rather than prevented outright. This module assumes a
    trusted local filesystem with no concurrent hostile writer racing the
    read; it does not claim atomicity on Windows.
    """

    try:
        pre_open_lstat = path.lstat()
    except OSError as exc:
        raise AtlasCatalogPathError(f"{what} not found at {path}") from exc
    _reject_unsafe_stat(path, pre_open_lstat, what=what)

    open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, open_flags)
    except OSError as exc:
        raise AtlasCatalogPathError(f"{what} could not be opened at {path}") from exc

    try:
        post_open_stat = os.fstat(fd)
        if not stat.S_ISREG(post_open_stat.st_mode) or _identity(post_open_stat) != _identity(pre_open_lstat):
            raise AtlasCatalogPathError(
                f"{what} {path} identity changed between check and open (TOCTOU)"
            )
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        post_read_stat = os.fstat(fd)
    finally:
        os.close(fd)

    if not stat.S_ISREG(post_read_stat.st_mode) or _identity(post_read_stat) != _identity(pre_open_lstat):
        raise AtlasCatalogPathError(f"{what} {path} identity changed during read (TOCTOU)")

    try:
        post_close_lstat = path.lstat()
    except OSError as exc:
        raise AtlasCatalogPathError(f"{what} vanished immediately after read at {path}") from exc
    _reject_unsafe_stat(path, post_close_lstat, what=what)
    if _identity(post_close_lstat) != _identity(pre_open_lstat):
        raise AtlasCatalogPathError(f"{what} {path} was swapped immediately after read (TOCTOU)")

    if content_root is not None:
        try:
            real_check = path.resolve(strict=True)
        except OSError as exc:
            raise AtlasCatalogPathError(f"{what} not found at {path}") from exc
        if real_check != content_root and content_root not in real_check.parents:
            raise AtlasCatalogPathError(
                f"{what} {real_check} escapes the allowed content_root {content_root}"
            )

    return data


# ---------------------------------------------------------------------------
# CitationCatalog + load_catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CitationCatalog:
    """A loaded, self-hash-verified, deep-frozen citation catalog."""

    schema: str
    catalog_id: str
    catalog_version: str
    catalog_content_hash: str
    disease_pack_binding: Mapping[str, Any]
    sources: Tuple[CatalogSource, ...]
    alias_index: Mapping[str, str]
    content_root: Path


def load_catalog(
    path_or_catalog_id: Union[str, "os.PathLike[str]"],
    *,
    content_root: Union[str, "os.PathLike[str]"],
) -> CitationCatalog:
    """Load, structurally validate, self-hash-verify, and deep-freeze a
    versioned local citation catalog manifest.

    Diverges intentionally from ``pack.py``'s ``_resolve_pack_path`` (str
    only): accepts ``path_or_catalog_id`` and ``content_root`` as either
    ``str`` or ``os.PathLike[str]``, reusing the same containment
    principles (repo-root-anchored id root, stat-independent syntax
    classification, resolved-realpath containment, non-symlink manifest).
    Fails closed with a distinct :class:`~raptor.atlas.model.AtlasCatalogError`
    subclass on any structural, hash, or path-safety violation.
    """

    manifest_path = _resolve_catalog_manifest_path(path_or_catalog_id)

    manifest_bytes = _read_verified_file(manifest_path, what="citation catalog manifest")
    try:
        manifest_text = manifest_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AtlasCatalogSchemaError(
            f"citation catalog manifest at {manifest_path} is not valid UTF-8"
        ) from exc
    raw_manifest = yaml.safe_load(manifest_text)

    _validate_catalog_manifest(raw_manifest)
    sources, alias_index = _validate_and_build_sources(raw_manifest["sources"])

    stored_hash = raw_manifest.get("catalog_content_hash")
    computed_hash = catalog_content_hash(raw_manifest)
    if not isinstance(stored_hash, str) or stored_hash.lower() != computed_hash:
        raise AtlasCatalogHashError(
            f"citation catalog manifest at {manifest_path} has catalog_content_hash "
            f"{stored_hash!r} but recomputes to {computed_hash!r}"
        )

    resolved_content_root = _resolve_content_root(content_root)

    return CitationCatalog(
        schema=raw_manifest["schema"],
        catalog_id=raw_manifest["catalog_id"],
        catalog_version=raw_manifest["catalog_version"],
        catalog_content_hash=stored_hash,
        disease_pack_binding=_deep_freeze(raw_manifest["disease_pack_binding"]),
        sources=sources,
        alias_index=types.MappingProxyType(dict(alias_index)),
        content_root=resolved_content_root,
    )


# ---------------------------------------------------------------------------
# Text normalization (atlas.text_norm.v1)
# ---------------------------------------------------------------------------


def _normalize_extracted_text(decoded_text: str) -> str:
    normalized = decoded_text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized)


# ---------------------------------------------------------------------------
# LocalCitationResolver
# ---------------------------------------------------------------------------


class LocalCitationResolver:
    """Offline, deterministic resolver bound to a single loaded
    :class:`CitationCatalog`. Implements the
    :class:`~raptor.atlas.model.CitationResolver` protocol
    (``resolve``/``verify_span``) plus the concrete ``verify_content``
    surface (not part of the minimal protocol)."""

    def __init__(self, catalog: CitationCatalog) -> None:
        self._catalog = catalog
        self._sources_by_id = {source.source_id: source for source in catalog.sources}

    def resolve(self, identifier: Union[CitationIdentifier, str]) -> ResolvedCitation:
        """Apply the FULL grounding predicate. This is the only resolve
        path in v1 -- there is no non-grounding resolve entry point."""

        if isinstance(identifier, CitationIdentifier):
            ident = identifier
        elif isinstance(identifier, str):
            ident = normalize_identifier(identifier)
        else:
            raise AtlasCitationResolutionError(
                f"identifier must be a CitationIdentifier or str, got {type(identifier)!r}"
            )

        source_id = self._catalog.alias_index.get(ident.canonical)
        if source_id is None:
            raise AtlasCitationResolutionError(
                f"identifier {ident.canonical!r} is not present in the catalog alias index"
            )

        source = self._sources_by_id[source_id]

        if source.role != "direct_evidence_leaf":
            raise AtlasCitationResolutionError(
                f"source {source_id!r} has role {source.role!r}; only a direct_evidence_leaf "
                "source is grounding-admissible"
            )
        if source.source_type not in DIRECT_EVIDENCE_LEAF_SOURCE_TYPES:
            raise AtlasCitationResolutionError(
                f"source {source_id!r} has source_type {source.source_type!r}; grounding "
                f"requires one of {DIRECT_EVIDENCE_LEAF_SOURCE_TYPES!r}"
            )
        if source.permitted_use != "grounding_and_quote":
            raise AtlasCitationResolutionError(
                f"source {source_id!r} has permitted_use {source.permitted_use!r}; grounding "
                "requires 'grounding_and_quote'"
            )
        if source.verification != "verified":
            raise AtlasCitationResolutionError(
                f"source {source_id!r} has verification {source.verification!r}; grounding "
                "requires 'verified'"
            )
        if not source.identifiers:
            raise AtlasCitationResolutionError(
                f"source {source_id!r} has no supported canonical identifier"
            )
        if not source.raw_relative_path or not source.raw_declared_sha256 or source.raw_declared_byte_length is None:
            raise AtlasCitationResolutionError(
                f"source {source_id!r} does not have a complete raw_artifact pin"
            )

        content = self.verify_content(source)

        return ResolvedCitation(identifier=ident, source=source, content=content, content_verified=True)

    def verify_content(self, source: CatalogSource) -> ContentVerification:
        """Recompute raw (and, when present, extracted-text) sha256 +
        byte-length from disk under ``content_root`` and compare against
        the catalog-declared values. Never trusts declared values."""

        raw_path = _resolve_content_artifact(self._catalog.content_root, source.raw_relative_path)
        raw_bytes = _read_verified_file(
            raw_path, content_root=self._catalog.content_root, what="raw content artifact"
        )
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest().lower()
        raw_byte_length = len(raw_bytes)
        if raw_sha256 != source.raw_declared_sha256 or raw_byte_length != source.raw_declared_byte_length:
            raise AtlasContentDriftError(
                f"raw artifact content drift for source {source.source_id!r}: declared "
                f"sha256={source.raw_declared_sha256!r}/byte_length={source.raw_declared_byte_length!r}, "
                f"recomputed sha256={raw_sha256!r}/byte_length={raw_byte_length!r}"
            )

        extracted_text_sha256: Optional[str] = None
        extracted_text_byte_length: Optional[int] = None
        if source.extracted_relative_path:
            extracted_path = _resolve_content_artifact(
                self._catalog.content_root, source.extracted_relative_path
            )
            extracted_bytes = _read_verified_file(
                extracted_path,
                content_root=self._catalog.content_root,
                what="extracted-text content artifact",
            )
            extracted_text_sha256 = hashlib.sha256(extracted_bytes).hexdigest().lower()
            extracted_text_byte_length = len(extracted_bytes)
            if (
                extracted_text_sha256 != source.extracted_declared_sha256
                or extracted_text_byte_length != source.extracted_declared_byte_length
            ):
                raise AtlasContentDriftError(
                    f"extracted-text content drift for source {source.source_id!r}: declared "
                    f"sha256={source.extracted_declared_sha256!r}/"
                    f"byte_length={source.extracted_declared_byte_length!r}, recomputed "
                    f"sha256={extracted_text_sha256!r}/byte_length={extracted_text_byte_length!r}"
                )

        return ContentVerification(
            raw_sha256=raw_sha256,
            raw_byte_length=raw_byte_length,
            extracted_text_sha256=extracted_text_sha256,
            extracted_text_byte_length=extracted_text_byte_length,
        )

    def verify_span(self, resolved: ResolvedCitation, span: Span) -> VerifiedSpan:
        """Re-locate and re-verify the extracted-text artifact (defense in
        depth), normalize per ``atlas.text_norm.v1``, and require an exact
        normalized-slice match at the ``text-char:<start>:<end>`` locator.
        No fuzzy/approximate matching; ``page_or_figure`` is never used
        for verification."""

        source = resolved.source
        if not source.extracted_relative_path:
            raise AtlasSpanMismatchError(
                f"source {source.source_id!r} has no extracted_text artifact to verify a span against"
            )

        extracted_path = _resolve_content_artifact(self._catalog.content_root, source.extracted_relative_path)
        raw_bytes = _read_verified_file(
            extracted_path, content_root=self._catalog.content_root, what="extracted-text content artifact"
        )

        recomputed_sha256 = hashlib.sha256(raw_bytes).hexdigest().lower()
        recomputed_byte_length = len(raw_bytes)
        if source.extracted_declared_sha256 and recomputed_sha256 != source.extracted_declared_sha256:
            raise AtlasContentDriftError(
                f"extracted-text content drift for source {source.source_id!r} during span verification"
            )
        if (
            source.extracted_declared_byte_length is not None
            and recomputed_byte_length != source.extracted_declared_byte_length
        ):
            raise AtlasContentDriftError(
                f"extracted-text byte-length drift for source {source.source_id!r} during span verification"
            )

        try:
            decoded_text = raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise AtlasContentDriftError(
                f"extracted-text artifact for source {source.source_id!r} is not valid UTF-8"
            ) from exc

        normalized_text = _normalize_extracted_text(decoded_text)

        locator = span.locator
        if not isinstance(locator, str):
            raise AtlasSpanMismatchError("span locator must be a string")

        match = _TEXT_CHAR_LOCATOR_RE.match(locator)
        if not match:
            raise AtlasSpanMismatchError(
                f"span locator {locator!r} does not match the 'text-char:<start>:<end>' grammar"
            )

        start = int(match.group(1))
        end = int(match.group(2))
        if start < 0 or end <= start or end > len(normalized_text):
            raise AtlasSpanMismatchError(
                f"span locator {locator!r} is out of range for normalized text of length "
                f"{len(normalized_text)}"
            )

        exact_quote = span.exact_quote
        if not isinstance(exact_quote, str):
            raise AtlasSpanMismatchError("span exact_quote must be a string")

        if normalized_text[start:end] != exact_quote:
            raise AtlasSpanMismatchError(
                f"exact_quote does not match the normalized text slice [{start}:{end}] for "
                f"source {source.source_id!r}"
            )

        return VerifiedSpan(
            source_id=source.source_id,
            locator=locator,
            start=start,
            end=end,
            exact_quote=exact_quote,
            extracted_text_sha256=recomputed_sha256,
        )
