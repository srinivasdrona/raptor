# Slot 3 — Anchor-regression preservation

## Frozen files

Do not modify:

- `tests/eval/test_live_eval_export.py`
  (`dc4437d91f9d3c98f6dbfaaceb5f7f55ecfd7e3d42468e14da7bac9c0e729585`)
- `tests/eval/test_kit_conformance_export.py`
  (`487c21a3b09e87535b785eaec49151f6a54408bf14a0516420e9c534efc854b1`)
- any production/config/script file.

## Three failure modes

1. **Vacuous green:** asserting only contig-start behavior misses the checker's short/malformed-anchor
   case. Exercise all four invalid anchor values for insertion and deletion.
2. **Broken deletion fixture:** if the fake reference also corrupts `fetch(1,2)`, the deletion test
   fails during deleted-sequence verification instead of testing the anchor. Return `"C"` there.
3. **Confirmation-biased test:** reading or matching the doer's private helper/message would encode
   the implementation rather than AC-A2. Test only public API + typed error.
