"""PRD-03 §4 FR8 / §5.1 — versioned migration runner + runtime-contract check.

A tiny runner that applies versioned ``.sql`` migration files (in filename
order) exactly once each, recording applied versions in
``schema_migrations``, and verifies the SQLite runtime contract mandated by
§5.1: ``foreign_keys=ON``, ``journal_mode=WAL``, ``synchronous=FULL``. It is
idempotent — running it again on an already-migrated database is a no-op.

No DDL is ever issued from Python code outside this module's bookkeeping
table and the ``.sql`` migration files themselves (GP-6: schema lives in
SQL/config, not hardcoded in Python).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class RuntimeContractError(RuntimeError):
    """Raised when the SQLite connection does not satisfy §5.1's contract."""


def _migration_files() -> list[Path]:
    """Return migration ``.sql`` files sorted by their numeric version prefix."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def _is_memory_database(conn: sqlite3.Connection) -> bool:
    """True for `:memory:` (or other in-process-only) SQLite connections.

    ``PRAGMA database_list`` reports an empty ``file`` for the ``main``
    database when it lives only in memory (no backing file) — this covers
    the KB's connection is *not* on disk, so WAL (which requires a
    filesystem-backed database) is structurally unavailable regardless of
    what pragma we ask for.
    """
    row = conn.execute("PRAGMA database_list").fetchone()
    return row is not None and not row[2]


def configure_connection(conn: sqlite3.Connection) -> None:
    """Apply the §5.1 runtime contract pragmas to a connection.

    ``foreign_keys`` and ``journal_mode`` are connection/database level and
    must be (re)applied every time a connection is opened — SQLite does not
    persist ``foreign_keys=ON`` across connections.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")


def verify_runtime_contract(conn: sqlite3.Connection) -> None:
    """Verify the §5.1 SQLite runtime contract; raise RuntimeContractError if violated.

    Checked: ``foreign_keys=ON``, ``journal_mode=WAL``, ``synchronous=FULL``
    (§5.1: "journal_mode=WAL, synchronous=FULL for the publish transaction,
    foreign_keys=ON per connection"). ``synchronous`` is a per-connection
    setting like ``foreign_keys`` — it does not persist across reconnects
    either — so it is verified here on the same connection ``KBStore`` uses
    for ``publish()``, immediately after ``configure_connection`` applies it.

    Exception: an in-memory (``:memory:``) database can never report
    ``journal_mode=wal`` — SQLite does not support WAL without a backing
    file, so it silently stays on ``memory`` regardless of the pragma
    request. WAL exists for crash-durability across process restarts, which
    is moot for a connection with no persistent file to recover from, so
    ``journal_mode=memory`` is accepted there instead (used by fast,
    isolated test-only `KBStore(":memory:")` instances).
    """
    (fk,) = conn.execute("PRAGMA foreign_keys").fetchone()
    if not fk:
        raise RuntimeContractError("runtime contract violated: PRAGMA foreign_keys is OFF")

    (journal_mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    journal_mode = str(journal_mode).lower()
    if journal_mode != "wal" and not (journal_mode == "memory" and _is_memory_database(conn)):
        raise RuntimeContractError(
            f"runtime contract violated: journal_mode={journal_mode!r}, expected 'wal'"
        )

    # SQLite reports `synchronous` as an integer: 0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA.
    (synchronous,) = conn.execute("PRAGMA synchronous").fetchone()
    if int(synchronous) != 2:
        raise RuntimeContractError(
            f"runtime contract violated: synchronous={synchronous!r}, expected FULL (2)"
        )


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    if cur.fetchone() is None:
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply all not-yet-applied migrations in filename order. Idempotent.

    Returns the list of migration versions applied by *this* call (empty if
    the database was already up to date).
    """
    configure_connection(conn)

    directory = migrations_dir or MIGRATIONS_DIR
    files = sorted(directory.glob("*.sql"), key=lambda p: p.name) if migrations_dir else _migration_files()

    already = applied_versions(conn)
    newly_applied: list[str] = []

    for path in files:
        version = path.stem
        if version in already:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
            (version,),
        )
        conn.commit()
        newly_applied.append(version)

    verify_runtime_contract(conn)
    return newly_applied
