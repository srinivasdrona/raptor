"""AC tests for live eval export (Task A)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

# RED by design initially: module does not exist yet.
from raptor.eval.export import (
    ExportConfig,
    load_export_config,
    spdi_to_vcf,
    export_holdout,
    ExportReferenceMismatchError,
    ContigStartAnchorError,
)

class FakeReference:
    def __init__(self, seqs: dict[str, str]):
        self.seqs = seqs

    def fetch(self, contig: str, start: int, end: int) -> str:
        seq = self.seqs.get(contig, "")
        return seq[start:end]

def test_aca1_all_shape_conversion():
    """AC-A1 (mechanical) — All shapes convert, hand-computed."""
    # 0123456789
    # ACGTACGTAC
    ref = FakeReference({"NC_1": "ACGTACGTAC"})

    assert spdi_to_vcf("NC_1:1:C:T", ref) == ("NC_1", 2, "C", "T")
    assert spdi_to_vcf("NC_1:1:CG:TA", ref) == ("NC_1", 2, "CG", "TA")
    assert spdi_to_vcf("NC_1:1:CG:T", ref) == ("NC_1", 2, "CG", "T")
    assert spdi_to_vcf("NC_1:2:GT:", ref) == ("NC_1", 2, "CGT", "C")
    assert spdi_to_vcf("NC_1:2::A", ref) == ("NC_1", 2, "C", "CA")

def test_aca2_contig_start_anchor_fails_loud():
    """AC-A2 (mechanical) — Contig-start anchor fails loud."""
    ref = FakeReference({"NC_1": "ACGTACGTAC"})
    with pytest.raises(ContigStartAnchorError):
        spdi_to_vcf("NC_1:0::A", ref)
    with pytest.raises(ContigStartAnchorError):
        spdi_to_vcf("NC_1:0:A:", ref)

def test_aca3_reference_mismatch_fails_loud():
    """AC-A3 (mechanical) — Reference mismatch fails loud."""
    ref = FakeReference({"NC_1": "ACGTACGTAC"})
    with pytest.raises(ExportReferenceMismatchError):
        spdi_to_vcf("NC_1:1:G:T", ref)

def test_aca5_determinism_and_sort_order(tmp_path):
    """AC-A5 (mechanical) — determinism + total sort key (contig,POS,REF,ALT)."""
    ref = FakeReference({
        "NC_16": "ACGTACGTAC" * 10,
        "NC_9": "ACGTACGTAC" * 10
    })

    config = ExportConfig(
        assembly="GRCh38",
        # Configured order: chr9 before chr16, despite chr16 < chr9 lexically
        contigs=[
            {"accession": "NC_9", "vcf_contig": "chr9"},
            {"accession": "NC_16", "vcf_contig": "chr16"}
        ]
    )

    inputs = [
        "NC_16:5:C:T",
        "NC_9:1:C:T",
        "NC_9:1:C:A",
        "NC_16:1:C:T",
    ]

    prov_in = {"some": "data"}
    import copy
    prov_in_orig = copy.deepcopy(prov_in)
    result = export_holdout(inputs, ref, config, provenance=prov_in)
    assert prov_in == prov_in_orig
    out_dir = tmp_path / "out1"
    out_dir.mkdir()
    result.write(out_dir, "test")

    vcf_text = (out_dir / "test.vcf").read_text(encoding="utf-8")
    data_rows = [line for line in vcf_text.splitlines() if not line.startswith("#")]

    expected_contigs = ["chr9", "chr9", "chr16", "chr16"]
    expected_pos = ["2", "2", "2", "6"]
    expected_alt = ["A", "T", "T", "T"]

    for i, row in enumerate(data_rows):
        fields = row.split("\t")
        assert fields[0] == expected_contigs[i]
        assert fields[1] == expected_pos[i]
        assert fields[4] == expected_alt[i]

    result_rev = export_holdout(inputs[::-1], ref, config, provenance=prov_in)
    assert prov_in == prov_in_orig
    out_dir2 = tmp_path / "out2"
    out_dir2.mkdir()
    result_rev.write(out_dir2, "test")

    vcf_text_rev = (out_dir2 / "test.vcf").read_text(encoding="utf-8")
    manifest_text = (out_dir / "test.manifest.jsonl").read_text(encoding="utf-8").strip()
    manifest_text_rev = (out_dir2 / "test.manifest.jsonl").read_text(encoding="utf-8").strip()
    manifest_rows = [json.loads(line) for line in manifest_text.splitlines()]
    manifest_rows_rev = [json.loads(line) for line in manifest_text_rev.splitlines()]
    prov_text = (out_dir / "test.provenance.json").read_text(encoding="utf-8")
    prov_text_rev = (out_dir2 / "test.provenance.json").read_text(encoding="utf-8")

    assert vcf_text == vcf_text_rev
    assert manifest_text == manifest_text_rev
    assert manifest_rows == manifest_rows_rev
    assert prov_text == prov_text_rev
    assert result.vcf_hash == result_rev.vcf_hash
    assert result.manifest_hash == result_rev.manifest_hash

@st.composite
def valid_spdi_for_fixed_ref(draw):
    """
    Generate substitution/MNV SPDI strings at drawn unique positions.
    By using reference-matching deletions and nonidentical insertions of the same length,
    and forcing distinct positions via unique_by, the generated list is guaranteed
    to map injectively to unique VCF keys (preventing false-positive collisions).
    """
    pos = draw(st.integers(min_value=1, max_value=8))
    ref_str = "ACGTACGTACGT"
    shape_len = draw(st.integers(min_value=1, max_value=2))
    ref_seq = ref_str[pos:pos+shape_len]
    alt_seq = draw(st.text(alphabet=["A", "C", "G", "T"], min_size=shape_len, max_size=shape_len))
    if ref_seq == alt_seq:
        alt_seq = "".join("T" if c != "T" else "A" for c in ref_seq)
    return f"NC_1:{pos}:{ref_seq}:{alt_seq}"

@given(st.lists(valid_spdi_for_fixed_ref(), min_size=1, max_size=10, unique_by=lambda x: int(x.split(":")[1])))
def test_aca6_bijection_property(variants):
    """AC-A6 (mechanical) — conservation + bijection (property-based)."""
    ref = FakeReference({"NC_1": "ACGTACGTACGT"})
    config = ExportConfig(assembly="GRCh38", contigs=[{"accession": "NC_1", "vcf_contig": "chr1"}])

    result = export_holdout(variants, ref, config)

    assert result.conservation_count == len(variants)
    assert len(result.manifest_rows) == len(variants)

    # Check bijection: VCF keys must be unique.
    vcf_keys = [row["vcf_key"] for row in result.manifest_rows]
    assert len(set(vcf_keys)) == len(variants)
    canonical_ids = [row["variant_id"] for row in result.manifest_rows]
    assert len(set(canonical_ids)) == len(variants)

def test_aca6_distinct_ids_same_vcf_key_collision_fatal():
    """Distinct SPDI strings mapping to the same VCF key -> fatal ValueError."""
    ref = FakeReference({"NC_1": "ACGTACGTACGT"})
    config = ExportConfig(assembly="GRCh38", contigs=[{"accession": "NC_1", "vcf_contig": "chr1"}])

    inputs = ["NC_1:2:G:", "NC_1:1:CG:C"]
    with pytest.raises(ValueError):
        export_holdout(inputs, ref, config)

def test_aca6_collision_fatal():
    """Duplicate/collision -> fatal ValueError."""
    ref = FakeReference({"NC_1": "ACGTACGTAC"})
    config = ExportConfig(assembly="GRCh38", contigs=[{"accession": "NC_1", "vcf_contig": "chr1"}])

    inputs = ["NC_1:1:C:T", "NC_1:1:C:T"]
    with pytest.raises(ValueError):
        export_holdout(inputs, ref, config)

def test_aca7_manifest_write_contract(tmp_path):
    """AC-A7 (evidence-form) — manifest identity/provenance stable subset."""
    ref = FakeReference({"NC_1": "ACGTACGTAC"})
    config = ExportConfig(assembly="GRCh38", contigs=[{"accession": "NC_1", "vcf_contig": "chr1"}])
    inputs = ["NC_1:1:C:T"]

    prov_in = {
        "benchmark_snapshot": "snap-123",
        "reference_checksums": {"NC_1": "sha256:abc"},
        "code_version": "v1.0"
    }

    result = export_holdout(inputs, ref, config, provenance=prov_in)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result.write(out_dir, prefix="holdout_input")

    paths = list(out_dir.iterdir())
    assert len(paths) == 3
    names = {p.name for p in paths}
    assert names == {"holdout_input.vcf", "holdout_input.manifest.jsonl", "holdout_input.provenance.json"}

    prov = json.loads((out_dir / "holdout_input.provenance.json").read_text(encoding="utf-8"))
    assert "vcf_hash" in prov
    assert "manifest_hash" in prov
    assert prov["conservation_count"] == 1
    assert prov["benchmark_snapshot"] == "snap-123"
    assert prov["reference_checksums"] == {"NC_1": "sha256:abc"}
    assert prov["code_version"] == "v1.0"

    manifest_lines = (out_dir / "holdout_input.manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(manifest_lines) == 1
    manifest_obj = json.loads(manifest_lines[0])
    assert set(manifest_obj.keys()) == {"variant_id", "vcf_key", "accession", "contig"}

class DummyGeneConfig:
    def __init__(self, ga):
        self.genome_accession = ga

class DummyIngestConfig:
    def __init__(self, assembly, accessions):
        self.assembly = assembly
        self.gene_configs = {f"gene_{i}": DummyGeneConfig(acc) for i, acc in enumerate(accessions)}

    def gene_config(self, gene: str) -> DummyGeneConfig:
        return self.gene_configs[gene]

def test_load_export_config_schema(tmp_path):
    """Config loader schema tests. Rejects bad configurations."""
    ingest_config = DummyIngestConfig("GRCh38", ["NC_9", "NC_16"])

    # Valid
    cfg_path = tmp_path / "valid.yaml"
    cfg_path.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n  - accession: NC_16\n    vcf_contig: chr16\n", encoding="utf-8")
    config = load_export_config(cfg_path, ingest_config)
    assert config.assembly == "GRCh38"
    assert config.contigs == [{"accession": "NC_9", "vcf_contig": "chr9"}, {"accession": "NC_16", "vcf_contig": "chr16"}]

    # Wrong assembly
    wrong_asm = tmp_path / "wrong.yaml"
    wrong_asm.write_text("assembly: GRCh37\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n  - accession: NC_16\n    vcf_contig: chr16\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(wrong_asm, ingest_config)

    # Missing accession
    drift = tmp_path / "drift.yaml"
    drift.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(drift, ingest_config)

    # Extra accession
    extra = tmp_path / "extra.yaml"
    extra.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n  - accession: NC_16\n    vcf_contig: chr16\n  - accession: NC_X\n    vcf_contig: chrX\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(extra, ingest_config)

    # Duplicate accession with diff vcf contig
    dup_acc = tmp_path / "dup_acc.yaml"
    dup_acc.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n  - accession: NC_9\n    vcf_contig: chr9_alt\n  - accession: NC_16\n    vcf_contig: chr16\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(dup_acc, ingest_config)

    # Duplicate vcf contig with diff accession
    dup_vcf = tmp_path / "dup_vcf.yaml"
    dup_vcf.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: chr9\n  - accession: NC_16\n    vcf_contig: chr9\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(dup_vcf, ingest_config)

    # Blank accession
    blank_acc = tmp_path / "blank_acc.yaml"
    blank_acc.write_text("assembly: GRCh38\ncontigs:\n  - accession: ''\n    vcf_contig: chr9\n  - accession: NC_16\n    vcf_contig: chr16\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(blank_acc, ingest_config)

    # Blank vcf contig
    blank_vcf = tmp_path / "blank_vcf.yaml"
    blank_vcf.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_9\n    vcf_contig: ''\n  - accession: NC_16\n    vcf_contig: chr16\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_export_config(blank_vcf, ingest_config)

def test_cli_contract(tmp_path):
    """AC-A4 + E2E CLI contract: scripts/export_holdout_vcf.py"""
    import hashlib
    import pysam

    # 1. Create reference fasta and index
    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    ref_fa = ref_dir / "NC_1.fasta"
    ref_fa.write_bytes(b">NC_1\nACGTACGTACGT\n")
    pysam.faidx(str(ref_fa))

    sha256 = hashlib.sha256(ref_fa.read_bytes()).hexdigest()

    # 2. Create full ingest config
    ingest_cfg_path = tmp_path / "ingest.yaml"
    ingest_cfg_path.write_text(f"""genes:
  - gene1
assembly: GRCh38
assembly_patch: p14
mane_release: "1.2"
normalizer:
  tool: "test_norm"
  version: "1.0"
clinvar_snapshot_id: "snap1"
clinvar_snapshot_date: "2023-01-01"
clinvar_snapshot_file_checksum: "sha256:abc"
reference_checksums:
  NC_1: "{sha256}"
gene1:
  genome_accession: NC_1
  transcript_accession: NM_1
  protein_accession: NP_1
""", encoding="utf-8")

    # 3. Create export config
    export_cfg_path = tmp_path / "export.yaml"
    export_cfg_path.write_text("assembly: GRCh38\ncontigs:\n  - accession: NC_1\n    vcf_contig: chr1\n", encoding="utf-8")

    # 4. Create holdout JSONL
    bench_path = tmp_path / "holdout.jsonl"

    sentinel_label = "SENTINEL_LABEL_999"
    sentinel_source = "SENTINEL_SOURCE_999"
    sentinel_review = "SENTINEL_REVIEW_999"
    sentinel_class = "SENTINEL_CLASS_999"

    row = {
        "variant_id": "NC_1:1:C:T",
        "label": sentinel_label,
        "source": sentinel_source,
        "review_status": sentinel_review,
        "variant_class": sentinel_class
    }
    bench_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    script_path = Path("scripts/export_holdout_vcf.py")

    result = subprocess.run([
        sys.executable, str(script_path),
        "--heldout", str(bench_path),
        "--export-config", str(export_cfg_path),
        "--ingest-config", str(ingest_cfg_path),
        "--reference-root", str(ref_dir),
        "--benchmark-snapshot", "snap-test-1",
        "--out-dir", str(out_dir)
    ], capture_output=True, text=True, check=True)

    paths = list(out_dir.iterdir())
    assert len(paths) == 3
    names = {p.name for p in paths}
    assert names == {"holdout_input.vcf", "holdout_input.manifest.jsonl", "holdout_input.provenance.json"}

    vcf_text = (out_dir / "holdout_input.vcf").read_text(encoding="utf-8")
    man_text = (out_dir / "holdout_input.manifest.jsonl").read_text(encoding="utf-8")
    prov_text = (out_dir / "holdout_input.provenance.json").read_text(encoding="utf-8")

    prov_obj = json.loads(prov_text)

    assert prov_obj["vcf_hash"] in result.stdout
    assert prov_obj["manifest_hash"] in result.stdout

    # Unambiguous conservation count rendering
    try:
        stdout_json = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
        assert any(p.get("conservation_count") == 1 for p in stdout_json), "JSON summary missing conservation_count=1"
    except (json.JSONDecodeError, AssertionError):
        # Fallback to labeled text if not JSON
        normalized_stdout = result.stdout.lower().replace(" ", "").replace(":", "=")
        assert "conservation_count=1" in normalized_stdout or "conservation=1" in normalized_stdout, "Missing unambiguous conservation count in stdout"

    # Check no truth leakage anywhere
    for text, name in [(vcf_text, "vcf"), (man_text, "manifest"), (prov_text, "prov")]:
        assert sentinel_label not in text, f"Leak in {name}"
        assert sentinel_source not in text, f"Leak in {name}"
        assert sentinel_review not in text, f"Leak in {name}"
        assert sentinel_class not in text, f"Leak in {name}"

    data_rows = [line for line in vcf_text.splitlines() if not line.startswith("#")]
    assert len(data_rows) == 1
    fields = data_rows[0].split("\t")
    assert fields[7] == ".", "INFO field must be exactly '.'"

    manifest_obj = json.loads(man_text.strip())
    assert set(manifest_obj.keys()) == {"variant_id", "vcf_key", "accession", "contig"}

    prov_obj = json.loads(prov_text)
    assert prov_obj["benchmark_snapshot"] == "snap-test-1"
    assert "reference_checksums" in prov_obj
    assert "code_version" in prov_obj
