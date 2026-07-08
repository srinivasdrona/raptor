"""PRD-03: KB schema & provenance ledger.

This package implements the SQLite knowledge-base schema, migration runner,
append-only provenance ledger, and the ``KBStore`` run-scoped staging /
atomic-publish API described in
``docs/prd/PRD-03-kb-schema-provenance-ledger.md``.

Nothing in this package reads benchmark, label, or oracle data (GP-9/H1) —
it is a pure storage substrate consumed by PRD-01 (evidence writer) and
PRD-02 (variant/manual-queue writer).
"""

__all__: list[str] = []
