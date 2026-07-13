#!/usr/bin/env python3
"""Sync RAPTOR's committed todo list with a local SQLite execution cache.

`docs/project/TODOS.yaml` is the durable, git-tracked source of truth: it
survives across sessions, machines, and Copilot CLI restarts. A session's
SQL `todos`/`todo_deps` tables (as used by the `sql` tool) are a disposable
per-session cache -- convenient for querying "what's ready to work on" during
a session, but never persisted anywhere durable on their own.

This script is the ONLY sanctioned bridge between the two:

    python scripts/sync_todos.py import [--db PATH]
        Load docs/project/TODOS.yaml into a local SQLite file (default
        .raptor/todos.sqlite, gitignored) with `todos`/`todo_deps` tables
        matching the session tool's schema. Safe to re-run: recreates the
        tables from the YAML every time (YAML always wins).

    python scripts/sync_todos.py export [--db PATH]
        Read the SQLite file's `todos`/`todo_deps` tables and OVERWRITE
        docs/project/TODOS.yaml with their current contents (e.g. after a
        session added/updated todos and you want to commit the result).
        Fails loudly if the SQLite file/tables don't exist -- never creates
        an empty commit-worthy file by accident.

    python scripts/sync_todos.py check [--db PATH]
        Non-mutating: diff YAML vs SQLite todos/status and report drift
        (exit 1 if any). Useful as a pre-commit/CI sanity check.

Never edit the SQLite cache and expect it to persist on its own -- always
follow with `export` and commit the resulting TODOS.yaml diff.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YAML = ROOT / "docs" / "project" / "TODOS.yaml"
DEFAULT_DB = ROOT / ".raptor" / "todos.sqlite"

_VALID_STATUSES = frozenset({"pending", "in_progress", "done", "blocked"})
_SCHEMA_ID = "raptor-todos-v1"


class TodoSyncError(ValueError):
    """Raised on a malformed TODOS.yaml or an unusable SQLite cache."""


def _load_yaml(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise TodoSyncError(f"todos file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != _SCHEMA_ID:
        raise TodoSyncError(
            f"{path} must be a mapping with schema: {_SCHEMA_ID!r} (got {raw!r})"
        )
    todos = raw.get("todos")
    if not isinstance(todos, list):
        raise TodoSyncError(f"{path}: `todos` must be a list")

    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in todos:
        if not isinstance(entry, dict):
            raise TodoSyncError(f"{path}: each todo entry must be a mapping, got {entry!r}")
        todo_id = entry.get("id")
        if not isinstance(todo_id, str) or not todo_id.strip():
            raise TodoSyncError(f"{path}: todo entry missing non-blank `id`: {entry!r}")
        if todo_id in seen_ids:
            raise TodoSyncError(f"{path}: duplicate todo id {todo_id!r}")
        seen_ids.add(todo_id)

        status = entry.get("status", "pending")
        if status not in _VALID_STATUSES:
            raise TodoSyncError(
                f"{path}: todo {todo_id!r} has invalid status {status!r} "
                f"(must be one of {sorted(_VALID_STATUSES)})"
            )
        depends_on = entry.get("depends_on") or []
        if not isinstance(depends_on, list) or not all(isinstance(d, str) for d in depends_on):
            raise TodoSyncError(f"{path}: todo {todo_id!r} `depends_on` must be a list of strings")

        normalized.append(
            {
                "id": todo_id,
                "title": str(entry.get("title", "")),
                "description": str(entry.get("description", "")).strip(),
                "status": status,
                "depends_on": list(depends_on),
                "created": str(entry.get("created", "")),
            }
        )

    all_ids = {t["id"] for t in normalized}
    for todo in normalized:
        unknown = [d for d in todo["depends_on"] if d not in all_ids]
        if unknown:
            raise TodoSyncError(
                f"{path}: todo {todo['id']!r} depends_on unknown id(s): {unknown!r}"
            )
    return normalized


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def _import(yaml_path: Path, db_path: Path) -> None:
    todos = _load_yaml(yaml_path)
    conn = _connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS todo_deps")
        conn.execute("DROP TABLE IF EXISTS todos")
        conn.execute(
            """
            CREATE TABLE todos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE todo_deps (
                todo_id TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                PRIMARY KEY (todo_id, depends_on)
            )
            """
        )
        for todo in todos:
            conn.execute(
                "INSERT INTO todos (id, title, description, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    todo["id"],
                    todo["title"],
                    todo["description"],
                    todo["status"],
                    todo["created"],
                    todo["created"],
                ),
            )
            for dep in todo["depends_on"]:
                conn.execute(
                    "INSERT INTO todo_deps (todo_id, depends_on) VALUES (?, ?)",
                    (todo["id"], dep),
                )
        conn.commit()
    finally:
        conn.close()
    print(f"imported {len(todos)} todo(s) from {yaml_path} into {db_path}")


def _export(yaml_path: Path, db_path: Path) -> None:
    if not db_path.is_file():
        raise TodoSyncError(f"SQLite cache not found: {db_path} (nothing to export)")
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('todos','todo_deps')"
        )
        tables = {row[0] for row in cur.fetchall()}
        if {"todos", "todo_deps"} - tables:
            raise TodoSyncError(f"{db_path} is missing todos/todo_deps tables")

        rows = conn.execute(
            "SELECT id, title, description, status, created_at FROM todos ORDER BY created_at, id"
        ).fetchall()
        deps_by_id: dict[str, list[str]] = {}
        for todo_id, depends_on in conn.execute(
            "SELECT todo_id, depends_on FROM todo_deps ORDER BY todo_id, depends_on"
        ):
            deps_by_id.setdefault(todo_id, []).append(depends_on)
    finally:
        conn.close()

    todos = []
    for todo_id, title, description, status, created_at in rows:
        created = (created_at or "")[:10] or ""
        todos.append(
            {
                "id": todo_id,
                "title": title,
                "description": description,
                "status": status,
                "depends_on": deps_by_id.get(todo_id, []),
                "created": created,
            }
        )

    payload = {"schema": _SCHEMA_ID, "todos": todos}
    header = (
        "# RAPTOR project todos — committed source of truth.\n"
        "#\n"
        "# Regenerated by `python scripts/sync_todos.py export`. Edit this file\n"
        "# directly, or re-run the export after updating the session SQL cache.\n"
        "#\n"
        "# Schema: schema/id/title/description/status/depends_on/created --\n"
        "# see scripts/sync_todos.py module docstring for the full contract.\n"
        "#\n"
    )
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=88)
    yaml_path.write_text(header + body, encoding="utf-8")
    print(f"exported {len(todos)} todo(s) from {db_path} to {yaml_path}")


def _check(yaml_path: Path, db_path: Path) -> int:
    yaml_todos = {t["id"]: t for t in _load_yaml(yaml_path)}
    if not db_path.is_file():
        print(f"no SQLite cache at {db_path} -- nothing to compare (this is not an error)")
        return 0
    conn = _connect(db_path)
    try:
        db_rows = conn.execute("SELECT id, status FROM todos").fetchall()
    finally:
        conn.close()
    db_status = {row[0]: row[1] for row in db_rows}

    drift = False
    only_in_yaml = sorted(set(yaml_todos) - set(db_status))
    only_in_db = sorted(set(db_status) - set(yaml_todos))
    if only_in_yaml:
        drift = True
        print(f"present only in YAML: {only_in_yaml}")
    if only_in_db:
        drift = True
        print(f"present only in SQLite cache (run export?): {only_in_db}")
    for todo_id in sorted(set(yaml_todos) & set(db_status)):
        if yaml_todos[todo_id]["status"] != db_status[todo_id]:
            drift = True
            print(
                f"status drift for {todo_id!r}: yaml={yaml_todos[todo_id]['status']!r} "
                f"sqlite={db_status[todo_id]!r}"
            )
    if not drift:
        print("no drift between TODOS.yaml and SQLite cache")
    return 1 if drift else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["import", "export", "check"])
    parser.add_argument("--yaml", type=Path, default=DEFAULT_YAML, help="Path to TODOS.yaml")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to the local SQLite cache")
    args = parser.parse_args(argv)

    try:
        if args.action == "import":
            _import(args.yaml, args.db)
            return 0
        if args.action == "export":
            _export(args.yaml, args.db)
            return 0
        return _check(args.yaml, args.db)
    except TodoSyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
