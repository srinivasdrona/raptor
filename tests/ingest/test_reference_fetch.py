from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "fetch_reference.py"


def _load_fetch_reference_module():
    spec = importlib.util.spec_from_file_location("raptor_fetch_reference", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_reference_pins_reads_genomic_accessions(tmp_path):
    fetch_reference = _load_fetch_reference_module()
    config = tmp_path / "tsc.yaml"
    config.write_text(
        """
genes: [TSC1, TSC2]
TSC1:
  genome_accession: NC_000009.12
  transcript_accession: NM_000368.5
TSC2:
  genome_accession: NC_000016.10
  transcript_accession: NM_000548.5
reference_checksums:
  NC_000016.10: "22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0"
  NC_000009.12: "650011382f44e91b90c85271833737af2afdb6f9e92ef56f1f8f58f2389e3351"
  NM_000548.5: "confirm-pending"
""",
        encoding="utf-8",
    )

    assert fetch_reference.parse_reference_pins(config) == {
        "NC_000016.10": "22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0",
        "NC_000009.12": "650011382f44e91b90c85271833737af2afdb6f9e92ef56f1f8f58f2389e3351",
    }


def test_verify_checksum_flags_mismatch(tmp_path):
    fetch_reference = _load_fetch_reference_module()
    fasta = tmp_path / "NC_000016.10.fasta"
    fasta.write_text("x\n", encoding="utf-8")

    with pytest.raises(fetch_reference.ChecksumMismatchError) as exc:
        fetch_reference.verify_checksum(fasta, "0" * 64, "NC_000016.10")

    assert "checksum mismatch" in str(exc.value).lower()


@pytest.mark.requires_reference
def test_verify_only_against_real_reference_succeeds(capsys):
    fetch_reference = _load_fetch_reference_module()
    root = fetch_reference.resolve_reference_root()
    required = [root / "NC_000016.10.fasta", root / "NC_000009.12.fasta"]
    if not all(path.is_file() for path in required):
        pytest.skip(f"real reference FASTAs not present under {root}")

    assert fetch_reference.main(["--verify-only"]) == 0
    output = capsys.readouterr().out
    assert "NC_000016.10: present+verified" in output
    assert "NC_000009.12: present+verified" in output
