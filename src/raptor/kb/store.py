"""PRD-03 §4 FR4/FR5 — ``KBStore``: run-scoped staging + atomic publish.

This is the single write/read surface PRD-01 and PRD-02 use to interact with
the KB. It never issues raw DDL from Python (schema lives in
``migrations/*.sql``; run-scoped staging-table DDL lives in ``sql/staging.sql``
— GP-6); it enforces the §5.1 runtime contract on every connection; it stages
candidate rows *outside* the published tables (SQLite ``TEMP`` tables — a
genuinely separate, connection-scoped database, not the main KB file) and
publishes them in a single ``BEGIN IMMEDIATE`` transaction (FR4/AC3); and it
can replay the ledger to reconstruct the effective evidence at any
``ledger_high_watermark`` (FR5/AC4).

Nothing here reads a benchmark/label/oracle file (GP-9/H1) — the only
"rule" this module knows about is ``fixture_combination_rule``, a tiny
local toy aggregation used solely to prove storage-determinism (AC5); the
*real* ACMG/Bayesian combination rule belongs to PRD-01.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from raptor.kb import ledger as ledger_mod
from raptor.kb.ledger import EventType
from raptor.kb.schema import migrate

# Run-scoped staging DDL (GP-6): loaded from a SQL resource file, never
# hardcoded as a Python string. Unlike `migrations/*.sql` (versioned,
# applied exactly once, tracked in `schema_migrations`), this file is
# re-executed on *every* new connection — SQLite TEMP tables are
# connection-scoped and do not persist across connections, so they must be
# (re)created each time, which is precisely why this DDL cannot live in the
# versioned-migration runner.
STAGING_SQL_PATH = Path(__file__).resolve().parent / "sql" / "staging.sql"

# Tables that make up the persisted (published) KB state, in a fixed order
# so published_state_hash() is deterministic regardless of insertion order.
# `schema_migrations` is runner bookkeeping, not KB content, and is excluded.
PUBLISHED_TABLES: tuple[str, ...] = (
    "evidence_kinds",
    "source_refs",
    "variants",
    "variant_source_refs",
    "ledger",
    "evidence",
    "evidence_snapshots",
    "classification_versions",
    "knowledge_assertions",
    "manual_queue",
)

REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "tool_version",
    "source",
    "source_snapshot_version",
    "env_versions",
    "originating_run",
    "timestamp",
)

_STRENGTH_WEIGHT: dict[str, int] = {
    "stand_alone": 8,
    "very_strong": 8,
    "strong": 4,
    "moderate": 2,
    "supporting": 1,
}

# ---------------------------------------------------------------------------
# Surrogate-id canonicalization registry (§5.1/AC3): a single, closed-form
# map of every place a raw surrogate id can appear in HASHED content — its
# own PK/FK column, a ledger `target_id`, or a JSON `payload` key — keyed
# to a "kind" naming WHICH rank map (the `rank_maps` dict built in
# `KBStore._canonicalize_for_hash` / `build_evidence_snapshot`)
# canonicalizes it. Adding a future surrogate is ONE entry in these
# registries, never a new `if` branch in `_canon`/`_remap_payload_json` —
# this is what keeps the whole leak CLASS closed instead of chasing
# individual instances.
#
# Two surrogate "families" exist, each ranked differently (see
# `_ledger_rank_map`/`_evidence_rank_map` vs. `KBStore._content_rank`):
#   * AUTOINCREMENT integers (`ledger_seq`, `evidence_id`, `mq_id`,
#     `assertion_id`) — `_INT_KEYED_KINDS` below.
#   * content-addressed TEXT ids (`source_ref_id`, `snapshot_id`) — ranked
#     by the content of their OWN table's row (they carry no ledger_seq /
#     creating-event link to piggyback on), keyed by the raw string value.
# `target_id`/JSON-payload values are always str/whatever json.loads
# produced even when the underlying surrogate is an int, so looking one up
# needs to know which family it belongs to — `_rank_lookup` below.
# ---------------------------------------------------------------------------
_INT_KEYED_KINDS: frozenset[str] = frozenset({"ledger", "evidence", "mq", "assertion"})

# `(table, column) -> kind`. Keyed by the PAIR, not the bare column name:
# some surrogate column *names* collide with an unrelated NATURAL column in
# a different table — e.g. `source_refs.snapshot_id` is a natural, external
# data-source snapshot version (one of the natural-key fields
# `compute_source_ref_id` hashes to derive `source_ref_id`) and must NEVER
# be remapped, even though `evidence_snapshots.snapshot_id` — a different
# table, same column name — IS the surrogate PK for evidence snapshots and
# MUST be. Table-scoping the registry is what keeps that distinction safe.
_SURROGATE_COLUMNS: dict[tuple[str, str], str] = {
    ("ledger", "ledger_seq"): "ledger",
    ("evidence", "ledger_seq"): "ledger",
    ("evidence_snapshots", "ledger_high_watermark"): "ledger",
    ("evidence", "evidence_id"): "evidence",
    ("evidence", "supersedes_evidence_id"): "evidence",
    ("manual_queue", "mq_id"): "mq",
    ("knowledge_assertions", "assertion_id"): "assertion",
    ("source_refs", "source_ref_id"): "source_ref",
    ("variant_source_refs", "source_ref_id"): "source_ref",
    ("evidence", "source_ref_id"): "source_ref",
    ("knowledge_assertions", "source_ref_id"): "source_ref",
    ("manual_queue", "source_ref_id"): "source_ref",
    ("evidence_snapshots", "snapshot_id"): "snapshot",
    ("classification_versions", "evidence_snapshot_ref"): "snapshot",
}

# `ledger.target_id` is TEXT and holds either a natural key (e.g.
# `variant_id` for `evidence_added`/`variant_observed`/
# `classification_versioned` — never a surrogate, needs no remap) or a raw
# surrogate id naming a PRIOR/existing row this event acts on:
# `evidence_corrected`/`evidence_retracted` target a prior `evidence_id`;
# `source_superseded` targets the superseded `source_ref_id`. Any
# event_type absent here is assumed to target a natural key and is left
# untouched.
_TARGET_ID_SURROGATE_KIND: dict[str, str] = {
    EventType.EVIDENCE_CORRECTED: "evidence",
    EventType.EVIDENCE_RETRACTED: "evidence",
    EventType.SOURCE_SUPERSEDED: "source_ref",
}

# JSON payload keys that embed a raw surrogate id, keyed to which rank map
# canonicalizes them. This is the ONE registry every id-bearing payload key
# is checked against — `evidence_corrected`'s `prior_evidence_id`,
# `evidence_retracted`'s `evidence_id`, `source_superseded`'s
# `superseded_by` (a `source_ref_id`), and `classification_versioned`'s
# `evidence_snapshot_ref` (a `snapshot_id`) all fall out of the same
# generic walk (see `_remap_payload_json`) rather than hand-written
# per-event fixes, so adding a future id-bearing key only means adding one
# entry here.
_PAYLOAD_SURROGATE_KEYS: dict[str, str] = {
    "evidence_id": "evidence",
    "prior_evidence_id": "evidence",
    "supersedes_evidence_id": "evidence",
    "superseded_by": "source_ref",
    "evidence_snapshot_ref": "snapshot",
}


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization: sorted keys, fixed separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _rank_lookup(kind: str, value: Any, rank_maps: Mapping[str, Mapping[Any, int]]) -> int:
    """Resolve a raw surrogate ``value`` to its canonical rank for ``kind``.

    ``target_id``/JSON-payload values always arrive as whatever type
    ``json.loads``/SQLite TEXT produced (e.g. the string ``"5"`` for an
    ``evidence_id`` target), even when the underlying rank map is keyed by
    the native int (AUTOINCREMENT kinds) — so those are cast back to int
    before lookup; content-addressed TEXT kinds (``source_ref``,
    ``snapshot``) are looked up by the raw string as-is.
    """
    rank_map = rank_maps[kind]
    return rank_map[int(value)] if kind in _INT_KEYED_KINDS else rank_map[value]


def _rank_has(kind: str, value: Any, rank_maps: Mapping[str, Mapping[Any, int]]) -> bool:
    """``True`` iff ``value`` is a resolvable surrogate for ``kind`` — guards
    `_rank_lookup` against JSON values that merely share a registered key
    name but aren't actually a member of that rank map (defensive; keeps
    `_remap_payload_json` from raising on unexpected payload shapes).
    """
    rank_map = rank_maps[kind]
    if kind in _INT_KEYED_KINDS:
        try:
            return int(value) in rank_map
        except (TypeError, ValueError):
            return False
    return value in rank_map


def _remap_payload_json(payload_json: str, rank_maps: Mapping[str, Mapping[Any, int]]) -> str:
    """Parse a ledger ``payload`` JSON blob, replace every surrogate id
    embedded under a key listed in ``_PAYLOAD_SURROGATE_KEYS`` with its
    canonical rank (from ``rank_maps``), and re-serialize canonically
    (sorted keys, via `canonical_json`).

    Applied unconditionally to EVERY ledger payload when hashing: event
    payloads that carry none of these keys (e.g. ``evidence_added``'s
    ``{variant_id, tier, criterion, ...}``) pass through unchanged, so one
    pass safely covers the whole leak class instead of special-casing
    individual event types. Recurses into nested dicts/lists so a
    surrogate id nested inside a future payload shape is still caught.
    Surrogate values may be int (AUTOINCREMENT kinds) OR str
    (content-addressed `source_ref_id`/`snapshot_id` kinds).
    """
    obj = json.loads(payload_json)

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            remapped: dict[str, Any] = {}
            for key, value in node.items():
                kind = _PAYLOAD_SURROGATE_KEYS.get(key)
                if kind is not None and isinstance(value, (int, str)) and _rank_has(kind, value, rank_maps):
                    remapped[key] = _rank_lookup(kind, value, rank_maps)
                else:
                    remapped[key] = _walk(value)
            return remapped
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    return canonical_json(_walk(obj))


def fixture_combination_rule(effective_evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A tiny LOCAL fixture combination rule — for AC5 storage-determinism only.

    This is **not** the real ACMG/Bayesian combination rule (that is PRD-01's
    responsibility, validated on its own accuracy ceiling). It exists solely
    so PRD-03 can demonstrate that a fixed snapshot + a pinned
    ``combination_rule_ref`` + canonically-serialized inputs recompute to an
    identical stored derived output.
    """
    rows = sorted(effective_evidence, key=lambda r: (str(r["criterion"]), int(r["evidence_id"])))
    pathogenic_weight = sum(_STRENGTH_WEIGHT[r["strength"]] for r in rows if r["direction"] == "pathogenic")
    benign_weight = sum(_STRENGTH_WEIGHT[r["strength"]] for r in rows if r["direction"] == "benign")
    net = pathogenic_weight - benign_weight
    if net >= 8:
        label = "P"
    elif net >= 4:
        label = "LP"
    elif net <= -8:
        label = "B"
    elif net <= -4:
        label = "LB"
    else:
        label = "VUS"
    return {
        "label": label,
        "pathogenic_weight": pathogenic_weight,
        "benign_weight": benign_weight,
        "net": net,
    }


class PublishError(RuntimeError):
    """Raised when a publish() run fails; staging for that run is discarded."""


class KBStore:
    """Open connection + staging/publish/replay API over the PRD-03 KB schema."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        # isolation_level=None (autocommit) so this class has full manual
        # control over BEGIN IMMEDIATE / COMMIT / ROLLBACK for publish() —
        # otherwise sqlite3's implicit-transaction behavior would already
        # have an open transaction by the time publish() tries to start one.
        self.conn = sqlite3.connect(str(self.db_path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        migrate(self.conn)  # applies migrations (idempotent) + verifies runtime contract
        self._ensure_staging_tables()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KBStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Grounding / provenance helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_source_ref_id(
        source: str, accession: str | None, snapshot_id: str, row_locator: str | None
    ) -> str:
        """Deterministic, content-addressed source_ref_id.

        Computed from the natural key so staged rows can reference a
        source_ref before it is published in the same run, with no
        post-publish id-rewrite step.
        """
        key = "|".join("" if v is None else str(v) for v in (source, accession, snapshot_id, row_locator))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def build_provenance(
        *,
        tool_version: str,
        source: str,
        source_snapshot_version: str,
        env_versions: Mapping[str, str],
        originating_run: str,
        timestamp: str,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> str:
        """Build a complete provenance JSON blob (ARCHITECTURE §8 / PRD-03 FR7)."""
        prov: dict[str, Any] = {
            "tool_version": tool_version,
            "source": source,
            "source_snapshot_version": source_snapshot_version,
            "env_versions": dict(env_versions),
            "originating_run": originating_run,
            "timestamp": timestamp,
        }
        if model is not None:
            prov["model"] = model
        if prompt_version is not None:
            prov["prompt_version"] = prompt_version
        return canonical_json(prov)

    # ------------------------------------------------------------------
    # Run-scoped staging (FR4) — TEMP tables: connection-scoped, never part
    # of the published/main-file schema, automatically gone if the
    # connection is dropped without publishing.
    # ------------------------------------------------------------------

    def _ensure_staging_tables(self) -> None:
        """Create this connection's TEMP staging tables from ``sql/staging.sql``.

        GP-6: no DDL string lives in this module — the schema is read from
        a ``.sql`` resource file. Re-run (harmlessly, ``IF NOT EXISTS``) on
        every connection open, since TEMP tables never survive a
        reconnect.
        """
        self.conn.executescript(STAGING_SQL_PATH.read_text(encoding="utf-8"))

    def stage_variant(
        self,
        run_id: str,
        *,
        variant_id: str,
        gene: str,
        class_: str,
        provenance: str,
        source_ref_ids: str | Sequence[str],
        hgvs_g: str | None = None,
        hgvs_c: str | None = None,
        hgvs_p: str | None = None,
        hgvs_c_null_reason: str | None = None,
        hgvs_p_null_reason: str | None = None,
    ) -> None:
        """Stage a variants row AND its grounding link(s) (AC1/FR2).

        ``source_ref_ids`` is required, not optional: PRD-02 §2.1 models a
        variant as grounded through >=1 rows in the ``variant_source_refs``
        link table (never a single FK column on ``variants``), so this is
        the one sanctioned staging entry point for a variant — passing no
        source_ref_id is a construction error, not a valid "ungrounded"
        variant. Accepts one id (``str``) or several (for a variant backed
        by multiple source rows); each is staged as its own
        ``variant_source_refs`` link via ``stage_variant_source_ref``,
        using the same ``provenance`` as the variant row itself.

        publish() additionally re-verifies this invariant against the
        *published* ``variant_source_refs`` table before committing (belt
        and suspenders: the check here guards the sanctioned API, the
        check in publish() guards the ledger/published state itself, since
        staging tables have no FK enforcement of their own).
        """
        ids = [source_ref_ids] if isinstance(source_ref_ids, str) else list(source_ref_ids)
        if not ids:
            raise ValueError(
                f"stage_variant({variant_id!r}): source_ref_ids must be non-empty — "
                "a variant cannot be staged without >=1 grounding source_ref (AC1)"
            )
        self.conn.execute(
            """
            INSERT INTO temp.stg_variants
                (run_id, variant_id, gene, class, hgvs_g, hgvs_c, hgvs_p,
                 hgvs_c_null_reason, hgvs_p_null_reason, provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, variant_id, gene, class_, hgvs_g, hgvs_c, hgvs_p,
             hgvs_c_null_reason, hgvs_p_null_reason, provenance),
        )
        for source_ref_id in ids:
            self.stage_variant_source_ref(
                run_id, variant_id=variant_id, source_ref_id=source_ref_id, provenance=provenance
            )

    def stage_source_ref(
        self,
        run_id: str,
        *,
        source: str,
        snapshot_id: str,
        snapshot_date: str,
        source_file_checksum: str,
        raw_value: str,
        provenance: str,
        accession: str | None = None,
        row_locator: str | None = None,
        resolver_status: str = "unresolved",
    ) -> str:
        """Stage a source_refs row; returns its (deterministic) source_ref_id."""
        source_ref_id = self.compute_source_ref_id(source, accession, snapshot_id, row_locator)
        self.conn.execute(
            """
            INSERT INTO temp.stg_source_refs
                (run_id, source_ref_id, source, accession, snapshot_id, snapshot_date,
                 source_file_checksum, row_locator, raw_value, resolver_status, provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, source_ref_id, source, accession, snapshot_id, snapshot_date,
             source_file_checksum, row_locator, raw_value, resolver_status, provenance),
        )
        return source_ref_id

    def stage_variant_source_ref(
        self, run_id: str, *, variant_id: str, source_ref_id: str, provenance: str
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO temp.stg_variant_source_refs (run_id, variant_id, source_ref_id, provenance)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, variant_id, source_ref_id, provenance),
        )

    def stage_evidence_added(
        self,
        run_id: str,
        *,
        seq_in_run: int,
        variant_id: str,
        tier: str,
        criterion: str,
        strength: str,
        direction: str,
        source_ref_id: str,
        row_provenance: str,
        event_provenance: str,
        event_timestamp: str,
        supporting_record: str | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(event_payload or {})
        payload.setdefault("variant_id", variant_id)
        payload.setdefault("tier", tier)
        payload.setdefault("criterion", criterion)
        payload.setdefault("strength", strength)
        payload.setdefault("direction", direction)
        self.conn.execute(
            """
            INSERT INTO temp.stg_evidence_rows
                (run_id, seq_in_run, event_type, target_id, event_payload, event_provenance,
                 event_timestamp, variant_id, tier, criterion, strength, direction,
                 supporting_record, source_ref_id, supersedes_evidence_id, row_provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, seq_in_run, EventType.EVIDENCE_ADDED, variant_id,
                canonical_json(payload), event_provenance, event_timestamp,
                variant_id, tier, criterion, strength, direction,
                supporting_record, source_ref_id, None, row_provenance,
            ),
        )

    def stage_evidence_correction(
        self,
        run_id: str,
        *,
        seq_in_run: int,
        prior_evidence_id: int,
        variant_id: str,
        tier: str,
        criterion: str,
        strength: str,
        direction: str,
        source_ref_id: str,
        row_provenance: str,
        event_provenance: str,
        event_timestamp: str,
        supporting_record: str | None = None,
        event_payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Stage a correction: a NEW evidence row that supersedes `prior_evidence_id`.

        `prior_evidence_id` must already be published (from an earlier
        `publish()` call) — corrections within the same not-yet-published
        batch are not supported (see module docstring design notes).
        """
        payload = dict(event_payload or {})
        payload.setdefault("prior_evidence_id", prior_evidence_id)
        payload.setdefault("variant_id", variant_id)
        payload.setdefault("tier", tier)
        payload.setdefault("criterion", criterion)
        payload.setdefault("strength", strength)
        payload.setdefault("direction", direction)
        self.conn.execute(
            """
            INSERT INTO temp.stg_evidence_rows
                (run_id, seq_in_run, event_type, target_id, event_payload, event_provenance,
                 event_timestamp, variant_id, tier, criterion, strength, direction,
                 supporting_record, source_ref_id, supersedes_evidence_id, row_provenance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, seq_in_run, EventType.EVIDENCE_CORRECTED, str(prior_evidence_id),
                canonical_json(payload), event_provenance, event_timestamp,
                variant_id, tier, criterion, strength, direction,
                supporting_record, source_ref_id, prior_evidence_id, row_provenance,
            ),
        )

    def stage_evidence_retraction(
        self,
        run_id: str,
        *,
        seq_in_run: int,
        evidence_id: int,
        provenance: str,
        timestamp: str,
        reason: str | None = None,
    ) -> None:
        payload = {"evidence_id": evidence_id, "reason": reason}
        self.conn.execute(
            """
            INSERT INTO temp.stg_ledger_events
                (run_id, seq_in_run, event_type, target_id, payload, provenance, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, seq_in_run, EventType.EVIDENCE_RETRACTED, str(evidence_id),
             canonical_json(payload), provenance, timestamp),
        )

    def stage_manual_queue(
        self,
        run_id: str,
        *,
        raw_input: str,
        source_ref_id: str,
        failure_stage: str,
        error_code: str,
        reason: str,
        config_pins: Mapping[str, Any],
        provenance: str,
        created_at: str,
        attempted_coords: str | None = None,
        tool_error: str | None = None,
        excluded_from_scorer: int = 1,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO temp.stg_manual_queue
                (run_id, raw_input, source_ref_id, failure_stage, error_code, reason,
                 attempted_coords, tool_error, config_pins, excluded_from_scorer,
                 provenance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, raw_input, source_ref_id, failure_stage, error_code, reason,
             attempted_coords, tool_error, canonical_json(dict(config_pins)),
             excluded_from_scorer, provenance, created_at),
        )

    def discard_staging(self, run_id: str) -> None:
        """Drop all staged (not-yet-published) rows for a run (FR4: failed run discards staging)."""
        for table in (
            "stg_variants", "stg_source_refs", "stg_variant_source_refs",
            "stg_evidence_rows", "stg_ledger_events", "stg_manual_queue",
        ):
            self.conn.execute(f"DELETE FROM temp.{table} WHERE run_id = ?", (run_id,))
        self.conn.commit()

    def staged_counts(self, run_id: str) -> dict[str, int]:
        counts = {}
        for table in (
            "stg_variants", "stg_source_refs", "stg_variant_source_refs",
            "stg_evidence_rows", "stg_ledger_events", "stg_manual_queue",
        ):
            (n,) = self.conn.execute(
                f"SELECT COUNT(*) FROM temp.{table} WHERE run_id = ?", (run_id,)
            ).fetchone()
            counts[table] = n
        return counts

    # ------------------------------------------------------------------
    # Atomic publish (FR4/AC3)
    # ------------------------------------------------------------------

    def publish(self, run_id: str) -> None:
        """Publish everything staged for `run_id` in one BEGIN IMMEDIATE transaction.

        On any failure, the transaction is rolled back (the published state
        is left exactly as it was) and the run's staging is discarded
        (FR4: "a failed run discards staging").
        """
        try:
            self.conn.execute("BEGIN IMMEDIATE")

            self.conn.execute(
                """
                INSERT INTO variants
                    (variant_id, gene, class, hgvs_g, hgvs_c, hgvs_p,
                     hgvs_c_null_reason, hgvs_p_null_reason, provenance)
                SELECT variant_id, gene, class, hgvs_g, hgvs_c, hgvs_p,
                       hgvs_c_null_reason, hgvs_p_null_reason, provenance
                FROM temp.stg_variants WHERE run_id = ?
                """,
                (run_id,),
            )

            for row in self.conn.execute(
                "SELECT variant_id, gene, class, provenance FROM temp.stg_variants WHERE run_id = ?",
                (run_id,),
            ).fetchall():
                ledger_mod.append_event(
                    self.conn,
                    event_type=EventType.VARIANT_OBSERVED,
                    target_id=row["variant_id"],
                    run_id=run_id,
                    payload_json=canonical_json(
                        {"variant_id": row["variant_id"], "gene": row["gene"], "class": row["class"]}
                    ),
                    provenance_json=row["provenance"],
                    timestamp=json.loads(row["provenance"]).get("timestamp", ""),
                )

            self.conn.execute(
                """
                INSERT INTO source_refs
                    (source_ref_id, source, accession, snapshot_id, snapshot_date,
                     source_file_checksum, row_locator, raw_value, resolver_status, provenance)
                SELECT source_ref_id, source, accession, snapshot_id, snapshot_date,
                       source_file_checksum, row_locator, raw_value, resolver_status, provenance
                FROM temp.stg_source_refs WHERE run_id = ?
                """,
                (run_id,),
            )

            self.conn.execute(
                """
                INSERT INTO variant_source_refs (variant_id, source_ref_id, provenance)
                SELECT variant_id, source_ref_id, provenance
                FROM temp.stg_variant_source_refs WHERE run_id = ?
                """,
                (run_id,),
            )

            # AC1/FR2 grounding invariant, re-verified at publish time (not
            # merely trusted from the staging API): every variant this run
            # is about to publish must have >=1 linked, complete
            # `source_refs` row via `variant_source_refs`. Staging tables
            # carry no FK enforcement of their own, so this is where an
            # ungrounded variant is actually caught before it becomes part
            # of the published/ledger state.
            ungrounded = self.conn.execute(
                """
                SELECT v.variant_id
                FROM temp.stg_variants v
                WHERE v.run_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM variant_source_refs vsr WHERE vsr.variant_id = v.variant_id
                  )
                """,
                (run_id,),
            ).fetchall()
            if ungrounded:
                ids = ", ".join(repr(row["variant_id"]) for row in ungrounded)
                raise ValueError(
                    f"AC1 grounding violation: run {run_id!r} would publish variant(s) "
                    f"{ids} with zero linked source_refs rows (variant_source_refs)"
                )

            for row in self.conn.execute(
                """
                SELECT * FROM temp.stg_evidence_rows WHERE run_id = ? ORDER BY seq_in_run ASC
                """,
                (run_id,),
            ).fetchall():
                seq = ledger_mod.append_event(
                    self.conn,
                    event_type=row["event_type"],
                    target_id=row["target_id"],
                    run_id=run_id,
                    payload_json=row["event_payload"],
                    provenance_json=row["event_provenance"],
                    timestamp=row["event_timestamp"],
                )
                self.conn.execute(
                    """
                    INSERT INTO evidence
                        (ledger_seq, variant_id, tier, criterion, strength, direction,
                         supporting_record, source_ref_id, run_id, supersedes_evidence_id, provenance)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seq, row["variant_id"], row["tier"], row["criterion"], row["strength"],
                        row["direction"], row["supporting_record"], row["source_ref_id"], run_id,
                        row["supersedes_evidence_id"], row["row_provenance"],
                    ),
                )

            for row in self.conn.execute(
                "SELECT * FROM temp.stg_ledger_events WHERE run_id = ? ORDER BY seq_in_run ASC",
                (run_id,),
            ).fetchall():
                ledger_mod.append_event(
                    self.conn,
                    event_type=row["event_type"],
                    target_id=row["target_id"],
                    run_id=run_id,
                    payload_json=row["payload"],
                    provenance_json=row["provenance"],
                    timestamp=row["timestamp"],
                )

            self.conn.execute(
                """
                INSERT INTO manual_queue
                    (raw_input, source_ref_id, failure_stage, error_code, reason,
                     attempted_coords, tool_error, config_pins, run_id, excluded_from_scorer,
                     provenance, created_at)
                SELECT raw_input, source_ref_id, failure_stage, error_code, reason,
                       attempted_coords, tool_error, config_pins, run_id, excluded_from_scorer,
                       provenance, created_at
                FROM temp.stg_manual_queue WHERE run_id = ?
                """,
                (run_id,),
            )

            for table in (
                "stg_variants", "stg_source_refs", "stg_variant_source_refs",
                "stg_evidence_rows", "stg_ledger_events", "stg_manual_queue",
            ):
                self.conn.execute(f"DELETE FROM temp.{table} WHERE run_id = ?", (run_id,))

            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            self.discard_staging(run_id)
            raise PublishError(f"publish failed for run {run_id!r}: {exc}") from exc

    # ------------------------------------------------------------------
    # Published-state hash (§5.1 / AC3): checkpoint WAL, then hash content.
    # ------------------------------------------------------------------

    def published_state_hash(self) -> str:
        """SHA-256 over the full published state — canonical / content-
        addressed w.r.t. non-semantic surrogate ids, but SEQUENCE-sensitive
        for the ledger (AC3).

        Two databases holding the exact same *logical* rows hash
        identically even if those rows were published in a different order
        and therefore received different surrogate id *values* — both the
        SQLite ``AUTOINCREMENT`` family (``ledger.ledger_seq``,
        ``evidence.evidence_id``, ``manual_queue.mq_id``,
        ``knowledge_assertions.assertion_id``) AND the content-addressed
        TEXT family (``source_refs.source_ref_id``,
        ``evidence_snapshots.snapshot_id``): every such surrogate id is
        replaced by a rank/position before rows are hashed, never by its
        raw value (an insertion-order or hashing-implementation artifact,
        not part of the KB's logical content) — and this normalization is
        applied to EVERY place a surrogate value can appear, not just its
        own PK/FK column: a ledger `target_id` that names a surrogate
        (`evidence_corrected`/`evidence_retracted` target a prior
        `evidence_id`; `source_superseded` targets a superseded
        `source_ref_id`), and any JSON `payload` key that embeds one (e.g.
        `prior_evidence_id`, `superseded_by`, `evidence_snapshot_ref`), are
        canonicalized the same way, driven by the `_SURROGATE_COLUMNS` /
        `_TARGET_ID_SURROGATE_KIND` / `_PAYLOAD_SURROGATE_KEYS` registries
        (see `_canonicalize_for_hash`). Natural keys (`variant_id`,
        `(tier, criterion)`, `source_refs.snapshot_id` — the external
        data-source's OWN snapshot version, unrelated to
        `evidence_snapshots.snapshot_id`) are never remapped.

        BUT the ledger's *event sequence* is itself semantic (FR1/FR5):
        replay (``ledger.events_up_to`` / ``effective_evidence_at`` /
        ``classification_versions_at``) reads events ``ORDER BY ledger_seq
        ASC``, so two DBs holding the same SET of ledger events in a
        DIFFERENT relative order can replay to different results and MUST
        NOT hash equal. `ledger_seq` is therefore canonicalized to its
        0-based POSITION when rows are read in that same ``ledger_seq ASC``
        order (neutralizing only the raw integer *value*, e.g. a different
        starting offset) — never to a rank computed by sorting on row
        *content*, which would silently discard the sequence and collapse
        differently-ordered ledgers to the same hash. The ledger table's
        rows are folded into the hash in that same positional order rather
        than being content-sorted like every other published table.

        SCOPE (descoped 2026-07-08, ADR-0006): the *binding* contract is
        **AC3 — same-DB atomic-publish detection**: hash the published
        state before a run and after a failed/partial publish; equal ⇒ no
        partial state leaked. AC3 is fully satisfied and is unaffected by
        every limitation below (within one DB, across a failed publish,
        the rows/values do not change).

        The cross-DB *canonical logical fingerprint* (two DIFFERENT DBs with
        the same logical content hash equal) is a BEST-EFFORT bonus with a
        KNOWN LIMITATION: JSON TEXT columns other than `ledger.payload`
        (`evidence.provenance`, `classification_versions.approvals`,
        `manual_queue.config_pins`, `evidence_kinds.strength_vocab`) are
        hashed as raw strings, so two different DBs whose JSON differs only
        by key order can hash differently (a cross-DB false-negative). This
        does NOT affect AC3. Full cross-DB canonicalization (a `_JSON_COLUMNS`
        registry parsing + re-serializing every JSON TEXT column) is
        DEFERRED to the reproducibility work (R-A11); see PRD-03 §9.
        """
        self.conn.execute("PRAGMA wal_checkpoint(FULL)")
        return self._canonicalize_for_hash()

    def _ledger_rank_map(self, *, high_watermark: int | None = None) -> dict[int, int]:
        """``ledger_seq -> 0-based position`` in ``ORDER BY ledger_seq ASC``
        — the exact order ledger replay (`ledger.events_up_to`) uses.
        Canonicalizes away the raw AUTOINCREMENT *value* while preserving
        the SEMANTIC event sequence. Optionally scoped to
        ``ledger_seq <= high_watermark`` so a snapshot's canonical inputs
        never depend on ledger events that happen after it.
        """
        if high_watermark is None:
            rows = self.conn.execute("SELECT ledger_seq FROM ledger ORDER BY ledger_seq ASC").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT ledger_seq FROM ledger WHERE ledger_seq <= ? ORDER BY ledger_seq ASC",
                (high_watermark,),
            ).fetchall()
        return {row["ledger_seq"]: pos for pos, row in enumerate(rows)}

    def _evidence_rank_map(
        self, ledger_rank: Mapping[int, int], *, high_watermark: int | None = None
    ) -> dict[int, int]:
        """``evidence_id -> position of its own creating ledger event``.

        Each evidence row is created by exactly one ledger event (1:1 via
        ``evidence.ledger_seq``) in the SAME publish-time loop that appends
        that event, so the event's ledger position is already a canonical,
        order-preserving, surrogate-free stand-in for ``evidence_id`` —
        used both to hash the `evidence` table itself AND to canonicalize
        every OTHER place `evidence_id` leaks (ledger `target_id`, JSON
        payload keys, `evidence_snapshots.input_hash` inputs).
        """
        if high_watermark is None:
            rows = self.conn.execute("SELECT evidence_id, ledger_seq FROM evidence").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT evidence_id, ledger_seq FROM evidence WHERE ledger_seq <= ?", (high_watermark,)
            ).fetchall()
        return {row["evidence_id"]: ledger_rank[row["ledger_seq"]] for row in rows}

    def _content_rank(
        self,
        table: str,
        id_col: str,
        *,
        canon_overrides: Mapping[str, Mapping[Any, int]] | None = None,
        restrict_ids: Iterable[Any] | None = None,
    ) -> dict[Any, int]:
        """Content-derived ``surrogate_value -> rank`` for a table with NO
        ledger relationship (`manual_queue`, `knowledge_assertions`,
        `source_refs`, `evidence_snapshots`): none of these rows are ever
        replayed from the ledger, so their relative insertion order is
        genuinely non-semantic, and ranking by the content of every OTHER
        column is safe/correct — unlike `ledger`/`evidence`, which MUST use
        `_ledger_rank_map`/`_evidence_rank_map` to preserve the semantic
        event sequence.

        Works for both AUTOINCREMENT-int PKs (`mq_id`, `assertion_id`) and
        content-addressed TEXT PKs (`source_ref_id`, `snapshot_id`) — the
        id's own type is irrelevant, only the OTHER columns are sorted on.

        The rank is the row's 0-based position in the SORTED SEQUENCE OF
        DISTINCT canonical content keys (every column but ``id_col``,
        serialized via `canonical_json`) — a *dense* rank, NOT a bare
        `enumerate` of the fetched rows. Two (or more) rows that are
        genuinely tied — identical canonical content, differing only in
        their meaningless surrogate id — therefore collapse onto the SAME
        rank, rather than being split into adjacent ranks whose relative
        order (which tied row gets the lower number) would otherwise be
        decided by SQLite's row-fetch/insertion order — a non-semantic
        artifact. This keeps the whole mapping a pure function of the
        table's CONTENT (invariant to insertion/fetch order) even for
        content-ranks used as a CROSS-reference key by another table's FK
        (e.g. `evidence_snapshots.snapshot_id` <- referenced by
        `classification_versions.evidence_snapshot_ref`): a reference to
        either member of a tied pair now resolves to the identical rank in
        both DBs, regardless of which physical row happened to be inserted
        first, instead of leaking the insertion order through the FK.

        ``canon_overrides`` lets a caller substitute an already-canonical
        rank for a column that is itself a surrogate FK (e.g.
        `evidence_snapshots.ledger_high_watermark` -> ledger rank,
        `manual_queue`/`knowledge_assertions.source_ref_id` -> source_ref
        rank) instead of that column's raw value, so two DBs whose ONLY
        difference is a surrogate's raw representation still content-rank
        identically.

        ``restrict_ids``, when given, scopes both the row SET being ranked
        AND the ranks it produces to just those ids — used by
        `build_evidence_snapshot` so a snapshot's `source_ref_rank` depends
        only on the source_refs actually referenced by ITS effective
        evidence, never on unrelated `source_refs` rows that merely happen
        to exist in the DB at build time (those would otherwise shift every
        rank via the GLOBAL content-sort, changing `input_hash` for a
        snapshot that is otherwise byte-identical).
        """
        overrides = canon_overrides or {}
        if restrict_ids is not None:
            ids = list(restrict_ids)
            if not ids:
                return {}
            placeholders = ",".join("?" for _ in ids)
            rows = self.conn.execute(
                f'SELECT * FROM "{table}" WHERE "{id_col}" IN ({placeholders})', ids
            ).fetchall()
        else:
            rows = self.conn.execute(f'SELECT * FROM "{table}"').fetchall()

        def _cell(col: str, value: Any) -> str:
            # Type-preserving: `canonical_json` (json.dumps) distinguishes
            # every raw SQLite value by its OWN type -- SQL NULL (`None`)
            # serializes to `"null"`, the TEXT literal `"None"` to
            # `"\"None\""`, the int `1` to `"1"`, the TEXT `"1"` to
            # `"\"1\""`, the float `1.0` to `"1.0"` -- so no two
            # type-distinct raw values can ever coerce onto the same
            # content key. `str(value)` (the prior implementation) instead
            # collapsed all of those onto the identical string `"None"` /
            # `"1"`, producing a false content-tie between rows that only
            # LOOK equal after stringification.
            if col in overrides and value is not None:
                return canonical_json(overrides[col][value])
            return canonical_json(value)

        keyed = [
            (row[id_col], canonical_json(tuple(_cell(col, row[col]) for col in row.keys() if col != id_col)))
            for row in rows
        ]
        distinct_content = {content_key: rank for rank, content_key in enumerate(sorted({ck for _rid, ck in keyed}))}
        return {rid: distinct_content[content_key] for rid, content_key in keyed}

    def _canonicalize_for_hash(self) -> str:
        """Build ONE fully surrogate-free logical representation of the
        full published state, then fold it into a SHA-256 — a single
        canonicalization pass rather than a scattered set of per-field
        patches, so it closes the whole surrogate-id leak CLASS at once.

        Three properties held simultaneously:

        * **surrogate-remap-invariant** — every raw surrogate id (both
          AUTOINCREMENT ints: `ledger_seq`, `evidence_id`, `mq_id`,
          `assertion_id`; and content-addressed TEXT ids: `source_ref_id`,
          `snapshot_id`), and every place that raw value appears (its own
          PK/FK column — see `_SURROGATE_COLUMNS` — a ledger `target_id` —
          see `_TARGET_ID_SURROGATE_KIND` — or a JSON `payload` key — see
          `_PAYLOAD_SURROGATE_KEYS`), is replaced by a content-derived rank
          before hashing, so two DBs with identical logical state but
          different surrogate VALUES hash equal.
        * **ledger-order-sensitive** — `ledger_seq`'s rank is its POSITION
          in `ORDER BY ledger_seq ASC` (the replay order), never a
          content-sort rank, and ledger rows are folded in that same
          positional order — so re-ordering ledger events changes the hash.
        * **logical-difference-sensitive** — nothing outside the
          surrogate-id columns/keys enumerated in the registries above is
          touched (natural keys — `variant_id`, `(tier, criterion)`, and
          `source_refs.snapshot_id`, the natural external-snapshot field —
          are never remapped), so any real content difference (an extra
          row, a changed field) still changes the hash.
        """
        ledger_rows = self.conn.execute(
            "SELECT ledger_seq, event_type, target_id, run_id, payload, provenance, timestamp "
            "FROM ledger ORDER BY ledger_seq ASC"
        ).fetchall()
        ledger_rank = self._ledger_rank_map()
        evidence_rank = self._evidence_rank_map(ledger_rank)
        # source_ref_rank has no dependency on any other rank map (every
        # OTHER `source_refs` column is natural); mq_rank/ka_rank in turn
        # depend on it (both reference `source_ref_id`); snapshot_rank
        # depends only on ledger_rank (`ledger_high_watermark`) — computed
        # in that dependency order.
        source_ref_rank = self._content_rank("source_refs", "source_ref_id")
        mq_rank = self._content_rank(
            "manual_queue", "mq_id", canon_overrides={"source_ref_id": source_ref_rank}
        )
        ka_rank = self._content_rank(
            "knowledge_assertions", "assertion_id", canon_overrides={"source_ref_id": source_ref_rank}
        )
        snapshot_rank = self._content_rank(
            "evidence_snapshots", "snapshot_id", canon_overrides={"ledger_high_watermark": ledger_rank}
        )
        rank_maps: dict[str, Mapping[Any, int]] = {
            "ledger": ledger_rank,
            "evidence": evidence_rank,
            "source_ref": source_ref_rank,
            "mq": mq_rank,
            "assertion": ka_rank,
            "snapshot": snapshot_rank,
        }

        def _canon(table: str, col: str, row: sqlite3.Row) -> Any:
            value = row[col]
            if value is None:
                return None
            if table == "ledger" and col == "target_id":
                # target_id is TEXT: a natural key (e.g. variant_id) for
                # most event types, or a raw surrogate id naming a prior
                # row for correction/retraction/supersession events (see
                # _TARGET_ID_SURROGATE_KIND) — remap only the latter.
                kind = _TARGET_ID_SURROGATE_KIND.get(row["event_type"])
                return _rank_lookup(kind, value, rank_maps) if kind is not None else value
            if table == "ledger" and col == "payload":
                # Every id-bearing JSON key (prior_evidence_id, evidence_id,
                # superseded_by, evidence_snapshot_ref, ...) remapped in one
                # generic pass — see _PAYLOAD_SURROGATE_KEYS / _remap_payload_json.
                return _remap_payload_json(value, rank_maps)
            # Every other surrogate PK/FK column falls out of the ONE
            # (table, column) -> kind registry — no per-table branches.
            kind = _SURROGATE_COLUMNS.get((table, col))
            if kind is not None:
                return _rank_lookup(kind, value, rank_maps)
            return value

        h = hashlib.sha256()
        for table in PUBLISHED_TABLES:
            cols = [r[1] for r in self.conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if table == "ledger":
                # Fold ledger rows in ORDER BY ledger_seq ASC — the
                # SEMANTIC replay order — never re-sorted by content.
                canonical_rows = [[_canon(table, col, row) for col in cols] for row in ledger_rows]
            else:
                rows = self.conn.execute(f'SELECT * FROM "{table}"').fetchall()
                canonical_rows = [[_canon(table, col, row) for col in cols] for row in rows]
                canonical_rows.sort(key=canonical_json)

            h.update(table.encode("utf-8"))
            h.update(b"\x00")
            for row in canonical_rows:
                h.update(canonical_json(row).encode("utf-8"))
                h.update(b"\x1e")
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Ledger replay (FR1/FR5/AC4)
    # ------------------------------------------------------------------

    def effective_evidence_at(
        self, ledger_high_watermark: int, variant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Reconstruct the effective evidence set as of a ledger position.

        Replays `evidence_added` / `evidence_corrected` / `evidence_retracted`
        events up to (and including) `ledger_high_watermark`: the latest
        added/corrected evidence row per (variant_id, criterion) wins, unless
        it was subsequently retracted at or before the watermark.
        """
        events = ledger_mod.events_up_to(self.conn, ledger_high_watermark)
        evidence_rows: dict[int, dict[str, Any]] = {
            row["evidence_id"]: dict(row)
            for row in self.conn.execute(
                "SELECT * FROM evidence WHERE ledger_seq <= ?", (ledger_high_watermark,)
            ).fetchall()
        }
        by_ledger_seq: dict[int, dict[str, Any]] = {r["ledger_seq"]: r for r in evidence_rows.values()}

        effective_by_key: dict[tuple[str, str], int] = {}
        retracted: set[int] = set()

        for ev in events:
            if ev.event_type in (EventType.EVIDENCE_ADDED, EventType.EVIDENCE_CORRECTED):
                erow = by_ledger_seq.get(ev.ledger_seq)
                if erow is None:
                    continue
                key = (erow["variant_id"], erow["criterion"])
                effective_by_key[key] = erow["evidence_id"]
            elif ev.event_type == EventType.EVIDENCE_RETRACTED:
                retracted.add(int(ev.target_id))

        result: list[dict[str, Any]] = []
        for (v_id, _criterion), eid in effective_by_key.items():
            if eid in retracted:
                continue
            if variant_id is not None and v_id != variant_id:
                continue
            result.append(evidence_rows[eid])

        result.sort(key=lambda r: (r["variant_id"], r["criterion"]))
        return result

    # ------------------------------------------------------------------
    # Evidence snapshots + classification versions (FR5/AC4/AC5)
    # ------------------------------------------------------------------

    def build_evidence_snapshot(
        self,
        *,
        snapshot_id: str,
        variant_id: str,
        ledger_high_watermark: int,
        combination_rule_ref: str,
        provenance: str,
    ) -> tuple[dict[str, Any], str]:
        """Compute + publish an evidence_snapshots row. Returns (derived_output, input_hash).

        `derived_output` comes from `fixture_combination_rule` — a local toy
        rule for AC5 storage-determinism, not the real ACMG rule (PRD-01's).

        `input_hash` uses `evidence_rank` (position of each row's creating
        ledger event, scoped to `ledger_high_watermark`) in place of the raw
        `evidence.evidence_id` surrogate, AND `source_ref_rank` (content
        rank over `source_refs`, since source_refs carry no ledger_seq /
        creating-event link to piggyback on) in place of the raw
        `evidence.source_ref_id` surrogate — the same canonicalization
        `published_state_hash()` applies — so two DBs holding the exact same
        logical evidence set, reached via different surrogate id values
        (AUTOINCREMENT OR content-addressed-string), recompute the
        identical `input_hash` (closing the same surrogate-id leak class
        for this stored hash, not just the ledger).

        `source_ref_rank` is scoped to `restrict_ids` = the distinct
        `source_ref_id`s actually referenced by THIS snapshot's own
        `effective` evidence, NOT the global `source_refs` table: an
        unrelated `source_ref` row that merely exists in the DB at build
        time (e.g. for a different variant, or added/removed by a run this
        snapshot never observes) must not shift the content-sort of the
        ones this snapshot's evidence actually points at — otherwise
        `input_hash` would depend on data outside this snapshot's own
        logical inputs.
        """
        effective = self.effective_evidence_at(ledger_high_watermark, variant_id=variant_id)
        ledger_rank = self._ledger_rank_map(high_watermark=ledger_high_watermark)
        evidence_rank = self._evidence_rank_map(ledger_rank, high_watermark=ledger_high_watermark)
        referenced_source_ref_ids = sorted({r["source_ref_id"] for r in effective})
        source_ref_rank = self._content_rank(
            "source_refs", "source_ref_id", restrict_ids=referenced_source_ref_ids
        )
        canonical_inputs = canonical_json(
            [
                {
                    "evidence_rank": evidence_rank[r["evidence_id"]],
                    "variant_id": r["variant_id"],
                    "tier": r["tier"],
                    "criterion": r["criterion"],
                    "strength": r["strength"],
                    "direction": r["direction"],
                    "source_ref_rank": source_ref_rank[r["source_ref_id"]],
                }
                for r in sorted(effective, key=lambda r: (r["variant_id"], r["criterion"]))
            ]
        )
        input_hash = hashlib.sha256(canonical_inputs.encode("utf-8")).hexdigest()
        derived = fixture_combination_rule(effective)

        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                """
                INSERT INTO evidence_snapshots
                    (snapshot_id, variant_id, ledger_high_watermark, input_hash,
                     combination_rule_ref, provenance)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, variant_id, ledger_high_watermark, input_hash, combination_rule_ref, provenance),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        return derived, input_hash

    def record_classification_version(
        self,
        *,
        variant_id: str,
        version: str,
        evidence_snapshot_ref: str,
        status: str,
        approvals: Sequence[Mapping[str, Any]],
        timestamp: str,
        provenance: str,
    ) -> None:
        """Record a classification version — FR1: the ledger is the single
        source of truth, so this appends a ``classification_versioned``
        ledger event in the *same* transaction as the
        ``classification_versions`` projection row, rather than writing
        only the projection. ``classification_versions_at()`` reconstructs
        this projection purely by replaying those events (AC4).
        """
        approvals_list = list(approvals)
        run_id = json.loads(provenance)["originating_run"]
        event_payload = canonical_json(
            {
                "variant_id": variant_id,
                "version": version,
                "evidence_snapshot_ref": evidence_snapshot_ref,
                "status": status,
                "approvals": approvals_list,
            }
        )
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            ledger_mod.append_event(
                self.conn,
                event_type=EventType.CLASSIFICATION_VERSIONED,
                target_id=variant_id,
                run_id=run_id,
                payload_json=event_payload,
                provenance_json=provenance,
                timestamp=timestamp,
            )
            self.conn.execute(
                """
                INSERT INTO classification_versions
                    (variant_id, version, evidence_snapshot_ref, status, approvals, timestamp, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (variant_id, version, evidence_snapshot_ref, status, canonical_json(approvals_list),
                 timestamp, provenance),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def classification_versions_at(
        self, ledger_high_watermark: int, variant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Reconstruct classification versions by replaying
        ``classification_versioned`` ledger events up to
        ``ledger_high_watermark`` (FR1/AC4) — the source of truth is the
        ledger, not a direct read of ``classification_versions``.

        Returns dicts (one per event, in ledger order) with keys
        ``variant_id``, ``version``, ``evidence_snapshot_ref``, ``status``,
        ``approvals``, ``timestamp``, ``ledger_seq``.
        """
        events = ledger_mod.events_up_to(self.conn, ledger_high_watermark)
        result: list[dict[str, Any]] = []
        for ev in events:
            if ev.event_type != EventType.CLASSIFICATION_VERSIONED:
                continue
            payload = json.loads(ev.payload)
            if variant_id is not None and payload.get("variant_id") != variant_id:
                continue
            result.append(
                {
                    "variant_id": payload["variant_id"],
                    "version": payload["version"],
                    "evidence_snapshot_ref": payload["evidence_snapshot_ref"],
                    "status": payload["status"],
                    "approvals": payload["approvals"],
                    "timestamp": ev.timestamp,
                    "ledger_seq": ev.ledger_seq,
                }
            )
        result.sort(key=lambda r: r["ledger_seq"])
        return result
