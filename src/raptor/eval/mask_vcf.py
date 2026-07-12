"""Streaming, TSC-scoped ClinVar VCF masking for held-out evaluation.

ClinVar's source VCF spans the genome, while RAPTOR deliberately pins only
the GRCh38 chromosome 9 and 16 reference FASTAs. This module therefore
passes non-TSC records through byte-for-byte and normalizes only precise
TSC-chromosome alleles before deciding whether to remove them.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Callable


class VcfMaskError(ValueError):
    """Raised when a source VCF cannot be masked without ambiguity."""


_ACCESSION_BY_CONTIG = {
    "9": "NC_000009.12",
    "chr9": "NC_000009.12",
    "NC_000009.12": "NC_000009.12",
    "16": "NC_000016.10",
    "chr16": "NC_000016.10",
    "NC_000016.10": "NC_000016.10",
}
_LITERAL_BASES = frozenset(b"ACGT")


@dataclass(frozen=True)
class VcfMaskLedger:
    source_path: str
    output_path: str
    input_sha256: str
    output_sha256: str
    input_records: int
    output_records: int
    target_records_normalized: int
    symbolic_target_records_preserved: int
    matched_records_removed: int
    matched_holdout_identities: tuple[str, ...]
    holdout_identities_not_present: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def write(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_binary(path: Path, mode: str) -> BinaryIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, mode)
    return open(path, mode)


def _is_literal_allele(value: bytes) -> bool:
    return bool(value) and all(base in _LITERAL_BASES for base in value.upper())


def mask_tsc_holdout_from_vcf(
    source_path: str | Path,
    output_path: str | Path,
    holdout_ids: frozenset[str],
    canonicalize: Callable[[str, int, str, str], str],
) -> VcfMaskLedger:
    """Remove held-out TSC identities from a ClinVar VCF in one streaming pass.

    Non-TSC records and header lines are copied as their original bytes.
    Precise chromosome 9/16 alleles are canonicalized to GRCh38 SPDI. A
    multi-allelic record that only partially matches the holdout fails loud,
    because editing its ALT and allele-indexed INFO fields safely would need a
    VCF-aware rewrite rather than line filtering.
    """
    source = Path(source_path).resolve()
    output = Path(output_path).resolve()
    if source == output:
        raise VcfMaskError("source and masked output paths must differ")
    if not source.is_file():
        raise VcfMaskError(f"source VCF does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)

    input_records = 0
    output_records = 0
    normalized_records = 0
    symbolic_records = 0
    removed_records = 0
    matched_ids: set[str] = set()

    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=output.suffix,
        dir=output.parent,
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)

    try:
        with _open_binary(source, "rb") as source_handle, _open_binary(temp_path, "wb") as output_handle:
            for line_no, raw_line in enumerate(source_handle, start=1):
                if raw_line.startswith(b"#"):
                    output_handle.write(raw_line)
                    continue

                input_records += 1
                fields = raw_line.rstrip(b"\r\n").split(b"\t")
                if len(fields) < 5:
                    raise VcfMaskError(
                        f"VCF data row {line_no} has {len(fields)} fields; expected at least 5"
                    )
                try:
                    chrom = fields[0].decode("ascii")
                except UnicodeDecodeError as exc:
                    raise VcfMaskError(f"VCF row {line_no} has a non-ASCII CHROM value") from exc
                accession = _ACCESSION_BY_CONTIG.get(chrom)
                if accession is None:
                    output_handle.write(raw_line)
                    output_records += 1
                    continue

                try:
                    position = int(fields[1])
                    ref = fields[3].decode("ascii").upper()
                    alts = [alt.decode("ascii").upper() for alt in fields[4].split(b",")]
                except (UnicodeDecodeError, ValueError) as exc:
                    raise VcfMaskError(f"VCF row {line_no} has invalid TSC coordinates/alleles") from exc
                if position <= 0:
                    raise VcfMaskError(f"VCF row {line_no} has non-positive POS {position}")

                if not _is_literal_allele(fields[3]) or any(
                    not _is_literal_allele(alt) for alt in fields[4].split(b",")
                ):
                    output_handle.write(raw_line)
                    output_records += 1
                    symbolic_records += 1
                    continue

                normalized_records += 1
                canonical_ids = tuple(
                    canonicalize(accession, position, ref, alt) for alt in alts
                )
                matched = tuple(identity in holdout_ids for identity in canonical_ids)
                if any(matched) and not all(matched):
                    raise VcfMaskError(
                        f"VCF row {line_no} is multi-allelic and only partly held out: "
                        f"{canonical_ids!r}"
                    )
                if all(matched):
                    removed_records += 1
                    matched_ids.update(canonical_ids)
                    continue

                output_handle.write(raw_line)
                output_records += 1

        if output_records != input_records - removed_records:
            raise VcfMaskError(
                "mask conservation failure: output_records != input_records - removed_records"
            )
        os.replace(temp_path, output)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    matched_sorted = tuple(sorted(matched_ids))
    return VcfMaskLedger(
        source_path=str(source),
        output_path=str(output),
        input_sha256=_sha256(source),
        output_sha256=_sha256(output),
        input_records=input_records,
        output_records=output_records,
        target_records_normalized=normalized_records,
        symbolic_target_records_preserved=symbolic_records,
        matched_records_removed=removed_records,
        matched_holdout_identities=matched_sorted,
        holdout_identities_not_present=tuple(sorted(holdout_ids - matched_ids)),
    )
