"""RAPTOR v2 TSC2 functional-row identity normalization -- row contract.

``raptor.external.normalized_functional_row.v1`` (see the binding spec,
``docs/project/specs/raptor-v2-functional-identity-normalization-v1.yaml``,
``normalized_row`` section) is the single output-row shape shared by every
source normalizer in this slice (``normalize.py``): a strict, exact field
set, a fixed vocabulary for ``variant_kind``/``identity_state``/
``unresolved_reason``, and a small set of cross-field invariants (e.g. a
verified genomic SPDI is only ever present alongside
``identity_state == "GENOMIC_SPDI_VERIFIED"``).

``NormalizedFunctionalRow`` is a validated, frozen dataclass used internally
by ``normalize.py`` to build every row; ``to_dict()`` -- the exact,
sorted-key-independent field mapping this module's tests and
``bundle.canonical_jsonl_bytes`` expect -- is the only representation ever
handed back across this package's public API.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from typing import Any

#: The fixed gene identity pin for this entire slice (spec
#: ``inputs.identity_pins.gene``) -- never configurable per row/call.
GENE = "TSC2"

NORMALIZED_FUNCTIONAL_ROW_SCHEMA = "raptor.external.normalized_functional_row.v1"

REQUIRED_ROW_FIELDS: frozenset[str] = frozenset(
    {
        "schema",
        "source_id",
        "source_row",
        "source_record_id",
        "gene",
        "assembly",
        "transcript",
        "protein_accession",
        "hgvs_c",
        "hgvs_p",
        "hgvs_g",
        "spdi",
        "variant_kind",
        "identity_state",
        "unresolved_reason",
        "score_name",
        "score_raw",
    }
)

ALLOWED_VARIANT_KINDS: frozenset[str] = frozenset(
    {"MISSENSE", "SYNONYMOUS", "STOP_GAINED", "OTHER", "REFERENCE_CONTROL"}
)

ALLOWED_IDENTITY_STATES: frozenset[str] = frozenset(
    {
        "GENOMIC_SPDI_VERIFIED",
        "GENOMIC_REFERENCE_MISMATCH",
        "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED",
        "PROTEIN_ONLY_CROSSWALK_REQUIRED",
        "REFERENCE_CONTROL",
    }
)

ALLOWED_UNRESOLVED_REASONS: frozenset[Any] = frozenset(
    {None, "REFERENCE_ALLELE_MISMATCH", "CDNA_PROJECTOR_REQUIRED", "NUCLEOTIDE_CROSSWALK_REQUIRED", "NOT_A_VARIANT"}
)

#: Every ``identity_state`` binds to EXACTLY one ``unresolved_reason`` (this
#: is the single source of truth other modules must derive aggregate
#: ``unresolved_reason_counts`` from -- see ``bundle.build_committed_summary``).
IDENTITY_STATE_TO_UNRESOLVED_REASON: dict[str, str | None] = {
    "GENOMIC_SPDI_VERIFIED": None,
    "GENOMIC_REFERENCE_MISMATCH": "REFERENCE_ALLELE_MISMATCH",
    "TRANSCRIPT_ONLY_PROJECTOR_REQUIRED": "CDNA_PROJECTOR_REQUIRED",
    "PROTEIN_ONLY_CROSSWALK_REQUIRED": "NUCLEOTIDE_CROSSWALK_REQUIRED",
    "REFERENCE_CONTROL": "NOT_A_VARIANT",
}

#: Fixed identity pins a ``GENOMIC_SPDI_VERIFIED`` row must carry (spec
#: ``normalized_row.invariants``).
_VERIFIED_ASSEMBLY = "GRCh38"
_VERIFIED_TRANSCRIPT = "NM_000548.5"
_VERIFIED_GENOMIC_ACCESSION = "NC_000016.10"

#: A canonical SNV SPDI string: ``<accession>:<position0>:<ref>:<alt>``.
_SPDI_SNV_RE = re.compile(r"^(?P<accession>[A-Za-z0-9_.]+):(?P<position>\d+):(?P<ref>[ACGT]+):(?P<alt>[ACGT]+)$")
#: A canonical genomic HGVS SNV string: ``<accession>:g.<position1><ref>><alt>``.
_HGVS_G_SNV_RE = re.compile(r"^(?P<accession>[A-Za-z0-9_.]+):g\.(?P<position>\d+)(?P<ref>[ACGT])>(?P<alt>[ACGT])$")


class NormalizationContractError(ValueError):
    """Raised for any structural/schema/vocabulary/invariant violation of
    the normalized-row contract: an unexpected header or row count, an
    unknown ``variant_kind``/``identity_state``/``unresolved_reason``, a
    mismatched ``identity_state``/``unresolved_reason`` pairing, an
    ``spdi`` present without ``GENOMIC_SPDI_VERIFIED`` (or vice versa), a
    malformed source accession/HGVS shape, or a duplicate
    ``(source_id, source_row)`` key."""


class ScoreValidationError(ValueError):
    """Raised when a source row's score string is blank, non-numeric, NaN
    or infinite -- ``score_raw`` must always be a finite numeric string,
    copied verbatim without numeric transformation."""


class NormalizationOutcomeError(ValueError):
    """Raised when ``SeqRepoGenomicNormalizer`` (or an injected stand-in)
    returns any ``ManualQueueItem``/error outcome other than
    ``error_code == "REF_MISMATCH"`` (which maps to
    ``GENOMIC_REFERENCE_MISMATCH``): every other manual/error outcome
    aborts the whole run rather than being silently dropped or guessed."""


@dataclass(frozen=True)
class NormalizedFunctionalRow:
    """A single validated ``raptor.external.normalized_functional_row.v1``
    row. Construction validates the exact vocabulary and cross-field
    invariants (see module docstring); ``to_dict()`` is the only shape
    handed back across this package's public API."""

    source_id: str
    source_row: int
    source_record_id: str
    gene: str
    assembly: str | None
    transcript: str | None
    protein_accession: str | None
    hgvs_c: str | None
    hgvs_p: str | None
    hgvs_g: str | None
    spdi: str | None
    variant_kind: str
    identity_state: str
    unresolved_reason: str | None
    score_name: str
    score_raw: str
    schema: str = NORMALIZED_FUNCTIONAL_ROW_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != NORMALIZED_FUNCTIONAL_ROW_SCHEMA:
            raise NormalizationContractError(
                f"schema must be {NORMALIZED_FUNCTIONAL_ROW_SCHEMA!r}, got {self.schema!r}"
            )
        if self.gene != GENE:
            raise NormalizationContractError(f"gene must be {GENE!r}, got {self.gene!r}")
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise NormalizationContractError("source_id must be a non-blank string")
        if not isinstance(self.score_name, str) or not self.score_name.strip():
            raise NormalizationContractError("score_name must be a non-blank string")
        if not isinstance(self.score_raw, str) or not self.score_raw.strip():
            raise NormalizationContractError("score_raw must be a non-blank numeric string")
        try:
            score_value = float(self.score_raw)
        except ValueError as exc:
            raise NormalizationContractError(f"score_raw {self.score_raw!r} is not a numeric string") from exc
        if not math.isfinite(score_value):
            raise NormalizationContractError(f"score_raw {self.score_raw!r} is not finite")
        if not isinstance(self.source_row, int) or isinstance(self.source_row, bool) or self.source_row < 1:
            raise NormalizationContractError(
                f"source_row must be a one-based positive int, got {self.source_row!r}"
            )
        if not isinstance(self.source_record_id, str) or not self.source_record_id:
            raise NormalizationContractError("source_record_id must be a non-empty string")
        if self.variant_kind not in ALLOWED_VARIANT_KINDS:
            raise NormalizationContractError(
                f"variant_kind {self.variant_kind!r} is not one of {sorted(ALLOWED_VARIANT_KINDS)!r}"
            )
        if self.identity_state not in ALLOWED_IDENTITY_STATES:
            raise NormalizationContractError(
                f"identity_state {self.identity_state!r} is not one of {sorted(ALLOWED_IDENTITY_STATES)!r}"
            )
        if self.unresolved_reason not in ALLOWED_UNRESOLVED_REASONS:
            raise NormalizationContractError(
                f"unresolved_reason {self.unresolved_reason!r} is not one of "
                f"{sorted(str(v) for v in ALLOWED_UNRESOLVED_REASONS)!r}"
            )
        expected_reason = IDENTITY_STATE_TO_UNRESOLVED_REASON[self.identity_state]
        if self.unresolved_reason != expected_reason:
            raise NormalizationContractError(
                f"identity_state {self.identity_state!r} requires unresolved_reason "
                f"{expected_reason!r}, got {self.unresolved_reason!r}"
            )
        if self.identity_state == "GENOMIC_SPDI_VERIFIED":
            if self.spdi is None:
                raise NormalizationContractError("GENOMIC_SPDI_VERIFIED rows must carry a non-null spdi")
            if self.assembly != _VERIFIED_ASSEMBLY or self.transcript != _VERIFIED_TRANSCRIPT:
                raise NormalizationContractError(
                    "GENOMIC_SPDI_VERIFIED requires assembly "
                    f"{_VERIFIED_ASSEMBLY!r} and transcript {_VERIFIED_TRANSCRIPT!r}, got "
                    f"assembly={self.assembly!r} transcript={self.transcript!r}"
                )
            spdi_match = _SPDI_SNV_RE.match(self.spdi)
            if spdi_match is None:
                raise NormalizationContractError(
                    f"spdi {self.spdi!r} is not a canonical <accession>:<position>:<ref>:<alt> SNV string"
                )
            if spdi_match["accession"] != _VERIFIED_GENOMIC_ACCESSION:
                raise NormalizationContractError(
                    f"spdi {self.spdi!r} accession must be {_VERIFIED_GENOMIC_ACCESSION!r}"
                )
            if self.hgvs_g is None:
                raise NormalizationContractError(
                    "GENOMIC_SPDI_VERIFIED requires a non-null hgvs_g to cross-validate spdi against"
                )
            hgvs_g_match = _HGVS_G_SNV_RE.match(self.hgvs_g)
            if hgvs_g_match is None:
                raise NormalizationContractError(
                    f"hgvs_g {self.hgvs_g!r} is not a canonical <accession>:g.<position><ref>><alt> SNV string"
                )
            if hgvs_g_match["accession"] != _VERIFIED_GENOMIC_ACCESSION:
                raise NormalizationContractError(
                    f"hgvs_g {self.hgvs_g!r} accession must be {_VERIFIED_GENOMIC_ACCESSION!r}"
                )
            expected_position = int(hgvs_g_match["position"]) - 1
            if (
                int(spdi_match["position"]) != expected_position
                or spdi_match["ref"] != hgvs_g_match["ref"]
                or spdi_match["alt"] != hgvs_g_match["alt"]
            ):
                raise NormalizationContractError(
                    f"spdi {self.spdi!r} does not match the normalized hgvs_g {self.hgvs_g!r} "
                    "(expected position = hgvs_g position - 1, same ref/alt)"
                )
        elif self.spdi is not None:
            raise NormalizationContractError(
                f"only GENOMIC_SPDI_VERIFIED rows may carry a non-null spdi (identity_state="
                f"{self.identity_state!r})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


__all__ = [
    "GENE",
    "NORMALIZED_FUNCTIONAL_ROW_SCHEMA",
    "REQUIRED_ROW_FIELDS",
    "ALLOWED_VARIANT_KINDS",
    "ALLOWED_IDENTITY_STATES",
    "ALLOWED_UNRESOLVED_REASONS",
    "IDENTITY_STATE_TO_UNRESOLVED_REASON",
    "NormalizationContractError",
    "ScoreValidationError",
    "NormalizationOutcomeError",
    "NormalizedFunctionalRow",
]
