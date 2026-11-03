"""RAPTOR v2 VAMP-seq protein -> genomic SPDI crosswalk -- frozen-input
validation and the pure, offline, transport/normalizer-injected crosswalk
builder.

``validate_frozen_vamp_scores`` re-verifies the frozen IGVF VAMP-seq score
TSV (gzip-compressed) against this slice's pinned header/hash/byte-length/
row-count/protein-accession pins (spec ``inputs.frozen_vamp_scores``), and
returns one parsed record per data row -- ``{"source_row",
"protein_variant"}`` -- in ascending, file-order ``source_row`` (1-based).
Every non-identity score column (abundance score, standard error,
replicates, functional class) is read only far enough to validate the
pinned header shape and byte-count; NONE of those values are ever
returned or carried into a crosswalk row.

``validate_reference_fasta_checksum`` verifies the pinned ``NC_000016.10``
FASTA's actual sha256 -- this MUST be checked, and MUST succeed, BEFORE
any archive/score byte is even parsed (spec's coordinate-acceptance rule
depends on this reference being trustworthy).

``build_vamp_genomic_crosswalk`` is the single, pure orchestration entry
point ``scripts/fetch_tsc2_vamp_genomic_crosswalk.py`` calls: it verifies
the reference FASTA checksum FIRST, then the Zenodo archive bytes
(``archive.validate_zenodo_archive_and_extract_members`` +
``archive.parse_gmm_identity_rows``), then the frozen score bytes
(``validate_frozen_vamp_scores``), then joins every score row (in its own
file order) against the archive by its FULL protein token
(``{protein_accession}:{hgvs_p}``) -- never a bare residue/synonym match.
An archive-absent score row is retained as ``ARCHIVE_CROSSWALK_ABSENT``.
An archive-matched row is accepted as a genomic coordinate ONLY when
``len(ref_allele) == end - start + 1`` AND the (injected or default)
pinned-FASTA slice at that 1-based-inclusive interval equals
``ref_allele`` exactly -- ANY other interpretation (zero-based, half-
open, alternate offset) is explicitly forbidden by the spec and is never
attempted. An accepted row is normalized ONLY through the injected
``normalizer`` (the same ``raptor.ingest.normalizer.Normalizer`` protocol
used elsewhere in this repository); any ``ManualQueueItem`` outcome (a
normalizer-declared manual/error outcome) aborts the WHOLE run rather
than being silently skipped, since a reference-consistent row that the
normalizer itself cannot resolve indicates a deeper problem than a single
bad row. A returned ``NormalizedVariant`` is independently re-verified:
its ``variant_id`` must be pinned to ``genomic_accession`` and, for a
simple single-base substitution, must retain the exact source ref/alt
(an MNV/delins-shape normalization is allowed to differ, since legitimate
canonicalization may shift/repack a multi-base representation).

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from .archive import parse_gmm_identity_rows, validate_zenodo_archive_and_extract_members
from .model import VampGenomicCrosswalkRow

#: The frozen IGVF VAMP-seq score TSV's exact pinned header (spec
#: ``inputs.frozen_vamp_scores`` / ``configs/external/
#: tsc2_functional_identity_normalization_v1.yaml``'s ``igvf_vamp_seq``
#: source rule) -- never caller-configurable, since this slice is
#: permanently bound to this one frozen artifact.
VAMP_SCORE_HEADER = ["variant", "score", "standard_error", "rep1", "rep2", "rep3", "functional_class"]

#: The gene pin this whole slice is bound to.
GENE = "TSC2"

_CHUNK_SIZE = 1024 * 1024  # 1 MiB

#: Bare cDNA SNV shape: ``c.<pos><ref>><alt>`` -- always affects exactly 1
#: transcript base.
_CDNA_SNV_RE = re.compile(r"^c\.\d+[ACGT]>[ACGT]$")
#: Bare cDNA span shapes this frozen GMM archive actually contains:
#: ``c.<start>_<end>delins<seq>`` and ``c.<start>_<end>inv`` -- both affect
#: exactly ``end - start + 1`` transcript bases.
_CDNA_SPAN_RE = re.compile(r"^c\.(?P<start>\d+)_(?P<end>\d+)(?:delins[ACGT]+|inv)$")


def _parse_cdna_affected_length(hgvs_c: Any) -> int | None:
    """Parse the number of transcript bases a bare cDNA ``hgvs_c`` token
    (``c.<pos><ref>><alt>``, ``c.<start>_<end>delins<seq>``, or
    ``c.<start>_<end>inv``) claims to replace/invert -- 1 for an SNV,
    ``end - start + 1`` for a delins/inv span. Returns ``None`` for any
    other/unparseable shape (e.g. a reversed span), which the caller MUST
    treat as a length-equivalence failure, never as "no constraint"."""
    if not isinstance(hgvs_c, str):
        return None
    if _CDNA_SNV_RE.match(hgvs_c):
        return 1
    match = _CDNA_SPAN_RE.match(hgvs_c)
    if match:
        start = int(match["start"])
        end = int(match["end"])
        if end < start:
            return None
        return end - start + 1
    return None


class VampCrosswalkIngestError(RuntimeError):
    """Base error for this slice's ingest-time domain errors."""


class FrozenInputError(VampCrosswalkIngestError):
    """Raised when the frozen IGVF VAMP-seq score TSV's header, row count,
    sha256/md5/byte-length, or per-row protein-token shape/uniqueness does
    not match this slice's frozen expectations."""


class ReferenceIntegrityError(VampCrosswalkIngestError):
    """Raised when the pinned ``NC_000016.10`` reference FASTA is missing
    or its actual sha256 does not match the pinned value. Always raised
    (and always succeeds) before any archive/score byte is parsed."""


class CrosswalkNormalizationError(VampCrosswalkIngestError):
    """Raised when the injected normalizer returns a manual/error outcome
    for a reference-consistent row (aborting the whole run, never silently
    skipped), or when a returned ``NormalizedVariant`` fails independent
    re-verification (wrong pinned accession, non-ACGT alleles, or -- for a
    simple single-base substitution -- a ref/alt that no longer matches
    the source archive row)."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_reference_fasta_checksum(*, reference_fasta_path: Path | str, expected_sha256: str) -> str:
    """Return the actual sha256 of ``reference_fasta_path`` if it matches
    ``expected_sha256``; otherwise raise ``ReferenceIntegrityError``. Also
    raises if the file does not exist. This MUST be called -- and MUST
    succeed -- before any archive/score byte is parsed."""
    path = Path(reference_fasta_path)
    if not path.is_file():
        raise ReferenceIntegrityError(
            f"pinned reference FASTA not found at {path}; refusing to build any crosswalk row "
            "without a verified reference"
        )
    actual = _sha256_file(path)
    if actual.lower() != str(expected_sha256).lower():
        raise ReferenceIntegrityError(
            f"reference FASTA checksum mismatch at {path}: pinned {expected_sha256!r} != actual "
            f"sha256 {actual!r}; refusing to build any crosswalk row against an unverified/altered "
            "reference"
        )
    return actual


def validate_frozen_vamp_scores(
    *,
    score_tsv_gz_bytes: bytes,
    expected_header: list[str],
    expected_sha256: str,
    expected_md5: str,
    expected_byte_length: int,
    expected_rows: int,
    required_protein_accession: str,
) -> list[dict[str, Any]]:
    """Re-verify the frozen, gzip-compressed IGVF VAMP-seq score TSV and
    return one parsed record per data row: ``{"source_row",
    "protein_variant"}``, in ascending ``source_row`` (1-based, matching
    file order). Raises ``FrozenInputError`` on any byte-length/sha256/
    md5/header/row-count mismatch, a protein token that does not carry
    the pinned ``required_protein_accession`` prefix, or a duplicate
    protein token."""
    if not isinstance(score_tsv_gz_bytes, bytes):
        raise FrozenInputError(f"score_tsv_gz_bytes must be bytes, got {type(score_tsv_gz_bytes).__name__}")
    if len(score_tsv_gz_bytes) != expected_byte_length:
        raise FrozenInputError(
            f"score artifact byte_length mismatch: expected {expected_byte_length!r}, observed "
            f"{len(score_tsv_gz_bytes)!r}"
        )
    actual_sha256 = hashlib.sha256(score_tsv_gz_bytes).hexdigest()
    if actual_sha256.lower() != str(expected_sha256).lower():
        raise FrozenInputError(
            f"score artifact sha256 mismatch: expected {expected_sha256!r}, observed {actual_sha256!r}"
        )
    actual_md5 = hashlib.md5(score_tsv_gz_bytes).hexdigest()  # nosec B303 - matching pinned upstream MD5
    if actual_md5.lower() != str(expected_md5).lower():
        raise FrozenInputError(f"score artifact md5 mismatch: expected {expected_md5!r}, observed {actual_md5!r}")

    try:
        text = gzip.decompress(score_tsv_gz_bytes).decode("utf-8")
    except OSError as exc:
        raise FrozenInputError(f"score artifact is not valid gzip: {exc}") from exc

    lines = [line for line in text.splitlines() if line != ""]
    if not lines:
        raise FrozenInputError("score artifact is empty (no header row)")
    header = lines[0].split("\t")
    if header != list(expected_header):
        raise FrozenInputError(f"score artifact unexpected header {header!r} (expected {list(expected_header)!r})")
    data_lines = lines[1:]
    if len(data_lines) != expected_rows:
        raise FrozenInputError(f"score artifact expected exactly {expected_rows} rows, found {len(data_lines)}")

    seen_tokens: set[str] = set()
    parsed: list[dict[str, Any]] = []
    prefix = f"{required_protein_accession}:p."
    for index, line in enumerate(data_lines, start=1):
        values = line.split("\t")
        if len(values) != len(header):
            raise FrozenInputError(f"score artifact row {index}: has {len(values)} fields, expected {len(header)}")
        protein_variant = values[0]
        if not protein_variant.startswith(prefix):
            raise FrozenInputError(
                f"score artifact row {index}: protein token {protein_variant!r} does not carry the "
                f"pinned prefix {prefix!r}"
            )
        if protein_variant in seen_tokens:
            raise FrozenInputError(f"score artifact row {index}: duplicate protein token {protein_variant!r}")
        seen_tokens.add(protein_variant)
        parsed.append({"source_row": index, "protein_variant": protein_variant})

    return parsed


def _build_fasta_index(path: Path, *, accession: str) -> dict[str, int]:
    with open(path, "rb") as handle:
        header_line = handle.readline()
        if not header_line.startswith(b">"):
            raise ReferenceIntegrityError(f"reference FASTA {path} does not start with a '>' header line")
        tokens = header_line[1:].split()
        header_id = tokens[0].decode("ascii", errors="replace") if tokens else ""
        if header_id != accession:
            raise ReferenceIntegrityError(
                f"reference FASTA {path} header {header_id!r} does not match expected accession {accession!r}"
            )
        offset = handle.tell()
        first_seq_line = handle.readline()
        if not first_seq_line:
            raise ReferenceIntegrityError(f"reference FASTA {path} has no sequence data after its header")
        linewidth = len(first_seq_line)
        linebases = len(first_seq_line.rstrip(b"\r\n"))
        if linebases <= 0:
            raise ReferenceIntegrityError(f"reference FASTA {path} first sequence line is empty")
    return {"offset": offset, "linebases": linebases, "linewidth": linewidth}


def _read_fasta_bases(path: Path, index: dict[str, int], *, position0: int, length: int) -> str:
    if length <= 0:
        return ""
    linebases = index["linebases"]
    linewidth = index["linewidth"]
    offset = index["offset"]
    line_number, line_offset = divmod(position0, linebases)
    byte_offset = offset + line_number * linewidth + line_offset
    lines_spanned = ((line_offset + length - 1) // linebases) + 1
    read_len = lines_spanned * linewidth
    with open(path, "rb") as handle:
        handle.seek(byte_offset)
        raw = handle.read(read_len)
    bases = raw.translate(None, b"\r\n").decode("ascii", errors="replace").upper()
    if len(bases) < length:
        raise ReferenceIntegrityError(
            f"reference FASTA {path} does not contain {length} base(s) at 0-based position {position0} "
            "(sequence exhausted)"
        )
    return bases[:length]


def _make_default_fasta_deleted_allele_checker(*, reference_fasta_path: Path, accession: str) -> Callable[..., str]:
    """Build the DEFAULT ``fasta_deleted_allele_checker`` used when a
    caller (the real operator) does not inject one: a small, dependency-
    free FASTA random-access reader (no pysam requirement) built once from
    the already-checksum-verified reference FASTA."""
    index = _build_fasta_index(reference_fasta_path, accession=accession)

    def checker(*, accession: str, start_1based: int, end_1based: int, expected_ref: str) -> str:
        length = end_1based - start_1based + 1
        return _read_fasta_bases(reference_fasta_path, index, position0=start_1based - 1, length=length)

    return checker


def build_vamp_genomic_crosswalk(
    *,
    source_id: str,
    score_tsv_gz_bytes: bytes,
    archive_zip_bytes: bytes,
    score_pins: dict[str, Any],
    archive_pins: dict[str, Any],
    reference_fasta_path: Path | str,
    expected_reference_sha256: str,
    required_columns: list[str],
    required_values: dict[str, str],
    transcript: str,
    genomic_accession: str,
    assembly: str,
    normalizer: Any,
    normalizer_config: Any,
    fasta_deleted_allele_checker: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Build the deterministic VAMP-seq protein -> genomic SPDI crosswalk
    for every row of the frozen score file, in that file's own order.
    Returns ``{"crosswalk_rows": list[dict], "status_counts": dict[str,
    int]}``. Raises ``ReferenceIntegrityError`` before any archive/score
    byte is parsed on a reference checksum failure;
    ``archive.ArchiveValidationError``/``FrozenInputError`` on an archive/
    score integrity failure; ``CrosswalkNormalizationError`` the instant
    the injected normalizer returns a manual/error outcome for a
    reference-consistent row, or the instant a returned
    ``NormalizedVariant`` fails independent re-verification -- both abort
    the WHOLE run rather than skipping a row."""
    validate_reference_fasta_checksum(
        reference_fasta_path=reference_fasta_path, expected_sha256=expected_reference_sha256
    )

    required_members = archive_pins["required_members"]
    expected_archive = {key: value for key, value in archive_pins.items() if key != "required_members"}
    members = validate_zenodo_archive_and_extract_members(
        archive_bytes=archive_zip_bytes, expected_archive=expected_archive, required_members=required_members
    )
    archive_rows = parse_gmm_identity_rows(
        members=members, required_columns=required_columns, required_values=required_values
    )
    protein_accession = score_pins["protein_accession"]
    archive_by_token = {f"{protein_accession}:{row['protein_variant']}": row for row in archive_rows}

    score_rows = validate_frozen_vamp_scores(
        score_tsv_gz_bytes=score_tsv_gz_bytes,
        expected_header=VAMP_SCORE_HEADER,
        expected_sha256=score_pins["sha256"],
        expected_md5=score_pins["md5"],
        expected_byte_length=score_pins["byte_length"],
        expected_rows=score_pins["row_count"],
        required_protein_accession=protein_accession,
    )

    if fasta_deleted_allele_checker is None:
        fasta_deleted_allele_checker = _make_default_fasta_deleted_allele_checker(
            reference_fasta_path=Path(reference_fasta_path), accession=genomic_accession
        )

    crosswalk_rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    def _finalize(row_fields: dict[str, Any]) -> None:
        built = VampGenomicCrosswalkRow(**row_fields).to_dict()
        crosswalk_rows.append(built)
        status_counts[built["status"]] = status_counts.get(built["status"], 0) + 1

    for score_row in score_rows:
        source_row = score_row["source_row"]
        full_token = score_row["protein_variant"]
        base_fields = {"source_id": source_id, "source_row": source_row, "protein_variant": full_token}

        archive_row = archive_by_token.get(full_token)
        if archive_row is None:
            _finalize(
                {
                    **base_fields,
                    "archive_member": None,
                    "archive_row": None,
                    "transcript": None,
                    "hgvs_c": None,
                    "assembly": None,
                    "genomic_spdi": None,
                    "status": "ARCHIVE_CROSSWALK_ABSENT",
                    "unresolved_reason": "PROTEIN_VARIANT_NOT_IN_ARCHIVE",
                }
            )
            continue

        archive_provenance = {
            "archive_member": archive_row["archive_member"],
            "archive_row": archive_row["archive_row"],
            "transcript": transcript,
            "hgvs_c": archive_row["hgvs_c"],
        }
        ref_allele = archive_row["ref_allele"]
        alt_allele = archive_row["alt_allele"]
        start = archive_row["source_start"]
        end = archive_row["source_end"]
        interval_length = end - start + 1

        # cDNA/genomic length-equivalence gate (spec: block a cross-exon
        # pseudo-variant BEFORE any FASTA read or normalizer call). The
        # archive's hg38_start/hg38_end span can be a large, cross-exon
        # (intron-spanning) genomic footprint EVEN WHEN ref_allele's own
        # length happens to equal that footprint -- the only trustworthy
        # cross-check is against the cDNA (hgvs_c) token's OWN claimed
        # affected length, which is bounded by the transcript's exonic
        # arithmetic and is never itself cross-exon.
        cdna_length = _parse_cdna_affected_length(archive_row["hgvs_c"])
        if (
            cdna_length is None
            or cdna_length != len(ref_allele)
            or cdna_length != len(alt_allele)
            or cdna_length != interval_length
        ):
            _finalize(
                {
                    **base_fields,
                    **archive_provenance,
                    "assembly": None,
                    "genomic_spdi": None,
                    "status": "SOURCE_COORDINATE_CDNA_LENGTH_MISMATCH",
                    "unresolved_reason": "SOURCE_GENOMIC_INTERVAL_NOT_EQUIVALENT_TO_CDNA_REPLACEMENT",
                }
            )
            continue

        observed_ref = fasta_deleted_allele_checker(
            accession=genomic_accession, start_1based=start, end_1based=end, expected_ref=ref_allele
        )

        if observed_ref != ref_allele:
            _finalize(
                {
                    **base_fields,
                    **archive_provenance,
                    "assembly": None,
                    "genomic_spdi": None,
                    "status": "SOURCE_COORDINATE_REFERENCE_MISMATCH",
                    "unresolved_reason": "SOURCE_REF_DOES_NOT_MATCH_PINNED_FASTA",
                }
            )
            continue

        raw_variant = _RawVariantFactory.build(
            chromosome=genomic_accession,
            position=start,
            ref=ref_allele,
            alt=alt_allele,
            gene=GENE,
            archive_pins=archive_pins,
            archive_row=archive_row,
        )
        outcome = normalizer.normalize(raw_variant, normalizer_config)
        normalized = _require_normalized_variant(outcome, source_row=source_row)
        genomic_spdi = _verify_normalized_spdi(
            normalized.variant_id, genomic_accession=genomic_accession, ref=ref_allele, alt=alt_allele, source_row=source_row
        )

        _finalize(
            {
                **base_fields,
                **archive_provenance,
                "assembly": assembly,
                "genomic_spdi": genomic_spdi,
                "status": "CROSSWALK_SPDI_VERIFIED",
                "unresolved_reason": None,
            }
        )

    return {"crosswalk_rows": crosswalk_rows, "status_counts": status_counts}


class _RawVariantFactory:
    """Builds a ``raptor.ingest.model.RawVariant`` for one accepted
    archive row, lazily importing the ingest model (never at module import
    time, keeping this package importable even if ``raptor.ingest`` is
    unavailable in a minimal test environment)."""

    @staticmethod
    def build(*, chromosome: str, position: int, ref: str, alt: str, gene: str, archive_pins: dict[str, Any], archive_row: dict[str, Any]) -> Any:
        from raptor.ingest.model import RawVariant

        member = archive_row["archive_member"]
        row_locator = f"{member}:{archive_row['archive_row']}"
        return RawVariant(
            chromosome=chromosome,
            position=position,
            ref=ref,
            alt=alt,
            gene=gene,
            variation_id=archive_row["protein_variant"],
            snapshot_id=str(archive_pins.get("record_id", "")),
            snapshot_date=str(archive_pins.get("publication_date", "")),
            source_file_checksum=str(archive_pins.get("sha256", "")),
            row_locator=row_locator,
            raw_source_value=archive_row["hgvs_c"],
        )


def _require_normalized_variant(outcome: Any, *, source_row: int) -> Any:
    from raptor.ingest.model import ManualQueueItem, NormalizedVariant

    if isinstance(outcome, NormalizedVariant):
        return outcome
    if isinstance(outcome, ManualQueueItem):
        raise CrosswalkNormalizationError(
            f"source_row {source_row}: normalizer returned a manual/error outcome "
            f"(error_code={outcome.error_code!r}) for a reference-consistent row; aborting the whole "
            "run rather than silently skipping it"
        )
    raise CrosswalkNormalizationError(
        f"source_row {source_row}: normalizer returned an unrecognized outcome type {type(outcome).__name__}"
    )


def _verify_normalized_spdi(variant_id: Any, *, genomic_accession: str, ref: str, alt: str, source_row: int) -> str:
    if not isinstance(variant_id, str):
        raise CrosswalkNormalizationError(f"source_row {source_row}: normalizer variant_id is not a string: {variant_id!r}")
    spdi_re = re.compile(rf"^{re.escape(genomic_accession)}:(\d+):([ACGT]+):([ACGT]+)$")
    match = spdi_re.match(variant_id)
    if match is None:
        raise CrosswalkNormalizationError(
            f"source_row {source_row}: normalizer variant_id {variant_id!r} is not a canonical "
            f"{genomic_accession} SPDI"
        )
    normalized_ref, normalized_alt = match.group(2), match.group(3)
    if len(ref) == 1 and len(alt) == 1:
        # A simple single-base substitution must retain the EXACT source
        # ref/alt -- no shift/repack is ever legitimate for an SNV.
        if normalized_ref != ref or normalized_alt != alt:
            raise CrosswalkNormalizationError(
                f"source_row {source_row}: normalizer SNV ref/alt {normalized_ref}/{normalized_alt} does "
                f"not match the source archive row {ref}/{alt}"
            )
    return variant_id


__all__ = [
    "VAMP_SCORE_HEADER",
    "VampCrosswalkIngestError",
    "FrozenInputError",
    "ReferenceIntegrityError",
    "CrosswalkNormalizationError",
    "validate_frozen_vamp_scores",
    "validate_reference_fasta_checksum",
    "build_vamp_genomic_crosswalk",
]
