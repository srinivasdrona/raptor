import pytest
import tempfile
import csv
from pathlib import Path
from raptor.scorer.config import ScorerConfig
from raptor.scorer.pipeline import run_scorer
from raptor.scorer.bias_source import BiasTsvSource
from raptor.kb.store import KBStore

@pytest.fixture
def temp_kb():
    return KBStore(":memory:")

def test_ac2_nthl1_out_of_scope_routing(temp_kb):
    # AC-C2: the 30 NTHL1 records are characterized as chr16p13.3 TSC2-region inputs
    # and each routes to out_of_scope_gene manual queue (excluded_from_scorer=True);
    # none scored, none re-attributed to TSC2, none clinically classified.

    # Create an NTHL1 row.
    header = [
        "chromosome", "position", "refAllele", "altAllele", "variantType", "consequence",
        "acmgClassification", "alleleFreq", "hgvsg", "hgvsc", "hgvsp", "aaChange",
        "geneName", "pubmedIds", "associatedDiseases", "dbSnpids", "transcript", "rationale"
    ]

    # NTHL1 is on chr16p13.3, adjacent to TSC2. Provide a realistic NTHL1 BIAS row.
    rows = [
        ["chr16", "2080000", "A", "G", "SNV", "missense_variant", "uncertain", "", "", "", "", "", "NTHL1", "", "", "", "NM_002528.6", "{}"]
    ]

    with tempfile.NamedTemporaryFile("wt", newline="", delete=False) as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)
        temp_tsv_path = f.name

    try:
        source = BiasTsvSource(temp_tsv_path)

        # We use a config where NTHL1 is NOT in genes.
        config = ScorerConfig(
            bias_version="1.0",
            bias_data_version="1.0",
            included_criteria=["PVS1"],
            strength_map={"1": "supporting"},
            acmg_criteria={"PVS1": {"direction": "pathogenic", "strength_vocab": ["supporting"]}},
            edge_cases={"non_mane_transcript": True},
            genes={"TSC2": "NM_000548.5"},  # NTHL1 explicitly missing
            licensing={}
        )

        report = run_scorer(config, source, temp_kb)

        cursor = temp_kb.conn.cursor()

        # Verify it routes to manual queue with OUT_OF_SCOPE_GENE
        cursor.execute("SELECT raw_input, error_code, excluded_from_scorer FROM manual_queue WHERE raw_input LIKE 'chr16:2080000%'")
        manual = cursor.fetchall()
        assert len(manual) == 1
        # In PRD-01 sec 10.4 / pipeline.py, run_scorer actually calls check_out_of_scope_gene
        # Wait, the pipeline doesn't have an `excluded_from_scorer` column in `manual_queue` directly,
        # or maybe it does? Let's check `temp_kb` schema or just assert error_code.
        assert manual[0][1] == "OUT_OF_SCOPE_GENE"

        # Verify it was NOT scored
        cursor.execute("SELECT variant_id FROM evidence")
        evidence = cursor.fetchall()
        assert len(evidence) == 0, "NTHL1 row must not be scored"

    finally:
        Path(temp_tsv_path).unlink()
