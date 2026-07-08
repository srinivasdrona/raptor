"""PRD-01 sec 10.3 — `KBStore.stage_evidence_kind` (FR9/AC7, no-state-change-on-failure).

`register_evidence_kind` (tests/kb/test_register_evidence_kind.py) writes
`evidence_kinds` eagerly and stays as the sanctioned "just register this
now" API. `stage_evidence_kind` is the atomic counterpart the scorer's
`run_scorer` uses instead: the candidate row is held in the
connection-scoped `temp.stg_evidence_kinds` table and only applied —
`INSERT OR IGNORE`, inside `publish()`'s single `BEGIN IMMEDIATE`
transaction — once the whole run's staged state is otherwise valid. A run
that never publishes (discarded) or whose `publish()` fails must leave
`evidence_kinds` (and therefore `published_state_hash()`) byte-identical.
"""
from __future__ import annotations

import json

import pytest

from raptor.kb.store import KBStore, PublishError


def test_staged_kind_not_registered_until_publish(store, make_provenance):
    run_id = "run-stage-kind-1"
    prov = make_provenance(run_id=run_id)

    store.stage_evidence_kind(
        run_id, tier="tier1", criterion="PP2", direction="pathogenic",
        strength_vocab=["supporting"],
    )

    # Not yet in the reference table -- staging is not the source of truth.
    row = store.conn.execute(
        "SELECT 1 FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PP2'"
    ).fetchone()
    assert row is None

    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession="VCV1", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    variant_id = "NC_000016.10:6300000:A:G"
    store.stage_variant(
        run_id, variant_id=variant_id, gene="TSC2", class_="missense", provenance=prov,
        source_ref_ids=source_ref_id,
    )
    store.stage_evidence_added(
        run_id, seq_in_run=1, variant_id=variant_id, tier="tier1", criterion="PP2",
        strength="supporting", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov, event_provenance=prov, event_timestamp="2026-01-01T00:00:00Z",
    )

    store.publish(run_id)

    row = store.conn.execute(
        "SELECT direction, strength_vocab FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PP2'"
    ).fetchone()
    assert row is not None
    assert row["direction"] == "pathogenic"
    assert json.loads(row["strength_vocab"]) == ["supporting"]

    # And the staged row itself is gone post-publish.
    (n,) = store.conn.execute(
        "SELECT COUNT(*) FROM temp.stg_evidence_kinds WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert n == 0


def test_discarded_staged_kind_never_reaches_evidence_kinds(store, make_provenance):
    """A run that stages a kind but is discarded (never published) must
    leave `evidence_kinds` and `published_state_hash()` untouched."""
    h_before = store.published_state_hash()

    run_id = "run-stage-kind-discarded"
    store.stage_evidence_kind(
        run_id, tier="tier1", criterion="PM3", direction="pathogenic",
        strength_vocab=["supporting"],
    )
    (n,) = store.conn.execute(
        "SELECT COUNT(*) FROM temp.stg_evidence_kinds WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert n == 1

    store.discard_staging(run_id)

    (n,) = store.conn.execute(
        "SELECT COUNT(*) FROM temp.stg_evidence_kinds WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert n == 0
    row = store.conn.execute(
        "SELECT 1 FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PM3'"
    ).fetchone()
    assert row is None
    assert store.published_state_hash() == h_before


def test_failed_publish_rolls_back_staged_kind_with_everything_else(store, make_provenance):
    """Same shape as test_atomic_publish.py's mid-publish failure case, but
    proving the staged evidence_kinds registration rolls back too, not just
    the variant/evidence/manual_queue rows."""
    h_before = store.published_state_hash()

    run_id = "run-stage-kind-fails-mid-publish"
    prov = make_provenance(run_id=run_id)

    store.stage_evidence_kind(
        run_id, tier="tier1", criterion="PP4", direction="pathogenic",
        strength_vocab=["supporting"],
    )

    source_ref_id = store.stage_source_ref(
        run_id, source="ClinVar", accession="VCV2", snapshot_id="snap-1",
        snapshot_date="2026-01-01", source_file_checksum="chk", raw_value="raw", provenance=prov,
    )
    variant_id = "NC_000016.10:6400000:A:G"
    store.stage_variant(
        run_id, variant_id=variant_id, gene="TSC2", class_="missense", provenance=prov,
        source_ref_ids=source_ref_id,
    )
    store.stage_evidence_added(
        run_id, seq_in_run=1, variant_id=variant_id, tier="tier1", criterion="PP4",
        strength="supporting", direction="pathogenic", source_ref_id=source_ref_id,
        row_provenance=prov, event_provenance=prov, event_timestamp="2026-01-01T00:00:00Z",
    )
    # Force publish() to fail partway through, AFTER the evidence_kinds
    # drain would already have run inside the same transaction: an invalid
    # manual_queue row violates a CHECK constraint only visible at publish
    # time (staging has no such constraint of its own).
    store.stage_manual_queue(
        run_id,
        raw_input="bad-row",
        source_ref_id=source_ref_id,
        failure_stage="normalize",
        error_code="E998",
        reason="forced failure for staged-kind rollback test",
        config_pins={"pin": "v1"},
        provenance=prov,
        created_at="2026-01-01T00:00:00Z",
        excluded_from_scorer=0,  # violates CHECK(excluded_from_scorer = 1)
    )

    with pytest.raises(PublishError):
        store.publish(run_id)

    assert store.published_state_hash() == h_before
    row = store.conn.execute(
        "SELECT 1 FROM evidence_kinds WHERE tier = 'tier1' AND criterion = 'PP4'"
    ).fetchone()
    assert row is None
    (n,) = store.conn.execute(
        "SELECT COUNT(*) FROM temp.stg_evidence_kinds WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert n == 0
