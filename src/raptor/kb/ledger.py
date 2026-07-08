"""PRD-03 §4 FR1 — the append-only provenance ledger.

The ledger is the single source of truth (FR1): ``evidence``,
``classification_versions``, etc. are projections derived by *replaying*
ledger events. This module defines the event-type vocabulary and small,
low-level helpers to append an event row (used by ``KBStore`` inside its
staging/publish flow — never called directly against the published table
from application code, so every event goes through the same atomic-publish
path, FR4).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


class EventType:
    """Ledger event-type vocabulary (PRD-03 FR1)."""

    VARIANT_OBSERVED = "variant_observed"
    EVIDENCE_ADDED = "evidence_added"
    EVIDENCE_CORRECTED = "evidence_corrected"
    EVIDENCE_RETRACTED = "evidence_retracted"
    SOURCE_SUPERSEDED = "source_superseded"
    CLASSIFICATION_VERSIONED = "classification_versioned"

    ALL = frozenset(
        {
            VARIANT_OBSERVED,
            EVIDENCE_ADDED,
            EVIDENCE_CORRECTED,
            EVIDENCE_RETRACTED,
            SOURCE_SUPERSEDED,
            CLASSIFICATION_VERSIONED,
        }
    )


@dataclass(frozen=True)
class LedgerEvent:
    """A materialized ledger row (read back from the DB)."""

    ledger_seq: int
    event_type: str
    target_id: str
    run_id: str
    payload: str
    provenance: str
    timestamp: str


def append_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    target_id: str,
    run_id: str,
    payload_json: str,
    provenance_json: str,
    timestamp: str,
) -> int:
    """Insert one ledger event row and return its assigned ``ledger_seq``.

    Must be called within an already-open write transaction (``KBStore``
    publish loop owns the ``BEGIN IMMEDIATE``); this helper performs no
    transaction management of its own so multiple events can be appended
    atomically alongside their derived projection rows.
    """
    if event_type not in EventType.ALL:
        raise ValueError(f"unknown ledger event_type: {event_type!r}")

    cur = conn.execute(
        """
        INSERT INTO ledger (event_type, target_id, run_id, payload, provenance, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (event_type, str(target_id), run_id, payload_json, provenance_json, timestamp),
    )
    assert cur.lastrowid is not None
    return int(cur.lastrowid)


def events_up_to(conn: sqlite3.Connection, ledger_high_watermark: int) -> list[LedgerEvent]:
    """Read all ledger events with ``ledger_seq <= ledger_high_watermark``, in order."""
    rows: list[Any] = conn.execute(
        """
        SELECT ledger_seq, event_type, target_id, run_id, payload, provenance, timestamp
        FROM ledger
        WHERE ledger_seq <= ?
        ORDER BY ledger_seq ASC
        """,
        (ledger_high_watermark,),
    ).fetchall()
    return [LedgerEvent(*row) for row in rows]
