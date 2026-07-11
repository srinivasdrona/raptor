import csv
import json
import pytest
import tempfile
from pathlib import Path
from raptor.scorer.config import ScorerConfig
from raptor.scorer.pipeline import run_scorer
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.model import BiasRecord
import yaml
from dataclasses import replace

@pytest.fixture
def tsc_acmg_config_dict():
    config_path = Path("configs/acmg/tsc.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)

@pytest.fixture
def tsc_ingest_config_dict():
    config_path = Path("configs/ingest/tsc.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)

def test_ac7_committed_pipeline_transcript_regression(temp_kb, tsc_acmg_config_dict, tsc_ingest_config_dict):
    # This test MUST fail before the doer implements the transcript reconciliation (baseline misroute)
    # and MUST pass after the doer implements it (corrected behavior).
    # Since we are writing the test first (RED first), we assert the *corrected* behavior.
    # The doer must make this test pass. We will also dynamically prove the baseline misroute
    # if the reconciliation logic is not yet active.

    # 1. Build a real TSV with representative .4 BIAS rows
    header = [
        "chromosome", "position", "refAllele", "altAllele", "variantType", "consequence",
        "acmgClassification", "alleleFreq", "hgvsg", "hgvsc", "hgvsp", "aaChange",
        "geneName", "pubmedIds", "associatedDiseases", "dbSnpids", "transcript", "rationale"
    ]

    # Fake rationale for PVS1 so they can be scored if not routed to manual queue
    rationale_pvs1 = json.dumps({"pvs": {"pvs1": [4, "PVS1_very_strong: ..."]}})

    # The normalizer will need a valid SPDI, but the test doesn't necessarily run the normalizer
    # in `run_scorer`, `run_scorer` runs `check_edge_cases` directly using config.
    # Wait, the doer is going to add `spdi_equivalent` check which implies `run_scorer`
    # will call the normalizer OR the transcript_reconcile helper which needs SPDI!
    # Let's provide realistic coordinates.
    # Representative rows from the pinned 6,618-row BIAS output.

    rows = [
        ["chr16", "2048616", "A", "G", "SNV", "start_lost", "uncertain", "", "", "", "", "", "TSC2", "", "", "", "NM_000548.4", rationale_pvs1],
        ["chr9", "132891409", "T", "G", "SNV", "3_prime_UTR_variant", "uncertain", "", "", "", "", "", "TSC1", "", "", "", "NM_000368.4", rationale_pvs1],
        ["chr16", "2048008", "A", "G", "SNV", "upstream_gene_variant", "uncertain", "", "", "", "", "", "NTHL1", "", "", "", "NM_002528.6", rationale_pvs1],
    ]

    with tempfile.NamedTemporaryFile("wt", newline="", delete=False) as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)
        temp_tsv_path = f.name

    try:
        parsed = tuple(BiasTsvSource(temp_tsv_path).records())
        canonical_by_key = {
            "chr16:2048616:A:G": "NC_000016.10:2048615:A:G",
            "chr9:132891409:T:G": "NC_000009.12:132891408:T:G",
            "chr16:2048008:A:G": "NC_000016.10:2048007:A:G",
        }
        enriched = tuple(
            replace(
                record,
                provenance={
                    **record.provenance,
                    "canonical_spdi": canonical_by_key[record.variant_id],
                },
            )
            for record in parsed
        )

        class CanonicalManifestBiasSource:
            def records(self, run=None):
                return iter(enriched)

        source = CanonicalManifestBiasSource()

        # Load the real committed config
        # We need a ScorerConfig object. The codebase might load it from a dictionary.
        # We will create a ScorerConfig with the merged dict.
        config = ScorerConfig(
            bias_version=tsc_acmg_config_dict.get("bias_version"),
            bias_data_version=tsc_acmg_config_dict.get("bias_data_version"),
            included_criteria=tsc_acmg_config_dict.get("included_criteria"),
            strength_map=tsc_acmg_config_dict.get("strength_map"),
            acmg_criteria=tsc_acmg_config_dict.get("acmg_criteria"),
            edge_cases=tsc_acmg_config_dict.get("edge_cases"),
            genes=tsc_acmg_config_dict.get("genes"),
            licensing=tsc_acmg_config_dict.get("licensing")
        )

        # Run scorer
        report = run_scorer(config, source, temp_kb)

        # Check what happened
        cursor = temp_kb.conn.cursor()

        # The 30 NTHL1 rows must remain in manual queue (excluded_from_scorer=True isn't a column we can query easily, but error_code=OUT_OF_SCOPE_GENE is)
        cursor.execute("SELECT raw_input, error_code FROM manual_queue WHERE raw_input LIKE 'chr16:2048008%'")
        nthl1_manual = cursor.fetchall()
        assert len(nthl1_manual) == 1
        assert nthl1_manual[0][1] == "OUT_OF_SCOPE_GENE"

        # Corrected scope includes TSC1 and reconciles its .4 annotation to pinned .5 by SPDI.
        cursor.execute("SELECT raw_input, error_code FROM manual_queue WHERE raw_input LIKE 'chr9:132891409%'")
        tsc1_manual = cursor.fetchall()
        assert tsc1_manual == []
        cursor.execute("SELECT variant_id FROM evidence WHERE variant_id LIKE 'chr9:132891409%'")
        assert cursor.fetchall(), "TSC1 .4 row must be scored after scope+transcript reconciliation."

        # The TSC2 .4 row:
        # BASELINE: EDGE_CASE_ROUTED (because NM_000548.4 != NM_000548.5)
        # CORRECTED: scored (because of SPDI reconciliation)
        # Since this test must pass when the feature is complete, we assert the CORRECTED state.

        cursor.execute("SELECT raw_input, error_code FROM manual_queue WHERE raw_input LIKE 'chr16:2048616%'")
        tsc2_manual = cursor.fetchall()

        if len(tsc2_manual) == 1 and tsc2_manual[0][1] == "EDGE_CASE_ROUTED":
            pytest.fail("BASELINE MISROUTE ACTIVE: TSC2 .4 row misrouted to EDGE_CASE_ROUTED. "
                        "The doer must implement transcript reconciliation to score this row.")

        cursor.execute("SELECT variant_id FROM evidence WHERE variant_id LIKE 'chr16:2048616%'")
        tsc2_evidence = cursor.fetchall()
        assert len(tsc2_evidence) > 0, "TSC2 .4 row must be scored after reconciliation."

    finally:
        Path(temp_tsv_path).unlink()
