"""AC8 — Manual-queue integrity.

`manual_queue` rows conform to PRD-02 FR6 (source_ref, run_id, error_code,
failure_stage, config_pins, excluded_from_scorer=1); a scorer-includable
manual row (excluded_from_scorer != 1) fails.
"""

from __future__ import annotations

import sqlite3

import pytest

from raptor.kb.store import KBStore


def _valid_source_ref(store, prov, row_locator="mq-row-1"):
    source_ref_id = KBStore.compute_source_ref_id("ClinVar", "VCV_mq", "snap-1", row_locator)
    store.conn.execute(
        """
        INSERT INTO source_refs
            (source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance)
        VALUES (?, 'ClinVar', 'VCV_mq', 'snap-1', '2026-01-01', 'chk', ?, 'raw row', 'resolved', ?)
        """,
        (source_ref_id, row_locator, prov),
    )
    return source_ref_id


def test_fr6_conformant_row_succeeds(store, make_provenance):
    prov = make_provenance(run_id="run-mq-1")
    source_ref_id = _valid_source_ref(store, prov)
    store.conn.execute(
        """
        INSERT INTO manual_queue
            (raw_input, source_ref_id, failure_stage, error_code, reason,
             attempted_coords, tool_error, config_pins, run_id, excluded_from_scorer,
             provenance, created_at)
        VALUES ('NM_000548.5:c.999+1G>A', ?, 'normalize', 'E-TRANSCRIPT-PROJECTION',
                'transcript projection failed for non-MANE alias', 'g.2100000A>G', 'ProjectionError: ...',
                '{"mane_version":"1.4","assembly":"GRCh38"}', 'run-mq-1', 1, ?, '2026-01-01T00:00:00Z')
        """,
        (source_ref_id, prov),
    )
    row = dict(
        store.conn.execute(
            "SELECT * FROM manual_queue WHERE error_code = 'E-TRANSCRIPT-PROJECTION'"
        ).fetchone()
    )
    assert row["source_ref_id"] == source_ref_id
    assert row["run_id"] == "run-mq-1"
    assert row["error_code"] == "E-TRANSCRIPT-PROJECTION"
    assert row["failure_stage"] == "normalize"
    assert row["config_pins"] == '{"mane_version":"1.4","assembly":"GRCh38"}'
    assert row["excluded_from_scorer"] == 1
    assert row["status"] == "open"


def test_scorer_includable_row_rejected(store, make_provenance):
    prov = make_provenance(run_id="run-mq-2")
    source_ref_id = _valid_source_ref(store, prov)
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO manual_queue
                (raw_input, source_ref_id, failure_stage, error_code, reason,
                 config_pins, run_id, excluded_from_scorer, provenance, created_at)
            VALUES ('raw', ?, 'normalize', 'E001', 'reason', '{}', 'run-mq-2', 0, ?, '2026-01-01T00:00:00Z')
            """,
            (source_ref_id, prov),
        )


@pytest.mark.parametrize(
    "column,value",
    [
        ("failure_stage", None),
        ("error_code", None),
        ("reason", None),
        ("config_pins", None),
        ("run_id", None),
    ],
)
def test_required_fr6_field_missing_rejected(store, make_provenance, column, value):
    prov = make_provenance(run_id="run-mq-3")
    source_ref_id = _valid_source_ref(store, prov)
    fields = {
        "raw_input": "raw",
        "source_ref_id": source_ref_id,
        "failure_stage": "normalize",
        "error_code": "E001",
        "reason": "some reason",
        "config_pins": "{}",
        "run_id": "run-mq-3",
        "excluded_from_scorer": 1,
        "provenance": prov,
        "created_at": "2026-01-01T00:00:00Z",
    }
    fields[column] = value
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            """
            INSERT INTO manual_queue
                (raw_input, source_ref_id, failure_stage, error_code, reason,
                 config_pins, run_id, excluded_from_scorer, provenance, created_at)
            VALUES (:raw_input, :source_ref_id, :failure_stage, :error_code, :reason,
                    :config_pins, :run_id, :excluded_from_scorer, :provenance, :created_at)
            """,
            fields,
        )


def test_only_status_is_mutable(store, make_provenance):
    prov = make_provenance(run_id="run-mq-4")
    source_ref_id = _valid_source_ref(store, prov)
    store.conn.execute(
        """
        INSERT INTO manual_queue
            (raw_input, source_ref_id, failure_stage, error_code, reason,
             config_pins, run_id, excluded_from_scorer, provenance, created_at)
        VALUES ('raw', ?, 'normalize', 'E001', 'reason', '{}', 'run-mq-4', 1, ?, '2026-01-01T00:00:00Z')
        """,
        (source_ref_id, prov),
    )
    (mq_id,) = store.conn.execute(
        "SELECT mq_id FROM manual_queue WHERE run_id = 'run-mq-4'"
    ).fetchone()

    # status IS mutable — this must succeed.
    store.conn.execute("UPDATE manual_queue SET status = 'resolved' WHERE mq_id = ?", (mq_id,))
    (status,) = store.conn.execute(
        "SELECT status FROM manual_queue WHERE mq_id = ?", (mq_id,)
    ).fetchone()
    assert status == "resolved"

    # Any other column is NOT mutable, even on an operational table.
    with pytest.raises(sqlite3.IntegrityError, match="only status is mutable"):
        store.conn.execute("UPDATE manual_queue SET reason = 'changed my mind' WHERE mq_id = ?", (mq_id,))

    with pytest.raises(sqlite3.IntegrityError, match="only status is mutable"):
        store.conn.execute("UPDATE manual_queue SET excluded_from_scorer = 0 WHERE mq_id = ?", (mq_id,))


def test_staged_manual_queue_row_publishes_with_run_id_intact(store, make_provenance):
    """AC8-STAGED-MANUAL-QUEUE-RUN-ID-DROP (checker fix): a manual_queue row
    staged through the REAL `stage_manual_queue()` API must actually
    PUBLISH successfully and be present afterward with its `run_id` intact.

    Previously, `publish()`'s `INSERT INTO manual_queue ... SELECT ...`
    omitted the `run_id` column while the schema requires it NOT NULL, so
    every validly staged manual_queue row failed to publish at all.
    """
    run_id = "run-mq-publish-1"
    prov = make_provenance(run_id=run_id)
    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession="VCV_mq_publish", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    store.stage_manual_queue(
        run_id,
        raw_input="NM_000548.5:c.999+1G>A",
        source_ref_id=source_ref_id,
        failure_stage="normalize",
        error_code="E-TRANSCRIPT-PROJECTION",
        reason="transcript projection failed for non-MANE alias",
        config_pins={"mane_version": "1.4", "assembly": "GRCh38"},
        provenance=prov,
        created_at="2026-01-01T00:00:00Z",
        attempted_coords="g.2100000A>G",
        tool_error="ProjectionError: ...",
    )

    # Must not raise, and staging for this run must empty out afterward.
    store.publish(run_id)
    assert store.staged_counts(run_id)["stg_manual_queue"] == 0

    row = dict(
        store.conn.execute(
            "SELECT * FROM manual_queue WHERE error_code = 'E-TRANSCRIPT-PROJECTION'"
        ).fetchone()
    )
    assert row["run_id"] == run_id
    assert row["source_ref_id"] == source_ref_id
    assert row["failure_stage"] == "normalize"
    assert row["config_pins"] == '{"assembly":"GRCh38","mane_version":"1.4"}'
    assert row["excluded_from_scorer"] == 1
    assert row["status"] == "open"
