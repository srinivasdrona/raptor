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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The exact schema id an artifact must declare (AC-G9).
SCHEMA_ID = "bp4pp3-predictor-policy"

#: The artifact's exact, closed field set (slot 2 §1) -- an extra/unknown
#: field is a malformed artifact (AC-G8/G9 "blank/unknown field"), never
#: silently ignored.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema",
    "status",
    "predictor_source_hash",
    "correction_hash",
    "decision_reference",
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
    """

    schema: str
    status: str
    predictor_source_hash: str
    correction_hash: str
    decision_reference: str
    approved: bool


def load_predictor_policy(path: str | Path) -> PredictorPolicy:
    """Load + fail-closed-validate a `bp4pp3-predictor-policy` artifact.

    Raises `PredictorPolicyError` for: a missing file, invalid JSON, a
    non-object root, a missing/blank required field, an unknown/extra
    field, a wrong `schema` id, or a non-64-hex `predictor_source_hash`/
    `correction_hash`. Never a silent default -- every failure mode raises.
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

    unknown = set(raw.keys()) - set(_REQUIRED_FIELDS)
    if unknown:
        raise PredictorPolicyError(f"predictor-policy artifact has unknown field(s): {sorted(unknown)}")

    for field_name in _REQUIRED_FIELDS:
        if field_name not in raw:
            raise PredictorPolicyError(f"predictor-policy artifact missing required field {field_name!r}")
        value = raw[field_name]
        if not isinstance(value, str) or not value.strip():
            raise PredictorPolicyError(
                f"predictor-policy artifact field {field_name!r} must be a non-blank string, got {value!r}"
            )

    schema = raw["schema"]
    if schema != SCHEMA_ID:
        raise PredictorPolicyError(f"predictor-policy artifact schema must be {SCHEMA_ID!r}, got {schema!r}")

    predictor_source_hash = raw["predictor_source_hash"]
    correction_hash = raw["correction_hash"]
    for hash_name, hash_value in (
        ("predictor_source_hash", predictor_source_hash),
        ("correction_hash", correction_hash),
    ):
        if not _HEX64_RE.match(hash_value):
            raise PredictorPolicyError(
                f"predictor-policy artifact field {hash_name!r} must be a 64-hex-char sha256 digest, "
                f"got {hash_value!r}"
            )

    status = raw["status"]
    decision_reference = raw["decision_reference"]

    return PredictorPolicy(
        schema=schema,
        status=status,
        predictor_source_hash=predictor_source_hash,
        correction_hash=correction_hash,
        decision_reference=decision_reference,
        approved=(status == "approved"),
    )
