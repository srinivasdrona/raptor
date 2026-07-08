"""AC6 — Provenance completeness (GP-5).

A row missing any required provenance field fails. Required field set
(PRD-03 FR7 / ARCHITECTURE §8): tool_version, source, source_snapshot_version,
env_versions, originating_run, timestamp. `model` and `prompt_version` are
optional.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from raptor.kb.store import KBStore, canonical_json

REQUIRED_FIELDS = (
    "tool_version",
    "source",
    "source_snapshot_version",
    "env_versions",
    "originating_run",
    "timestamp",
)


def _provenance_missing(field: str, run_id: str = "run-1") -> str:
    prov = {
        "tool_version": "raptor-kb-test-0.1.0",
        "source": "test-fixture",
        "source_snapshot_version": "snap-1",
        "env_versions": {"python": "3.12.3"},
        "originating_run": run_id,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    del prov[field]
    return canonical_json(prov)


@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_source_refs_row_missing_provenance_field_rejected(store, missing_field):
    bad_prov = _provenance_missing(missing_field)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO source_refs
                (source_ref_id, source, accession, snapshot_id, snapshot_date,
                 source_file_checksum, row_locator, raw_value, resolver_status, provenance)
            VALUES ('sref-missing', 'ClinVar', 'VCV1', 'snap-1', '2026-01-01', 'chk', 'row-1',
                    'raw', 'resolved', ?)
            """,
            (bad_prov,),
        )
    (count,) = store.conn.execute(
        "SELECT COUNT(*) FROM source_refs WHERE source_ref_id = 'sref-missing'"
    ).fetchone()
    assert count == 0


@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_variants_row_missing_provenance_field_rejected(store, missing_field):
    bad_prov = _provenance_missing(missing_field)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO variants (variant_id, gene, class, provenance) VALUES ('v-missing', 'TSC2', 'missense', ?)",
            (bad_prov,),
        )


@pytest.mark.parametrize("missing_field", REQUIRED_FIELDS)
def test_ledger_row_missing_provenance_field_rejected(store, missing_field):
    bad_prov = _provenance_missing(missing_field)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp)
            VALUES ('variant_observed', 'v-missing', 'run-1', '{}', ?, '2026-01-01T00:00:00Z')
            """,
            (bad_prov,),
        )


def test_ledger_originating_run_must_match_run_id_column(store):
    """provenance.originating_run and the row's own run_id column must agree."""
    mismatched_prov = canonical_json(
        {
            "tool_version": "v1",
            "source": "test",
            "source_snapshot_version": "snap-1",
            "env_versions": {"python": "3.12.3"},
            "originating_run": "run-A",
            "timestamp": "2026-01-01T00:00:00Z",
        }
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp)
            VALUES ('variant_observed', 'v-mismatch', 'run-B', '{}', ?, '2026-01-01T00:00:00Z')
            """,
            (mismatched_prov,),
        )


def test_malformed_json_provenance_rejected(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO variants (variant_id, gene, class, provenance) VALUES ('v-badjson', 'TSC2', 'missense', ?)",
            ("{not valid json",),
        )


def test_complete_provenance_succeeds(store, make_provenance):
    """Positive control: proves rejections above are due to missing fields, not unrelated errors."""
    prov = make_provenance()
    store.conn.execute(
        "INSERT INTO variants (variant_id, gene, class, provenance) VALUES ('v-good', 'TSC2', 'missense', ?)",
        (prov,),
    )
    (count,) = store.conn.execute("SELECT COUNT(*) FROM variants WHERE variant_id = 'v-good'").fetchone()
    assert count == 1
    # And every required field really is present in what we stored.
    stored = json.loads(
        store.conn.execute("SELECT provenance FROM variants WHERE variant_id = 'v-good'").fetchone()[0]
    )
    for field in REQUIRED_FIELDS:
        assert field in stored and stored[field] not in (None, "")
