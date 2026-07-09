import pytest
from raptor.ingest.contract import VariantSummaryContract

def write_variant_summary(tmp_path, rows):
    header = VariantSummaryContract.REQUIRED_COLUMNS
    file_path = tmp_path / "variant_summary.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            out_row = []
            for col in header:
                out_row.append(str(row.get(col, "")))
            f.write("\t".join(out_row) + "\n")
    return file_path

class FakeNormalizer:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def normalize(self, raw, config):
        self.calls.append(raw)
        return self.mapping.get(raw.variation_id)
