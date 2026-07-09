#!/usr/bin/env python
"""Fetch and verify RAPTOR's pinned genomic reference FASTAs.

The normalizer looks for ``{accession}.fasta`` under ``RAPTOR_SEQREPO_ROOT`` or
``~/raptor-refseq``. This utility uses the same layout, verifies the FASTAs
against the sha256 pins in ``configs/ingest/tsc.yaml``, and builds the pysam
``.fai`` index when constructing the reference.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SEQREPO_ROOT_ENV = "RAPTOR_SEQREPO_ROOT"
DEFAULT_SEQREPO_ROOT = Path.home() / "raptor-refseq"
DEFAULT_CONFIG = Path("configs") / "ingest" / "tsc.yaml"
CHUNK_SIZE = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

DOWNLOAD_SOURCES = {
    "NC_000009.12": (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        "?db=nuccore&id=NC_000009.12&rettype=fasta&retmode=text"
    ),
    "NC_000016.10": (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        "?db=nuccore&id=NC_000016.10&rettype=fasta&retmode=text"
    ),
}


class ReferenceFetchError(RuntimeError):
    """Base error for reference reconstruction failures."""


class ConfigPinError(ReferenceFetchError):
    """Raised when the config does not contain usable genomic reference pins."""


class ChecksumMismatchError(ReferenceFetchError):
    """Raised when an on-disk/downloaded FASTA does not match its pinned sha256."""


@dataclass(frozen=True)
class ReferenceResult:
    accession: str
    status: str
    path: Path
    sha256: str
    index_status: str


def resolve_reference_root() -> Path:
    return Path(os.environ.get(SEQREPO_ROOT_ENV) or DEFAULT_SEQREPO_ROOT).expanduser()


def _strip_inline_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def parse_reference_pins(config_path: str | os.PathLike[str]) -> dict[str, str]:
    """Return genomic accession -> sha256 pins from an ingest YAML config.

    This intentionally parses only the small YAML subset used by RAPTOR's ingest
    config so the script stays dependency-free apart from pysam for indexing.
    Transcript checksum placeholders are ignored; only per-gene
    ``genome_accession`` values with 64-hex ``reference_checksums`` are used.
    """
    path = Path(config_path)
    lines = path.read_text(encoding="utf-8").splitlines()

    genome_accessions: list[str] = []
    reference_checksums: dict[str, str] = {}
    in_reference_checksums = False

    for raw in lines:
        line = _strip_inline_comment(raw)
        if not line.strip():
            continue

        genome_match = re.match(r"^\s*genome_accession:\s*([A-Za-z0-9_.-]+)\s*$", line)
        if genome_match:
            accession = genome_match.group(1)
            if accession not in genome_accessions:
                genome_accessions.append(accession)

        if not in_reference_checksums:
            if re.match(r"^reference_checksums:\s*$", line):
                in_reference_checksums = True
            continue

        if raw[:1] not in (" ", "\t"):
            break

        checksum_match = re.match(r"^\s+([A-Za-z0-9_.-]+):\s*(.+?)\s*$", line)
        if checksum_match:
            accession, expected = checksum_match.groups()
            reference_checksums[accession] = _clean_scalar(expected)

    if not genome_accessions:
        raise ConfigPinError(f"no genome_accession entries found in {path}")

    pins: dict[str, str] = {}
    for accession, expected in reference_checksums.items():
        if accession not in genome_accessions:
            continue
        if not SHA256_RE.match(expected):
            raise ConfigPinError(
                f"reference checksum for genomic accession {accession!r} is not a sha256 pin: "
                f"{expected!r}"
            )
        pins[accession] = expected.lower()

    missing = [accession for accession in genome_accessions if accession not in pins]
    if missing:
        raise ConfigPinError(
            "missing sha256 reference_checksums for genomic accession(s): "
            + ", ".join(missing)
        )
    if not pins:
        raise ConfigPinError(f"no genomic reference sha256 pins found in {path}")
    return pins


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(path: str | os.PathLike[str], expected_sha256: str, accession: str) -> str:
    actual = sha256_file(path)
    if actual.lower() != expected_sha256.lower():
        raise ChecksumMismatchError(
            f"checksum mismatch for {accession} at {Path(path)}: "
            f"expected {expected_sha256.lower()} != actual {actual.lower()}"
        )
    return actual.lower()


def _fai_path(fasta_path: Path) -> Path:
    return Path(str(fasta_path) + ".fai")


def ensure_fai(fasta_path: Path) -> str:
    fai_path = _fai_path(fasta_path)
    if fai_path.is_file():
        return "present"

    import pysam

    pysam.faidx(str(fasta_path))
    if not fai_path.is_file():
        raise ReferenceFetchError(f"pysam.faidx did not create expected index {fai_path}")
    return "built"


def _download_to_temp(accession: str, target: Path) -> Path:
    try:
        url = DOWNLOAD_SOURCES[accession]
    except KeyError as exc:
        raise ReferenceFetchError(
            f"no pinned download source configured for accession {accession!r}"
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.download")
    if temp_path.exists():
        temp_path.unlink()

    try:
        with urllib.request.urlopen(url) as response, temp_path.open("wb") as handle:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return temp_path


def process_accession(
    accession: str, expected_sha256: str, root: Path, *, verify_only: bool
) -> ReferenceResult:
    target = root / f"{accession}.fasta"

    if target.is_file():
        if verify_only:
            actual = verify_checksum(target, expected_sha256, accession)
            index_status = "present" if _fai_path(target).is_file() else "missing"
            return ReferenceResult(accession, "present+verified", target, actual, index_status)

        try:
            actual = verify_checksum(target, expected_sha256, accession)
        except ChecksumMismatchError:
            pass
        else:
            index_status = ensure_fai(target)
            return ReferenceResult(accession, "present+verified", target, actual, index_status)

    elif verify_only:
        raise ReferenceFetchError(f"missing reference FASTA for {accession} at {target}")

    temp_path = _download_to_temp(accession, target)
    try:
        actual = verify_checksum(temp_path, expected_sha256, accession)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    os.replace(temp_path, target)
    index_status = ensure_fai(target)
    return ReferenceResult(accession, "downloaded+verified", target, actual, index_status)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch/verify RAPTOR's pinned genomic reference FASTAs."
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"ingest YAML with reference_checksums (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="do not download; only verify existing FASTAs against config pins",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = resolve_reference_root()
    pins = parse_reference_pins(args.config)

    print(f"Reference root: {root}", flush=True)
    results = [
        process_accession(accession, expected, root, verify_only=args.verify_only)
        for accession, expected in pins.items()
    ]

    print("Summary:")
    for result in results:
        print(
            f"  {result.accession}: {result.status}; sha256={result.sha256}; "
            f"index={result.index_status}; path={result.path}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReferenceFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
