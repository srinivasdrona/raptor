import pytest
from raptor.eval.export import spdi_to_vcf, ExportReferenceMismatchError

class InvalidAnchorReference:
    def __init__(self, invalid_anchor: str):
        self.invalid_anchor = invalid_anchor

    def fetch(self, contig: str, start: int, end: int) -> str:
        if contig == "NC_1" and start == 0 and end == 1:
            return self.invalid_anchor
        if contig == "NC_1" and start == 1 and end == 2:
            return "C"
        raise ValueError(f"Unexpected fetch: {contig}:{start}-{end}")

@pytest.mark.parametrize("invalid_anchor", ["", "AC", "N", "a"])
def test_invalid_anchor_insertion(invalid_anchor):
    ref = InvalidAnchorReference(invalid_anchor)
    with pytest.raises(ExportReferenceMismatchError):
        spdi_to_vcf("NC_1:1::A", ref)

@pytest.mark.parametrize("invalid_anchor", ["", "AC", "N", "a"])
def test_invalid_anchor_deletion(invalid_anchor):
    ref = InvalidAnchorReference(invalid_anchor)
    with pytest.raises(ExportReferenceMismatchError):
        spdi_to_vcf("NC_1:1:C:", ref)
