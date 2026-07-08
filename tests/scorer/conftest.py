import pytest
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable

# We won't import raptor directly in global scope because tests must fail cleanly with ImportError 
# on --collect-only before the doer implements it. We import inside fixtures/tests.

@pytest.fixture
def fake_bias_source():
    # Provide a FakeBiasSource class that tests can use
    class FakeBiasSource:
        def __init__(self, records):
            self._records = records
            
        def records(self, run=None):
            return self._records
    return FakeBiasSource

@pytest.fixture
def temp_kb():
    from raptor.kb.store import KBStore
    return KBStore(":memory:")

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"
