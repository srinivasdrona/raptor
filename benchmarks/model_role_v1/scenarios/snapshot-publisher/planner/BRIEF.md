# Planner task: verified snapshot publisher

Design an implementation-ready contract for a function that receives a JSON
source path, output path and expected SHA-256. It must verify the source and
publish a deterministic snapshot without allowing source drift between
verification and publication. An optional callback may run after initial
verification but before publication.

The authoritative contract is:

- read source bytes and require SHA-256 equality before parsing;
- parse JSON only after that initial hash check;
- snapshot content is `{"schema": "verified-snapshot-v1", "records": ...}`;
- normalize both path arguments to `pathlib.Path`;
- call `before_publish(source_path)` with that normalized `Path` after initial
  verification when provided;
- re-read the source after the callback and require the same SHA-256 before any
  destination write;
- canonical JSON uses `sort_keys=true`, `indent=2`, `ensure_ascii=false`,
  UTF-8, LF-only, and exactly one terminal LF;
- write a temporary sibling file and publish only with `os.replace`;
- require `output_path.parent` to exist as a directory; never create it;
- return exactly `schema`, `source_sha256`, `source_size`, `output_sha256`,
  `record_count`, and `checks`;
- audit schema is `snapshot-publish-audit-v1`;
- checks are exactly `[SOURCE_HASH, SOURCE_STABLE, CANONICAL_SNAPSHOT,
  ATOMIC_PUBLISH]`;
- typed errors are `SOURCE_HASH`, `SOURCE_JSON`, `SOURCE_DRIFT`, and
  `OUTPUT_PATH`;
- on failure, no new output may exist and any prior output remains
  byte-identical.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Cover the exact
read/verify/parse/reverify/write order, canonical serialization, atomic
publication, failure-state preservation, audit fields, tests and named failure
modes.
