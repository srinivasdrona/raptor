import pytest
from hypothesis import given, settings
import hypothesis.strategies as st
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.pipeline import run_scorer
from collections import defaultdict

@given(generated_data=st.lists(
    st.fixed_dictionaries({
        "chr": st.sampled_from(["chr1", "chr16"]),
        "pos": st.integers(1, 1000000),
        "ref": st.sampled_from(["A", "C", "G", "T"]),
        "alt": st.sampled_from(["A", "C", "G", "T"]),
        "crit1_val": st.integers(0, 5),
        "crit2_val": st.integers(0, 5)
    }),
    min_size=1, max_size=5
))
@settings(max_examples=10)
def test_ac4_no_double_count(fake_bias_source, generated_data):
    from raptor.kb.store import KBStore
    temp_kb = KBStore(":memory:")
    config = ScorerConfig(
        bias_version="1.0",
        bias_data_version="1.0",
        included_criteria=["PVS1", "PM2"],
        strength_map={"1": "supporting", "2": "moderate", "3": "strong", "4": "very_strong", "5": "stand_alone"},
        acmg_criteria={
            "PVS1": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
        },
        edge_cases={},
        genes={"TSC2": "NM_000548.5"},
        licensing={}
    )
    records = []
    for i, d in enumerate(generated_data):
        records.append(BiasRecord(
            chromosome=d["chr"], position=d["pos"], ref_allele=d["ref"], alt_allele=d["alt"],
            variant_id=f'{d["chr"]}:{d["pos"]}:{d["ref"]}:{d["alt"]}:{i}',
            variant_type="SNV", consequence="missense_variant", acmg_classification="uncertain",
            gene_name="TSC2", transcript="NM_000548.5",
            criteria={"pvs1": (d["crit1_val"], "expl"), "pm2": (d["crit2_val"], "expl")},
            provenance={"source": "bias"}
        ))
    source = fake_bias_source(records)
    run_scorer(config, source, temp_kb)
    
    cursor = temp_kb.conn.cursor()
    cursor.execute("SELECT variant_id, criterion, COUNT(*) FROM evidence GROUP BY variant_id, criterion HAVING COUNT(*) > 1")
    rows = cursor.fetchall()
    
    assert len(rows) == 0, f"Found duplicate criteria counts: {rows}"
