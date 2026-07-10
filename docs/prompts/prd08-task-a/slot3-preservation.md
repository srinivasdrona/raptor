# Slot 3 — Task-A preservation and inversion

## Frozen assertions

Do not modify these pre-authored tests:

- `tests/eval/test_live_eval_export.py`
  - SHA-256 `dc4437d91f9d3c98f6dbfaaceb5f7f55ecfd7e3d42468e14da7bac9c0e729585`
- `tests/eval/test_kit_conformance_export.py`
  - SHA-256 `487c21a3b09e87535b785eaec49151f6a54408bf14a0516420e9c534efc854b1`

Also preserve `scripts/build_tsc_benchmark.py`, `scripts/devbox/make_sample_vcf.py`, and all PRD-01 /
PRD-06 tests. The checker compares hashes/diffs, not the doer's assurance.

## Three named failure modes

1. **Truth leak / hollow exam:** copying `label`, `source`, `review_status`, `variant_class`, or
   `CLASS=` into VCF/manifest/provenance lets answer-side data cross to the x64 scorer. Only
   `row["variant_id"]` may cross; every VCF data-row `INFO` is `.`.
2. **SNV-only or non-conserving export:** dropping MNV/delins/pure insertion/pure deletion, silently
   deduplicating, or allowing two canonical IDs to share one VCF key makes the held-out measurement
   partial. Every requested ID maps to exactly one VCF row and one manifest row or the run fails.
3. **Wrong-variant coordinates:** guessing a contig-start anchor, skipping deleted/reference
   verification, or mixing 0-based SPDI with 1-based VCF attaches evidence to the wrong variant.
   Reference mismatch and unanchorable indels fail loudly.

If any implementation shortcut weakens one of these assertions, stop rather than changing the test.
