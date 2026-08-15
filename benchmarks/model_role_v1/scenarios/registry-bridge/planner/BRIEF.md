# Planner task: registry bridge

Design an implementation-ready contract for validating four already-parsed YAML
objects: a registration, candidate universe, identity-map lock and identity-map
manifest. Inspect the supplied artifacts carefully. The implementation must
fail closed on mismatched bindings and return a compact audit result on success.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Do not implement code
or tests. The plan must identify authoritative field locations, exact
comparands, acceptance criteria, negative tests, preservation rules and named
failure modes.
