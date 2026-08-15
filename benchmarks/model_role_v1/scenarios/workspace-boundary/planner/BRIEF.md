# Planner task: workspace boundary

Design an implementation-ready contract for resolving requested paths beneath a
workspace root and for auditing a batch of requests. The design must be safe on
Windows, including resolved targets that differ from lexical paths, and must
produce a disposition for every request.

The authoritative contract is:

- reject empty/dot-only, absolute, drive-qualified, UNC, and any path containing
  a `..` segment;
- use an injectable resolver, defaulting to `Path.resolve(strict=False)`, on
  both root and candidate;
- compare resolved paths using `os.path.normcase` and `os.path.commonpath`;
- lexical string-prefix checks are forbidden;
- a resolved candidate outside the resolved root fails `RESOLVED_ESCAPE`;
- closed error codes are `EMPTY_PATH`, `ABSOLUTE_PATH`, `PARENT_SEGMENT`, and
  `RESOLVED_ESCAPE`;
- preserve request order and emit exactly one disposition for every request;
- accepted dispositions contain `request`, `status=ACCEPT`, `resolved_path`;
- rejected dispositions contain `request`, `status=REJECT`, `code`;
- audit schema is `workspace-disposition-audit-v1` with `total`, `accepted`,
  `rejected`, and `dispositions`;
- `total == len(requests)` and `accepted + rejected == total`;
- filesystem access is limited to resolver calls.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Address input
validation, resolved-path containment, case normalization, resolver injection,
closed error codes, complete accounting, negative tests and preservation rules.
