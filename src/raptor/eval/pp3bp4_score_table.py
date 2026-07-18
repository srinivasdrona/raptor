"""Slot 3 — `pp3bp4_score_table.py` — Stage A structured REVEL score-table
validation (RAPTOR PP3/BP4 shadow policy, steps 2-7).

Stage A (Slot 2 Rule 4): derives exact dev IDs and accepts/exports
structured scores WITHOUT reading labels. This module never opens a
labels/benchmark/held-out file itself -- it only validates rows + a sidecar
attestation against a caller-supplied `dev_ids` list.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

#: The score-table row's exact, closed field set (Slot 3 spec `row_fields`).
_ROW_FIELDS: tuple[str, ...] = (
    "variant_id", "score", "predictor", "predictor_version", "data_version",
    "source", "transcript", "consequence",
)
_ROW_NULLABLE_FIELDS: frozenset[str] = frozenset({"score", "transcript", "consequence"})

#: `ScoreTableAttestation`'s exact, closed sidecar field set (Slot 3 spec
#: `sidecar_fields`) -- identical to the dataclass's own field set.
_SIDECAR_FIELDS: tuple[str, ...] = (
    "schema", "predictor", "predictor_version", "data_version", "license",
    "dev_id_set_sha256", "table_content_sha256", "n_dev", "n_scored",
    "n_missing", "coverage", "reference_pins", "as_of", "snapshot",
)

#: Censored free-form BIAS-rationale provenance token (Rule 9) -- built by
#: concatenation so it is never accepted, mirroring
#: `pp3bp4_candidate_policy._FORBIDDEN_SOURCE`.
_FORBIDDEN_SOURCE: str = "bias" + "_" + "rationale"

#: Canonical SPDI variant identity: `accession:position:deleted:inserted`
#: (e.g. `NC_000009.12:12345:A:G`) -- never a raw `chrom:pos:ref:alt` or an
#: HGVS `g.`/`c.` string.
_SPDI_RE = re.compile(r"^[A-Za-z]{1,4}_\d+\.\d+:\d+:[ACGTNacgtn]*:[ACGTNacgtn]*$")


class ScoreTableValidationError(ValueError):
    """Raised on any malformed/unverified score-table row or sidecar.
    Fail-closed -- there is no silent row loss or default-valid path."""


@dataclass
class ScoreTableAttestation:
    """Stage-A->Stage-B trust boundary attestation (Slot 2 Rule 4/T-S2).

    Field set is identical to the sidecar's closed schema -- this is the
    ONLY object Stage B (`pp3bp4_transportability.evaluate_transportability`)
    may trust for dev-set membership/coverage; it never re-reads labels."""

    schema: str
    predictor: str
    predictor_version: str
    data_version: str
    license: str
    dev_id_set_sha256: str
    table_content_sha256: str
    n_dev: int
    n_scored: int
    n_missing: int
    coverage: float
    reference_pins: list
    as_of: str
    snapshot: str


def _compute_dev_id_set_hash(dev_ids: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for variant_id in sorted(dev_ids):
        digest.update(variant_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _compute_table_content_hash(rows: list[dict]) -> str:
    sorted_rows = sorted(rows, key=lambda r: r["variant_id"])
    canonical = json.dumps(sorted_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_and_validate_score_table(
    rows: list[dict], sidecar: dict, *, dev_ids: list[str], policy: Any
) -> tuple[list[dict], ScoreTableAttestation]:
    """Validate a structured REVEL score table (T-S1/T-S2).

    Rejects loudly: a missing/extra sidecar field, a predictor/version
    mismatch (sidecar or row level) against `policy`, a
    `dev_id_set_sha256`/`table_content_sha256` mismatch, a duplicate
    `variant_id`, any `variant_id` outside the exact `dev_ids` set
    (including a held-out id), a non-canonical-SPDI `variant_id`, a
    nonfinite/out-of-range/bool-typed score, a version-mismatched row, a
    `source == "bias_rationale"` row, or an extra row field (closed row
    schema). Never silently drops a missing-score row -- conservation
    `n_scored + n_missing == n_dev` is preserved exactly."""
    if not isinstance(sidecar, dict):
        raise ScoreTableValidationError("score-table sidecar must be an object")

    unknown_sidecar = sorted(set(sidecar.keys()) - set(_SIDECAR_FIELDS))
    if unknown_sidecar:
        raise ScoreTableValidationError(
            f"score-table sidecar has extra/unexpected field(s): {unknown_sidecar}"
        )
    missing_sidecar = sorted(set(_SIDECAR_FIELDS) - set(sidecar.keys()))
    if missing_sidecar:
        raise ScoreTableValidationError(
            f"score-table sidecar is missing required field(s): {missing_sidecar}"
        )

    for field_name in ("predictor", "predictor_version", "data_version"):
        sidecar_value = sidecar[field_name]
        policy_value = getattr(policy, field_name)
        if sidecar_value != policy_value:
            raise ScoreTableValidationError(
                f"score-table sidecar field {field_name!r} version mismatch: "
                f"sidecar={sidecar_value!r} policy={policy_value!r}"
            )

    dev_id_list = list(dev_ids)
    dev_id_set = set(dev_id_list)
    expected_dev_hash = _compute_dev_id_set_hash(dev_id_list)
    if sidecar["dev_id_set_sha256"] != expected_dev_hash:
        raise ScoreTableValidationError(
            "score-table sidecar dev_id_set_sha256 hash mismatch: "
            f"sidecar={sidecar['dev_id_set_sha256']!r} actual={expected_dev_hash!r}"
        )
    if sidecar["n_dev"] != len(dev_id_list):
        raise ScoreTableValidationError(
            f"score-table sidecar n_dev={sidecar['n_dev']!r} does not match "
            f"len(dev_ids)={len(dev_id_list)!r}"
        )

    expected_table_hash = _compute_table_content_hash(rows)
    if sidecar["table_content_sha256"] != expected_table_hash:
        raise ScoreTableValidationError(
            "score-table sidecar table_content_sha256 hash mismatch: "
            f"sidecar={sidecar['table_content_sha256']!r} actual={expected_table_hash!r}"
        )

    seen_ids: set[str] = set()
    n_scored = 0
    validated_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ScoreTableValidationError(f"score-table row must be an object, got {row!r}")

        unknown_row_fields = sorted(set(row.keys()) - set(_ROW_FIELDS))
        if unknown_row_fields:
            raise ScoreTableValidationError(
                f"score-table row has extra field(s) outside the closed schema: {unknown_row_fields}"
            )
        missing_row_fields = sorted(set(_ROW_FIELDS) - set(row.keys()))
        if missing_row_fields:
            raise ScoreTableValidationError(
                f"score-table row is missing required field(s): {missing_row_fields}"
            )
        for field_name in _ROW_FIELDS:
            if field_name not in _ROW_NULLABLE_FIELDS and row[field_name] is None:
                raise ScoreTableValidationError(
                    f"score-table row field {field_name!r} may not be null"
                )

        variant_id = row["variant_id"]
        if not isinstance(variant_id, str) or not _SPDI_RE.match(variant_id):
            raise ScoreTableValidationError(
                f"score-table row variant_id {variant_id!r} is not canonical SPDI format "
                "(expected accession:position:deleted:inserted)"
            )
        if variant_id in seen_ids:
            raise ScoreTableValidationError(
                f"score-table has duplicate variant_id: {variant_id!r}"
            )
        seen_ids.add(variant_id)
        if variant_id not in dev_id_set:
            raise ScoreTableValidationError(
                f"score-table row variant_id {variant_id!r} is not in the dev set "
                "(extra id, or a held-out id leaked into the dev score table)"
            )

        score = row["score"]
        if score is not None:
            if isinstance(score, bool):
                raise ScoreTableValidationError(
                    f"score-table row score must be numeric, not bool: {score!r}"
                )
            if not isinstance(score, (int, float)):
                raise ScoreTableValidationError(
                    f"score-table row score must be a number, got {type(score).__name__}"
                )
            if not math.isfinite(score):
                raise ScoreTableValidationError(
                    f"score-table row score is not finite: {score!r}"
                )
            if not (0.0 <= float(score) <= 1.0):
                raise ScoreTableValidationError(
                    f"score-table row score {score!r} is out of REVEL range [0, 1]"
                )
            n_scored += 1

        for field_name in ("predictor", "predictor_version", "data_version"):
            row_value = row[field_name]
            policy_value = getattr(policy, field_name)
            if row_value != policy_value:
                raise ScoreTableValidationError(
                    f"score-table row field {field_name!r} does not match policy: "
                    f"row={row_value!r} policy={policy_value!r}"
                )

        if row["source"] == _FORBIDDEN_SOURCE:
            raise ScoreTableValidationError(
                f"score-table row source is the forbidden {_FORBIDDEN_SOURCE!r} route "
                f"(variant_id={variant_id!r}); no censored free-form-rationale token is "
                "ever an accepted structured score source"
            )

        validated_rows.append(dict(row))

    # Exact-set conservation (Slot 2 Rule 3): every expected dev id must have
    # an explicit row (missing scores are `score:null` rows, never omitted
    # rows) -- an omitted dev id is an exact-set breach, not silent undercount.
    missing_dev_ids = sorted(dev_id_set - seen_ids)
    if missing_dev_ids:
        raise ScoreTableValidationError(
            "score-table is missing an explicit row for expected dev variant_id(s) "
            f"(exact-set/conservation breach): {missing_dev_ids}"
        )

    # Missingness/coverage are computed against the expected dev id count,
    # never the submitted-row count (Slot 2 Rule 3).
    n_dev = len(dev_id_list)
    n_missing = n_dev - n_scored
    if sidecar["n_scored"] != n_scored or sidecar["n_missing"] != n_missing:
        raise ScoreTableValidationError(
            f"score-table sidecar n_scored/n_missing ({sidecar['n_scored']}/{sidecar['n_missing']}) "
            f"does not match actual rows ({n_scored}/{n_missing})"
        )

    coverage = (n_scored / n_dev) if n_dev > 0 else 1.0

    attestation = ScoreTableAttestation(
        schema=sidecar["schema"],
        predictor=sidecar["predictor"],
        predictor_version=sidecar["predictor_version"],
        data_version=sidecar["data_version"],
        license=sidecar["license"],
        dev_id_set_sha256=expected_dev_hash,
        table_content_sha256=expected_table_hash,
        n_dev=len(dev_id_list),
        n_scored=n_scored,
        n_missing=n_missing,
        coverage=coverage,
        reference_pins=list(sidecar["reference_pins"]),
        as_of=sidecar["as_of"],
        snapshot=sidecar["snapshot"],
    )
    return sorted(validated_rows, key=lambda r: r["variant_id"]), attestation
