"""Regression tests for the two ranking-determinism bugs in
``published_state_hash()`` / ``build_evidence_snapshot()``.

Bug 1 (tie-breaking): ``_content_rank()`` ranked content-tied rows (rows
whose canonical content is identical apart from a meaningless surrogate id)
by SQLite fetch/insertion order rather than by canonical content alone. Two
DBs holding the exact same SET of such rows, inserted in opposite order,
therefore assigned OPPOSITE ranks to the tied pair -- and since a
content-rank is also used as a CROSS-reference key by another table's FK
(``evidence_snapshots.snapshot_id`` <- ``classification_versions
.evidence_snapshot_ref``; ``source_refs.source_ref_id`` <-
``manual_queue``/``knowledge_assertions.source_ref_id``), that referencing
row's canonicalized content differed between the two DBs even though both
were logically identical -- a false-negative (`hashes_equal` False for
logically-equal state).

Bug 2 (unscoped source_ref_rank): ``build_evidence_snapshot()`` canonicalized
``evidence.source_ref_id`` using a GLOBAL content-rank over ALL of
``source_refs``, so an unrelated ``source_refs`` row merely existing in the
DB at build time (for a different variant, or added/removed by an unrelated
run) shifted the rank of the snapshot's OWN referenced source_ref(s),
changing ``input_hash`` for an otherwise byte-identical snapshot -- another
false-negative.

Both fixes preserve ledger-order-sensitivity (`test_ledger_order_sensitive`
is untouched) and logical-difference-sensitivity (asserted again below).

Bug 3 (serialization coercion): ``_content_rank()``'s ``_cell()`` built each
non-overridden column's rank-key with plain ``str(value)``, which coerces
type-distinct raw values onto the SAME string -- SQL ``NULL`` (Python
``None``) and the TEXT literal ``"None"`` both stringify to ``"None"``; the
int ``1`` and the TEXT ``"1"`` both stringify to ``"1"``; etc. Two rows that
are NOT actually content-tied (they differ in TYPE, not just formatting)
therefore collapsed onto the same dense rank, and -- since that rank is also
used as a cross-reference key by another table's FK (e.g.
``evidence.source_ref_id`` -> ``source_refs`` rank) -- a row referencing one
vs. the other of the type-distinct pair canonicalized IDENTICALLY, a
false-equal. Fixed by serializing every cell with `canonical_json` (the same
JSON serialization already used for the override branch and the rest of the
canonicalization pipeline) instead of `str()`, so `json.dumps`'s native
per-type encoding (`null` vs `"None"` vs `1` vs `"1"` vs `1.0`) keeps every
type-distinct value a DISTINCT content key.
"""

from __future__ import annotations

from pathlib import Path

from raptor.kb.store import KBStore

VARIANT_ID = "VAR1"


def _prov(run_id: str, timestamp: str) -> str:
    return KBStore.build_provenance(
        tool_version="1.0",
        source="test",
        source_snapshot_version="1",
        env_versions={},
        originating_run=run_id,
        timestamp=timestamp,
    )


def _seed_base(store: KBStore, run_id: str) -> tuple[str, str, int]:
    """Stage+publish one grounded variant with a single evidence row.

    Returns ``(variant_id, source_ref_id, ledger_high_watermark)``. Uses
    fixed literal field values (not random/parametrized) so the exact same
    real, content-addressed ``source_ref_id`` is produced regardless of
    which store calls this helper.
    """
    prov = _prov(run_id, "2026-01-01T00:00:00Z")
    source_ref_id = store.stage_source_ref(
        run_id,
        source="ClinVar",
        accession="ACC1",
        snapshot_id="snap1",
        snapshot_date="2026-01-01",
        source_file_checksum="chk1",
        raw_value="raw1",
        provenance=prov,
    )
    store.stage_variant(
        run_id,
        variant_id=VARIANT_ID,
        gene="GENE1",
        class_="missense",
        provenance=prov,
        source_ref_ids=source_ref_id,
    )
    store.stage_evidence_added(
        run_id,
        seq_in_run=1,
        variant_id=VARIANT_ID,
        tier="tier1",
        criterion="PM2",
        strength="moderate",
        direction="pathogenic",
        source_ref_id=source_ref_id,
        row_provenance=prov,
        event_provenance=prov,
        event_timestamp="2026-01-01T00:00:00Z",
    )
    store.publish(run_id)
    (watermark,) = store.conn.execute("SELECT MAX(ledger_seq) FROM ledger").fetchone()
    return VARIANT_ID, source_ref_id, watermark


def test_content_rank_tie_is_insertion_order_invariant(tmp_path: Path) -> None:
    """Two DBs holding the identical SET of content-tied rows -- inserted in
    OPPOSITE order -- must hash equal, including through a cross-table FK
    that references one specific member of the tied pair.
    """
    db1_path = tmp_path / "db1.sqlite3"
    db2_path = tmp_path / "db2.sqlite3"

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        variant_id, source_ref_id, watermark = _seed_base(store1, "run1")
        variant_id2, source_ref_id2, watermark2 = _seed_base(store2, "run1")
        assert (variant_id, source_ref_id, watermark) == (variant_id2, source_ref_id2, watermark2)

        prov = _prov("run1", "2026-01-02T00:00:00Z")

        # Two evidence_snapshots rows tied in EVERY column but `snapshot_id`
        # (same variant/watermark/input_hash/combination_rule_ref/provenance)
        # -- a genuine content tie -- inserted in OPPOSITE order.
        snap_cols = (
            "(snapshot_id, variant_id, ledger_high_watermark, input_hash, "
            "combination_rule_ref, provenance)"
        )
        snap_common = (variant_id, watermark, "deadbeef" * 4, "rule1", prov)
        store1.conn.execute(
            f"INSERT INTO evidence_snapshots {snap_cols} VALUES (?,?,?,?,?,?)", ("SNAP_A", *snap_common)
        )
        store1.conn.execute(
            f"INSERT INTO evidence_snapshots {snap_cols} VALUES (?,?,?,?,?,?)", ("SNAP_B", *snap_common)
        )
        store2.conn.execute(
            f"INSERT INTO evidence_snapshots {snap_cols} VALUES (?,?,?,?,?,?)", ("SNAP_B", *snap_common)
        )
        store2.conn.execute(
            f"INSERT INTO evidence_snapshots {snap_cols} VALUES (?,?,?,?,?,?)", ("SNAP_A", *snap_common)
        )

        # classification_versions references SNAP_A SPECIFICALLY -- byte
        # identical in both DBs -- so only the A/B insertion order differs.
        cv_cols = (
            "(variant_id, version, evidence_snapshot_ref, status, approvals, timestamp, provenance)"
        )
        for store in (store1, store2):
            store.conn.execute(
                f"INSERT INTO classification_versions {cv_cols} VALUES (?,?,?,?,?,?,?)",
                (variant_id, "v1.0", "SNAP_A", "VUS", "[]", "2026-01-03T00:00:00Z", prov),
            )

        # manual_queue: two rows tied in every column but the AUTOINCREMENT
        # `mq_id`, inserted in opposite order -- exercises the SAME
        # `_content_rank` helper for a table with no downstream FK reference.
        mq_cols = (
            "(raw_input, source_ref_id, failure_stage, error_code, reason, "
            "config_pins, run_id, provenance, created_at)"
        )
        mq_vals = ("raw-x", source_ref_id, "parse", "E1", "reason1", "{}", "run1", prov, "2026-01-04T00:00:00Z")
        store1.conn.execute(f"INSERT INTO manual_queue {mq_cols} VALUES (?,?,?,?,?,?,?,?,?)", mq_vals)
        store1.conn.execute(f"INSERT INTO manual_queue {mq_cols} VALUES (?,?,?,?,?,?,?,?,?)", mq_vals)
        store2.conn.execute(f"INSERT INTO manual_queue {mq_cols} VALUES (?,?,?,?,?,?,?,?,?)", mq_vals)
        store2.conn.execute(f"INSERT INTO manual_queue {mq_cols} VALUES (?,?,?,?,?,?,?,?,?)", mq_vals)

        # knowledge_assertions: same idea.
        ka_cols = "(source_ref_id, assertion_type, subject, object, status, provenance)"
        ka_vals = (source_ref_id, "type1", "sub1", "obj1", "hypothesis", prov)
        store1.conn.execute(f"INSERT INTO knowledge_assertions {ka_cols} VALUES (?,?,?,?,?,?)", ka_vals)
        store1.conn.execute(f"INSERT INTO knowledge_assertions {ka_cols} VALUES (?,?,?,?,?,?)", ka_vals)
        store2.conn.execute(f"INSERT INTO knowledge_assertions {ka_cols} VALUES (?,?,?,?,?,?)", ka_vals)
        store2.conn.execute(f"INSERT INTO knowledge_assertions {ka_cols} VALUES (?,?,?,?,?,?)", ka_vals)

        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        assert hash1 == hash2, (
            "published_state_hash() must be invariant to the insertion/fetch order of "
            "content-tied rows (evidence_snapshots SNAP_A/SNAP_B), including through the "
            "classification_versions.evidence_snapshot_ref cross-reference"
        )

        # Negative control: a GENUINE difference must still hash different --
        # the tie fix must not create a false-equal (H1-adjacent safety net).
        store2.conn.execute(
            f"INSERT INTO knowledge_assertions {ka_cols} VALUES (?,?,?,?,?,?)",
            (source_ref_id, "type2", "sub2", "obj2", "hypothesis", prov),
        )
        hash2_after_extra_row = store2.published_state_hash()
        assert hash2_after_extra_row != hash2, (
            "a real extra row must still change published_state_hash() after the tie fix"
        )


def test_snapshot_input_hash_scoped_to_effective_evidence(tmp_path: Path) -> None:
    """``build_evidence_snapshot``'s ``input_hash`` must depend only on the
    snapshot's OWN effective-evidence inputs, never on an unrelated
    ``source_refs`` row that merely exists in the DB at build time.
    """
    db1_path = tmp_path / "db1.sqlite3"
    db2_path = tmp_path / "db2.sqlite3"

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        variant_id, source_ref_id, watermark = _seed_base(store1, "run1")
        variant_id2, source_ref_id2, watermark2 = _seed_base(store2, "run1")
        assert (variant_id, source_ref_id, watermark) == (variant_id2, source_ref_id2, watermark2)

        prov = _prov("run1", "2026-01-02T00:00:00Z")

        def _stage_unrelated_source_ref(store: KBStore) -> None:
            store.stage_source_ref(
                "run-unrelated",
                source="AAA_Unrelated",
                accession="ZZZ",
                snapshot_id="snap-u",
                snapshot_date="2026-01-01",
                source_file_checksum="chk-u",
                raw_value="raw-u",
                provenance=prov,
            )
            store.publish("run-unrelated")

        # store1: the unrelated source_ref is ALREADY present when the
        # snapshot is built.
        _stage_unrelated_source_ref(store1)
        derived1, input_hash1 = store1.build_evidence_snapshot(
            snapshot_id="SNAP1",
            variant_id=variant_id,
            ledger_high_watermark=watermark,
            combination_rule_ref="rule1",
            provenance=prov,
        )

        # store2: the (logically identical) snapshot is built FIRST, while
        # the unrelated source_ref does not exist yet -- added afterward.
        derived2, input_hash2 = store2.build_evidence_snapshot(
            snapshot_id="SNAP1",
            variant_id=variant_id,
            ledger_high_watermark=watermark,
            combination_rule_ref="rule1",
            provenance=prov,
        )
        _stage_unrelated_source_ref(store2)

        assert derived1 == derived2
        assert input_hash1 == input_hash2, (
            "input_hash must not depend on an unrelated source_ref's mere presence (or its "
            "build-time ordering) -- it must be scoped to this snapshot's own effective evidence"
        )

        # Both DBs now hold IDENTICAL logical content (same variant, same
        # single evidence row, same unrelated source_ref, same snapshot with
        # equal input_hash) -- only the ORDER in which the unrelated
        # source_ref was published differs. Record identical classification
        # versions and confirm the two DBs converge to the SAME published
        # state hash too.
        for store in (store1, store2):
            store.record_classification_version(
                variant_id=variant_id,
                version="v1.0",
                evidence_snapshot_ref="SNAP1",
                status="VUS",
                approvals=[],
                timestamp="2026-01-05T00:00:00Z",
                provenance=prov,
            )

        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        assert hash1 == hash2, (
            "two DBs that converge to the same logical published state (differing only in WHEN "
            "an unrelated source_ref was added) must hash equal"
        )

        # Negative control: a genuine difference must still hash different.
        store2.conn.execute(
            "INSERT INTO knowledge_assertions "
            "(source_ref_id, assertion_type, subject, object, status, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source_ref_id, "type-extra", "sub-extra", "obj-extra", "hypothesis", prov),
        )
        assert store2.published_state_hash() != hash2, (
            "a real extra row must still change published_state_hash() after the scoping fix"
        )


def test_content_rank_is_type_preserving(tmp_path: Path) -> None:
    """``_content_rank`` must never coerce type-distinct raw values (SQL
    ``NULL`` vs the TEXT literal ``"None"``) onto the same rank-key.

    Both DBs hold the exact same PAIR of ``source_refs`` rows -- one with
    ``accession IS NULL``, one with ``accession = "None"`` (TEXT) -- byte
    identical in every OTHER column. The only difference between the two
    DBs is WHICH of that pair the (otherwise identical) variant's sole
    evidence row references: DB1 references the ``NULL``-accession one,
    DB2 the ``"None"``-TEXT one.

    Pre-fix, ``_cell()`` stringified both accessions to the literal string
    ``"None"`` via ``str(value)``, so the two source_refs collapsed onto
    the SAME dense content-rank -- meaning ``evidence.source_ref_id``
    canonicalized IDENTICALLY in both DBs regardless of which row it
    actually referenced, and ``published_state_hash()`` came out EQUAL for
    two genuinely different logical states (a false-equal). Post-fix, the
    two source_refs must rank as two DISTINCT contents, so the two DBs'
    hashes must DIFFER.
    """
    db1_path = tmp_path / "db1.sqlite3"
    db2_path = tmp_path / "db2.sqlite3"

    def _seed(store: KBStore, *, referenced_accession: str | None) -> None:
        prov = _prov("run1", "2026-01-01T00:00:00Z")
        # Two source_refs, identical in EVERY column except `accession`:
        # SQL NULL vs. the TEXT literal "None".
        null_ref = store.stage_source_ref(
            "run1",
            source="ClinVar",
            accession=None,
            snapshot_id="snap1",
            snapshot_date="2026-01-01",
            source_file_checksum="chk1",
            raw_value="raw1",
            provenance=prov,
        )
        none_text_ref = store.stage_source_ref(
            "run1",
            source="ClinVar",
            accession="None",
            snapshot_id="snap1",
            snapshot_date="2026-01-01",
            source_file_checksum="chk1",
            raw_value="raw1",
            provenance=prov,
        )
        store.stage_variant(
            "run1",
            variant_id=VARIANT_ID,
            gene="GENE1",
            class_="missense",
            provenance=prov,
            source_ref_ids=[null_ref, none_text_ref],
        )
        referenced = null_ref if referenced_accession is None else none_text_ref
        store.stage_evidence_added(
            "run1",
            seq_in_run=1,
            variant_id=VARIANT_ID,
            tier="tier1",
            criterion="PM2",
            strength="moderate",
            direction="pathogenic",
            source_ref_id=referenced,
            row_provenance=prov,
            event_provenance=prov,
            event_timestamp="2026-01-01T00:00:00Z",
        )
        store.publish("run1")

    with KBStore(db1_path) as store1, KBStore(db2_path) as store2:
        _seed(store1, referenced_accession=None)
        _seed(store2, referenced_accession="None")

        hash1 = store1.published_state_hash()
        hash2 = store2.published_state_hash()
        assert hash1 != hash2, (
            "published_state_hash() must DIFFER when the sole evidence row references the "
            "NULL-accession source_ref (DB1) vs. the TEXT-\"None\"-accession source_ref (DB2) -- "
            "collapsing them onto the same rank via str()-coercion is a false-equal"
        )


def test_content_rank_type_preserving_coercion_pairs(tmp_path: Path) -> None:
    """Direct probe of ``_content_rank`` proving the fix closes the whole
    SERIALIZATION-COERCION class, not just the NULL-vs-``"None"`` instance.

    Every existing STRICT-table column ``_content_rank`` is ever called on
    (``source_refs``, ``manual_queue``, ``knowledge_assertions``,
    ``evidence_snapshots``) is declared TEXT/INTEGER, and SQLite's
    STRICT-table type coercion silently normalizes an inserted Python
    ``int``/``float`` to TEXT *before* ``_content_rank`` ever sees it --
    which would mask an int-vs-text (or float-vs-int) collision at the DB
    layer regardless of ``_content_rank``'s own behavior (verified: STRICT
    stores ``1`` bound to a TEXT column as the text ``"1"``). An ad hoc,
    non-STRICT scratch table (an undeclared column type, so SQLite's
    dynamic type affinity keeps whatever Python type was bound) preserves
    the raw type handed to sqlite3, exercising ``_content_rank``'s value
    serialization directly for pairs no STRICT column can ever reproduce.
    """
    with KBStore(tmp_path / "scratch.sqlite3") as store:
        store.conn.execute("CREATE TABLE _scratch_rank (id INTEGER PRIMARY KEY, val)")
        store.conn.execute("INSERT INTO _scratch_rank (id, val) VALUES (1, ?)", (1,))
        store.conn.execute("INSERT INTO _scratch_rank (id, val) VALUES (2, ?)", ("1",))
        store.conn.execute("INSERT INTO _scratch_rank (id, val) VALUES (3, ?)", (1.0,))
        # Sanity: the scratch table really did preserve the raw sqlite3 types.
        types = dict(store.conn.execute("SELECT id, typeof(val) FROM _scratch_rank").fetchall())
        assert types == {1: "integer", 2: "text", 3: "real"}

        rank = store._content_rank("_scratch_rank", "id")
        assert len({rank[1], rank[2], rank[3]}) == 3, (
            "int 1, text '1', and float 1.0 must rank as three DISTINCT contents -- "
            "str()-coercion collapsed all three onto the identical rank-key '1'"
        )
