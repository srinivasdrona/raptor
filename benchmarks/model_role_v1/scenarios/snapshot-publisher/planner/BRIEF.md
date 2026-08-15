# Planner task: verified snapshot publisher

Design an implementation-ready contract for a function that receives a JSON
source path, output path and expected SHA-256. It must verify the source and
publish a deterministic snapshot without allowing source drift between
verification and publication. An optional callback may run after initial
verification but before publication.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Cover the exact
read/verify/parse/reverify/write order, canonical serialization, atomic
publication, failure-state preservation, audit fields, tests and named failure
modes.
