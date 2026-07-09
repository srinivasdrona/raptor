import pytest
import gzip
from raptor.ingest.contract import VariantSummaryContract

def _rows_to_text(rows):
    header = VariantSummaryContract.REQUIRED_COLUMNS
    lines = ["\t".join(header)]
    for row in rows:
        lines.append("\t".join(str(row.get(col, "")) for col in header))
    return "\n".join(lines) + "\n"

def write_variant_summary(tmp_path, rows):
    file_path = tmp_path / "variant_summary.txt"
    file_path.write_text(_rows_to_text(rows), encoding="utf-8")
    return file_path

def write_variant_summary_gz(tmp_path, rows):
    """Write a gzipped variant_summary.txt.gz -- the REAL ClinVar snapshot format."""
    file_path = tmp_path / "variant_summary.txt.gz"
    with gzip.open(file_path, "wt", encoding="utf-8", newline="") as f:
        f.write(_rows_to_text(rows))
    return file_path

class FakeNormalizer:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def normalize(self, raw, config):
        self.calls.append(raw)
        return self.mapping.get(raw.variation_id)
