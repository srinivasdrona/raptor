# Planner task: workspace boundary

Design an implementation-ready contract for resolving requested paths beneath a
workspace root and for auditing a batch of requests. The design must be safe on
Windows, including resolved targets that differ from lexical paths, and must
produce a disposition for every request.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Address input
validation, resolved-path containment, case normalization, resolver injection,
closed error codes, complete accounting, negative tests and preservation rules.
