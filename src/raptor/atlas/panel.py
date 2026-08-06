"""Atlas Phase-2 deterministic contrast-panel selector.

Implements the frozen protocol's ``select_panel`` pipeline: verify every
precondition (V1-V7) against live, hash-verified artifacts (registration,
disease pack, candidate universe, raw discovery inventory, universe lock,
identity map), independently replay normalization (RP1-RP7), recompute
source lineage and evidence strata from raw observation primitives (never
trusting a declared audit field), evaluate per-record eligibility (E1-E8),
run the exhaustive relaxation-ladder search (Section 17), classify every
record's disposition (Section 18), and render a complete run record.

This module is statically pure: it reads no clock, no environment variable,
no argv, and performs no network access. The single wall-clock read
(``run_started_at``) and all file paths are supplied by the caller via
:class:`~raptor.atlas.model.SelectionInputs`. Every mapping/sequence loaded
from disk is deep-frozen (``MappingProxyType``/``tuple``) before it is
returned or attached to a result object.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional, Sequence

import yaml

from raptor.atlas.identity_map import AtlasIdentityMapError, load_identity_map
from raptor.atlas.model import (
    AnchorSpec,
    AtlasIdentityMapAmbiguityError,
    AtlasIdentityMapBindingError,
    AtlasLockDeltaError,
    AtlasPanelError,
    AtlasPanelInputError,
    AtlasPanelPackDriftError,
    AtlasPanelRegistrationError,
    AtlasUniverseContractError,
    AtlasUniverseLockError,
    AttemptOutcome,
    DiseasePack,
    IdentityMapAttestation,
    LineageIndex,
    LockProtocolVersionDelta,
    NormalizationReplay,
    PreconditionReport,
    RawIdentityMapper,
    RecordDisposition,
    SelectionInputs,
    SelectionRun,
)
from raptor.atlas.pack import load_disease_pack

# ---------------------------------------------------------------------------
# Fixed protocol constants (Section 3 sampling strata, Section 17 ladder).
# Module-level constants are tuples ONLY, per the static purity scan: this
# module reads no clock/environment/argv and holds no mutable global state.
# ---------------------------------------------------------------------------

OMEGA: tuple[str, ...] = ("S6", "S4", "S5", "S2", "S3", "S1")
LADDER_STEPS: tuple[str, ...] = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
LEVELS: tuple[str, ...] = ("L0",) + LADDER_STEPS
EXECUTION_ORDER: tuple[str, ...] = ("V1", "V2", "V3", "V4", "V5", "V7", "V6")

_SECTION_4_4_FORBIDDEN_FIELD_KEYWORDS: tuple[str, ...] = (
    "effect_size", "score", "p_value", "percentage", "threshold", "rank", "priority",
    "novelty", "recommended", "promising", "interesting", "consensus", "overall",
)

_CROSSWALK_CONTRADICTORY: tuple[tuple[str, str], ...] = (
    ("vus_with_functional_evidence", "S6"),
    ("vus_without_functional_evidence", "S1"),
    ("vus_without_functional_evidence", "S2"),
    ("vus_without_functional_evidence", "S3"),
    ("vus_without_functional_evidence", "S4"),
    ("vus_without_functional_evidence", "S5"),
)
_CROSSWALK_DISCORDANT: tuple[tuple[str, str], ...] = (
    ("known_pathogenic", "S3"),
    ("known_benign", "S1"),
)

_CONSTRAINT_GROUPS: tuple[tuple[str, str], ...] = (
    ("C", "coverage"),
    ("D", "diversity"),
    ("P", "source_concentration"),
)

_FORMULA_RE = re.compile(r"^ceil\((\d*)n(?:/(\d+))?\)$")

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]")


# ---------------------------------------------------------------------------
# Hashing / canonicalization primitives -- bit-exact ports of the frozen
# protocol's own reference algorithm (Sections 6, 9, 11, 17).
# ---------------------------------------------------------------------------


def _text_norm(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _plain(value: Any) -> Any:
    """Recursively convert a (possibly deep-frozen) structure back into
    plain ``dict``/``list`` so it can be canonically JSON-serialized. Safe
    to call on already-plain structures too."""

    if isinstance(value, (dict, MappingProxyType)):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _canonical_json(payload: Any) -> str:
    return json.dumps(_plain(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_hash(manifest: Mapping[str, Any], self_key: str) -> str:
    plain = _plain(manifest)
    plain.pop(self_key, None)
    return _sha256_text(json.dumps(plain, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _doc_hash(path: Path) -> str:
    return _sha256_text(_text_norm(path.read_text(encoding="utf-8")))


def _raw_inventory_file_digest(path: Path) -> tuple[str, int]:
    normalized = _text_norm(path.read_text(encoding="utf-8"))
    encoded = normalized.encode("utf-8")
    return _sha256_bytes(encoded), len(encoded)


def _ledger_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_text(_canonical_json(list(rows)))


def _discovery_commitment(keys: Iterable[str]) -> tuple[int, str]:
    distinct = sorted(set(keys))
    return len(distinct), _sha256_text("\n".join(distinct))


def _raw_identity_normalized(raw: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", raw).strip())


def protocol_doc_hash(path: Path) -> str:
    """Public wrapper: the protocol document's recomputed content hash."""

    return _doc_hash(path)


def registration_content_hash(registration: Mapping[str, Any]) -> str:
    """Public wrapper: the registration's recomputed self-hash."""

    return _canonical_hash(registration, "registration_content_hash")


def universe_lock_content_hash(lock: Mapping[str, Any]) -> str:
    """Public wrapper: the universe lock's recomputed self-hash."""

    return _canonical_hash(lock, "lock_content_hash")


def candidate_universe_content_hash(universe: Mapping[str, Any]) -> str:
    """Public wrapper: the candidate universe's recomputed self-hash."""

    return _canonical_hash(universe, "universe_content_hash")


def canonical_content_hash(manifest: Mapping[str, Any], *, self_key: str) -> str:
    """Public wrapper over the shared canonical self-hash primitive."""

    return _canonical_hash(manifest, self_key)


def raw_identity_normalized(text: str) -> str:
    """Public wrapper: Unicode NFC + whitespace-collapse normalization."""

    return _raw_identity_normalized(text)


def universe_key(*, identity_state: str, spdi_canonical: Optional[str], raw_identity_string: str) -> str:
    """The deterministic universe-key derivation (Section 9): the resolved
    SPDI when the identity resolved to a truthy value, else a stable
    ``UNRESOLVED:`` surrogate hashed from the normalized raw identity
    string."""

    if identity_state == "resolved" and spdi_canonical:
        return spdi_canonical
    return "UNRESOLVED:" + _sha256_text(_raw_identity_normalized(raw_identity_string))


def draw_key(spdi_canonical: str, *, selection_seed: str) -> str:
    """The deterministic per-candidate draw key (Section 17): a pure
    function of the registration's frozen ``selection_seed`` and the
    record's own ``spdi_canonical`` -- never of wall-clock time, argv, or
    any mutable global."""

    return _sha256_text(f"{selection_seed}|{spdi_canonical}")


def _lineage_group_key(identifiers: Iterable[str]) -> str:
    normalized = sorted({_raw_identity_normalized(i) for i in identifiers})
    return "LG:" + _sha256_text("|".join(normalized))[:16]


# ---------------------------------------------------------------------------
# Deep-freeze / path-safety / generic YAML loading helpers.
# ---------------------------------------------------------------------------


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return value
    if isinstance(value, dict):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _reject_symlink(path: Path, *, what: str) -> None:
    try:
        is_symlink = path.is_symlink()
    except OSError:
        is_symlink = False
    if is_symlink:
        raise AtlasPanelInputError(f"{what} path {path} must not be a symlink", code="INPUT_FAULT")


def _reject_datetime_leak(value: Any, *, what: str) -> None:
    if isinstance(value, (datetime, date)):
        raise AtlasPanelInputError(
            f"{what} contains an unquoted timestamp that YAML auto-coerced into a date/datetime object; "
            "all timestamps must be quoted strings",
            code="INPUT_FAULT",
        )
    if isinstance(value, dict):
        for item in value.values():
            _reject_datetime_leak(item, what=what)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_datetime_leak(item, what=what)


def _repo_relative_path(repo_root: Path, relative: Any, *, what: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise AtlasPanelInputError(f"{what} path must be a non-empty string, got {relative!r}", code="INPUT_FAULT")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive:
        raise AtlasPanelInputError(
            f"{what} path {relative!r} must be repo-relative, not absolute", code="INPUT_FAULT",
        )
    if ".." in candidate.parts:
        raise AtlasPanelInputError(
            f"{what} path {relative!r} must not contain a '..' traversal segment", code="INPUT_FAULT",
        )
    return repo_root / candidate


def _load_yaml_mapping(path: Path, *, what: str, schema_id: Optional[str] = None) -> Mapping[str, Any]:
    _reject_symlink(path, what=what)
    if not path.is_file():
        raise AtlasPanelInputError(f"{what} not found at {path}", code="INPUT_FAULT")
    try:
        text = path.read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise AtlasPanelInputError(f"{what} at {path} could not be parsed as YAML: {exc}", code="INPUT_FAULT") from exc
    if not isinstance(payload, dict):
        raise AtlasPanelInputError(f"{what} at {path} must be a YAML mapping", code="INPUT_FAULT")
    _reject_datetime_leak(payload, what=what)
    if schema_id is not None and payload.get("schema") != schema_id:
        raise AtlasPanelInputError(
            f"{what} at {path} has schema {payload.get('schema')!r}, expected {schema_id!r}",
            code="INPUT_FAULT",
        )
    return _deep_freeze(payload)


def _parse_iso8601(value: Any, *, what: str) -> datetime:
    if not isinstance(value, str) or not _ISO_TIMESTAMP_RE.match(value):
        raise AtlasPanelInputError(f"{what} must be an ISO-8601 timestamp string, got {value!r}", code="INPUT_FAULT")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise AtlasPanelInputError(f"{what} is not a valid ISO-8601 timestamp: {value!r}", code="INPUT_FAULT") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Public artifact loaders (also independently exercised by PS-X-004).
# ---------------------------------------------------------------------------


def load_selection_registration(path: Path) -> Mapping[str, Any]:
    """Load, schema-check, and deep-freeze the Phase-2 selection
    registration. Does not verify its self-hash -- see
    :func:`verify_registration`."""

    return _load_yaml_mapping(path, what="registration", schema_id="atlas.phase2_panel_selection_registration.v1")


def load_candidate_universe(path: Path) -> Mapping[str, Any]:
    """Load, schema-check, and deep-freeze the candidate universe. Does not
    verify its self-hash or conservation -- see :func:`verify_conservation`."""

    return _load_yaml_mapping(path, what="candidate universe", schema_id="atlas.candidate_universe.v1")


def _load_protocol_doc(path: Path) -> tuple[str, str]:
    _reject_symlink(path, what="protocol document")
    if not path.is_file():
        raise AtlasPanelInputError(f"protocol document not found at {path}", code="INPUT_FAULT")
    text = path.read_text(encoding="utf-8")
    return text, _doc_hash(path)


def _load_raw_inventory(path: Path) -> Mapping[str, Any]:
    return _load_yaml_mapping(path, what="raw discovery inventory", schema_id="atlas.discovery_inventory.raw.v1")


# ---------------------------------------------------------------------------
# V1-V4: registration self-consistency, protocol-doc drift, seed shape, and
# pack-binding agreement.
# ---------------------------------------------------------------------------


def verify_registration(registration: Mapping[str, Any], *, protocol_text: str, protocol_doc_hash: str) -> str:
    """V1-V3. Returns the recomputed ``registration_content_hash``."""

    if registration.get("protocol_doc_hash") != protocol_doc_hash:
        raise AtlasPanelRegistrationError(
            "registration protocol_doc_hash does not match the live protocol document's recomputed hash",
            code="PROTOCOL_DIGEST_MISMATCH", check_id="V1",
        )
    recomputed = _canonical_hash(registration, "registration_content_hash")
    if registration.get("registration_content_hash") != recomputed:
        raise AtlasPanelRegistrationError(
            "registration registration_content_hash does not match its own recomputed content",
            code="REGISTRATION_SELF_HASH_MISMATCH", check_id="V2",
        )
    seed = registration.get("selection_seed")
    if not isinstance(seed, str) or not re.search(r"-v\d+$", seed):
        raise AtlasPanelRegistrationError(
            f"registration selection_seed {seed!r} does not carry the required trailing version suffix",
            code="SEED_MISMATCH", check_id="V3",
        )
    return recomputed


def verify_pack_binding(registration: Mapping[str, Any], universe: Mapping[str, Any], pack: DiseasePack) -> None:
    """V4: the live disease pack's content hash must equal both the
    registration's freeze-time snapshot and the candidate universe's own
    pack binding."""

    live_hash = pack.pack_content_hash
    reg_hash = (registration.get("pack_binding_observed_at_freeze") or {}).get("pack_content_hash")
    universe_hash = (universe.get("pack_binding") or {}).get("pack_content_hash")
    if reg_hash != live_hash or universe_hash != live_hash:
        raise AtlasPanelPackDriftError(
            "registration and/or candidate universe pack_binding.pack_content_hash disagrees with the "
            "live disease pack's recomputed content hash",
            code="PACK_DRIFT", check_id="V4",
        )


def _verify_search_parameters(registration: Mapping[str, Any]) -> None:
    params = registration.get("search_parameters") or {}
    if params.get("search_scope") != "full_eligible_universe":
        raise AtlasPanelRegistrationError(
            f"unsupported search_scope {params.get('search_scope')!r}; only 'full_eligible_universe' is implemented",
            code="UNSUPPORTED_SEARCH_SCOPE",
        )
    if params.get("stratum_shortlist_size") is not None:
        raise AtlasPanelRegistrationError(
            "stratum_shortlist_size must be null; shortlisted search is not implemented",
            code="UNSUPPORTED_SEARCH_SCOPE",
        )


# ---------------------------------------------------------------------------
# K1-K6 / V5: universe-lock resolution and cross-verification.
# ---------------------------------------------------------------------------


def resolve_active_lock(registration: Mapping[str, Any], *, repo_root: Path) -> tuple[Path, Mapping[str, Any]]:
    """K1: resolve and load the registration-active universe lock."""

    active = ((registration.get("candidate_universe_contract") or {}).get("universe_lock") or {}).get("active") or {}
    lock_path = _repo_relative_path(repo_root, active.get("path"), what="active universe lock")
    _reject_symlink(lock_path, what="universe lock")
    if not lock_path.is_file():
        raise AtlasUniverseLockError(
            f"registration-active universe lock not found at {lock_path}",
            code="UNIVERSE_LOCK_MISSING", check_id="K1",
        )
    try:
        lock = _load_yaml_mapping(lock_path, what="universe lock", schema_id="atlas.candidate_universe_lock.v1")
    except AtlasPanelError as exc:
        raise AtlasUniverseLockError(
            f"registration-active universe lock at {lock_path} is corrupt: {exc}",
            code="UNIVERSE_LOCK_CORRUPT", check_id="K1",
        ) from exc
    return lock_path, lock


def verify_universe_lock(
    lock: Mapping[str, Any],
    *,
    lock_path: Path,
    registration: Mapping[str, Any],
    universe: Mapping[str, Any],
    pack: DiseasePack,
    run_started_at: datetime,
) -> str:
    """K2, K4, K6. Returns the recomputed ``lock_content_hash``. K3 (the
    universe/raw-inventory/ledger/discovery-set cross-check) is verified
    separately by :func:`_verify_lock_conservation_binding`, which must run
    only after V7 (identity-map) per PS-V-005."""

    recomputed_lock_hash = _canonical_hash(lock, "lock_content_hash")
    active = ((registration.get("candidate_universe_contract") or {}).get("universe_lock") or {}).get("active") or {}
    if lock.get("lock_content_hash") != recomputed_lock_hash or active.get("lock_content_hash") != recomputed_lock_hash:
        raise AtlasUniverseLockError(
            "universe lock lock_content_hash does not match its own recomputed content or the "
            "registration's mirrored value",
            code="UNIVERSE_LOCK_CORRUPT", check_id="K2",
        )

    lock_pack_hash = (lock.get("pack_binding") or {}).get("pack_content_hash")
    if lock_pack_hash != pack.pack_content_hash:
        raise AtlasPanelPackDriftError(
            "universe lock pack_binding.pack_content_hash disagrees with the live disease pack",
            code="PACK_DRIFT", check_id="V4/K4",
        )

    # K6: sibling-duplicate universe_version and future-dated lock.
    universe_version = lock.get("universe_version")
    for sibling in sorted(lock_path.parent.glob("*.yaml")):
        if sibling == lock_path:
            continue
        try:
            sibling_payload = yaml.safe_load(sibling.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if (
            isinstance(sibling_payload, dict)
            and sibling_payload.get("schema") == "atlas.candidate_universe_lock.v1"
            and sibling_payload.get("universe_version") == universe_version
        ):
            raise AtlasUniverseLockError(
                f"another universe lock at {sibling} declares the same universe_version {universe_version!r}",
                code="UNIVERSE_LOCK_INVALID", check_id="K6",
            )
    created_at = _parse_iso8601(lock.get("created_at"), what="universe lock created_at")
    if created_at > run_started_at:
        raise AtlasUniverseLockError(
            f"universe lock created_at {lock.get('created_at')!r} is future-dated relative to run_started_at",
            code="UNIVERSE_LOCK_INVALID", check_id="K6",
        )

    return recomputed_lock_hash


def _verify_lock_conservation_binding(
    lock: Mapping[str, Any],
    *,
    universe: Mapping[str, Any],
    raw_hash: str,
    raw_record_count: int,
    ledger_hash: str,
    ledger_row_count: int,
    discovery_count: Optional[int],
    discovery_hash: Optional[str],
) -> None:
    """K3: the universe lock's snapshot of the universe/raw-inventory/
    normalization-ledger/discovery-set must agree with the freshly verified
    conservation values. Runs after V7/identity-map and V6/conservation per
    PS-V-005 (a missing identity-map lock must win over a K3 mismatch)."""

    raw_inventory = lock.get("raw_inventory") or {}
    normalization_ledger = lock.get("normalization_ledger") or {}
    commitment = lock.get("discovery_set_commitment") or {}
    mismatches = []
    if lock.get("universe_content_hash") != universe.get("universe_content_hash"):
        mismatches.append("universe_content_hash")
    if raw_inventory.get("content_hash") != raw_hash:
        mismatches.append("raw_inventory.content_hash")
    if raw_inventory.get("record_count") != raw_record_count:
        mismatches.append("raw_inventory.record_count")
    if normalization_ledger.get("hash") != ledger_hash:
        mismatches.append("normalization_ledger.hash")
    if normalization_ledger.get("row_count") != ledger_row_count:
        mismatches.append("normalization_ledger.row_count")
    if commitment.get("hash") != discovery_hash:
        mismatches.append("discovery_set_commitment.hash")
    if commitment.get("count") != discovery_count:
        mismatches.append("discovery_set_commitment.count")
    if mismatches:
        raise AtlasUniverseLockError(
            f"universe lock disagrees with the recomputed universe/raw-inventory/ledger/discovery-set "
            f"binding: {', '.join(mismatches)}",
            code="UNIVERSE_LOCK_MISMATCH", check_id="K3",
        )


def build_lock_delta(
    lock: Mapping[str, Any],
    registration: Mapping[str, Any],
    *,
    verified_protocol_doc_hash: str,
    verified_registration_content_hash: str,
) -> LockProtocolVersionDelta:
    """K5: walk the registration's amendment log to determine whether the
    universe lock's frozen protocol/registration digests are still
    reconcilable to the live registration."""

    amendment_log = registration.get("amendment_log") or ()
    versions = [str(entry.get("version")) for entry in amendment_log]
    by_version = dict(zip(versions, amendment_log))

    lock_version = lock.get("protocol_version")
    lock_doc_hash = lock.get("protocol_doc_hash")
    lock_reg_hash = lock.get("registration_content_hash")
    if lock_version is None or lock_doc_hash is None or lock_reg_hash is None:
        raise AtlasLockDeltaError(
            "universe lock is missing one of protocol_version/protocol_doc_hash/registration_content_hash",
            code="UNIVERSE_LOCK_DELTA_INCOMPLETE", check_id="K5",
        )
    lock_version = str(lock_version)
    current_version = str(registration.get("protocol_version"))

    # Section 4.6.2: a lock whose recorded lock-time bindings are false
    # (rather than merely stale) is an invalid-binding lock and can never be
    # an admissible K5 predecessor, regardless of whether its digests
    # otherwise chain correctly. The registration's own superseded list is
    # the authoritative, registrar-attested record of which locks are in
    # that state -- matched here by lock_content_hash.
    lock_content_hash = lock.get("lock_content_hash")
    superseded_entries = (
        (registration.get("candidate_universe_contract") or {}).get("universe_lock") or {}
    ).get("superseded") or ()
    for entry in superseded_entries:
        if entry.get("lock_content_hash") != lock_content_hash:
            continue
        if entry.get("status") == "invalid_binding" or entry.get("admissible_as_k5_predecessor") is False:
            raise AtlasUniverseLockError(
                f"universe lock {lock_content_hash!r} is a recorded invalid-binding lock (protocol "
                "section 4.6.2): its lock-time bindings are false, so it can never be an admissible "
                "K5 predecessor regardless of digest agreement",
                code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN", check_id="K5",
            )
        break

    if lock_version not in by_version:
        raise AtlasLockDeltaError(
            f"universe lock protocol_version {lock_version!r} is not present in the registration amendment log",
            code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN", check_id="K5",
        )

    reconciled: tuple[str, ...] = ()
    if lock_version == current_version:
        # The lock's protocol_version identifies the CURRENT registration
        # exactly: there is no drift to reconcile, regardless of any
        # incidental cross-reference hash quirk between the lock and the
        # registration that mirrors it (they are mutually self-consistent
        # by construction whenever the versions agree).
        differs = False
    else:
        idx = versions.index(lock_version)
        if idx + 1 < len(versions):
            nxt = by_version[versions[idx + 1]]
            supersedes = nxt.get("supersedes_digests") or {}
            if supersedes.get("protocol_doc_hash") != lock_doc_hash or supersedes.get("registration_content_hash") != lock_reg_hash:
                raise AtlasLockDeltaError(
                    "universe lock protocol/registration digests do not match the amendment log's "
                    "supersedes_digests for the next amendment",
                    code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN", check_id="K5",
                )
        else:
            if lock_doc_hash != verified_protocol_doc_hash or lock_reg_hash != verified_registration_content_hash:
                raise AtlasLockDeltaError(
                    "universe lock protocol/registration digests do not match the live protocol/registration "
                    "and the lock's protocol_version has no successor in the amendment log",
                    code="UNIVERSE_LOCK_PROTOCOL_UNKNOWN", check_id="K5",
                )

        differs = True
        if current_version not in by_version:
            raise AtlasLockDeltaError(
                f"current registration protocol_version {current_version!r} is not present in the "
                "amendment log",
                code="UNIVERSE_LOCK_DELTA_INCOMPLETE", check_id="K5",
            )
        cur_idx = versions.index(current_version)
        if cur_idx <= idx:
            raise AtlasLockDeltaError(
                "current registration protocol_version does not postdate the universe lock's protocol_version "
                "in the amendment log",
                code="UNIVERSE_LOCK_DELTA_INCOMPLETE", check_id="K5",
            )
        steps = tuple(versions[idx + 1 : cur_idx + 1])
        for step_version in steps:
            if not by_version[step_version].get("supersedes_digests"):
                raise AtlasLockDeltaError(
                    f"amendment log entry {step_version!r} is missing supersedes_digests, breaking the "
                    "reconciliation chain",
                    code="UNIVERSE_LOCK_DELTA_INCOMPLETE", check_id="K5",
                )
        reconciled = steps

    return LockProtocolVersionDelta(
        lock_protocol_version=lock_version,
        lock_protocol_doc_hash=lock_doc_hash,
        lock_registration_content_hash=lock_reg_hash,
        current_protocol_version=current_version,
        current_protocol_doc_hash=verified_protocol_doc_hash,
        current_registration_content_hash=verified_registration_content_hash,
        differs=differs,
        reconciled_via_amendment_log_versions=reconciled,
    )


# ---------------------------------------------------------------------------
# U1-U6 / V6 (part 1): candidate-universe conservation against the raw
# discovery inventory and its normalization ledger.
# ---------------------------------------------------------------------------


def verify_conservation(
    universe: Mapping[str, Any], *, raw_manifest: Mapping[str, Any], raw_hash: str, raw_bytes_len: int,
) -> tuple[str, int]:
    """U1-U6. Returns ``(ledger_hash, ledger_row_count)`` for K3
    cross-checking."""

    raw_rows = list(raw_manifest.get("rows") or ())

    universe_raw = universe.get("raw_inventory") or {}
    if universe_raw.get("content_hash") != raw_hash:
        raise AtlasUniverseContractError(
            "candidate universe raw_inventory.content_hash does not match the recomputed raw inventory "
            "file digest",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U1",
        )
    if universe_raw.get("record_count") != len(raw_rows):
        raise AtlasUniverseContractError(
            "candidate universe raw_inventory.record_count does not match the raw inventory's own row count",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U1",
        )

    ledger = universe.get("normalization_ledger")
    if not isinstance(ledger, (list, tuple)):
        raise AtlasUniverseContractError(
            "candidate universe normalization_ledger must be a list", code="UNIVERSE_CONTRACT_BREACH", check_id="U2",
        )
    ledger = list(ledger)
    raw_ids = [row.get("raw_record_id") for row in raw_rows]
    ledger_ids = [row.get("raw_record_id") for row in ledger]
    if sorted(raw_ids) != sorted(ledger_ids) or len(set(ledger_ids)) != len(ledger_ids):
        raise AtlasUniverseContractError(
            "normalization_ledger is not a bijection onto the raw discovery inventory rows",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U2",
        )

    records = list(universe.get("records") or ())
    record_keys = [record.get("universe_key") for record in records]
    ledger_keys = [row.get("universe_key") for row in ledger]
    if (
        len(set(record_keys)) != len(record_keys)
        or len(set(ledger_keys)) != len(ledger_keys)
        or set(record_keys) != set(ledger_keys)
    ):
        raise AtlasUniverseContractError(
            "normalization_ledger universe_key set does not match the universe record universe_key set",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U3",
        )

    discovery_count, discovery_hash = _discovery_commitment(ledger_keys)
    commitment = universe.get("discovery_set_commitment") or {}
    if commitment.get("discovery_set_count") != discovery_count or commitment.get("discovery_set_hash") != discovery_hash:
        raise AtlasUniverseContractError(
            "candidate universe discovery_set_commitment does not match the recomputed commitment over "
            "the normalization ledger's universe keys",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U4",
        )

    recomputed_universe_hash = _canonical_hash(universe, "universe_content_hash")
    if universe.get("universe_content_hash") != recomputed_universe_hash:
        raise AtlasUniverseContractError(
            "candidate universe universe_content_hash does not match its own recomputed content",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U5",
        )

    attestation = universe.get("completeness_attestation") or {}
    role = attestation.get("attesting_role")
    if not isinstance(role, str) or not role.strip():
        raise AtlasUniverseContractError(
            "candidate universe completeness_attestation.attesting_role is missing",
            code="UNIVERSE_CONTRACT_BREACH", check_id="U6",
        )
    for record in records:
        present = sorted(
            field for field in record
            if not field.startswith("_")
            and any(keyword in field.lower() for keyword in _SECTION_4_4_FORBIDDEN_FIELD_KEYWORDS)
        )
        if present:
            raise AtlasUniverseContractError(
                f"candidate universe record {record.get('record_id')!r} carries Section 4.4 prohibited "
                f"field(s): {', '.join(present)}",
                code="UNIVERSE_CONTRACT_BREACH", check_id="U6",
            )

    return _ledger_hash(ledger), len(ledger)


# ---------------------------------------------------------------------------
# V7 / IM1-IM6: identity-map verification and attestation assembly.
# ---------------------------------------------------------------------------


#: Mirrors ``raptor.atlas.identity_map._REQUIRED_LOCK_FIELDS`` exactly. Kept
#: as an independent constant (rather than importing the private name) so
#: that a map-lock *shape* violation (missing/extra key) is classified as
#: IDENTITY_MAP_LOCK_CORRUPT/IM1 before the payload is ever handed to
#: ``load_identity_map`` -- whose own (differently-coded) schema check would
#: otherwise be the first thing to see it.
_IDENTITY_MAP_LOCK_FIELDS = frozenset((
    "schema", "lock_id", "lock_version", "created_at", "map_id", "map_version",
    "map_content_hash", "map_record_count", "raw_inventory_content_hash",
    "raw_inventory_record_count", "response_bundle_hash", "response_file_count",
    "response_byte_count", "pack_binding", "reference_binding",
    "acquisition_tool_sha256", "lock_content_hash",
))


def _load_and_verify_map_lock(lock_path: Path) -> Mapping[str, Any]:
    """IM1: independently load and verify the identity-map lock's own
    existence, YAML shape, schema id, and self-hash -- WITHOUT delegating to
    :func:`raptor.atlas.identity_map.load_identity_map` -- so a missing or
    corrupt map lock can never be confused with a downstream lock-to-map
    binding mismatch (which is a distinct code)."""

    _reject_symlink(lock_path, what="identity map lock")
    if not lock_path.is_file():
        raise AtlasIdentityMapBindingError(
            f"identity map lock not found at {lock_path}", code="IDENTITY_MAP_LOCK_MISSING", check_id="IM1",
        )
    try:
        text = lock_path.read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise AtlasIdentityMapBindingError(
            f"identity map lock at {lock_path} could not be parsed as YAML: {exc}",
            code="IDENTITY_MAP_LOCK_CORRUPT", check_id="IM1",
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != "atlas.raw_identity_map_lock.v2":
        raise AtlasIdentityMapBindingError(
            f"identity map lock at {lock_path} has schema {(payload or {}).get('schema')!r}, expected "
            "'atlas.raw_identity_map_lock.v2'",
            code="IDENTITY_MAP_LOCK_CORRUPT", check_id="IM1",
        )
    missing = _IDENTITY_MAP_LOCK_FIELDS - payload.keys()
    extra = payload.keys() - _IDENTITY_MAP_LOCK_FIELDS
    if missing or extra:
        raise AtlasIdentityMapBindingError(
            f"identity map lock at {lock_path} has the wrong field set "
            f"(missing={sorted(missing)}, extra={sorted(extra)})",
            code="IDENTITY_MAP_LOCK_CORRUPT", check_id="IM1",
        )
    _reject_datetime_leak(payload, what="identity map lock")
    lock = _deep_freeze(payload)
    recomputed = _canonical_hash(lock, "lock_content_hash")
    if lock.get("lock_content_hash") != recomputed:
        raise AtlasIdentityMapBindingError(
            f"identity map lock at {lock_path} lock_content_hash does not match its own recomputed content",
            code="IDENTITY_MAP_LOCK_CORRUPT", check_id="IM1",
        )
    return lock


def verify_identity_map(
    *,
    map_path: Path,
    lock_path: Path,
    response_root: Path,
    pack: DiseasePack,
    raw_inventory_path: Path,
    registration_active: Mapping[str, Any],
) -> IdentityMapAttestation:
    """V7 (IM2-IM5 delegated to :func:`raptor.atlas.identity_map.load_identity_map`,
    which independently recomputes every self-hash, binding, and per-record
    resolution classification from disk bytes). IM1 (map lock
    existence/shape/self-hash and its mirror agreement with the
    registration) is verified independently by :func:`_load_and_verify_map_lock`
    and the two mirror checks below, so a mapper fault can never be masked
    by -- or confused with -- a downstream binding mismatch."""

    map_lock = _load_and_verify_map_lock(lock_path)
    if registration_active.get("lock_content_hash") != map_lock.get("lock_content_hash"):
        raise AtlasIdentityMapBindingError(
            "registration identity_map_contract.active.lock_content_hash does not match the verified "
            "identity map lock",
            code="IDENTITY_MAP_LOCK_CORRUPT", check_id="IM1",
        )
    if (
        str(registration_active.get("map_version")) != str(map_lock.get("map_version"))
        or str(registration_active.get("lock_version")) != str(map_lock.get("lock_version"))
    ):
        raise AtlasIdentityMapBindingError(
            "registration identity_map_contract.active map_version/lock_version does not match the "
            "verified identity map lock",
            code="IDENTITY_MAP_MISMATCH", check_id="IM1",
        )

    try:
        mapper = load_identity_map(
            map_path,
            response_root=response_root,
            lock_path=lock_path,
            disease_pack=pack,
            raw_inventory_path=raw_inventory_path,
        )
    except AtlasIdentityMapAmbiguityError as exc:
        raise AtlasIdentityMapBindingError(
            f"identity map failed verification: {exc}", code="IDENTITY_MAP_UNVERIFIED", check_id="IM1",
        ) from exc
    except AtlasIdentityMapError as exc:
        raise AtlasIdentityMapBindingError(
            f"identity map failed verification: {exc}", code="IDENTITY_MAP_MISMATCH", check_id="IM1",
        ) from exc

    map_manifest = _load_yaml_mapping(map_path, what="identity map manifest", schema_id="atlas.raw_identity_map.v2")
    reference_binding = map_manifest.get("reference_binding") or {}
    pins = reference_binding.get("protein_reference_response_pins") or ()

    return IdentityMapAttestation(
        lock_path=lock_path,
        lock_version=str(map_lock.get("lock_version")),
        map_version=str(map_manifest.get("map_version")),
        lock_content_hash=map_lock.get("lock_content_hash"),
        map_content_hash=map_manifest.get("map_content_hash"),
        map_record_count=map_lock.get("map_record_count"),
        response_bundle_hash=map_lock.get("response_bundle_hash"),
        response_file_count=map_lock.get("response_file_count"),
        response_byte_count=map_lock.get("response_byte_count"),
        acquisition_tool_sha256=map_lock.get("acquisition_tool_sha256"),
        reference_assembly=reference_binding.get("assembly"),
        reference_transcript=reference_binding.get("transcript"),
        reference_protein=reference_binding.get("protein"),
        reference_page_count=len(pins),
        checks_passed=("IM1", "IM2", "IM3", "IM4", "IM5"),
        mapper=mapper,
    )


def _verify_identity_map_binding_on_universe_lock(
    lock: Mapping[str, Any], attestation: IdentityMapAttestation,
) -> None:
    """IM6: the universe lock's own ``identity_map_binding`` sub-object
    must agree with the independently verified identity map."""

    binding = lock.get("identity_map_binding")
    if not isinstance(binding, Mapping):
        raise AtlasIdentityMapBindingError(
            "universe lock is missing an identity_map_binding", code="IDENTITY_MAP_MISMATCH", check_id="IM6",
        )
    mismatches = []
    if binding.get("map_content_hash") != attestation.map_content_hash:
        mismatches.append("map_content_hash")
    if binding.get("lock_content_hash") != attestation.lock_content_hash:
        mismatches.append("lock_content_hash")
    if str(binding.get("map_version")) != attestation.map_version:
        mismatches.append("map_version")
    if str(binding.get("lock_version")) != attestation.lock_version:
        mismatches.append("lock_version")
    if binding.get("response_bundle_hash") != attestation.response_bundle_hash:
        mismatches.append("response_bundle_hash")
    if binding.get("map_record_count") != attestation.map_record_count:
        mismatches.append("map_record_count")
    if mismatches:
        raise AtlasIdentityMapBindingError(
            f"universe lock identity_map_binding disagrees with the verified identity map: "
            f"{', '.join(mismatches)}",
            code="IDENTITY_MAP_MISMATCH", check_id="IM6",
        )


# ---------------------------------------------------------------------------
# Orchestrated precondition chain (V1-V7) and the public wrapper.
# ---------------------------------------------------------------------------


def _run_preconditions(
    inputs: SelectionInputs,
) -> tuple[PreconditionReport, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], DiseasePack, RawIdentityMapper]:
    protocol_text, protocol_doc_hash = _load_protocol_doc(inputs.protocol_path)
    registration = load_selection_registration(inputs.registration_path)
    verified_registration_hash = verify_registration(
        registration, protocol_text=protocol_text, protocol_doc_hash=protocol_doc_hash,
    )
    _verify_search_parameters(registration)

    pack = load_disease_pack(str(inputs.pack_path))
    universe = load_candidate_universe(inputs.universe_path)
    verify_pack_binding(registration, universe, pack)

    raw_manifest = _load_raw_inventory(inputs.raw_inventory_path)
    raw_hash, raw_bytes_len = _raw_inventory_file_digest(inputs.raw_inventory_path)
    raw_record_count = len(raw_manifest.get("rows") or ())

    # K1/K2/K4/K6: resolve and self/pack/sibling-verify the universe lock.
    # K3 (the cross-check against the freshly verified universe/raw/ledger
    # content) and V6/U1-U6 (conservation) are both deferred until AFTER V7
    # (identity-map) per PS-V-005 -- a missing/corrupt identity map must be
    # reported even when the universe lock or ledger is simultaneously
    # broken.
    lock_path, lock = resolve_active_lock(registration, repo_root=inputs.repo_root)
    verified_lock_hash = verify_universe_lock(
        lock, lock_path=lock_path, registration=registration, universe=universe, pack=pack,
        run_started_at=inputs.run_started_at,
    )
    delta = build_lock_delta(
        lock,
        registration,
        verified_protocol_doc_hash=protocol_doc_hash,
        verified_registration_content_hash=verified_registration_hash,
    )

    map_lock_relative = ((registration.get("identity_map_contract") or {}).get("active") or {}).get("path")
    map_lock_path = _repo_relative_path(inputs.repo_root, map_lock_relative, what="identity map lock")
    identity_map_active = (registration.get("identity_map_contract") or {}).get("active") or {}

    attestation = verify_identity_map(
        map_path=inputs.identity_map_path,
        lock_path=map_lock_path,
        response_root=inputs.identity_map_response_root,
        pack=pack,
        raw_inventory_path=inputs.raw_inventory_path,
        registration_active=identity_map_active,
    )
    _verify_identity_map_binding_on_universe_lock(lock, attestation)

    # V6/U1-U6: full conservation semantics, run only after V7 has verified
    # clean.
    ledger_hash, ledger_row_count = verify_conservation(
        universe, raw_manifest=raw_manifest, raw_hash=raw_hash, raw_bytes_len=raw_bytes_len,
    )
    commitment = universe.get("discovery_set_commitment") or {}
    discovery_count = commitment.get("discovery_set_count")
    discovery_hash = commitment.get("discovery_set_hash")

    # K3: deferred cross-check, now that both the universe's own conservation
    # and the identity map have independently verified clean.
    _verify_lock_conservation_binding(
        lock,
        universe=universe,
        raw_hash=raw_hash,
        raw_record_count=raw_record_count,
        ledger_hash=ledger_hash,
        ledger_row_count=ledger_row_count,
        discovery_count=discovery_count,
        discovery_hash=discovery_hash,
    )

    active_universe_lock = (
        (registration.get("candidate_universe_contract") or {}).get("universe_lock") or {}
    ).get("active") or {}

    checks_passed = EXECUTION_ORDER + ("K1", "K2", "K3", "K4", "K5", "K6", "IM1", "IM2", "IM3", "IM4", "IM5", "IM6")

    report = PreconditionReport(
        verified_protocol_doc_hash=protocol_doc_hash,
        verified_registration_content_hash=verified_registration_hash,
        verified_live_pack_content_hash=pack.pack_content_hash,
        active_universe_lock=active_universe_lock,
        verified_lock_content_hash=verified_lock_hash,
        verified_universe_content_hash=universe.get("universe_content_hash"),
        verified_raw_inventory_hash=raw_hash,
        verified_raw_inventory_record_count=raw_record_count,
        verified_normalization_ledger_hash=ledger_hash,
        verified_normalization_ledger_row_count=ledger_row_count,
        verified_discovery_set_hash=discovery_hash,
        verified_discovery_set_count=discovery_count,
        lock_protocol_version_delta=delta,
        identity_map=attestation,
        checks_passed=checks_passed,
    )
    return report, registration, universe, raw_manifest, pack, attestation.mapper


def verify_preconditions(inputs: SelectionInputs) -> PreconditionReport:
    """Run the complete V1-V7 precondition chain and return the resulting
    attestation. Raises the first :class:`~raptor.atlas.model.AtlasPanelError`
    encountered; never returns a partial report."""

    report, *_ = _run_preconditions(inputs)
    return report


# ---------------------------------------------------------------------------
# RP1-RP7: independent normalization replay.
# ---------------------------------------------------------------------------


def replay_normalization(
    universe: Mapping[str, Any], *, raw_manifest: Mapping[str, Any], mapper: RawIdentityMapper,
) -> NormalizationReplay:
    raw_rows = list(raw_manifest.get("rows") or ())
    ledger_by_id = {row.get("raw_record_id"): row for row in (universe.get("normalization_ledger") or ())}
    records_by_universe_key = {record.get("universe_key"): record for record in (universe.get("records") or ())}

    outcome_counts: dict[str, int] = {}
    unresolved_confirmed = 0
    for raw_row in raw_rows:
        raw_record_id = raw_row.get("raw_record_id")
        replay = mapper.replay(
            raw_record_id, raw_row.get("raw_identity_string"), raw_row.get("source_reported_consequence_hint"),
        )
        outcome_counts[replay.normalization_outcome] = outcome_counts.get(replay.normalization_outcome, 0) + 1

        ledger_row = ledger_by_id.get(raw_record_id)
        if ledger_row is None:
            raise AtlasUniverseContractError(
                f"raw record {raw_record_id!r} has no normalization_ledger row", code="UNIVERSE_CONTRACT_BREACH", check_id="RP1",
            )
        if replay.normalization_outcome != ledger_row.get("normalization_outcome"):
            raise AtlasUniverseContractError(
                f"raw record {raw_record_id!r} normalization_outcome disagrees with the verified replay",
                code="UNIVERSE_CONTRACT_BREACH", check_id="RP1",
            )

        universe_key_value = ledger_row.get("universe_key")
        if replay.identity_state == "unresolved":
            unresolved_confirmed += 1
            if replay.universe_key != universe_key_value:
                raise AtlasUniverseContractError(
                    f"raw record {raw_record_id!r} unresolved universe_key does not match the recomputed "
                    "surrogate",
                    code="UNIVERSE_CONTRACT_BREACH", check_id="RP2",
                )

        record = records_by_universe_key.get(universe_key_value)
        if record is None:
            raise AtlasUniverseContractError(
                f"universe_key {universe_key_value!r} for raw record {raw_record_id!r} has no matching "
                "candidate universe record",
                code="UNIVERSE_CONTRACT_BREACH", check_id="RP2",
            )
        if replay.identity_state != record.get("identity_state"):
            raise AtlasUniverseContractError(
                f"raw record {raw_record_id!r} identity_state disagrees between the candidate universe "
                "and the verified replay",
                code="UNIVERSE_CONTRACT_BREACH", check_id="RP3",
            )
        for field in ("spdi_canonical", "hgvs_c", "hgvs_p", "transcript_pin", "residue_index", "codon_index"):
            if getattr(replay, field) != record.get(field):
                raise AtlasUniverseContractError(
                    f"raw record {raw_record_id!r} field {field!r} disagrees between the candidate "
                    "universe and the verified replay",
                    code="UNIVERSE_CONTRACT_BREACH", check_id="RP4",
                )
        if replay.consequence_class != record.get("consequence_class"):
            raise AtlasUniverseContractError(
                f"raw record {raw_record_id!r} consequence_class disagrees between the candidate universe "
                "and the verified replay",
                code="UNIVERSE_CONTRACT_BREACH", check_id="RP5",
            )
        expected_flags = [replay.exclusion_code] if replay.exclusion_code else []
        if list(record.get("exclusion_flags") or ()) != expected_flags:
            raise AtlasUniverseContractError(
                f"raw record {raw_record_id!r} exclusion_flags disagrees with the verified replay's "
                "exclusion_code",
                code="UNIVERSE_CONTRACT_BREACH", check_id="RP6",
            )

    return NormalizationReplay(
        replayed_row_count=len(raw_rows),
        outcome_counts=outcome_counts,
        unresolved_confirmed_count=unresolved_confirmed,
        checks_passed=("RP1", "RP2", "RP3", "RP4", "RP5", "RP6", "RP7"),
    )


# ---------------------------------------------------------------------------
# Lineage / strata / support-class recomputation (Section 15-16). Never
# reads the declared spec_stratum, spec_stratum_basis, access_status,
# license_family, or span_verifiable "firewall" fields.
# ---------------------------------------------------------------------------


def _context_key(observation: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        observation.get("assay_kind"),
        observation.get("model_system"),
        observation.get("cell_or_tissue"),
        observation.get("zygosity_context"),
    )


def _matched_strata_set(functional_evidence_present: bool, observations: Sequence[Mapping[str, Any]]) -> set[str]:
    matched: set[str] = set()
    if not functional_evidence_present:
        matched.add("S6")
    buckets = {o.get("reported_outcome_bucket") for o in observations}
    if len(observations) >= 2:
        for left, right in itertools.combinations(observations, 2):
            if left.get("reported_outcome_bucket") == right.get("reported_outcome_bucket"):
                continue
            if _context_key(left) == _context_key(right):
                matched.add("S4")
            else:
                matched.add("S5")
    if len(observations) >= 1:
        if "intermediate_deviation" in buckets:
            matched.add("S2")
        if "near_reference" in buckets:
            matched.add("S3")
        if "substantial_deviation" in buckets:
            matched.add("S1")
    return matched


def recompute_all_matched_strata(record: Mapping[str, Any], *, omega: tuple[str, ...] = OMEGA) -> tuple[str, ...]:
    """S1-S6 stratum recomputation from raw observation primitives only.
    Deliberately takes the whole ``record`` mapping (not individual
    keyword parameters) so that declared audit-only fields such as
    ``spec_stratum``/``spec_stratum_basis``/``access_status``/
    ``license_family``/``span_verifiable`` are structurally unreachable --
    only ``functional_evidence_present`` and ``observations`` are read."""

    matched = _matched_strata_set(
        bool(record.get("functional_evidence_present")), list(record.get("observations") or ()),
    )
    return tuple(s for s in omega if s in matched)


def recompute_primary_stratum(strata: Iterable[str]) -> str:
    """The Omega-first pick over an already-matched stratum set."""

    matched = set(strata)
    for stratum in OMEGA:
        if stratum in matched:
            return stratum
    return "S6"


def _lineage_edges(observations: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []
    for i, j in itertools.combinations(range(len(observations)), 2):
        left, right = observations[i], observations[j]
        linked = False
        if left.get("dataset_accession") and left.get("dataset_accession") == right.get("dataset_accession"):
            linked = True
        left_sources = set(left.get("source_identifiers") or ())
        right_sources = set(right.get("source_identifiers") or ())
        if left.get("version_of") in right_sources or right.get("version_of") in left_sources:
            linked = True
        if (
            left.get("experimental_program_id") not in (None, "unknown")
            and left.get("experimental_program_id") == right.get("experimental_program_id")
        ):
            linked = True
        if (
            left.get("lab_lineage_key") not in (None, "unknown")
            and left.get("lab_lineage_key") == right.get("lab_lineage_key")
            and left.get("assay_protocol_lineage_key") not in (None, "unknown")
            and left.get("assay_protocol_lineage_key") == right.get("assay_protocol_lineage_key")
        ):
            linked = True
        if right.get("observation_id") in (left.get("derived_from_observation_ids") or ()):
            linked = True
        if left.get("observation_id") in (right.get("derived_from_observation_ids") or ()):
            linked = True
        if left_sources & right_sources:
            linked = True
        if linked:
            edges.append((i, j))
    return edges


def _lineage_components(observations: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    parent = list(range(len(observations)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in _lineage_edges(observations):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[int]] = {}
    for index in range(len(observations)):
        groups.setdefault(find(index), []).append(index)
    return [sorted(members) for _, members in sorted(groups.items())]


def _observation_unknown(observation: Mapping[str, Any]) -> bool:
    return observation.get("lab_lineage_key") == "unknown" or observation.get("assay_protocol_lineage_key") == "unknown"


def _lineage_index_map(all_observations: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for component in _lineage_components(all_observations):
        members = [all_observations[i] for i in component]
        established = not any(_observation_unknown(o) for o in members)
        if established:
            identifiers: set[str] = set()
            for member in members:
                identifiers.update(member.get("source_identifiers") or ())
            key = _lineage_group_key(identifiers)
        else:
            key = "LG:UNKNOWN-POOL"
        for member in members:
            mapping[member.get("observation_id")] = key
    return mapping


def recompute_lineage_index(universe: Mapping[str, Any]) -> LineageIndex:
    """Recompute the L1-L6 source-lineage grouping over every observation
    in the candidate universe. Unknown lineage is always pooled into the
    single ``"LG:UNKNOWN-POOL"`` group."""

    records = list(universe.get("records") or ())
    all_observations = [obs for record in records for obs in (record.get("observations") or ())]
    index = _lineage_index_map(all_observations)
    confidence = {
        group: ("unknown" if group == "LG:UNKNOWN-POOL" else "established")
        for group in sorted(set(index.values()))
    }
    unknown_observation_count = sum(1 for group in index.values() if group == "LG:UNKNOWN-POOL")
    unknown_record_count = 0
    for record in records:
        obs_ids = [obs.get("observation_id") for obs in (record.get("observations") or ())]
        if obs_ids and any(index.get(obs_id) == "LG:UNKNOWN-POOL" for obs_id in obs_ids):
            unknown_record_count += 1
    return LineageIndex(
        group_of_observation=index,
        group_confidence=confidence,
        unknown_observation_count=unknown_observation_count,
        unknown_record_count=unknown_record_count,
    )


def _record_groups(record: Mapping[str, Any], index: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(sorted({index[obs.get("observation_id")] for obs in (record.get("observations") or ())}))


def _support_class(record: Mapping[str, Any], index: Mapping[str, str]) -> str:
    observations = list(record.get("observations") or ())
    if not record.get("functional_evidence_present"):
        return "evidence_absent"
    if not any(o.get("access_status") == "open_lawful" and o.get("span_verifiable") for o in observations):
        return "access_blocked"
    groups = _record_groups(record, index)
    established = tuple(g for g in groups if g != "LG:UNKNOWN-POOL")
    if len(established) >= 2:
        return "multi_independent"
    if observations and all(o.get("throughput_class") == "high_throughput" for o in observations):
        return "single_high_throughput_only"
    return "single_low_throughput"


def recompute_support_class(record: Mapping[str, Any], *, lineage: LineageIndex) -> str:
    """Public wrapper: Section 14.1 support-class classification computed
    from primitives alone, given a full :class:`LineageIndex`."""

    return _support_class(record, lineage.group_of_observation)


def _crosswalk_base(spec_stratum: Optional[str], primary_stratum: Optional[str]) -> str:
    pair = (spec_stratum, primary_stratum)
    if pair in _CROSSWALK_CONTRADICTORY:
        return "contradictory"
    if pair in _CROSSWALK_DISCORDANT:
        return "discordant"
    return "permitted"


def crosswalk_cell(spec_stratum: Optional[str], primary_stratum: Optional[str], spec_stratum_derivation: Optional[str]) -> str:
    """Pure, non-raising 3-argument crosswalk classifier (Section 14). A
    ``"contradictory"`` base result MAY be softened to ``"permitted"`` when
    the spec stratum derives from an external label rather than a
    recomputation from locked observations; the underlying fatal-vs-report
    -only gating for ``select_panel`` lives in :func:`_record_crosswalk`."""

    base = _crosswalk_base(spec_stratum, primary_stratum)
    if base == "contradictory" and spec_stratum_derivation == "external_label":
        return "permitted"
    return base


# ---------------------------------------------------------------------------
# E1-E8: per-record eligibility.
# ---------------------------------------------------------------------------


def evaluate_eligibility(
    record: Mapping[str, Any], *, universe: Mapping[str, Any], lineage: LineageIndex, anchor: AnchorSpec, pack: DiseasePack,
) -> tuple[bool, Optional[str], str]:
    """E1-E8 in the frozen priority order E1, E6, E2, E3, E7, E4, E5, E8.
    Returns ``(eligible, exclusion_code, rule_id)``; ``exclusion_code`` is
    ``None`` and ``rule_id`` is ``"ELIGIBLE"`` for an eligible record."""

    observations = list(record.get("observations") or ())
    functional_evidence_present = bool(record.get("functional_evidence_present"))

    if record.get("identity_state") != "resolved":
        return False, "X1", "E1"

    # E6 checks that primary_stratum recomputes to exactly one of the six
    # strata. The S1-S6 recomputation always yields a value (S6 is the
    # catch-all when nothing else matches -- see recompute_primary_stratum),
    # so the only way it can fail to "recompute" at all is a record that
    # claims functional evidence is present yet carries zero observations
    # to derive that evidence from; a real (if unclassifiable) observation
    # still legitimately recomputes to S6 and remains eligible.
    if functional_evidence_present and not observations:
        return False, "X7", "E6"

    if record.get("consequence_class") == "nonsense_substitution":
        return False, "X2", "E2"

    if record.get("residue_index") is not None and record.get("residue_index") == anchor.residue_index:
        return False, "X3", "E3"

    if record.get("hgvs_p") is None:
        return False, "X6", "E7"

    if functional_evidence_present and _support_class(record, lineage.group_of_observation) == "access_blocked":
        return False, "X5", "E4"

    forbidden = set(pack.prohibitions.get("non_public_license_families") or ())
    if any(o.get("license_family") in forbidden for o in observations):
        return False, "X9", "E5"

    if tuple(record.get("exclusion_flags") or ()):
        return False, "X8", "E8"

    return True, None, "ELIGIBLE"


# ---------------------------------------------------------------------------
# Section 17: relaxation-ladder constraint checking, allocation enumeration,
# and the exhaustive attempt schedule.
# ---------------------------------------------------------------------------


def _eval_threshold(value: Any, n: int) -> int:
    if isinstance(value, bool):
        raise AtlasPanelRegistrationError(
            f"constraint value {value!r} is boolean, not a numeric threshold", code="INPUT_FAULT",
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = _FORMULA_RE.match(value.replace(" ", ""))
        if match:
            coefficient = int(match.group(1)) if match.group(1) else 1
            denominator = int(match.group(2)) if match.group(2) else 1
            return math.ceil(coefficient * n / denominator)
    raise AtlasPanelRegistrationError(f"unrecognized constraint formula {value!r}", code="INPUT_FAULT")


def _constraint_base(registration: Mapping[str, Any], name: str) -> Any:
    for prefix, group in _CONSTRAINT_GROUPS:
        if name.startswith(prefix):
            return ((registration.get("constraints") or {}).get(group) or {}).get(name)
    raise AtlasPanelRegistrationError(f"unrecognized constraint family for {name!r}", code="INPUT_FAULT")


def _constraint_at_rung(registration: Mapping[str, Any], name: str, rung: int, *, n: int) -> int:
    value = _constraint_base(registration, name)
    ladder = registration.get("relaxation_ladder") or ()
    for position, step in enumerate(ladder, start=1):
        if position <= rung and step.get("constraint") == name:
            value = step.get("after")
    return _eval_threshold(value, n)


def _ceil_half(n: int) -> int:
    return -(-n // 2)


def enumerate_allocations(
    n: int, *, nonempty_strata: Iterable[str], pool_sizes: Mapping[str, int],
) -> list[tuple[int, ...]]:
    """Section 17.5: enumerate every per-stratum allocation vector summing
    to ``n``, ordered Omega-first, capped at ``min(ceil(n/2), pool_size)``
    per stratum (the fixed combinatorial cap, independent of the
    registration-configurable C3 threshold used during leaf-level
    constraint checking), returned in balance-first order."""

    ordered = [s for s in OMEGA if s in set(nonempty_strata)]
    half = _ceil_half(n)
    caps = [min(half, pool_sizes[s]) for s in ordered]
    vectors = [
        vector
        for vector in itertools.product(*[range(1, cap + 1) for cap in caps])
        if sum(vector) == n
    ]
    return sorted(vectors, key=lambda v: (max(v), v))


def _check_constraints(
    panel: Sequence[Mapping[str, Any]],
    *,
    n: int,
    nonempty_strata: Sequence[str],
    spec_values: Sequence[str],
    index: Mapping[str, str],
    level: str,
    pool: Sequence[Mapping[str, Any]],
    registration: Mapping[str, Any],
) -> bool:
    if len(panel) != n:
        return False
    rung = LEVELS.index(level)
    primaries = [record.get("primary_stratum") for record in panel]

    if set(nonempty_strata) - set(primaries):
        return False  # C1
    if "S6" in nonempty_strata and "S6" not in primaries:
        return False  # C2

    c3_cap = _constraint_at_rung(registration, "C3", rung, n=n)
    if any(primaries.count(stratum) > c3_cap for stratum in set(primaries)):
        return False  # C3

    if rung < 1:
        if set(spec_values) - {record.get("spec_stratum") for record in panel}:
            return False  # C5 (report-only from R1 onward)

    residues = [record.get("residue_index") for record in panel]
    if len(set(residues)) != len(residues):
        return False  # C4 residue collision
    codons = [(record.get("transcript_pin"), record.get("codon_index")) for record in panel]
    if len(set(codons)) != len(codons):
        return False  # C4 codon collision

    per_record_assays = [{o.get("assay_kind") for o in (record.get("observations") or ())} for record in panel]
    distinct_assays: set[str] = set().union(*per_record_assays) if per_record_assays else set()
    d1_min = _constraint_at_rung(registration, "D1", rung, n=n)
    if len(distinct_assays) < d1_min:
        return False  # D1

    per_record_models = [{o.get("model_system") for o in (record.get("observations") or ())} for record in panel]
    distinct_models: set[str] = set().union(*per_record_models) if per_record_models else set()
    d2_min = _constraint_at_rung(registration, "D2", rung, n=n)
    if len(distinct_models) < d2_min:
        return False  # D2

    d3_cap = _constraint_at_rung(registration, "D3", rung, n=n)
    for assay in distinct_assays:
        if sum(1 for kinds in per_record_assays if assay in kinds) > d3_cap:
            return False  # D3

    pool_has_multi_assay = any(
        len({o.get("assay_kind") for o in (record.get("observations") or ())}) >= 2 for record in pool
    )
    if pool_has_multi_assay:
        if not any(len(kinds) >= 2 for kinds in per_record_assays):
            return False  # D4

    sole_support: dict[str, int] = {}
    for record in panel:
        groups = _record_groups(record, index)
        if len(groups) == 1:
            sole_support[groups[0]] = sole_support.get(groups[0], 0) + 1
    p1_cap = _constraint_at_rung(registration, "P1", rung, n=n)
    if any(count > p1_cap for count in sole_support.values()):
        return False  # P1

    established_groups: set[str] = set()
    for record in panel:
        established_groups.update(g for g in _record_groups(record, index) if g != "LG:UNKNOWN-POOL")
    p2_min = _constraint_at_rung(registration, "P2", rung, n=n)
    if len(established_groups) < p2_min:
        return False  # P2

    p3_cap = _constraint_at_rung(registration, "P3", rung, n=n)
    if sum(1 for record in panel if _support_class(record, index) == "single_high_throughput_only") > p3_cap:
        return False  # P3

    return True


def _run_attempt(
    pool: Sequence[Mapping[str, Any]],
    *,
    n: int,
    level: str,
    nonempty_strata: Sequence[str],
    spec_values: Sequence[str],
    pool_by_stratum: Mapping[str, Sequence[Mapping[str, Any]]],
    index: Mapping[str, str],
    node_budget: int,
    registration: Mapping[str, Any],
) -> AttemptOutcome:
    ordered_strata = [s for s in OMEGA if s in set(nonempty_strata)]
    pool_sizes = {s: len(pool_by_stratum[s]) for s in ordered_strata}
    nodes_expanded = 0

    for vector in enumerate_allocations(n, nonempty_strata=nonempty_strata, pool_sizes=pool_sizes):
        per_stratum_subsets = [
            itertools.combinations(pool_by_stratum[stratum], count) for stratum, count in zip(ordered_strata, vector)
        ]
        for combo_parts in itertools.product(*per_stratum_subsets):
            if nodes_expanded >= node_budget:
                return AttemptOutcome(level=level, n=n, status="UNDETERMINED", nodes_expanded=node_budget, solution=None)
            nodes_expanded += 1
            candidate = [record for part in combo_parts for record in part]
            if _check_constraints(
                candidate, n=n, nonempty_strata=nonempty_strata, spec_values=spec_values, index=index,
                level=level, pool=pool, registration=registration,
            ):
                solution = tuple(sorted(record.get("record_id") for record in candidate))
                return AttemptOutcome(level=level, n=n, status="SOLUTION", nodes_expanded=nodes_expanded, solution=solution)

    return AttemptOutcome(level=level, n=n, status="INFEASIBLE_COMPLETE", nodes_expanded=nodes_expanded, solution=None)


def _resolve_node_budget(registration: Mapping[str, Any], override: Optional[int]) -> int:
    base = (registration.get("search_parameters") or {}).get("search_node_budget")
    if override is None:
        return base
    if not isinstance(override, int) or isinstance(override, bool) or override <= 0:
        raise AtlasPanelInputError(
            f"node_budget_override must be a positive integer, got {override!r}", code="INPUT_FAULT",
        )
    if base is not None and override > base:
        raise AtlasPanelInputError(
            f"node_budget_override {override} may not exceed the registration's search_node_budget {base}; "
            "the override may only lower the budget",
            code="INPUT_FAULT",
        )
    return override


def _panel_size_bounds(registration: Mapping[str, Any]) -> tuple[int, int]:
    rule = registration.get("panel_size_rule") or {}
    panel_min = rule.get("min", rule.get("minimum"))
    panel_max = rule.get("max", rule.get("maximum"))
    return int(panel_min), int(panel_max)


# ---------------------------------------------------------------------------
# Section 18: disposition classification and flags.
# ---------------------------------------------------------------------------


def _enrich_record(record: Mapping[str, Any], index: Mapping[str, str]) -> dict:
    observations = list(record.get("observations") or ())
    functional_evidence_present = bool(record.get("functional_evidence_present"))
    expected_evidence_present = bool(observations)
    if functional_evidence_present != expected_evidence_present:
        raise AtlasUniverseContractError(
            f"record {record.get('record_id')!r} declared functional_evidence_present "
            f"{functional_evidence_present!r} disagrees with its recomputed observation presence",
            code="UNIVERSE_CONTRACT_BREACH", check_id="S-FIREWALL",
        )
    matched = _matched_strata_set(functional_evidence_present, observations)
    primary = recompute_primary_stratum(matched)
    declared_primary = record.get("primary_stratum")
    if declared_primary is not None and declared_primary != primary:
        raise AtlasUniverseContractError(
            f"record {record.get('record_id')!r} declared primary_stratum {declared_primary!r} disagrees "
            f"with the recomputed value {primary!r}",
            code="UNIVERSE_CONTRACT_BREACH", check_id="S-FIREWALL",
        )
    recomputed_groups = _record_groups(record, index)
    declared_groups = record.get("support_source_groups")
    if declared_groups is not None and set(declared_groups) != set(recomputed_groups):
        raise AtlasUniverseContractError(
            f"record {record.get('record_id')!r} declared support_source_groups {declared_groups!r} "
            f"disagrees with the recomputed value {recomputed_groups!r}",
            code="UNIVERSE_CONTRACT_BREACH", check_id="S-FIREWALL",
        )
    recomputed_support_class = _support_class(record, index)
    declared_support_class = record.get("support_class")
    if declared_support_class is not None and declared_support_class != recomputed_support_class:
        raise AtlasUniverseContractError(
            f"record {record.get('record_id')!r} declared support_class {declared_support_class!r} "
            f"disagrees with the recomputed value {recomputed_support_class!r}",
            code="UNIVERSE_CONTRACT_BREACH", check_id="S-FIREWALL",
        )

    enriched = dict(record)
    enriched["all_matched_strata"] = tuple(s for s in OMEGA if s in matched)
    enriched["primary_stratum"] = primary
    enriched["support_class"] = recomputed_support_class
    enriched["source_group_keys"] = recomputed_groups
    return enriched


def _record_crosswalk(enriched: Mapping[str, Any]) -> tuple[bool, bool]:
    """Applies the derivation-conditional fatal-vs-report-only gating for
    a spec_stratum/primary_stratum crosswalk cell. Returns
    ``(label_function_discordant, stale_label_discordant)``; raises
    :class:`AtlasUniverseContractError` on a fatal breach."""

    spec_stratum = enriched.get("spec_stratum")
    primary_stratum = enriched.get("primary_stratum")
    derivation = enriched.get("spec_stratum_derivation")
    base = _crosswalk_base(spec_stratum, primary_stratum)

    if base == "contradictory" and derivation == "recomputed_from_locked_observations":
        raise AtlasUniverseContractError(
            f"record {enriched.get('record_id')!r} spec_stratum {spec_stratum!r} contradicts its "
            f"recomputed functional stratum {primary_stratum!r}",
            code="UNIVERSE_CONTRACT_BREACH", check_id="E-CROSSWALK",
        )
    label_function_discordant = base == "discordant" and derivation == "recomputed_from_locked_observations"
    stale_label_discordant = base in ("contradictory", "discordant") and derivation != "recomputed_from_locked_observations"
    return label_function_discordant, stale_label_discordant


def _classify_unselected(record: Mapping[str, Any], selected: Sequence[Mapping[str, Any]]) -> str:
    residue = record.get("residue_index")
    transcript_codon = (record.get("transcript_pin"), record.get("codon_index"))
    for selected_record in selected:
        if residue is not None and residue == selected_record.get("residue_index"):
            return "NS_COLLISION_RESIDUE"
        if record.get("transcript_pin") is not None and transcript_codon == (
            selected_record.get("transcript_pin"), selected_record.get("codon_index"),
        ):
            return "NS_COLLISION_CODON"
    return "NS_NOT_IN_SOLUTION"


def _build_dispositions(
    universe: Mapping[str, Any],
    *,
    lineage: LineageIndex,
    anchor: AnchorSpec,
    pack: DiseasePack,
    selection_seed: str,
    selected_ids: Sequence[str],
) -> tuple[RecordDisposition, ...]:
    index = lineage.group_of_observation
    selected_set = set(selected_ids)
    selected_enriched: list[dict] = []
    rows: list[RecordDisposition] = []

    enriched_by_id: dict[str, dict] = {}
    for record in universe.get("records") or ():
        enriched = _enrich_record(record, index)
        enriched_by_id[enriched.get("record_id")] = enriched
        _record_crosswalk(enriched)
        if enriched.get("record_id") in selected_set:
            selected_enriched.append(enriched)

    for record in universe.get("records") or ():
        enriched = enriched_by_id[record.get("record_id")]
        record_id = enriched.get("record_id")
        spdi = enriched.get("spdi_canonical")
        draw_key_value = draw_key(spdi, selection_seed=selection_seed) if spdi else None
        label_function_discordant, stale_label_discordant = _record_crosswalk(enriched)

        if record_id in selected_set:
            disposition = "SEL"
            rule_id = "ELIGIBLE"
            allocation_slot = enriched.get("primary_stratum")
        else:
            eligible, code, rule_id = evaluate_eligibility(
                record, universe=universe, lineage=lineage, anchor=anchor, pack=pack,
            )
            allocation_slot = None
            if not eligible:
                disposition = code
            else:
                disposition = _classify_unselected(enriched, selected_enriched)

        rows.append(
            RecordDisposition(
                record_id=record_id,
                universe_key=enriched.get("universe_key"),
                identity_state=enriched.get("identity_state"),
                all_matched_strata=enriched.get("all_matched_strata"),
                primary_stratum=enriched.get("primary_stratum"),
                spec_stratum=enriched.get("spec_stratum"),
                spec_stratum_derivation=enriched.get("spec_stratum_derivation"),
                support_class=enriched.get("support_class"),
                source_group_keys=enriched.get("source_group_keys"),
                draw_key=draw_key_value,
                disposition=disposition,
                rule_id=rule_id,
                allocation_slot=allocation_slot,
                label_function_discordant=label_function_discordant,
                stale_label_discordant=stale_label_discordant,
            )
        )
    return tuple(rows)


def _build_flags(
    *,
    dispositions: Sequence[RecordDisposition],
    terminal_outcome: str,
    applied_relaxation_steps: Sequence[str],
    independence_status: str,
    lineage: LineageIndex,
    nonempty_strata: Sequence[str],
) -> dict:
    unresolved_identity_count = sum(1 for row in dispositions if row.identity_state == "unresolved")
    x5_present = any(row.disposition == "X5" for row in dispositions)
    return {
        "independence_status": independence_status,
        "spec_taxonomy_coverage": "PARTIAL" if applied_relaxation_steps else "COMPLETE",
        "ABSTENTION_CONTROL_MISSING": "S6" not in nonempty_strata,
        "UNDETERMINED_SEARCH_INCOMPLETE": terminal_outcome == "UNDETERMINED_SEARCH_INCOMPLETE",
        "INFEASIBLE_PANEL": terminal_outcome == "INFEASIBLE_PANEL",
        "label_function_discordant": any(row.label_function_discordant for row in dispositions),
        "stale_label_discordant": any(row.stale_label_discordant for row in dispositions),
        "unresolved_identity_count": unresolved_identity_count,
        "x5_attrition_present": x5_present,
        "lineage_unknown_observation_count": lineage.unknown_observation_count,
        "lineage_unknown_record_count": lineage.unknown_record_count,
    }


# ---------------------------------------------------------------------------
# Orchestration: select_panel and render_run_record.
# ---------------------------------------------------------------------------


def select_panel(inputs: SelectionInputs) -> SelectionRun:
    """Run the complete Atlas Phase-2 contrast-panel selection pipeline
    (V1-V7 preconditions, RP1-RP7 replay, lineage/strata recomputation,
    E1-E8 eligibility, the Section 17 exhaustive relaxation-ladder search,
    and Section 18 disposition classification), returning a single pure
    :class:`~raptor.atlas.model.SelectionRun`. Nothing is written to disk
    or mutated."""

    report, registration, universe, raw_manifest, pack, mapper = _run_preconditions(inputs)
    replay = replay_normalization(universe, raw_manifest=raw_manifest, mapper=mapper)

    lineage = recompute_lineage_index(universe)
    selection_seed = registration.get("selection_seed")
    records = list(universe.get("records") or ())
    index = lineage.group_of_observation

    # Firewall + crosswalk breach checks run over every record up front, so
    # a contract breach anywhere aborts the whole run before any search.
    enriched_by_id: dict[str, dict] = {}
    for record in records:
        enriched = _enrich_record(record, index)
        enriched_by_id[enriched.get("record_id")] = enriched
        _record_crosswalk(enriched)

    eligible_pool: list[dict] = []
    for record in records:
        eligible, _code, _rule_id = evaluate_eligibility(
            record, universe=universe, lineage=lineage, anchor=inputs.anchor, pack=pack,
        )
        if eligible:
            eligible_pool.append(enriched_by_id[record.get("record_id")])
    eligible_pool.sort(key=lambda r: (draw_key(r.get("spdi_canonical"), selection_seed=selection_seed), r.get("spdi_canonical")))

    nonempty_strata = tuple(s for s in OMEGA if s in {r.get("primary_stratum") for r in eligible_pool})
    spec_values = tuple(sorted({r.get("spec_stratum") for r in eligible_pool}))
    pool_by_stratum = {s: [r for r in eligible_pool if r.get("primary_stratum") == s] for s in nonempty_strata}

    panel_min, panel_max = _panel_size_bounds(registration)
    k = len(nonempty_strata)
    n_target = max(panel_min, min(panel_max, k + 2))
    node_budget = _resolve_node_budget(registration, inputs.node_budget_override)

    attempts: list[AttemptOutcome] = []
    winning: Optional[AttemptOutcome] = None
    for level in LEVELS:
        for n in range(n_target, panel_min - 1, -1):
            outcome = _run_attempt(
                eligible_pool,
                n=n,
                level=level,
                nonempty_strata=nonempty_strata,
                spec_values=spec_values,
                pool_by_stratum=pool_by_stratum,
                index=index,
                node_budget=node_budget,
                registration=registration,
            )
            attempts.append(outcome)
            if outcome.status in ("SOLUTION", "UNDETERMINED"):
                winning = outcome
                break
        if winning is not None:
            break

    if winning is not None and winning.status == "SOLUTION":
        terminal_outcome = "PANEL_SELECTED"
        selected_ids = winning.solution or ()
        n_selected: Optional[int] = winning.n
        rung = LEVELS.index(winning.level)
        applied_relaxation_steps = LEVELS[1 : rung + 1]
    elif winning is not None and winning.status == "UNDETERMINED":
        terminal_outcome = "UNDETERMINED_SEARCH_INCOMPLETE"
        selected_ids = ()
        n_selected = None
        applied_relaxation_steps = ()
    else:
        terminal_outcome = "INFEASIBLE_PANEL"
        selected_ids = ()
        n_selected = None
        applied_relaxation_steps = ()

    independence_status = "RELAXED" if applied_relaxation_steps else "DECLARED"

    dispositions = _build_dispositions(
        universe, lineage=lineage, anchor=inputs.anchor, pack=pack, selection_seed=selection_seed, selected_ids=selected_ids,
    )
    flags = _build_flags(
        dispositions=dispositions,
        terminal_outcome=terminal_outcome,
        applied_relaxation_steps=applied_relaxation_steps,
        independence_status=independence_status,
        lineage=lineage,
        nonempty_strata=nonempty_strata,
    )

    return SelectionRun(
        terminal_outcome=terminal_outcome,
        preconditions=report,
        replay=replay,
        n_target=n_target,
        n_selected=n_selected,
        selected_record_ids=tuple(sorted(selected_ids)),
        attempts=tuple(attempts),
        applied_relaxation_steps=applied_relaxation_steps,
        independence_status=independence_status,
        dispositions=dispositions,
        flags=MappingProxyType(flags),
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, (dict, MappingProxyType)):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def render_run_record(run: SelectionRun, *, inputs: SelectionInputs) -> dict:
    """Render a complete, JSON-safe run record for ``run``. Every
    :class:`~raptor.atlas.model.PreconditionReport` field name appears as a
    key of ``verified_digests``; ``lock_protocol_version_delta`` is always
    rendered as a fully populated mapping."""

    report = run.preconditions
    delta = report.lock_protocol_version_delta
    attestation = report.identity_map

    identity_map_dict = {
        "lock_path": str(attestation.lock_path),
        "lock_version": attestation.lock_version,
        "map_version": attestation.map_version,
        "lock_content_hash": attestation.lock_content_hash,
        "map_content_hash": attestation.map_content_hash,
        "map_record_count": attestation.map_record_count,
        "response_bundle_hash": attestation.response_bundle_hash,
        "response_file_count": attestation.response_file_count,
        "response_byte_count": attestation.response_byte_count,
        "acquisition_tool_sha256": attestation.acquisition_tool_sha256,
        "reference_assembly": attestation.reference_assembly,
        "reference_transcript": attestation.reference_transcript,
        "reference_protein": attestation.reference_protein,
        "reference_page_count": attestation.reference_page_count,
        "checks_passed": list(attestation.checks_passed),
    }
    delta_dict = {
        "lock_protocol_version": delta.lock_protocol_version,
        "lock_protocol_doc_hash": delta.lock_protocol_doc_hash,
        "lock_registration_content_hash": delta.lock_registration_content_hash,
        "current_protocol_version": delta.current_protocol_version,
        "current_protocol_doc_hash": delta.current_protocol_doc_hash,
        "current_registration_content_hash": delta.current_registration_content_hash,
        "differs": delta.differs,
        "reconciled_via_amendment_log_versions": list(delta.reconciled_via_amendment_log_versions),
    }
    verified_digests = {
        "verified_protocol_doc_hash": report.verified_protocol_doc_hash,
        "verified_registration_content_hash": report.verified_registration_content_hash,
        "verified_live_pack_content_hash": report.verified_live_pack_content_hash,
        "active_universe_lock": report.active_universe_lock,
        "verified_lock_content_hash": report.verified_lock_content_hash,
        "verified_universe_content_hash": report.verified_universe_content_hash,
        "verified_raw_inventory_hash": report.verified_raw_inventory_hash,
        "verified_raw_inventory_record_count": report.verified_raw_inventory_record_count,
        "verified_normalization_ledger_hash": report.verified_normalization_ledger_hash,
        "verified_normalization_ledger_row_count": report.verified_normalization_ledger_row_count,
        "verified_discovery_set_hash": report.verified_discovery_set_hash,
        "verified_discovery_set_count": report.verified_discovery_set_count,
        "lock_protocol_version_delta": delta_dict,
        "identity_map": identity_map_dict,
        "checks_passed": list(report.checks_passed),
    }

    node_budget = inputs.node_budget_override
    if node_budget is None:
        node_budget = max((attempt.nodes_expanded for attempt in run.attempts), default=None)
    procedure = {
        "n_target": run.n_target,
        "node_budget": node_budget,
        "node_budget_override": inputs.node_budget_override,
        "attempts": [
            {
                "level": attempt.level,
                "n": attempt.n,
                "status": attempt.status,
                "nodes_expanded": attempt.nodes_expanded,
                "solution": list(attempt.solution) if attempt.solution else None,
            }
            for attempt in run.attempts
        ],
        "applied_relaxation_steps": list(run.applied_relaxation_steps),
        "independence_status": run.independence_status,
    }
    result = {
        "terminal_outcome": run.terminal_outcome,
        "n_target": run.n_target,
        "n_selected": run.n_selected,
        "selected_record_ids": list(run.selected_record_ids),
        "flags": dict(run.flags),
    }
    dispositions = [
        {
            "record_id": row.record_id,
            "universe_key": row.universe_key,
            "identity_state": row.identity_state,
            "all_matched_strata": list(row.all_matched_strata),
            "primary_stratum": row.primary_stratum,
            "spec_stratum": row.spec_stratum,
            "spec_stratum_derivation": row.spec_stratum_derivation,
            "support_class": row.support_class,
            "source_group_keys": list(row.source_group_keys),
            "draw_key": row.draw_key,
            "disposition": row.disposition,
            "rule_id": row.rule_id,
            "allocation_slot": row.allocation_slot,
            "label_function_discordant": row.label_function_discordant,
            "stale_label_discordant": row.stale_label_discordant,
        }
        for row in run.dispositions
    ]
    provenance = {
        "run_started_at": inputs.run_started_at.isoformat(),
        "executor_identity": inputs.executor_identity,
        "repo_root": str(inputs.repo_root),
        "anchor": {"spdi_canonical": inputs.anchor.spdi_canonical, "residue_index": inputs.anchor.residue_index},
    }

    rendered = {
        "verified_digests": verified_digests,
        "normalization_replay": {
            "replayed_row_count": run.replay.replayed_row_count,
            "outcome_counts": dict(run.replay.outcome_counts),
            "unresolved_confirmed_count": run.replay.unresolved_confirmed_count,
            "checks_passed": list(run.replay.checks_passed),
        },
        "identity_map": identity_map_dict,
        "procedure": procedure,
        "result": result,
        "dispositions": dispositions,
        "provenance": provenance,
    }
    return _json_safe(rendered)
