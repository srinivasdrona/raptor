# Slot 2 — Fix invalid pure-indel anchors

- **Task:** `live-eval-export-invalid-anchor-fix`
- **Motivating artifacts:** PRD-08 AC-A2 at commit `52d09f9`; locked regression commit `3fcbb58`;
  GPT-5.5 `WITH-CHANGES` checker finding.
- **Goal:** make both pure-insertion and pure-deletion paths reject an anchor unless the reference
  returns exactly one uppercase A/C/G/T base.

Modify only:

- `src/raptor/eval/export.py`

Use one shared, self-explanatory anchor-validation path for insertion and deletion. The public error is
`ExportReferenceMismatchError`. Empty, multi-base, lowercase, or ambiguous anchors fail before REF/ALT
construction; valid uppercase A/C/G/T behavior stays unchanged. Do not normalize lowercase input, guess
another anchor, or alter deleted-sequence verification.

Run:

```powershell
$env:WSL_UTF8=1
wsl -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor && python -m pytest tests/eval/test_live_eval_export_anchor_regression.py tests/eval/test_live_eval_export.py tests/eval/test_kit_conformance_export.py -q"
wsl -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor && python -m pytest -q"
```

Also run `git diff --check` and prove all three frozen test hashes remain unchanged.
