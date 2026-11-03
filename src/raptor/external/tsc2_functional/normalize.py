"""RAPTOR v2 TSC2 functional normalization -- per-source row normalizers.

Three pure, deterministic parsers over already-injected bytes/text -- one
per frozen input format (spec ``source_rules``):

- ``normalize_mavedb``: MaveDB cliPE CSV (``accession, hgvs_nt, hgvs_splice,
  hgvs_pro, score``). Every bare ``c.`` value is prefixed with the pinned
  ``NM_000548.5`` transcript; no genomic SPDI is ever fabricated without an
  injected cDNA-to-genome projector (there is none in this slice) --
  every row is ``TRANSCRIPT_ONLY_PROJECTOR_REQUIRED``/
  ``CDNA_PROJECTOR_REQUIRED``.
- ``normalize_vamp_seq``: IGVF VAMP-seq gzip TSV. Every ``variant`` token
  must carry the pinned ``ENSP00000219476.3`` protein accession; protein
  identity is preserved verbatim and no transcript/genomic identity is ever
  fabricated without a frozen nucleotide crosswalk (there is none in this
  slice) -- every row is ``PROTEIN_ONLY_CROSSWALK_REQUIRED``/
  ``NUCLEOTIDE_CROSSWALK_REQUIRED``. ``functional_class`` is read from the
  source but never copied into the normalized row.
- ``normalize_sge``: IGVF SGE gzip TSV. Source accession separators
  (``NM_000548_5``/``NC_000016_10``) are checked EXACTLY before being
  normalized to dotted form; the three ``c.=``/``g.=``/``p.=`` rows are
  explicit ``REFERENCE_CONTROL`` rows, and every other row is parsed as one
  genomic SNV and sent through an injected ``Normalizer``
  (``raptor.ingest.normalizer.SeqRepoGenomicNormalizer`` in real use) via a
  freshly constructed ``raptor.ingest.model.RawVariant`` -- the ONLY way an
  SPDI is ever emitted. A ``ManualQueueItem`` with
  ``error_code == "REF_MISMATCH"`` maps to
  ``GENOMIC_REFERENCE_MISMATCH``/``REFERENCE_ALLELE_MISMATCH``; every other
  manual/error outcome raises ``NormalizationOutcomeError`` and aborts the
  run rather than being silently dropped or guessed.

Every row is validated (exact header, exact row count, a finite numeric
``score_raw`` string copied verbatim, one output row per input row) via
``model.NormalizedFunctionalRow`` before being returned as a plain dict
(``.to_dict()``) -- the only shape handed back across this module's public
API.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import re
from typing import Any

from raptor.ingest.model import ManualQueueItem, NormalizedVariant, RawVariant

from .model import (
    GENE,
    NormalizationContractError,
    NormalizationOutcomeError,
    NormalizedFunctionalRow,
    ScoreValidationError,
)

#: A simple missense HGVS protein-change shape: ``p.<Xxx><digits><Xxx>``.
#: Anything ending in ``=`` (synonymous) or containing ``Ter`` (nonsense) is
#: classified before this pattern is even tried; anything else (splice,
#: frameshift, extension, unknown ``p.?`` notation, ...) falls through to
#: ``OTHER`` rather than being guessed as MISSENSE.
_MISSENSE_HGVS_P_RE = re.compile(r"^p\.[A-Za-z]{3}\d+[A-Za-z]{3}$")

#: A single, precise genomic SNV shape once the (already prefix-checked and
#: separator-normalized) genomic accession has been stripped, e.g.
#: ``g.2044829C>T``. ``fullmatch`` is REQUIRED here (never ``match``): a
#: trailing garbage suffix (e.g. ``g.2044829C>Tjunk``) must be rejected, not
#: silently accepted by an unanchored end.
_SGE_SNV_RE = re.compile(r"^g\.(\d+)([ACGT])>([ACGT])$")

#: A bare (not source-accession-prefixed) cDNA HGVS value, e.g.
#: ``c.100A>G`` or ``c.100_102delinsAGT``. Must never contain a colon (that
#: would indicate a smuggled transcript/accession prefix) and must never be
#: blank.
_MAVEDB_BARE_CDNA_RE = re.compile(r"^c\.[^\s:]+$")

#: MaveDB cliPE only ever emits a supported source hgvs_pro SHAPE:
#: missense, synonymous (``=``) or nonsense (``Ter``) -- never an
#: unrecognized/blank shape (spec ``acceptance_criteria`` FN-04).
_MAVEDB_ALLOWED_VARIANT_KINDS = frozenset({"MISSENSE", "SYNONYMOUS", "STOP_GAINED"})

#: IGVF VAMP-seq only ever emits a supported source hgvs_p SHAPE: missense
#: or synonymous -- never a nonsense/unrecognized/blank shape.
_VAMP_ALLOWED_VARIANT_KINDS = frozenset({"MISSENSE", "SYNONYMOUS"})


def _classify_variant_kind(hgvs_p: str | None) -> str:
    """Classify a protein-change HGVS string into one of MISSENSE /
    SYNONYMOUS / STOP_GAINED / OTHER. Never guesses: any shape this
    doesn't recognize (splice notation, frameshift, ``p.?``, ...) is
    OTHER, never forced into MISSENSE/STOP_GAINED."""
    if not hgvs_p:
        return "OTHER"
    text = hgvs_p.strip()
    if text.endswith("="):
        return "SYNONYMOUS"
    if "Ter" in text:
        return "STOP_GAINED"
    if _MISSENSE_HGVS_P_RE.match(text):
        return "MISSENSE"
    return "OTHER"


def _validate_score(value: Any, *, source_id: str, source_row: int) -> str:
    """Return ``value`` unchanged if it is a finite numeric string;
    otherwise raise ``ScoreValidationError``. Never reformats/rounds the
    value -- ``score_raw`` is copied verbatim without numeric
    transformation."""
    if not isinstance(value, str) or value.strip() == "":
        raise ScoreValidationError(
            f"{source_id} row {source_row}: score value is blank or not a string ({value!r})"
        )
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ScoreValidationError(
            f"{source_id} row {source_row}: score {value!r} is not a numeric string"
        ) from exc
    if not math.isfinite(parsed):
        raise ScoreValidationError(f"{source_id} row {source_row}: score {value!r} is not finite")
    return value


def _split_tabular_rows(text: str) -> list[list[str]]:
    """Parse ``text`` as tab-separated rows using the standard ``csv``
    module (``delimiter='\\t'``) -- never a manual ``str.split`` on
    ``'\\n'``/``'\\t'``, which corrupts the final field of every row
    (leaving a trailing ``'\\r'`` attached to it, and to the header) on a
    CRLF-terminated file. ``csv.reader`` parses LF- and CRLF-terminated
    input identically (verified: a Windows-style ``\\r\\n`` line ending
    is consumed as the record terminator, never left attached to the
    last field's exact value), and a single trailing blank line (the
    file's final newline) yields no extra empty row, exactly like a
    LF-terminated file. Field values themselves are never stripped/
    altered beyond removing the record terminator."""
    return list(csv.reader(io.StringIO(text), delimiter="\t"))


def _decode_gzip_tsv(payload: bytes, *, source_id: str) -> list[list[str]]:
    """Gunzip + UTF-8 decode ``payload`` into a list of tab-split rows
    (header included). Wraps any decode failure -- a bad gzip stream, or
    bytes that are not valid UTF-8 -- as ``NormalizationContractError``
    rather than letting a raw ``OSError``/``UnicodeDecodeError`` escape."""
    try:
        raw = gzip.decompress(payload)
    except OSError as exc:
        raise NormalizationContractError(
            f"{source_id}: failed to gunzip source payload: {exc}"
        ) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NormalizationContractError(
            f"{source_id}: failed to decode gunzipped source payload as UTF-8: {exc}"
        ) from exc
    return _split_tabular_rows(text)


def _require_header_and_row_count(
    rows: list[list[str]], *, source_id: str, expected_header: list[str], expected_rows: int
) -> list[list[str]]:
    if not rows:
        raise NormalizationContractError(f"{source_id}: source payload is empty (no header row)")
    header = rows[0]
    if header != list(expected_header):
        raise NormalizationContractError(
            f"{source_id}: unexpected header {header!r} (expected {list(expected_header)!r})"
        )
    data_rows = rows[1:]
    if len(data_rows) != expected_rows:
        raise NormalizationContractError(
            f"{source_id}: expected exactly {expected_rows} rows, found {len(data_rows)}"
        )
    for index, values in enumerate(data_rows, start=1):
        if len(values) != len(header):
            raise NormalizationContractError(
                f"{source_id} row {index}: has {len(values)} fields, expected {len(header)}"
            )
    return data_rows


def normalize_mavedb(
    *,
    source_id: str,
    csv_text: str,
    expected_header: list[str],
    expected_rows: int,
    transcript: str,
) -> list[dict[str, Any]]:
    """Normalize a MaveDB cliPE score CSV (``accession, hgvs_nt,
    hgvs_splice, hgvs_pro, score``): each bare ``c.`` value is prefixed
    with ``transcript`` (spec ``mavedb_clipe.identity.hgvs_c_rule``); no
    genomic SPDI is ever emitted (``TRANSCRIPT_ONLY_PROJECTOR_REQUIRED`` /
    ``CDNA_PROJECTOR_REQUIRED`` on every row)."""
    reader = csv.reader(io.StringIO(csv_text))
    all_rows = [row for row in reader]
    data_rows = _require_header_and_row_count(
        all_rows, source_id=source_id, expected_header=expected_header, expected_rows=expected_rows
    )
    header = list(expected_header)

    results: list[dict[str, Any]] = []
    for index, values in enumerate(data_rows, start=1):
        record = dict(zip(header, values))
        accession = record["accession"]
        if not isinstance(accession, str) or not accession.strip():
            raise NormalizationContractError(f"{source_id} row {index}: accession must be a non-blank string")
        hgvs_nt = record["hgvs_nt"]
        if not isinstance(hgvs_nt, str) or not _MAVEDB_BARE_CDNA_RE.match(hgvs_nt):
            raise NormalizationContractError(
                f"{source_id} row {index}: hgvs_nt {hgvs_nt!r} is not a bare, non-blank pinned "
                f"{transcript} c. source value"
            )
        score_raw = _validate_score(record["score"], source_id=source_id, source_row=index)
        hgvs_c = f"{transcript}:{hgvs_nt}"
        hgvs_p = record["hgvs_pro"]
        variant_kind = _classify_variant_kind(hgvs_p)
        if variant_kind not in _MAVEDB_ALLOWED_VARIANT_KINDS:
            raise NormalizationContractError(
                f"{source_id} row {index}: hgvs_pro {hgvs_p!r} is not a supported source form "
                "(missense, synonymous, Ter)"
            )
        row = NormalizedFunctionalRow(
            source_id=source_id,
            source_row=index,
            source_record_id=accession,
            gene=GENE,
            assembly=None,
            transcript=transcript,
            protein_accession=None,
            hgvs_c=hgvs_c,
            hgvs_p=hgvs_p,
            hgvs_g=None,
            spdi=None,
            variant_kind=variant_kind,
            identity_state="TRANSCRIPT_ONLY_PROJECTOR_REQUIRED",
            unresolved_reason="CDNA_PROJECTOR_REQUIRED",
            score_name="score",
            score_raw=score_raw,
        )
        results.append(row.to_dict())
    return results


def normalize_vamp_seq(
    *,
    source_id: str,
    tsv_gz_bytes: bytes,
    expected_header: list[str],
    expected_rows: int,
    required_protein_accession: str,
) -> list[dict[str, Any]]:
    """Normalize an IGVF VAMP-seq gzip TSV (``variant, score,
    standard_error, rep1, rep2, rep3, functional_class``): every
    ``variant`` token must carry ``required_protein_accession`` verbatim;
    protein identity is preserved but no transcript/genomic identity is
    ever fabricated (``PROTEIN_ONLY_CROSSWALK_REQUIRED`` /
    ``NUCLEOTIDE_CROSSWALK_REQUIRED`` on every row). ``functional_class``
    is read but never copied into the normalized row."""
    all_rows = _decode_gzip_tsv(tsv_gz_bytes, source_id=source_id)
    data_rows = _require_header_and_row_count(
        all_rows, source_id=source_id, expected_header=expected_header, expected_rows=expected_rows
    )
    header = list(expected_header)
    prefix = required_protein_accession + ":"

    results: list[dict[str, Any]] = []
    for index, values in enumerate(data_rows, start=1):
        record = dict(zip(header, values))
        variant_token = record["variant"]
        if not variant_token.startswith(prefix):
            raise NormalizationContractError(
                f"{source_id} row {index}: variant token {variant_token!r} does not carry the "
                f"required protein accession {required_protein_accession!r}"
            )
        hgvs_p = variant_token[len(prefix) :]
        variant_kind = _classify_variant_kind(hgvs_p)
        if variant_kind not in _VAMP_ALLOWED_VARIANT_KINDS:
            raise NormalizationContractError(
                f"{source_id} row {index}: hgvs_p {hgvs_p!r} is not a supported source form "
                "(missense, synonymous)"
            )
        score_raw = _validate_score(record["score"], source_id=source_id, source_row=index)
        row = NormalizedFunctionalRow(
            source_id=source_id,
            source_row=index,
            source_record_id=variant_token,
            gene=GENE,
            assembly=None,
            transcript=None,
            protein_accession=required_protein_accession,
            hgvs_c=None,
            hgvs_p=hgvs_p,
            hgvs_g=None,
            spdi=None,
            variant_kind=variant_kind,
            identity_state="PROTEIN_ONLY_CROSSWALK_REQUIRED",
            unresolved_reason="NUCLEOTIDE_CROSSWALK_REQUIRED",
            score_name="score",
            score_raw=score_raw,
        )
        results.append(row.to_dict())
    return results


def normalize_sge(
    *,
    source_id: str,
    tsv_gz_bytes: bytes,
    expected_header: list[str],
    expected_rows: int,
    expected_source_transcript: str,
    expected_source_genomic_accession: str,
    normalized_transcript: str,
    normalized_genomic_accession: str,
    assembly: str,
    gene: str,
    normalizer: Any,
    normalizer_config: Any,
) -> list[dict[str, Any]]:
    """Normalize an IGVF SGE gzip TSV. Source accession separators
    (``expected_source_transcript``/``expected_source_genomic_accession``,
    e.g. ``NM_000548_5``/``NC_000016_10``) are checked EXACTLY before being
    rewritten to their dotted (``normalized_transcript``/
    ``normalized_genomic_accession``) form. The three ``c.=``/``g.=``/
    ``p.=`` rows are explicit ``REFERENCE_CONTROL`` rows; every other row
    is parsed as one genomic SNV, wrapped in a fresh
    ``raptor.ingest.model.RawVariant`` and sent through ``normalizer``.
    ``NormalizedVariant`` outcomes verify ``GENOMIC_SPDI_VERIFIED``;
    ``ManualQueueItem(error_code="REF_MISMATCH")`` maps to
    ``GENOMIC_REFERENCE_MISMATCH``/``REFERENCE_ALLELE_MISMATCH``; every
    other outcome raises ``NormalizationOutcomeError`` and aborts the
    entire run."""
    all_rows = _decode_gzip_tsv(tsv_gz_bytes, source_id=source_id)
    data_rows = _require_header_and_row_count(
        all_rows, source_id=source_id, expected_header=expected_header, expected_rows=expected_rows
    )
    header = list(expected_header)

    source_transcript_prefix = expected_source_transcript + ":"
    source_genomic_prefix = expected_source_genomic_accession + ":"
    control_hgvs_nt = source_transcript_prefix + "c.="
    control_hgvs_g = source_genomic_prefix + "g.="
    source_file_checksum = hashlib.sha256(tsv_gz_bytes).hexdigest()

    results: list[dict[str, Any]] = []
    for index, values in enumerate(data_rows, start=1):
        record = dict(zip(header, values))
        hgvs_nt_raw = record["hgvs_nt"]
        hgvs_g_raw = record["hgvs_g"]
        hgvs_p = record["hgvs_p"]

        if not hgvs_nt_raw.startswith(source_transcript_prefix):
            raise NormalizationContractError(
                f"{source_id} row {index}: hgvs_nt {hgvs_nt_raw!r} does not start with the "
                f"expected source transcript accession prefix {source_transcript_prefix!r}"
            )
        if not hgvs_g_raw.startswith(source_genomic_prefix):
            raise NormalizationContractError(
                f"{source_id} row {index}: hgvs_g {hgvs_g_raw!r} does not start with the "
                f"expected source genomic accession prefix {source_genomic_prefix!r}"
            )

        score_raw = _validate_score(record["pS6_score"], source_id=source_id, source_row=index)

        hgvs_c = normalized_transcript + hgvs_nt_raw[len(expected_source_transcript) :]
        hgvs_g = normalized_genomic_accession + hgvs_g_raw[len(expected_source_genomic_accession) :]

        is_control = (
            hgvs_nt_raw == control_hgvs_nt
            and hgvs_g_raw == control_hgvs_g
            and hgvs_p.strip() == "p.="
        )

        if is_control:
            row = NormalizedFunctionalRow(
                source_id=source_id,
                source_row=index,
                source_record_id=hgvs_g,
                gene=gene,
                assembly=assembly,
                transcript=normalized_transcript,
                protein_accession=None,
                hgvs_c=hgvs_c,
                hgvs_p=hgvs_p,
                hgvs_g=hgvs_g,
                spdi=None,
                variant_kind="REFERENCE_CONTROL",
                identity_state="REFERENCE_CONTROL",
                unresolved_reason="NOT_A_VARIANT",
                score_name="pS6_score",
                score_raw=score_raw,
            )
            results.append(row.to_dict())
            continue

        snv_match = _SGE_SNV_RE.fullmatch(hgvs_g_raw[len(source_genomic_prefix) :])
        if snv_match is None:
            raise NormalizationContractError(
                f"{source_id} row {index}: non-control hgvs_g {hgvs_g_raw!r} is not a genomic SNV"
            )
        position = int(snv_match.group(1))
        ref = snv_match.group(2)
        alt = snv_match.group(3)

        raw_variant = RawVariant(
            chromosome=normalized_genomic_accession,
            position=position,
            ref=ref,
            alt=alt,
            gene=gene,
            variation_id=hgvs_g,
            snapshot_id=source_id,
            snapshot_date="",
            source_file_checksum=source_file_checksum,
            row_locator=f"{source_id}:row{index}",
            raw_source_value=json.dumps(record, sort_keys=True),
        )
        outcome = normalizer.normalize(raw_variant, normalizer_config)

        if isinstance(outcome, NormalizedVariant):
            expected_spdi = f"{normalized_genomic_accession}:{position - 1}:{ref}:{alt}"
            if outcome.variant_id != expected_spdi:
                raise NormalizationOutcomeError(
                    f"{source_id} row {index}: normalizer returned SPDI {outcome.variant_id!r} which "
                    f"does not match the expected canonical SNV SPDI {expected_spdi!r} derived from "
                    "the source hgvs_g; direct arithmetic without reference validation is forbidden "
                    "and a mismatched normalizer result is never emitted"
                )
            spdi = outcome.variant_id
            identity_state = "GENOMIC_SPDI_VERIFIED"
            unresolved_reason = None
        elif isinstance(outcome, ManualQueueItem) and outcome.error_code == "REF_MISMATCH":
            spdi = None
            identity_state = "GENOMIC_REFERENCE_MISMATCH"
            unresolved_reason = "REFERENCE_ALLELE_MISMATCH"
        else:
            raise NormalizationOutcomeError(
                f"{source_id} row {index}: normalizer outcome {outcome!r} is neither a successful "
                "NormalizedVariant nor a ManualQueueItem(error_code='REF_MISMATCH'); every other "
                "manual/error outcome aborts the run"
            )

        row = NormalizedFunctionalRow(
            source_id=source_id,
            source_row=index,
            source_record_id=hgvs_g,
            gene=gene,
            assembly=assembly,
            transcript=normalized_transcript,
            protein_accession=None,
            hgvs_c=hgvs_c,
            hgvs_p=hgvs_p,
            hgvs_g=hgvs_g,
            spdi=spdi,
            variant_kind=_classify_variant_kind(hgvs_p),
            identity_state=identity_state,
            unresolved_reason=unresolved_reason,
            score_name="pS6_score",
            score_raw=score_raw,
        )
        results.append(row.to_dict())
    return results


__all__ = ["normalize_mavedb", "normalize_vamp_seq", "normalize_sge"]
