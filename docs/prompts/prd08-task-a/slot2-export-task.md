# Slot 2 — PRD-08 Task A: label-free held-out export

## Contract

- **Task:** `live-eval-holdout-export`
- **Goal:** implement the deterministic label-free GRCh38 SPDI-to-VCF exporter, bijective identity
  manifest, provenance sidecar, and CLI specified by PRD-08 Task A.
- **Motivating artifact:** `docs/prd/PRD-08-live-eval-evidence-adapter.md`
  (substantive Task-A contract frozen through commit `0ae9e9d`; read especially §§3.A, 5 Export(A),
  10.2, 10.3, 10.6, 11.1).
- **Pre-authored RED tests:** commit `1b1672e9a5a8a4b716da92eeaa2ab9bdb8aaf09e`.

## Context surface

Create:

- `src/raptor/eval/export.py`
- `scripts/export_holdout_vcf.py`
- `configs/eval/export.yaml`

Do not modify `run_eval`, benchmark construction, scorer code, the smoke exporter, or any existing
test. Do not implement Task C (ClinVar audit) or Task B (BIAS adapter).

## Reference files (four maximum)

1. `docs/prd/PRD-08-live-eval-evidence-adapter.md`
2. `tests/eval/test_live_eval_export.py`
3. `src/raptor/ingest/config.py`
4. `src/raptor/ingest/normalizer.py`

The conformance test is a frozen execution target; run it but do not alter it.

## Public behavior

Implement the exact PRD/test surface:

- `ExportConfig` and `load_export_config(path, ingest_config)`.
  - Preserve ordered `contigs` pins.
  - Validate assembly against `ingest_config.assembly`.
  - Derive expected genomic accessions from
    `ingest_config.gene_configs[*].genome_accession`.
  - Reject blank/duplicate accessions or VCF contigs and missing/extra accessions.
- `spdi_to_vcf(variant_id, reference)`.
  - Return `(accession, POS, REF, ALT)`.
  - Verify every non-empty deleted sequence against `reference.fetch`.
  - Convert SNV/MNV/delins with `POS=pos0+1`.
  - Left-anchor pure insertions/deletions with `POS=pos0`; fail at `pos0==0`.
- `export_holdout(variant_ids, reference, config, *, provenance=None)`.
  - Accept `Iterable[str]`, never label-bearing rows.
  - Map accession to configured VCF contig.
  - Emit VCF data rows with `INFO == "."`.
  - Emit manifest rows with exactly
    `{variant_id, vcf_key, accession, contig}`.
  - Enforce duplicate/collision failure, conservation, bijection, pinned total ordering, and
    permutation-independent bytes/hashes.
  - Copy the provenance mapping; never mutate caller input.
- `ExportResult.write(out_dir, prefix="holdout_input")`.
  - Emit exactly `{prefix}.vcf`, `{prefix}.manifest.jsonl`,
    `{prefix}.provenance.json`.
  - Sidecar includes conservation count, VCF/manifest hashes, and supplied file-level provenance.
- `scripts/export_holdout_vcf.py`.
  - Arguments are the PRD-pinned `--heldout`, `--out-dir`, `--prefix`,
    `--benchmark-snapshot`, `--export-config`, `--ingest-config`, `--reference-root`.
  - Read only `row["variant_id"]` from held-out JSONL.
  - Use the existing ingest config loader and checksum-verified
    `SeqRepoGenomicNormalizer` reference discipline (`{accession}.fasta`).
  - Print an unambiguous summary containing `conservation_count`, `vcf_hash`, and `manifest_hash`.

Use typed errors required by the tests (`ExportReferenceMismatchError`,
`ContigStartAnchorError`); other validation failures may be `ValueError`. Keep output UTF-8/LF and
JSON deterministic (`sort_keys` plus stable separators/order as appropriate). Do not add dependencies
or broad exception catches.

## Acceptance and verification

Run:

```powershell
$env:WSL_UTF8=1
wsl -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor && python -m pytest tests/eval/test_live_eval_export.py tests/eval/test_kit_conformance_export.py -q"
wsl -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor && python -m pytest -q"
```

The first command must pass every Task-A test; the second must preserve the existing suite. Also run
`git diff --check` and show that the frozen tests are byte-unchanged.

The real 2,577-row export is **not** part of this implementation task; it runs only after checker
sign-off.
