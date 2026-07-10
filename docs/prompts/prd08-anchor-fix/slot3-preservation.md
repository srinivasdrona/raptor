# Slot 3 — Invalid-anchor fix preservation

## Frozen tests

- `tests/eval/test_live_eval_export.py`
  (`dc4437d91f9d3c98f6dbfaaceb5f7f55ecfd7e3d42468e14da7bac9c0e729585`)
- `tests/eval/test_kit_conformance_export.py`
  (`487c21a3b09e87535b785eaec49151f6a54408bf14a0516420e9c534efc854b1`)
- `tests/eval/test_live_eval_export_anchor_regression.py`
  (`76e6acc07019f33f20a7b4e0d73717a07082d58aaae4cf71d76ef81d94d2f0d2`)

Do not modify tests, CLI, config, docs, or unrelated files.

## Three failure modes

1. **Half-fix:** validating insertion anchors but leaving deletion anchors unchecked (or vice versa).
   Both paths must share the same validator.
2. **Silent coercion:** uppercasing `"a"` or accepting `"N"` converts an untrusted reference result
   into a plausible allele. Reject; never repair.
3. **Collateral rewrite:** changing conversion, ordering, manifest, or CLI behavior to address a
   one-helper defect risks the already-green Task-A contract. Keep the diff surgical.
