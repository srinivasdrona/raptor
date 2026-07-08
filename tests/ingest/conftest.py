import os
import pytest
from raptor.kb.store import KBStore

# We use absolute imports but wrap in try/except or just let them fail during --collect-only
from raptor.ingest.model import (
    RawVariant, NormalizedVariant, ManualQueueItem, VariantClass
)
from raptor.ingest.normalizer import Normalizer

class FakeNormalizer:
    """A deterministic test double for the plumbing, not for correctness."""
    def __init__(self, fail_coords=None, manual_queue_coords=None):
        self.fail_coords = fail_coords or set()
        self.manual_queue_coords = manual_queue_coords or set()

    def normalize(self, raw, config):
        coords = f"{raw.chromosome}:{raw.position}:{raw.ref}:{raw.alt}"
        if coords in self.fail_coords:
            raise ValueError(f"Simulated normalizer crash for {coords}")
        
        if coords in self.manual_queue_coords:
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="normalize",
                error_code="COMPLEX",
                reason="Simulated complex variant",
                attempted_coords=coords,
                tool_error=None,
                config_pins={},
                run_id="test_run",
                excluded_from_scorer=True
            )
        
        return NormalizedVariant(
            variant_id=f"NC_000000.0:{raw.position}:{raw.ref}:{raw.alt}",
            hgvs_g=f"NC_000000.0:g.{raw.position}{raw.ref}>{raw.alt}",
            hgvs_c=f"NM_000000.0:c.1{raw.ref}>{raw.alt}",
            hgvs_p=f"NP_000000.0:p.X1Y",
            hgvs_c_null_reason=None,
            hgvs_p_null_reason=None,
            variant_class=VariantClass.SNV,
            gene=raw.gene,
            variation_id=raw.variation_id,
            snapshot_id=raw.snapshot_id,
            snapshot_date=raw.snapshot_date,
            source_file_checksum=raw.source_file_checksum,
            row_locator=raw.row_locator,
            raw_source_value=raw.raw_source_value
        )

@pytest.fixture
def fake_normalizer():
    return FakeNormalizer()

@pytest.fixture
def tmp_kb_store(tmp_path):
    db_path = tmp_path / "test_kb.sqlite"
    store = KBStore(str(db_path))
    # create schema if needed by calling some internal init or it might be auto-created
    return store
