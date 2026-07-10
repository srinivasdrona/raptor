# Slot 2 — Invalid-anchor checker regression

- **Task:** `live-eval-export-invalid-anchor-regression`
- **Motivating artifacts:**
  - PRD-08 AC-A2 / §10.6 at commit `52d09f9`
  - GPT-5.5 checker verdict: `WITH-CHANGES`, finding at
    `src/raptor/eval/export.py` anchor construction.
- **Goal:** add one independent RED regression module proving a pure-indel export cannot construct
  VCF alleles from an empty, multi-base, lowercase, or ambiguous reference anchor.

Create only:

- `tests/eval/test_live_eval_export_anchor_regression.py`

The test imports `spdi_to_vcf` and `ExportReferenceMismatchError` from `raptor.eval.export`.
Use a tiny injected reference double that:

- returns the parameterized invalid anchor for `fetch("NC_1", 0, 1)`;
- returns `"C"` for the pure-deletion deleted-sequence verification at
  `fetch("NC_1", 1, 2)`;
- fails the test on any unexpected fetch.

For each invalid anchor `["", "AC", "N", "a"]`, assert both:

- `spdi_to_vcf("NC_1:1::A", reference)` raises `ExportReferenceMismatchError`;
- `spdi_to_vcf("NC_1:1:C:", reference)` raises `ExportReferenceMismatchError`.

Assertions must verify failure occurs before any REF/ALT result is returned. Do not assert on a
private helper or implementation-specific message. This is one bug-class; do not add unrelated
export tests.

Verify:

```powershell
python -m py_compile tests/eval/test_live_eval_export_anchor_regression.py
$env:WSL_UTF8=1
wsl -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor && python -m pytest tests/eval/test_live_eval_export_anchor_regression.py -q"
```

Expected pre-fix state: 8 assertion cases fail because the current implementation returns invalid
VCF alleles instead of raising.
