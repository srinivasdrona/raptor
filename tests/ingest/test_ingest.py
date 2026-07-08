import json
import pytest
from pathlib import Path

from hypothesis import given, settings, HealthCheck, strategies as st

from raptor.ingest.config import load_config, IngestConfig
from raptor.ingest.contract import VariantSummaryContract, SourceContractError
from raptor.ingest.reader import ClinVarVariantSummaryReader
from raptor.ingest.pipeline import run_ingest
from raptor.ingest.report import IngestReport
from raptor.ingest.model import RawVariant, VariantClass
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer
from raptor.kb.store import KBStore
from conftest import FakeNormalizer

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared helpers / fixtures for the offline (fake-normalizer) plumbing tests
# ---------------------------------------------------------------------------
@pytest.fixture
def dummy_config(tmp_path):
    # A config for offline plumbing tests. The fake normalizer ignores it; it
    # only needs to load without error.
    yaml_text = """
genes: [TSC1, TSC2]
assembly: GRCh38
assembly_patch: p14
mane_release: 1.4
normalizer: {tool: hgvs, version: 1.0}
clinvar_snapshot_id: "snap1"
clinvar_snapshot_date: "2026-07-08"
clinvar_snapshot_file_checksum: "chk1"
TSC1: {genome_accession: NC_000009.12, transcript_accession: NM_000368.5, protein_accession: NP_000359.2}
TSC2: {genome_accession: NC_000016.10, transcript_accession: NM_000548.5, protein_accession: NP_000539.2}
reference_checksums: {}
"""
    p = tmp_path / "conf.yaml"
    p.write_text(yaml_text)
    return load_config(str(p))


class DummyReader:
    def __init__(self, variants):
        self.variants = variants

    def __iter__(self):
        return iter(self.variants)


def _raw(i, chrom, pos, gene, ref="A", alt="T"):
    return RawVariant(
        chromosome=chrom, position=pos, ref=ref, alt=alt, gene=gene,
        variation_id=str(i), snapshot_id="s1", snapshot_date="d1",
        source_file_checksum="c1", row_locator=str(i), raw_source_value=f"raw{i}",
    )


# ---------------------------------------------------------------------------
# AC1 — conservation (R-A10): no silent drops. Property-based over arbitrary
# input sets, cross-checked against the ACTUAL published KB state.
# ---------------------------------------------------------------------------
@st.composite
def _raw_variant_lists(draw):
    n = draw(st.integers(min_value=0, max_value=12))
    positions = draw(st.lists(st.integers(1, 10_000_000), min_size=n, max_size=n, unique=True))
    out = []
    for i, pos in enumerate(positions):
        gene, chrom = draw(st.sampled_from([("TSC1", "NC_000009.12"), ("TSC2", "NC_000016.10")]))
        out.append(_raw(i, chrom, pos, gene))
    return out


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(variants=_raw_variant_lists())
def test_ac1_conservation_property(variants, dummy_config):
    """AC1 (R-A10): for ANY input set, |input| == |normalized| + |manual_queue|,
    0 dropped — verified against the actual published KB state, not just the report."""
    fake = FakeNormalizer()
    for i, v in enumerate(variants):
        if i % 3 == 0:  # deterministically route a subset to the manual queue
            fake.manual_queue_coords.add(f"{v.chromosome}:{v.position}:{v.ref}:{v.alt}")
    store = KBStore(":memory:")
    try:
        report = run_ingest(dummy_config, DummyReader(variants), fake, store)
        assert report.total_dropped == 0
        assert report.total_input == len(variants)
        assert report.total_input == report.total_normalized + report.total_manual_queue
        # Cross-check the report against what actually landed in the KB.
        pub = store.conn.execute("SELECT COUNT(*) FROM variants").fetchone()[0]
        mq = store.conn.execute("SELECT COUNT(*) FROM manual_queue").fetchone()[0]
        assert pub == report.total_normalized
        assert mq == report.total_manual_queue
    finally:
        store.close()


def test_ac1_no_silent_drop_on_normalizer_exception(dummy_config):
    """AC1 (R-A10): an unexpected per-variant normalizer exception must NOT silently
    vanish — the run either fails loudly OR accounts for every input (0 dropped).
    Design-agnostic: does not force which of the two the doer chooses."""
    fake = FakeNormalizer()
    fake.fail_coords.add("NC_000009.12:100:A:T")
    variants = [
        _raw(1, "NC_000009.12", 100, "TSC1"),
        _raw(2, "NC_000016.10", 200, "TSC2"),
        _raw(3, "NC_000009.12", 300, "TSC1"),
    ]
    store = KBStore(":memory:")
    try:
        try:
            report = run_ingest(dummy_config, DummyReader(variants), fake, store)
        except Exception:
            return  # fail-loud is acceptable — the point is: no SILENT drop
        assert report.total_dropped == 0
        assert report.total_input == 3
        assert report.total_input == report.total_normalized + report.total_manual_queue
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC4 — grounding (GP-9): every published variant carries a resolvable source_ref.
# ---------------------------------------------------------------------------
def test_ac4_grounding(fake_normalizer, dummy_config):
    """AC4 (GP-9): 100% of published variants carry >=1 resolvable source_ref
    (verified by querying variant_source_refs JOIN source_refs); 0 unresolvable."""
    variants = [
        _raw(1, "NC_000009.12", 100, "TSC1"),
        _raw(2, "NC_000016.10", 200, "TSC2"),
        _raw(3, "NC_000009.12", 300, "TSC1"),
    ]
    fake_normalizer.manual_queue_coords.add("NC_000016.10:200:A:T")
    store = KBStore(":memory:")
    try:
        report = run_ingest(dummy_config, DummyReader(variants), fake_normalizer, store)
        conn = store.conn
        published = [r[0] for r in conn.execute("SELECT variant_id FROM variants").fetchall()]
        assert len(published) == report.total_normalized
        for vid in published:
            n = conn.execute(
                """SELECT COUNT(*) FROM variant_source_refs vsr
                   JOIN source_refs sr ON sr.source_ref_id = vsr.source_ref_id
                   WHERE vsr.variant_id = ?""",
                (vid,),
            ).fetchone()[0]
            assert n >= 1, f"variant {vid} has no resolvable source_ref (grounding violation)"
        # Manual-queue rows are also grounded (schema FKs source_ref_id NOT NULL).
        assert conn.execute("SELECT COUNT(*) FROM manual_queue").fetchone()[0] == report.total_manual_queue
    finally:
        store.close()


# ---------------------------------------------------------------------------
# AC2 — determinism (R-A11): identical content_hash across runs; run metadata excluded.
# ---------------------------------------------------------------------------
def test_ac2_determinism(fake_normalizer, dummy_config):
    """AC2 (R-A11): two runs on the same inputs/config produce IDENTICAL content_hash
    despite different run metadata (FR7 separation). Separate stores so neither run
    observes the other's published state."""
    variants = [
        _raw(1, "NC_000009.12", 100, "TSC1"),
        _raw(2, "NC_000016.10", 200, "TSC2"),
    ]
    r1 = run_ingest(dummy_config, DummyReader(variants), fake_normalizer, KBStore(":memory:"))
    r2 = run_ingest(dummy_config, DummyReader(variants), fake_normalizer, KBStore(":memory:"))
    assert r1.run_id != r2.run_id
    assert r1.content_hash() == r2.content_hash()


# ---------------------------------------------------------------------------
# AC5 — no trace-cribbing (H1): the RawVariant handed to the normalizer carries
# no oracle/label column.
# ---------------------------------------------------------------------------
def test_ac5_no_trace_cribbing_in_raw_variant():
    """AC5: RawVariant given to the normalizer lacks any oracle/label field."""
    names = set(dir(RawVariant))
    fields = getattr(RawVariant, "__dataclass_fields__", None)
    if fields:
        names |= set(fields.keys())
    for forbidden in ("CanonicalSPDI", "canonical_spdi", "label", "expected", "oracle",
                      "clinical_significance", "ClinicalSignificance"):
        assert forbidden not in names


# ---------------------------------------------------------------------------
# AC6 — source-contract (R-B1): passes on real header, fails loudly on drift.
# ---------------------------------------------------------------------------
def test_ac6_source_contract_passes_on_real_header():
    with open(FIXTURES_DIR / "header_only.tsv", "r") as f:
        header = f.readline().strip().split("\t")
    VariantSummaryContract.assert_columns(header)  # must not raise


def test_ac6_source_contract_fails_on_malformed_header():
    with open(FIXTURES_DIR / "header_malformed.tsv", "r") as f:
        header = f.readline().strip().split("\t")
    with pytest.raises(SourceContractError):
        VariantSummaryContract.assert_columns(header)


# ---------------------------------------------------------------------------
# AC7 — NFR: config schema-validates; rejects a missing required pin.
# ---------------------------------------------------------------------------
def test_ac7_config_loads_valid_and_rejects_invalid(tmp_path):
    valid_yaml = """
genes: [TSC1, TSC2]
assembly: GRCh38
assembly_patch: p14
mane_release: 1.4
normalizer:
  tool: hgvs
  version: "1.5.4"
clinvar_snapshot_id: "2026-07-08"
clinvar_snapshot_date: "2026-07-08"
clinvar_snapshot_file_checksum: "abcd123"
TSC1:
  genome_accession: NC_000009.12
  transcript_accession: NM_000368.5
  protein_accession: NP_000359.2
TSC2:
  genome_accession: NC_000016.10
  transcript_accession: NM_000548.5
  protein_accession: NP_000539.2
reference_checksums:
  NC_000016.10: "sha1"
  NC_000009.12: "sha2"
  NM_000548.5: "sha3"
  NM_000368.5: "sha4"
"""
    valid_file = tmp_path / "valid.yaml"
    valid_file.write_text(valid_yaml)
    config = load_config(str(valid_file))
    assert config.genes == ["TSC1", "TSC2"]

    invalid_yaml = valid_yaml.replace("assembly: GRCh38", "")
    invalid_file = tmp_path / "invalid.yaml"
    invalid_file.write_text(invalid_yaml)
    with pytest.raises((ValueError, KeyError)):
        load_config(str(invalid_file))


# ---------------------------------------------------------------------------
# AC3 — canonical correctness (frozen fixture, real normalizer, INDEPENDENT
# oracle = NCBI Variation Services SPDI). Genomic now; c./p. deferred to UTA.
# ---------------------------------------------------------------------------
@pytest.mark.requires_reference
def test_ac3_canonical_correctness_genomic(dummy_config):
    """AC3: genomic SPDI (and hgvs_g where the oracle provided it) correctness,
    asserted against independently-derived expected values. The normalizer receives
    ONLY coordinates — never the oracle SPDI (anti-cribbing)."""
    try:
        real_normalizer = SeqRepoGenomicNormalizer()
    except Exception:
        pytest.skip("SeqRepoGenomicNormalizer not implemented / reference not present yet")

    with open(FIXTURES_DIR / "ac3_canonical.json") as f:
        fixtures = json.load(f)

    for item in fixtures:
        chrom, pos, ref, alt = item["raw_coords"].split(":")
        raw = RawVariant(
            chromosome=chrom, position=int(pos) if pos.lstrip("-").isdigit() else pos,
            ref=ref, alt=alt, gene=item["gene"], variation_id=item["variation_id"],
            snapshot_id="s1", snapshot_date="d1", source_file_checksum="c1",
            row_locator="1", raw_source_value="raw",
        )
        outcome = real_normalizer.normalize(raw, dummy_config)

        if item.get("expected_manual_queue"):
            assert outcome.__class__.__name__ == "ManualQueueItem"
            continue

        assert outcome.__class__.__name__ == "NormalizedVariant"
        assert outcome.variant_id == item["expected_variant_id"]
        if item.get("expected_hgvs_g"):
            assert outcome.hgvs_g == item["expected_hgvs_g"]
        # c./p. deferred to UTA in this increment (explicit null-with-reason).
        assert outcome.hgvs_c is None
        assert outcome.hgvs_p is None
        assert outcome.hgvs_c_null_reason == item["expected_hgvs_c_null_reason"]
        assert outcome.hgvs_p_null_reason == item["expected_hgvs_p_null_reason"]


@pytest.mark.requires_uta
def test_ac3_canonical_correctness_uta():
    """AC3: c./p. correctness using UTA — deferred until the UTA setup step."""
    pass


# ===========================================================================
# Fix-round tests (checker findings, round 1). Planner-authored from concrete
# checker probes; assert SPEC-correct GENERAL invariants (not the impl's current
# buggy output). RED against the pre-fix implementation.
# ===========================================================================
import hashlib
import yaml as _yaml


def _config_with(tmp_path, **overrides):
    base = {
        "genes": ["TSC1", "TSC2"],
        "assembly": "GRCh38", "assembly_patch": "p14", "mane_release": "1.4",
        "normalizer": {"tool": "hgvs", "version": "1.0"},
        "clinvar_snapshot_id": "snap1", "clinvar_snapshot_date": "2026-07-08",
        "clinvar_snapshot_file_checksum": "chk1",
        "reference_checksums": {},
        "TSC1": {"genome_accession": "NC_000009.12", "transcript_accession": "NM_000368.5", "protein_accession": "NP_000359.2"},
        "TSC2": {"genome_accession": "NC_000016.10", "transcript_accession": "NM_000548.5", "protein_accession": "NP_000539.2"},
    }
    base.update(overrides)
    p = tmp_path / "cfg_override.yaml"
    p.write_text(_yaml.safe_dump(base))
    return load_config(str(p))


@pytest.fixture
def real_normalizer():
    try:
        return SeqRepoGenomicNormalizer()
    except Exception:
        pytest.skip("real reference (~/raptor-refseq) not present")


@pytest.mark.requires_reference
def test_ref_mismatch_routes_to_manual_queue(real_normalizer, dummy_config):
    """[blocker] R-A10: an input REF that disagrees with the reference genome is a
    coordinate/build mismatch -> manual queue, NEVER silently 'corrected' into the
    reference-derived variant. Reference base at NC_000016.10:2087897 is C."""
    ok = real_normalizer.normalize(_raw(1, "NC_000016.10", 2087897, "TSC2", ref="C", alt="T"), dummy_config)
    assert ok.__class__.__name__ == "NormalizedVariant"
    assert ok.variant_id == "NC_000016.10:2087896:C:T"  # control: correct REF normalizes
    bad = real_normalizer.normalize(_raw(2, "NC_000016.10", 2087897, "TSC2", ref="A", alt="T"), dummy_config)
    assert bad.__class__.__name__ == "ManualQueueItem", f"REF mismatch must manual-queue, got {bad!r}"


@pytest.mark.requires_reference
@pytest.mark.parametrize("bad_alt", ["<DEL>", ".", "<INS>", "<DUP>", "N", "*"])
def test_symbolic_or_invalid_alt_routes_to_manual_queue(real_normalizer, dummy_config, bad_alt):
    """[major] FR3: symbolic / non-ACGT ALTs (imprecise SV/CNV or no-call) must
    route to manual queue, never be treated as literal inserted sequence."""
    raw = _raw(1, "NC_000016.10", 2087897, "TSC2", ref="C", alt=bad_alt)
    outcome = real_normalizer.normalize(raw, dummy_config)
    assert outcome.__class__.__name__ == "ManualQueueItem", f"{bad_alt!r} must manual-queue, got {outcome!r}"


@pytest.mark.requires_reference
def test_wrong_reference_checksum_fails_loud(real_normalizer, tmp_path):
    """[major] R-A11/FR8: a reference FASTA whose sha256 != the pinned
    reference_checksums entry is a reproducibility breach -> FAIL LOUD, never
    proceed on an unverified reference."""
    cfg = _config_with(tmp_path, reference_checksums={"NC_000016.10": "0" * 64})
    raw = _raw(1, "NC_000016.10", 2087897, "TSC2", ref="C", alt="T")
    with pytest.raises(Exception) as exc:
        real_normalizer.normalize(raw, cfg)
    assert "checksum" in str(exc.value).lower()


def test_reader_fails_loud_on_source_checksum_mismatch(tmp_path):
    """[major] FR1/FR5/AC4: if the config pins a source_file_checksum that does not
    match the file being read, the reader must fail loud (it is ingesting a
    different file than pinned), not silently record the placeholder."""
    slice_path = FIXTURES_DIR / "clinvar_tsc_slice.tsv"
    cfg = _config_with(tmp_path, clinvar_snapshot_file_checksum="deadbeef" * 8)
    with pytest.raises(Exception) as exc:
        list(ClinVarVariantSummaryReader(slice_path, "TSC2", cfg))
    assert "checksum" in str(exc.value).lower()


def test_reader_records_real_file_checksum(tmp_path):
    """[major] FR5/AC4: the source_file_checksum recorded on every emitted row is
    the ACTUAL sha256 of the ingested file (resolvable grounding)."""
    slice_path = FIXTURES_DIR / "clinvar_tsc_slice.tsv"
    real_sha = hashlib.sha256(slice_path.read_bytes()).hexdigest()
    cfg = _config_with(tmp_path, clinvar_snapshot_file_checksum=real_sha)
    rows = list(ClinVarVariantSummaryReader(slice_path, "TSC2", cfg))
    assert rows, "reader yielded no TSC2 rows from the slice"
    assert all(r.source_file_checksum == real_sha for r in rows)


def test_reader_reads_gzipped_snapshot(tmp_path):
    """[major] FR1: the real snapshot is variant_summary.txt.gz — the reader must
    read gzip and yield the same rows as the uncompressed form."""
    import gzip as _gz
    slice_path = FIXTURES_DIR / "clinvar_tsc_slice.tsv"
    data = slice_path.read_bytes()
    gz_path = tmp_path / "slice.tsv.gz"
    gz_path.write_bytes(_gz.compress(data))
    cfg_plain = _config_with(tmp_path, clinvar_snapshot_file_checksum=hashlib.sha256(data).hexdigest())
    cfg_gz = _config_with(tmp_path, clinvar_snapshot_file_checksum=hashlib.sha256(gz_path.read_bytes()).hexdigest())
    rows_plain = list(ClinVarVariantSummaryReader(slice_path, "TSC2", cfg_plain))
    rows_gz = list(ClinVarVariantSummaryReader(gz_path, "TSC2", cfg_gz))
    assert len(rows_gz) == len(rows_plain) > 0
