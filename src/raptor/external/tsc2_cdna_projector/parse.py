"""NCBI Variation Services step1/step2 JSON response parsing for the cliPE
cDNA -> GRCh38 SPDI projector.

``parse_step1_contextuals_response`` enforces the spec's
``api.endpoint_sequence.step1_hgvs_contextuals.acceptance_invariants_step1``:
``data.input_hgvs_validity == 'valid'``, exactly one contextual SPDI, that
SPDI's ``seq_id`` equal to the expected transcript, and uppercase-ACGT-only
``deleted_sequence``/``inserted_sequence`` fields (never the obsolete
``deletion-sequence``/``insertion-sequence`` documentation spellings).

``parse_step2_canonical_representative_response`` enforces the spec's
``acceptance_invariants_step2``: the canonical representative's ``seq_id``
must equal the expected (pinned) genomic accession, and its alleles must
likewise be uppercase-ACGT-only. Both parsers fail closed on ANY top-level
``warnings`` key in the response envelope (an alignment-drift/non-pinned-
sequence warning is never silently accepted) -- this is the "warnings/non-
pinned sequence fail closed" rule.

Each raised ``Step1SchemaError``/``Step2SchemaError`` carries a ``.reason``
attribute drawn from a small fixed vocabulary so ``ingest.py`` can map it
directly onto the spec's ``error_states.status_vocabulary`` without ever
string-matching an exception message.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import json
from typing import Any

_ACGT_RE_SOURCE = "^[ACGT]*$"


class Step1SchemaError(ValueError):
    """Raised when a step1 (``/hgvs/{hgvs}/contextuals``) response fails
    schema/acceptance-invariant validation. ``reason`` is one of
    ``"INVALID_HGVS"``, ``"AMBIGUOUS_SPDIS"``, ``"UNEXPECTED_SEQ_ID"``,
    ``"NON_ACGT_ALLELE"``, ``"WARNINGS_PRESENT"`` or ``"SCHEMA_VIOLATION"``."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class Step2SchemaError(ValueError):
    """Raised when a step2 (``/spdi/{spdi}/canonical_representative``)
    response fails schema/acceptance-invariant validation. ``reason`` is
    one of ``"NON_PINNED_GENOME"``, ``"NON_ACGT_ALLELE"``,
    ``"WARNINGS_PRESENT"`` or ``"SCHEMA_VIOLATION"``."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _decode_json(body: bytes, media_type: str, *, error_cls: type[Exception], reason: str) -> Any:
    if not isinstance(media_type, str) or not media_type.split(";")[0].strip().lower() == "application/json":
        raise error_cls(  # type: ignore[misc]
            f"response media_type is not application/json: {media_type!r}", reason=reason
        )
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_cls(f"response body is not valid UTF-8: {exc}", reason=reason) from exc  # type: ignore[misc]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise error_cls(f"response body is not valid JSON: {exc}", reason=reason) from exc  # type: ignore[misc]
    if not isinstance(payload, dict):
        raise error_cls(  # type: ignore[misc]
            f"response body did not decode to a JSON object: {type(payload).__name__}", reason=reason
        )
    return payload


def _require_acgt(value: Any, *, field_name: str, error_cls: type[Exception]) -> str:
    if not isinstance(value, str):
        raise error_cls(f"{field_name} must be a string, got {type(value).__name__}", reason="SCHEMA_VIOLATION")  # type: ignore[misc]
    if not value or not all(ch in "ACGT" for ch in value):
        raise error_cls(  # type: ignore[misc]
            f"{field_name} {value!r} is empty or contains non-uppercase-ACGT characters "
            "(this pinned score set never contains a pure empty-del or empty-ins allele)",
            reason="NON_ACGT_ALLELE",
        )
    return value


def _reject_nested_warnings(container: Any, *, where: str, error_cls: type[Exception]) -> None:
    if isinstance(container, dict) and "warnings" in container:
        raise error_cls(  # type: ignore[misc]
            f"{where} carries a 'warnings' key; failing closed rather than silently accepting "
            "an alignment-drift/non-pinned-sequence warning",
            reason="WARNINGS_PRESENT",
        )


def parse_step1_contextuals_response(
    *, body: bytes, media_type: str, expected_seq_id: str
) -> dict[str, Any]:
    """Parse and strictly validate a step1 ``contextuals`` response body.
    Returns ``{"seq_id", "position", "deleted_sequence", "inserted_sequence",
    "spdi"}`` on success. Raises ``Step1SchemaError`` (with a ``.reason``)
    on any acceptance-invariant violation, including a ``warnings`` key
    nested at the payload, ``data``, or ``spdis[0]`` item level, or an
    empty deleted/inserted allele (this pinned score set never contains a
    pure empty-del or empty-ins allele)."""
    payload = _decode_json(body, media_type, error_cls=Step1SchemaError, reason="SCHEMA_VIOLATION")
    _reject_nested_warnings(payload, where="step1 response", error_cls=Step1SchemaError)

    data = payload.get("data")
    if not isinstance(data, dict):
        raise Step1SchemaError("step1 response is missing a 'data' object", reason="SCHEMA_VIOLATION")
    _reject_nested_warnings(data, where="step1 response data", error_cls=Step1SchemaError)

    validity = data.get("input_hgvs_validity")
    if validity != "valid":
        raise Step1SchemaError(
            f"step1 input_hgvs_validity is not 'valid': {validity!r}", reason="INVALID_HGVS"
        )

    spdis = data.get("spdis")
    if not isinstance(spdis, list) or len(spdis) != 1:
        raise Step1SchemaError(
            f"step1 spdis must be a single-element list, got "
            f"{len(spdis) if isinstance(spdis, list) else type(spdis).__name__}",
            reason="AMBIGUOUS_SPDIS",
        )

    item = spdis[0]
    if not isinstance(item, dict):
        raise Step1SchemaError("step1 spdis[0] is not an object", reason="SCHEMA_VIOLATION")
    _reject_nested_warnings(item, where="step1 response spdis[0]", error_cls=Step1SchemaError)
    for field_name in ("seq_id", "position", "deleted_sequence", "inserted_sequence"):
        if field_name not in item:
            raise Step1SchemaError(f"step1 spdis[0] is missing required field {field_name!r}", reason="SCHEMA_VIOLATION")

    seq_id = item["seq_id"]
    if not isinstance(seq_id, str) or seq_id != expected_seq_id:
        raise Step1SchemaError(
            f"step1 spdis[0].seq_id {seq_id!r} does not match the expected transcript "
            f"{expected_seq_id!r}",
            reason="UNEXPECTED_SEQ_ID",
        )

    position = item["position"]
    if not isinstance(position, int) or isinstance(position, bool) or position < 0:
        raise Step1SchemaError(f"step1 spdis[0].position is not a non-negative int: {position!r}", reason="SCHEMA_VIOLATION")

    deleted_sequence = _require_acgt(item["deleted_sequence"], field_name="step1 deleted_sequence", error_cls=Step1SchemaError)
    inserted_sequence = _require_acgt(item["inserted_sequence"], field_name="step1 inserted_sequence", error_cls=Step1SchemaError)

    return {
        "seq_id": seq_id,
        "position": position,
        "deleted_sequence": deleted_sequence,
        "inserted_sequence": inserted_sequence,
        "spdi": f"{seq_id}:{position}:{deleted_sequence}:{inserted_sequence}",
    }


def parse_step2_canonical_representative_response(
    *, body: bytes, media_type: str, expected_seq_id: str
) -> dict[str, Any]:
    """Parse and strictly validate a step2 ``canonical_representative``
    response body. Returns ``{"seq_id", "position", "deleted_sequence",
    "inserted_sequence", "spdi"}`` on success. Raises ``Step2SchemaError``
    (with a ``.reason``) on any acceptance-invariant violation, including
    a canonical representative on any accession other than
    ``expected_seq_id`` (``reason="NON_PINNED_GENOME"``), a ``warnings``
    key nested at the payload or ``data`` level, or an empty deleted/
    inserted allele."""
    payload = _decode_json(body, media_type, error_cls=Step2SchemaError, reason="SCHEMA_VIOLATION")
    _reject_nested_warnings(payload, where="step2 response", error_cls=Step2SchemaError)

    data = payload.get("data")
    if not isinstance(data, dict):
        raise Step2SchemaError("step2 response is missing a 'data' object", reason="SCHEMA_VIOLATION")
    _reject_nested_warnings(data, where="step2 response data", error_cls=Step2SchemaError)

    for field_name in ("seq_id", "position", "deleted_sequence", "inserted_sequence"):
        if field_name not in data:
            raise Step2SchemaError(f"step2 data is missing required field {field_name!r}", reason="SCHEMA_VIOLATION")

    seq_id = data["seq_id"]
    if not isinstance(seq_id, str) or seq_id != expected_seq_id:
        raise Step2SchemaError(
            f"step2 canonical_representative seq_id {seq_id!r} is not the pinned genome "
            f"{expected_seq_id!r}",
            reason="NON_PINNED_GENOME",
        )

    position = data["position"]
    if not isinstance(position, int) or isinstance(position, bool) or position < 0:
        raise Step2SchemaError(f"step2 data.position is not a non-negative int: {position!r}", reason="SCHEMA_VIOLATION")

    deleted_sequence = _require_acgt(data["deleted_sequence"], field_name="step2 deleted_sequence", error_cls=Step2SchemaError)
    inserted_sequence = _require_acgt(data["inserted_sequence"], field_name="step2 inserted_sequence", error_cls=Step2SchemaError)

    return {
        "seq_id": seq_id,
        "position": position,
        "deleted_sequence": deleted_sequence,
        "inserted_sequence": inserted_sequence,
        "spdi": f"{seq_id}:{position}:{deleted_sequence}:{inserted_sequence}",
    }


__all__ = [
    "Step1SchemaError",
    "Step2SchemaError",
    "parse_step1_contextuals_response",
    "parse_step2_canonical_representative_response",
]
