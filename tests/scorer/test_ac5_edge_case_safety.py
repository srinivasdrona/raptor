import pytest
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.pipeline import run_scorer

def test_ac5_edge_cases_route_to_manual_review(temp_kb, fake_bias_source):
    config = ScorerConfig(
        bias_version="1.0",
        bias_data_version="1.0",
        included_criteria=["PVS1", "PM2"],
        strength_map={"1": "supporting", "3": "strong"},
        acmg_criteria={
            "PVS1": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
        },
        edge_cases={
            "non_mane_transcript": True,
            "splice_region": True
        },
        genes={"TSC2": "NM_000548.5"},
        licensing={}
    )
    records = [
        BiasRecord(
            chromosome="chr16", position=100, ref_allele="A", alt_allele="T", variant_id="var1",
            variant_type="SNV", consequence="missense_variant", acmg_classification="uncertain",
            gene_name="TSC2", transcript="NM_999999.1",
            criteria={"pvs1": (3, "expl")},
            provenance={"source": "bias"}
        ),
        BiasRecord(
            chromosome="chr16", position=200, ref_allele="C", alt_allele="G", variant_id="var2",
            variant_type="SNV", consequence="splice_region_variant", acmg_classification="uncertain",
            gene_name="TSC2", transcript="NM_000548.5",
            criteria={"pm2": (1, "expl")},
            provenance={"source": "bias"}
        )
    ]
    source = fake_bias_source(records)
    report = run_scorer(config, source, temp_kb)
    
    cursor = temp_kb.conn.cursor()
    cursor.execute("SELECT variant_id FROM evidence WHERE variant_id IN ('var1', 'var2')")
    scored = cursor.fetchall()
    assert len(scored) == 0, f"Edge cases were silently scored: {scored}"
    
    cursor.execute("SELECT raw_input FROM manual_queue")
    manual = cursor.fetchall()
    assert len(manual) == 2, "Both edge cases should be in the manual_queue"
    assert report.manual_review_count == 2
