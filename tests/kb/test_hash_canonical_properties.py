import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
import pytest

from raptor.kb.store import KBStore, canonical_json
from raptor.kb.ledger import EventType

def populate_kb(store: KBStore, run_id: str, surrogate_overrides: dict[str, Any]) -> None:
    """
    Helper to build a standard logical KB state.
    Applies operations so every surrogate type is represented in the data
    and in ledger payloads/target_ids.
    """
    prov = KBStore.build_provenance(
        tool_version="1.0",
        source="test",
        source_snapshot_version="1",
        env_versions={},
        originating_run=run_id,
        timestamp="2026-01-01T00:00:00Z"
    )

    orig_compute = KBStore.compute_source_ref_id
    def mock_compute(source, accession, snapshot_id, row_locator):
        if source == "test_source" and accession == "acc1":
            return surrogate_overrides.get("source_ref_id_1", orig_compute(source, accession, snapshot_id, row_locator))
        if source == "test_source" and accession == "acc2":
            return surrogate_overrides.get("source_ref_id_2", orig_compute(source, accession, snapshot_id, row_locator))
        return orig_compute(source, accession, snapshot_id, row_locator)

    with patch.object(KBStore, 'compute_source_ref_id', side_effect=mock_compute):
        sr1 = store.stage_source_ref(
            run_id=run_id,
            source="test_source",
            accession="acc1",
            snapshot_id="test_snap_1",
            snapshot_date="2026-01-01",
            source_file_checksum="xyz",
            raw_value="raw1",
            provenance=prov
        )
        sr2 = store.stage_source_ref(
            run_id=run_id,
            source="test_source",
            accession="acc2",
            snapshot_id="test_snap_2",
            snapshot_date="2026-01-01",
            source_file_checksum="abc",
            raw_value="raw2",
            provenance=prov
        )
        
        store.stage_variant(
            run_id=run_id,
            variant_id="VAR1",
            gene="GENE1",
            class_="class1",
            provenance=prov,
            source_ref_ids=[sr1, sr2]
        )

        store.stage_evidence_added(
            run_id=run_id,
            seq_in_run=1,
            variant_id="VAR1",
            tier="tier1",
            criterion="PVS1",
            strength="very_strong",
            direction="pathogenic",
            source_ref_id=sr1,
            row_provenance=prov,
            event_provenance=prov,
            event_timestamp="2026-01-01T00:00:00Z"
        )
        
        store.publish(run_id)

    # Run 2: Correct evidence
    ev_row = store.conn.execute("SELECT evidence_id FROM evidence WHERE variant_id='VAR1'").fetchone()
    ev1_id = ev_row["evidence_id"]

    run2_id = run_id + "_2"
    prov2 = KBStore.build_provenance(
        tool_version="1.0",
        source="test",
        source_snapshot_version="1",
        env_versions={},
        originating_run=run2_id,
        timestamp="2026-01-02T00:00:00Z"
    )
    
    store.stage_evidence_correction(
        run_id=run2_id,
        seq_in_run=1,
        prior_evidence_id=ev1_id,
        variant_id="VAR1",
        tier="tier1",
        criterion="PVS1",
        strength="strong",
        direction="pathogenic",
        source_ref_id=sr1,
        row_provenance=prov2,
        event_provenance=prov2,
        event_timestamp="2026-01-02T00:00:00Z"
    )
    store.publish(run2_id)
    
    # Run 3: Retract the new evidence and add source_superseded
    ev_row2 = store.conn.execute("SELECT evidence_id FROM evidence WHERE supersedes_evidence_id=?", (ev1_id,)).fetchone()
    ev2_id = ev_row2["evidence_id"]
    
    run3_id = run_id + "_3"
    prov3 = KBStore.build_provenance(
        tool_version="1.0",
        source="test",
        source_snapshot_version="1",
        env_versions={},
        originating_run=run3_id,
        timestamp="2026-01-03T00:00:00Z"
    )
    store.stage_evidence_retraction(
        run_id=run3_id,
        seq_in_run=1,
        evidence_id=ev2_id,
        provenance=prov3,
        timestamp="2026-01-03T00:00:00Z"
    )
    
    store.conn.execute(
        """
        INSERT INTO temp.stg_ledger_events
            (run_id, seq_in_run, event_type, target_id, payload, provenance, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (run3_id, 2, EventType.SOURCE_SUPERSEDED, sr1, canonical_json({"superseded_by": sr2}), prov3, "2026-01-03T00:00:00Z")
    )

    store.publish(run3_id)

    # Build snapshot and classification version
    snap_id = surrogate_overrides.get("snapshot_id", "SNAP_1")
    high_watermark = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()[0]
    
    store.build_evidence_snapshot(
        snapshot_id=snap_id,
        variant_id="VAR1",
        ledger_high_watermark=high_watermark,
        combination_rule_ref="rule_1",
        provenance=prov3
    )
    
    store.record_classification_version(
        variant_id="VAR1",
        version="v1.0",
        evidence_snapshot_ref=snap_id,
        status="VUS",
        approvals=[],
        timestamp="2026-01-04T00:00:00Z",
        provenance=prov3
    )

    # Add to manual_queue
    run4_id = run_id + "_4"
    prov4 = KBStore.build_provenance(
        tool_version="1.0",
        source="test",
        source_snapshot_version="1",
        env_versions={},
        originating_run=run4_id,
        timestamp="2026-01-05T00:00:00Z"
    )
    store.stage_manual_queue(
        run_id=run4_id,
        raw_input="raw",
        source_ref_id=sr1,
        failure_stage="parse",
        error_code="E1",
        reason="test",
        config_pins={},
        provenance=prov4,
        created_at="2026-01-05T00:00:00Z"
    )
    store.publish(run4_id)

    # Add to knowledge_assertions
    store.conn.execute(
        """
        INSERT INTO knowledge_assertions
            (source_ref_id, assertion_type, subject, object, status, provenance)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (sr1, "type1", "sub1", "obj1", "hypothesis", prov4)
    )

SURROGATES = [
    "ledger_seq",
    "evidence_id",
    "mq_id",
    "assertion_id",
    "source_ref_id",
    "snapshot_id"
]

@pytest.mark.parametrize("surrogate_type", SURROGATES)
def test_surrogate_remap_invariant(tmp_path: Path, surrogate_type: str):
    db1_path = tmp_path / "db1.sqlite"
    db2_path = tmp_path / "db2.sqlite"

    overrides1 = {}
    overrides2 = {}
    if surrogate_type == "source_ref_id":
        overrides1["source_ref_id_1"] = "SR_A_1"
        overrides1["source_ref_id_2"] = "SR_A_2"
        overrides2["source_ref_id_1"] = "SR_B_1"
        overrides2["source_ref_id_2"] = "SR_B_2"
    elif surrogate_type == "snapshot_id":
        overrides1["snapshot_id"] = "SNAP_A"
        overrides2["snapshot_id"] = "SNAP_B"

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        if surrogate_type in ("ledger_seq", "evidence_id", "mq_id", "assertion_id"):
            table_name = {
                "ledger_seq": "ledger",
                "evidence_id": "evidence",
                "mq_id": "manual_queue",
                "assertion_id": "knowledge_assertions"
            }[surrogate_type]
            
            if table_name == "ledger":
                store2.conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                store2.conn.execute("INSERT INTO dummy DEFAULT VALUES")
                store2.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, 100)", (table_name,))
            elif table_name == "evidence":
                store2.conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                store2.conn.execute("INSERT INTO dummy DEFAULT VALUES")
                store2.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, 100)", (table_name,))
            elif table_name == "manual_queue":
                store2.conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                store2.conn.execute("INSERT INTO dummy DEFAULT VALUES")
                store2.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, 100)", (table_name,))
            elif table_name == "knowledge_assertions":
                store2.conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY AUTOINCREMENT)")
                store2.conn.execute("INSERT INTO dummy DEFAULT VALUES")
                store2.conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, 100)", (table_name,))

        populate_kb(store1, "run1", overrides1)
        populate_kb(store2, "run1", overrides2)

        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        
        if surrogate_type in ("ledger_seq", "evidence_id", "mq_id", "assertion_id"):
            col = surrogate_type
            table = {
                "ledger_seq": "ledger",
                "evidence_id": "evidence",
                "mq_id": "manual_queue",
                "assertion_id": "knowledge_assertions"
            }[surrogate_type]
            id1 = store1.conn.execute(f"SELECT MIN({col}) FROM {table}").fetchone()[0]
            id2 = store2.conn.execute(f"SELECT MIN({col}) FROM {table}").fetchone()[0]
            assert id1 != id2, f"Failed to force different {col} values"
        
        assert hash1 == hash2, f"Hash is sensitive to raw {surrogate_type} values (not properly canonicalized)"

def test_ledger_order_sensitive(tmp_path: Path):
    db1_path = tmp_path / "db1.sqlite"
    db2_path = tmp_path / "db2.sqlite"

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        prov1 = KBStore.build_provenance(tool_version="1", source="test", source_snapshot_version="1", env_versions={}, originating_run="run1", timestamp="t1")
        prov2 = KBStore.build_provenance(tool_version="1", source="test", source_snapshot_version="1", env_versions={}, originating_run="run1", timestamp="t2")
        
        store1.conn.execute("PRAGMA foreign_keys=OFF")
        store2.conn.execute("PRAGMA foreign_keys=OFF")
        
        store1.conn.execute("INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) VALUES ('variant_observed', 'V1', 'run1', '{}', ?, 't1')", (prov1,))
        store1.conn.execute("INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) VALUES ('variant_observed', 'V2', 'run1', '{}', ?, 't2')", (prov2,))
        
        store2.conn.execute("INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) VALUES ('variant_observed', 'V2', 'run1', '{}', ?, 't2')", (prov2,))
        store2.conn.execute("INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp) VALUES ('variant_observed', 'V1', 'run1', '{}', ?, 't1')", (prov1,))
        
        store1.conn.execute("PRAGMA foreign_keys=ON")
        store2.conn.execute("PRAGMA foreign_keys=ON")
        
        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        
        assert hash1 != hash2, "Hash must be sensitive to ledger event order"

def test_logical_difference_sensitive(tmp_path: Path):
    db1_path = tmp_path / "db1.sqlite"
    db2_path = tmp_path / "db2.sqlite"

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        populate_kb(store1, "run1", {})
        populate_kb(store2, "run1", {})
        
        prov = KBStore.build_provenance(tool_version="1.0", source="test", source_snapshot_version="1", env_versions={}, originating_run="run1", timestamp="2026-01-05T00:00:00Z")
        sr1 = store2.conn.execute("SELECT source_ref_id FROM source_refs LIMIT 1").fetchone()[0]
        store2.conn.execute(
            "INSERT INTO knowledge_assertions (source_ref_id, assertion_type, subject, object, status, provenance) VALUES (?, ?, ?, ?, ?, ?)",
            (sr1, "type2", "sub2", "obj2", "hypothesis", prov)
        )
        
        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        assert hash1 != hash2, "Hash must change when logical state changes"
