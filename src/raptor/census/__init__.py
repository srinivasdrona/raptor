"""raptor.census — packet-free ADR-0012 VUS evidence census toolkit.

Public surface: strata reproduction (`strata.py`) and non-identifying
aggregate construction (`aggregate.py`). This package imports only
`raptor.scorer` + `raptor.eval`; it never imports `raptor.packet` (D1/P7).
The CLI (`raptor.census.cli`) is imported directly by callers/tests, not
re-exported here, so `import raptor.census` never pulls in argparse/CLI
plumbing as a side effect.
"""
from __future__ import annotations

from .aggregate import build_census_record
from .strata import (
    BASIS,
    STRENGTH_MAP,
    ConservationError,
    ManifestEntry,
    ManifestError,
    StratumEntry,
    load_manifest,
    reproduce_census_strata,
)

__all__ = [
    "BASIS",
    "STRENGTH_MAP",
    "ConservationError",
    "ManifestEntry",
    "ManifestError",
    "StratumEntry",
    "load_manifest",
    "reproduce_census_strata",
    "build_census_record",
]
