"""Arm C gate-fidelity — the `bp4pp3-predictor-policy` fail-closed loader.

`BP4`/`PP3` fire from computational predictors / splice models (ABSplice,
phyloP, REVEL/AlphaMissense-class scores) that are themselves trained on
ClinVar-labelled data. Whether that constitutes admissible independent
evidence or a predictor-mediated circularity when graded against a
ClinVar-derived benchmark is a separate, still-open Oracle policy question
(`decision_dependency: bp4pp3-predictor-policy`) -- NOT a
`configs/eval/bias_lineage.yaml` relabel; `BP4`/`PP3` keep their `allowed`
data-lineage disposition there. This module loads ONLY the external policy
decision + its provenance hashes -- never an evidence, label, or scorer
path -- and is fail-closed throughout: a missing, malformed, or unapproved
artifact never authorizes (no default-allow).
"""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: The exact schema id an artifact must declare (AC-G9).
SCHEMA_ID = "bp4pp3-predictor-policy"

#: Schema v2 (disabled/manual policy mode, slot 2 `policy_schema_v2`): adds
#: an explicit `mode` dimension ORTHOGONAL to `status`, plus the
#: production/eval/lineage config hashes and the runtime-code-bundle hash.
SCHEMA_ID_V2 = "bp4pp3-predictor-policy/2"

#: The v1 artifact's exact, closed field set (slot 2 §1) -- an extra/unknown
#: field is a malformed artifact (AC-G8/G9 "blank/unknown field"), never
#: silently ignored.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema",
    "status",
    "predictor_source_hash",
    "correction_hash",
    "decision_reference",
)

#: The v2 artifact's exact, closed field set (policy_schema_v2 §
#: `closed_field_set`) -- `mode`, `production_config_hash`,
#: `eval_config_hash`, `lineage_policy_hash`, `packet_policy_hash` and
#: `runtime_bundle_hash` are all REQUIRED for schema v2; an unknown/extra
#: field is malformed.
_REQUIRED_FIELDS_V2: tuple[str, ...] = (
    "schema",
    "status",
    "mode",
    "production_config_hash",
    "eval_config_hash",
    "lineage_policy_hash",
    "packet_policy_hash",
    "predictor_source_hash",
    "correction_hash",
    "runtime_bundle_hash",
    "decision_reference",
)

#: The v2 `mode` enum -- an evidence-mode dimension ORTHOGONAL to `status`;
#: `corrected_enabled` stays BLOCKED_POLICY in this track (D8).
_VALID_MODES: frozenset[str] = frozenset({"disabled_manual", "corrected_enabled"})

#: Every 64-hex-sha256 field a v2 artifact carries (policy_schema_v2
#: `field_rules`).
_HASH_FIELDS_V2: tuple[str, ...] = (
    "production_config_hash",
    "eval_config_hash",
    "lineage_policy_hash",
    "packet_policy_hash",
    "predictor_source_hash",
    "correction_hash",
    "runtime_bundle_hash",
)

#: `predictor_source_hash` / `correction_hash` must each be a genuine 64-hex
#: sha256-shaped digest -- never a placeholder/short string.
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class PredictorPolicyError(ValueError):
    """Raised on a missing/malformed `bp4pp3-predictor-policy` artifact.

    Fail-closed: this is the ONLY way an invalid artifact is signalled --
    there is no code path that returns a default-approved policy.
    """


@dataclass(frozen=True)
class PredictorPolicy:
    """A loaded, schema-valid `bp4pp3-predictor-policy` artifact.

    `approved` is `True` only when `status == "approved"` on an otherwise
    well-formed artifact; a well-formed but non-approved artifact still
    loads (no exception) with `approved=False` -- the caller (the terminal
    runner) is responsible for fail-closed `BLOCKED_POLICY` wiring on
    `approved=False`.

    `mode` and the five v2-only hashes (`production_config_hash`,
    `eval_config_hash`, `lineage_policy_hash`, `packet_policy_hash`,
    `runtime_bundle_hash`) are `None` for a schema-v1 artifact (D2) --
    `status` and `mode` are always independent; enablement is NEVER
    inferred from `status` alone (D1).
    """

    schema: str
    status: str
    predictor_source_hash: str
    correction_hash: str
    decision_reference: str
    approved: bool
    mode: str | None = None
    production_config_hash: str | None = None
    eval_config_hash: str | None = None
    lineage_policy_hash: str | None = None
    packet_policy_hash: str | None = None
    runtime_bundle_hash: str | None = None


def load_predictor_policy(path: str | Path) -> PredictorPolicy:
    """Load + fail-closed-validate a `bp4pp3-predictor-policy` artifact.

    Dispatches on the declared `schema`: `bp4pp3-predictor-policy` (v1) or
    `bp4pp3-predictor-policy/2` (v2, D2) -- any other value is malformed.
    Raises `PredictorPolicyError` for: a missing file, invalid JSON, a
    non-object root, a missing/blank required field, an unknown/extra
    field, an unrecognized `schema`, an unknown `mode` value (v2), or a
    non-64-hex hash field. Never a silent default -- every failure mode
    raises.
    """
    p = Path(path)
    if not p.is_file():
        raise PredictorPolicyError(f"predictor-policy artifact not found: {p}")

    try:
        raw: Any = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PredictorPolicyError(f"predictor-policy artifact is not valid JSON: {p} ({exc})") from exc

    if not isinstance(raw, dict):
        raise PredictorPolicyError(f"predictor-policy artifact root must be a JSON object: {p}")

    schema = raw.get("schema")
    if schema == SCHEMA_ID_V2:
        return _load_v2(raw)
    if schema == SCHEMA_ID:
        return _load_v1(raw)
    raise PredictorPolicyError(
        f"predictor-policy artifact schema must be {SCHEMA_ID!r} or {SCHEMA_ID_V2!r}, got {schema!r}"
    )


def _require_non_blank_fields(raw: dict[str, Any], required_fields: tuple[str, ...]) -> None:
    unknown = set(raw.keys()) - set(required_fields)
    if unknown:
        raise PredictorPolicyError(f"predictor-policy artifact has unknown field(s): {sorted(unknown)}")

    for field_name in required_fields:
        if field_name not in raw:
            raise PredictorPolicyError(f"predictor-policy artifact missing required field {field_name!r}")
        value = raw[field_name]
        if not isinstance(value, str) or not value.strip():
            raise PredictorPolicyError(
                f"predictor-policy artifact field {field_name!r} must be a non-blank string, got {value!r}"
            )


def _require_hex64_fields(raw: dict[str, Any], hash_fields: tuple[str, ...]) -> None:
    for hash_name in hash_fields:
        hash_value = raw[hash_name]
        if not _HEX64_RE.match(hash_value):
            raise PredictorPolicyError(
                f"predictor-policy artifact field {hash_name!r} must be a 64-hex-char sha256 digest, "
                f"got {hash_value!r}"
            )


def _load_v1(raw: dict[str, Any]) -> PredictorPolicy:
    """Load the v1 (legacy) closed field set -- unchanged fail-closed
    semantics, kept intact for fixtures/sentinel (D2)."""
    _require_non_blank_fields(raw, _REQUIRED_FIELDS)
    _require_hex64_fields(raw, ("predictor_source_hash", "correction_hash"))

    status = raw["status"]
    return PredictorPolicy(
        schema=raw["schema"],
        status=status,
        predictor_source_hash=raw["predictor_source_hash"],
        correction_hash=raw["correction_hash"],
        decision_reference=raw["decision_reference"],
        approved=(status == "approved"),
    )


def _load_v2(raw: dict[str, Any]) -> PredictorPolicy:
    """Load the v2 closed field set (policy_schema_v2): `mode` is REQUIRED
    and ORTHOGONAL to `status` (D1); `lineage_policy_hash`,
    `packet_policy_hash` and `runtime_bundle_hash` are REQUIRED
    (D9/D12/D13)."""
    _require_non_blank_fields(raw, _REQUIRED_FIELDS_V2)

    mode = raw["mode"]
    if mode not in _VALID_MODES:
        raise PredictorPolicyError(
            f"predictor-policy artifact field 'mode' has unknown mode {mode!r}; "
            f"must be one of {sorted(_VALID_MODES)}"
        )

    _require_hex64_fields(raw, _HASH_FIELDS_V2)

    status = raw["status"]
    return PredictorPolicy(
        schema=raw["schema"],
        status=status,
        predictor_source_hash=raw["predictor_source_hash"],
        correction_hash=raw["correction_hash"],
        decision_reference=raw["decision_reference"],
        approved=(status == "approved"),
        mode=mode,
        production_config_hash=raw["production_config_hash"],
        eval_config_hash=raw["eval_config_hash"],
        lineage_policy_hash=raw["lineage_policy_hash"],
        packet_policy_hash=raw["packet_policy_hash"],
        runtime_bundle_hash=raw["runtime_bundle_hash"],
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_predictor_policy_hashes(
    policy: PredictorPolicy,
    predictor_source_path: str | Path,
    correction_path: str | Path | Iterable[str | Path],
) -> None:
    """Bind an approved decision to the exact aggregation spec and code."""
    source = Path(predictor_source_path)
    correction_paths = (
        [Path(correction_path)]
        if isinstance(correction_path, (str, Path))
        else sorted((Path(path) for path in correction_path), key=lambda path: path.name)
    )
    if not source.is_file():
        raise PredictorPolicyError(f"predictor source artifact not found: {source}")
    if not correction_paths:
        raise PredictorPolicyError("predictor correction artifact bundle is empty")
    for correction in correction_paths:
        if not correction.is_file():
            raise PredictorPolicyError(f"predictor correction artifact not found: {correction}")
    actual_source = _sha256_file(source)
    if len(correction_paths) == 1:
        actual_correction = _sha256_file(correction_paths[0])
    else:
        digest = hashlib.sha256()
        for correction in correction_paths:
            digest.update(correction.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(correction.read_bytes())
            digest.update(b"\0")
        actual_correction = digest.hexdigest()
    if actual_source.lower() != policy.predictor_source_hash.lower():
        raise PredictorPolicyError(
            "predictor_source_hash mismatch: "
            f"policy={policy.predictor_source_hash} actual={actual_source}"
        )
    if actual_correction.lower() != policy.correction_hash.lower():
        raise PredictorPolicyError(
            "correction_hash mismatch: "
            f"policy={policy.correction_hash} actual={actual_correction}"
        )


def _sha256_bundle(paths: Iterable[str | Path]) -> str:
    """Deterministic multi-file bundle hash (D9/policy_schema_v2
    `hash_canonicalization`): files sorted by name, and for each,
    name+NUL+bytes+NUL -- the same convention `verify_predictor_policy_hashes`
    already uses for `correction_hash`."""
    sorted_paths = sorted((Path(path) for path in paths), key=lambda path: path.name)
    if not sorted_paths:
        raise PredictorPolicyError("runtime code bundle is empty")
    digest = hashlib.sha256()
    for candidate in sorted_paths:
        if not candidate.is_file():
            raise PredictorPolicyError(f"runtime code bundle file not found: {candidate}")
        digest.update(candidate.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(candidate.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_disabled_config_hashes(
    policy: PredictorPolicy,
    scorer_config_path: str | Path,
    eval_config_path: str | Path,
    lineage_policy_path: str | Path,
    packet_policy_path: str | Path,
) -> None:
    """CHECK-BEFORE-PROCEED: hash the ACTUAL given
    `--scorer-config`/`--eval-config`/bias-lineage/candidate-direction bytes
    and compare to the v2 artifact's pinned `production_config_hash`/
    `eval_config_hash`/`lineage_policy_hash`/`packet_policy_hash` (D10/D12/
    D13) -- an alternate path passes only if byte-identical; a changed byte
    (even one that also drops PP3/BP4) fails closed. Never proves the
    loader consumes these exact in-memory bytes afterward (TOCTOU is out of
    scope this phase; see the planner's `threat_model`/`residual_risk`)."""
    checks = (
        ("production_config_hash", scorer_config_path, policy.production_config_hash),
        ("eval_config_hash", eval_config_path, policy.eval_config_hash),
        ("lineage_policy_hash", lineage_policy_path, policy.lineage_policy_hash),
        ("packet_policy_hash", packet_policy_path, policy.packet_policy_hash),
    )
    for hash_name, candidate_path, expected in checks:
        candidate = Path(candidate_path)
        if not candidate.is_file():
            raise PredictorPolicyError(f"{hash_name} target not found: {candidate}")
        actual = _sha256_file(candidate)
        if expected is None or actual.lower() != expected.lower():
            raise PredictorPolicyError(
                f"{hash_name} mismatch: policy={expected} actual={actual} path={candidate}"
            )


def verify_runtime_bundle_hash(policy: PredictorPolicy, code_paths: Iterable[str | Path]) -> None:
    """Recompute the `runtime_bundle_hash` bundle over the ACTUAL given
    runtime code files and compare to the v2 artifact's pin (D9) -- detects
    ACCIDENTAL byte drift of the loader/wrapper/runner between approval and
    a run while the verifier/call-site execute. Never tamper-proof: a
    malicious edit that also removes/bypasses this verifier is out of scope
    this phase (see the planner's `threat_model`)."""
    actual = _sha256_bundle(code_paths)
    expected = policy.runtime_bundle_hash
    if expected is None or actual.lower() != expected.lower():
        raise PredictorPolicyError(
            f"runtime_bundle_hash mismatch: policy={expected} actual={actual}"
        )
