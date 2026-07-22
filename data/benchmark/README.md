# Frozen benchmark artifacts (Track A)

**Aggregate stats + provenance only.** The full frozen benchmark (`benchmark.jsonl` — the per-variant
truth set / answer key) is deliberately **NOT committed** here: it is regenerable deterministically
from the pinned ClinVar snapshot + `scripts/build_tsc_benchmark.py`, and keeping the labels out of the
repository preserves the trace-cribbing separation (H1 / R-A2) — a doer building the scorer must never
be able to read the held-out labels.

## Reproduce

```
python scripts/build_tsc_benchmark.py \
  --snapshot <path>/variant_summary.txt.gz \
  --out      <path>/benchmark
```

The script verifies the pinned snapshot sha256, filters to GRCh38 + TSC1/TSC2, runs the real
genomic-SPDI normalizer + PRD-07 loader, applies PRD-06 exclusions + label hierarchy, and emits the
frozen benchmark, the train/held-out split, and `benchmark_stats.json`.

## Pinned snapshot

| Pin | Value |
|---|---|
| Source | ClinVar `variant_summary.txt.gz` (NCBI FTP tab_delimited) |
| Date | 2026-07-07 |
| md5 (NCBI-published) | `bd3720834b62733a6a1c81d7e1eef941` |
| sha256 | `5fe4fe10783391d01dc414dc5583a3e63487b67f8cd3c8429d59227cd5f4f37f` |
| labels_snapshot id | `clinvar_2026-07-07` |

See [`docs/EVALUATION.md` Part II §3](../../docs/EVALUATION.md#evaluation-benchmark-composition) for the stratified counts and the power verdict.
