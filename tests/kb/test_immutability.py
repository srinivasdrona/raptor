"""AC2 — Immutability (H4/H5).

UPDATE/DELETE on every history table (ledger, variants, source_refs,
variant_source_refs, evidence, evidence_snapshots, classification_versions,
knowledge_assertions) fails; a correction/retraction is representable only
as a new ledger event targeting a prior id — never an in-place edit.
"""

from __future__ import annotations

import sqlite3

import pytest

from raptor.kb.store import KBStore

HISTORY_TABLES: tuple[str, ...] = (
    "ledger",
    "variants",
    "source_refs",
    "variant_source_refs",
    "evidence",
    "evidence_snapshots",
    "classification_versions",
    "knowledge_assertions",
)


@pytest.mark.parametrize("table", HISTORY_TABLES)
def test_update_rejected(store, seeded_history, table):
    where_clause, params = seeded_history[table]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(f"UPDATE {table} SET provenance = provenance WHERE {where_clause}", params)
    # Prove the row is genuinely unmodified (not merely "an exception happened").
    (count,) = store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", params).fetchone()
    assert count == 1


@pytest.mark.parametrize("table", HISTORY_TABLES)
def test_delete_rejected(store, seeded_history, table):
    where_clause, params = seeded_history[table]
    (before,) = store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", params).fetchone()
    assert before == 1

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(f"DELETE FROM {table} WHERE {where_clause}", params)

    (after,) = store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_clause}", params).fetchone()
    assert after == 1  # still there — DELETE was actually blocked, not a silent no-op match


def test_correction_is_new_ledger_event_not_mutation(store, seeded_history, make_provenance):
    """FR3: a correction to `evidence` must be a NEW ledger event + NEW evidence
    row (with `supersedes_evidence_id` pointing at the prior one) — the prior
    row's content is never touched."""
    ids = seeded_history["_ids"]
    prior_evidence_id = ids["evidence_id"]
    variant_id = ids["variant_id"]
    source_ref_id = ids["source_ref_id"]

    before_row = dict(
        store.conn.execute("SELECT * FROM evidence WHERE evidence_id = ?", (prior_evidence_id,)).fetchone()
    )

    run_id = "correction-run"
    prov = make_provenance(run_id=run_id)
    store.stage_evidence_correction(
        run_id,
        seq_in_run=1,
        prior_evidence_id=prior_evidence_id,
        variant_id=variant_id,
        tier="tier1",
        criterion="PM2",
        strength="strong",  # corrected from 'moderate' -> 'strong'
        direction="pathogenic",
        source_ref_id=source_ref_id,
        row_provenance=prov,
        event_provenance=prov,
        event_timestamp="2026-02-01T00:00:00Z",
    )
    store.publish(run_id)

    after_row = dict(
        store.conn.execute("SELECT * FROM evidence WHERE evidence_id = ?", (prior_evidence_id,)).fetchone()
    )
    assert after_row == before_row  # prior row byte-for-byte unchanged

    new_row = dict(
        store.conn.execute(
            "SELECT * FROM evidence WHERE supersedes_evidence_id = ?", (prior_evidence_id,)
        ).fetchone()
    )
    assert new_row["strength"] == "strong"
    assert new_row["evidence_id"] != prior_evidence_id
    assert new_row["supersedes_evidence_id"] == prior_evidence_id

    # And the prior row is still immutable even after the correction landed.
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE evidence SET strength = 'strong' WHERE evidence_id = ?", (prior_evidence_id,)
        )
