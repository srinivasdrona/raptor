import pytest
from raptor.scorer.config import ScorerConfig
from raptor.scorer.model import BiasRecord
from raptor.scorer.pipeline import run_scorer

def test_ac2_grounding(temp_kb, fake_bias_source):
    config = ScorerConfig(
        bias_version='1.0',
        bias_data_version='2015',
        included_criteria=['PVS1', 'PM2'],
        strength_map={'1': 'supporting', '2': 'moderate', '3': 'strong', '4': 'very_strong', '5': 'stand_alone'},
        acmg_criteria={
            "PVS1": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
            "PM2": {"direction": "pathogenic", "strength_vocab": ["stand_alone", "very_strong", "strong", "moderate", "supporting"]},
        },
        edge_cases={'mosaicism': 'mosaic'},
        genes={'TSC2': 'NM_000548.5'},
        licensing={}
    )
    records = [
        BiasRecord(
            chromosome='chr16', position=2097000, ref_allele='G', alt_allele='A',
            variant_id='chr16:2097000:G:A',
            variant_type='SNV', consequence='missense_variant', acmg_classification='uncertain',
            gene_name='TSC2', transcript='NM_000548.5',
            criteria={'pvs1': (3, 'PVS1_strong'), 'pm2': (1, 'PM2_supporting')},
            provenance={'source': 'bias'}
        )
    ]
    source = fake_bias_source(records)
    report = run_scorer(config, source, temp_kb)
    
    cursor = temp_kb.conn.cursor()
    cursor.execute('SELECT evidence_id, source_ref_id FROM evidence')
    evidence_rows = cursor.fetchall()
    assert len(evidence_rows) > 0, 'Should have emitted some evidence'
    for ev_id, source_ref_id in evidence_rows:
        assert source_ref_id is not None, 'Evidence has null source_ref_id'
        cursor.execute('SELECT source_ref_id FROM source_refs WHERE source_ref_id = ?', (source_ref_id,))
        ref = cursor.fetchone()
        assert ref is not None, 'Evidence points to missing source_ref'
