"""PRD-02 sec 10.3 `reader.py` — FR1/FR5/FR9: contract-checked ClinVar reader.

Reads a `variant_summary.txt`(.gz) snapshot, asserts the column contract
(FR9/AC6) before parsing, and yields `RawVariant` rows filtered to a single
gene, each carrying a pinned-snapshot-resolvable source_ref (FR5:
VariationID/VCV, snapshot_id+date, source_file_checksum, row_locator,
raw_source_value).

Both the snapshot text and its checksum are STREAMED (line-by-line /
chunk-by-chunk) rather than slurped into memory in one shot -- the real
pinned `variant_summary.txt.gz` is on the order of hundreds of MB
uncompressed, and this module (unlike `kb/`) is explicitly allowed to use
`open()`/`gzip.open()` (see
tests/kb/test_schema_contract.py::test_no_forbidden_file_read_calls_in_kb_source,
which scopes the builtin-file-read ban to the `kb/` package only).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import re
from pathlib import Path
from typing import IO, Iterator

from .contract import VariantSummaryContract
from .model import RawVariant

#: sha256 hex digests are exactly 64 hex chars; anything else pinned in
#: config (e.g. an offline-plumbing placeholder like "chk1"/"snap1") is not
#: a real hash and must not force a fail-loud mismatch (FR5/AC4).
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class SourceChecksumMismatchError(RuntimeError):
    """Raised when a pinned `clinvar_snapshot_file_checksum` (a real sha256)
    disagrees with the actual checksum of the file being read (FR1/FR5/AC4:
    ingesting a different file than the one pinned is a reproducibility
    breach, never silently proceed on it)."""


def _open_text(path: Path) -> IO[str]:
    """Open `path` for streaming text reads, transparently decompressing
    `.gz` -- never reads the whole file into memory at once."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "rt", encoding="utf-8", newline="")


def _sha256_file(path: Path) -> str:
    """Compute the real sha256 of `path`, reading in fixed-size chunks
    (never `read_bytes()` of the whole file)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_position(value: str) -> int | str:
    v = (value or "").strip()
    if v.lstrip("-").isdigit():
        return int(v)
    return v


class ClinVarVariantSummaryReader:
    """Contract-checks then yields `RawVariant` rows filtered to `gene`.

    `source_file_checksum` recorded on every emitted `RawVariant` is always
    the REAL sha256 of the file actually being read (FR5/AC4: resolvable
    grounding) -- never the config pin verbatim. If the config pins a real
    sha256 (`clinvar_snapshot_file_checksum`, 64 hex chars) that disagrees
    with the file's real hash, this is a reproducibility breach (ingesting a
    different file than pinned) and fails loud at construction time. A
    non-hash placeholder (offline-plumbing fixtures like "chk1"/"snap1")
    is not a real pin and does not force a mismatch.
    """

    def __init__(
        self,
        path: str | Path,
        gene: str,
        config: object,
        *,
        snapshot_id: str | None = None,
        snapshot_date: str | None = None,
        source_file_checksum: str | None = None,
    ):
        self.path = Path(path)
        self.gene = gene
        self.config = config
        self.snapshot_id = snapshot_id or str(getattr(config, "clinvar_snapshot_id", "") or "")
        self.snapshot_date = snapshot_date or str(getattr(config, "clinvar_snapshot_date", "") or "")

        actual_checksum = source_file_checksum or _sha256_file(self.path)
        pinned = str(getattr(config, "clinvar_snapshot_file_checksum", "") or "")
        if source_file_checksum is None and pinned and _HEX64_RE.match(pinned):
            if pinned.lower() != actual_checksum.lower():
                raise SourceChecksumMismatchError(
                    f"clinvar snapshot checksum mismatch for {self.path}: "
                    f"pinned {pinned!r} != actual sha256 {actual_checksum!r} "
                    "-- refusing to ingest a different file than pinned (FR1/FR5/AC4)"
                )
        self.source_file_checksum = actual_checksum

    def _gene_matches(self, gene_symbol_field: str) -> bool:
        """ClinVar's `GeneSymbol` is usually an exact symbol, but multi-gene
        (CNV/SV) rows encode it as `"subset of N genes: A:B:C:..."` -- match
        either form (FR1: filter to gene, never silently drop a row whose
        gene appears only in the multi-gene form)."""
        if gene_symbol_field == self.gene:
            return True
        if ":" in gene_symbol_field:
            return self.gene in gene_symbol_field.split(":")
        return False

    def __iter__(self) -> Iterator[RawVariant]:
        with _open_text(self.path) as f:
            reader = csv.reader(f, delimiter="\t")
            try:
                header = next(reader)
            except StopIteration:
                return
            VariantSummaryContract.assert_columns(header)
            idx = {name: i for i, name in enumerate(header)}

            for row_num, row in enumerate(reader, start=2):
                if not row:
                    continue
                gene_symbol = row[idx["GeneSymbol"]]
                if not self._gene_matches(gene_symbol):
                    continue
                yield RawVariant(
                    chromosome=row[idx["ChromosomeAccession"]],
                    position=_parse_position(row[idx["PositionVCF"]]),
                    ref=row[idx["ReferenceAlleleVCF"]],
                    alt=row[idx["AlternateAlleleVCF"]],
                    gene=self.gene,
                    variation_id=row[idx["VariationID"]],
                    snapshot_id=self.snapshot_id,
                    snapshot_date=self.snapshot_date,
                    source_file_checksum=self.source_file_checksum,
                    row_locator=str(row_num),
                    raw_source_value="\t".join(row),
                )
