# Planner task: registry bridge

Design an implementation-ready contract for validating four already-parsed YAML
objects: a registration, candidate universe, identity-map lock and identity-map
manifest. Inspect the supplied artifacts carefully. The implementation must
fail closed on mismatched bindings and return a compact audit result on success.

The authoritative behavior is:

- compare `registration.schema` with the literal `release-registration-v2`;
- compare `universe.schema` with `registration.universe_schema`;
- compare `map_lock.schema` with `registration.map_lock_schema`;
- compare `map_manifest.schema` with `map_lock.manifest_schema`;
- compare the **top-level** universe transcript pin with the registration pin;
- compare the universe constraint-key set exactly with
  `registration.required_constraints`;
- return schema `validation-result-v1`, `record_count`, and exactly the six
  ordered checks corresponding to those validations.

The two `content_sha256` fields are self-digests of different artifacts and are
**not compared with each other**. `map_manifest.rows` is informational and is
**not a binding** in this task. Constraint values are not interpreted; only the
exact key set is validated. Record-level transcript pins are not required and
cannot substitute for the top-level pin.

Write only `PLAN.yaml`, conforming to `OUTPUT_SCHEMA.yaml`. Do not implement code
or tests. The plan must identify authoritative field locations, exact
comparands, acceptance criteria, negative tests, preservation rules and named
failure modes.
