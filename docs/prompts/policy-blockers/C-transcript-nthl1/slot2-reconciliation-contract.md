# Slot 2 — Transcript/NTHL1 reconciliation contract: probes, public API, config, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the source
> surfaces in slot 1 only**, before the doer. The doer implements to pass (may add, not weaken). Facts are
> derived from the census, the ingest/scorer configs, and the pinned normalizer; each claim cites its
> source. **No clinical classification; no benchmark labels; reuse the existing SPDI algebra.**

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 The census arithmetic (cite `bias_gene_transcript` + `corpus`)
```
TSC1|NM_000368.4 = 2249   (== TSC1 corpus 2249)
TSC2|NM_000548.4 = 4339
NTHL1|NM_002528.6 =  30
                    -----
TSC2 corpus       = 4369   (== 4339 + 30)   ← the 30 NTHL1 are TSC2-region overflow
```
Production pins (`configs/ingest/tsc.yaml`): `TSC1 → NM_000368.5`, `TSC2 → NM_000548.5` (MANE Select,
`mane_release: "1.4"`, `assembly: GRCh38`). So **every** TSC1/TSC2 BIAS record carries `.4`; production
pins `.5`. `known_policy_gaps` records both the `.4/.5` delta and the 30-NTHL1 gap.

### 0.2 The two existing scope predicates (cite `scorer/policy.py`) — the defect is **active in committed config**
- `check_edge_cases` → `non_mane_transcript` (L67–76): compares `record.transcript` to
  `config.genes[gene]` by **exact string**. This predicate is **already enabled** in committed config
  (`configs/acmg/tsc.yaml` `edge_cases.non_mane_transcript: true`, L95), so today, on real `.4` BIAS rows,
  a `.4≠.5` version bump routes the whole TSC2 corpus to `EDGE_CASE_ROUTED` manual review — an **active
  committed defect, not a hypothetical**. This is the predicate to **refine** with SPDI reconciliation.
- `check_out_of_scope_gene` (L103–116): **always-on**; `record.gene_name ∉ config.genes` ⇒ manual review.
  The committed scorer `config.genes` (`configs/acmg/tsc.yaml`) is **TSC2-only**, so **both** NTHL1 **and
  every TSC1 record** currently route here as `OUT_OF_SCOPE_GENE`: the 30 NTHL1 rows *must* stay here
  (fail-loud, correct), while the TSC1 full-corpus misroute is part of the same committed defect the
  regression must demonstrate. NTHL1 routing stays fail-loud and unchanged in intent.

### 0.3 The canonical SPDI is the version-agnostic key (cite `ingest/normalizer.py`)
`SeqRepoGenomicNormalizer.normalize` emits `variant_id = f"{chrom}:{norm_start}:{norm_ref}:{norm_alt}"` —
a fully-justified GRCh38 **genomic** SPDI computed via `bioutils.normalize(EXPAND)`, independent of the
annotation transcript's version. `.4` and `.5` of the same base accession therefore share one genomic SPDI.
The normalizer already fails loud on `REF_MISMATCH`/`REFERENCE_UNAVAILABLE`/checksum mismatch and routes
imprecise/symbolic/out-of-scope rows to `ManualQueueItem(excluded_from_scorer=True)`. **Reuse this; do not
re-roll SPDI algebra.**

---

## 1. Empirical probes (run BEFORE the reconciliation policy)

### 1.1 Probe 1 — census-arithmetic + version-delta check
`scripts/probe_transcript_reconciliation.py <census_or_output> --output <report.json>` (or a test-owned
analyzer): assert `4339 + 30 == 4369` and `2249 == 2249`; confirm every TSC1/TSC2 record's transcript is
`.4` and every pinned accession is `.5`; emit `{gene, emitted_transcript, pinned_transcript, count}`.

### 1.2 Probe 2 — NTHL1 locus characterization
For the 30 `NTHL1|NM_002528.6` records, extract chr16 genomic coordinates and confirm they lie in/adjacent
to the TSC2 chr16p13.3 locus (TSC2 = `NC_000016.10`) — establishing "TSC2-region input mis-annotated to
NTHL1", not a genuine NTHL1-disease call. **Locus characterization only; no reclassification.** Each of the
30 must route to `out_of_scope_gene` manual queue.

### 1.3 Probe 3 — SPDI version-invariance proof
For a sample of TSC1/TSC2 variants, show the normalizer's genomic `variant_id` is **identical** under a
`.4` vs `.5` annotation (the version does not enter the genomic SPDI), and that an NTHL1 record gets a valid
SPDI but no in-scope MANE transcript ⇒ fail-loud. This proves SPDI is the correct reconciliation key.

### 1.4 Probe 4 — committed-pipeline regression (baseline misroute → corrected) — **mandatory**
A regression test that loads the **real committed config** (`configs/acmg/tsc.yaml` with
`non_mane_transcript: true` + TSC2-only `genes:` pinned `.5`, and `configs/ingest/tsc.yaml`) and drives
**representative real `.4` BIAS rows** (TSC2 `.4`, TSC1 `.4`, and NTHL1 `.6`) through the **actual
`BiasTsvSource` → `policy.check_out_of_scope_gene` / `check_edge_cases` → `pipeline`** path — **no** stubbed
policy, **no** hand-built record that bypasses the source. **Baseline (pre-fix, must be demonstrated, not
hypothesized):** the committed pipeline misroutes every TSC2 `.4` row to `EDGE_CASE_ROUTED`
(`non_mane_transcript`, `.4 ≠ .5`) and every TSC1 `.4` row to `OUT_OF_SCOPE_GENE` (TSC1 ∉ scorer `genes:`).
**Corrected:** add TSC1 `.5` to the scorer gene scope and, after a manifest/canonical-adapter-supplied
SPDI is validated against the record, the same real TSC1 **and** TSC2 `.4` rows are scored in-scope
(`reconciled_version_delta`, not routed), while the
**30 NTHL1 rows remain** in the manual queue
(`OUT_OF_SCOPE_GENE`, `excluded_from_scorer=True`). The census "30 manual" count is a separate census-level
analysis and is explicitly **not** accepted as proof the pipeline routes correctly — only this
real-config / real-row / real-pipeline regression is.

---

## 2. Public API / config (the exact surface the doer builds)

### 2.1 Config — per-gene MANE identity + reconciliation policy
Extend `configs/ingest/tsc.yaml` (or a co-located `configs/eval/transcript_reconciliation.yaml`), schema-
validated, with, per in-scope gene: `{mane_base_accession (e.g. NM_000548), pinned_version (5),
bias_emitted_version (4)}` and a policy flag `version_reconciliation: spdi_equivalent`. No wildcard / no
default gene mapping (schema rejects). This makes the `.4/.5` reconciliation an explicit, pinned,
reviewable policy — never an implicit guess.

### 2.2 `reconcile_transcript_identity(record, spdi, config) -> TranscriptReconciliation`
Fields `{gene, emitted_transcript, pinned_transcript, base_accession_match: bool, version_delta: bool,
spdi, disposition}` with `disposition ∈ {reconciled_version_delta, out_of_scope_gene,
transcript_base_mismatch, canonical_identity_unverified}`:
- **`reconciled_version_delta`** — same MANE base accession, pinned-vs-emitted version differs, canonical
  genomic SPDI present/valid ⇒ in-scope, **not** routed to manual review; the version delta is recorded as
  provenance.
- **`out_of_scope_gene`** — `record.gene_name ∉ config.genes` (the 30 NTHL1) ⇒ **fail-loud** →
  `ManualQueueItem(error_code="OUT_OF_SCOPE_GENE", excluded_from_scorer=True)`; never scored, never
  re-attributed to TSC2, never classified.
- **`transcript_base_mismatch`** — in-scope gene but a **different base accession** than the pinned MANE ⇒
  **fail-loud** → manual queue (`TRANSCRIPT_BASE_MISMATCH`), never silently coerced to the pinned accession
  (mirrors the normalizer's `REF_MISMATCH` no-silent-correct rule).
- **`canonical_identity_unverified`** — no canonical SPDI supplied, malformed SPDI, wrong genomic
  accession, or an SNV SPDI that does not match the record's position/ref/alt ⇒ **fail-loud** manual
  routing. A raw `chrom:pos:ref:alt` echo is never accepted as canonical proof. Track C's final pipeline
  correction therefore depends on leakage-validation's canonical adapter/manifest enrichment; direct
  `BiasTsvSource` remains blocked rather than silently trusted.

### 2.3 Scorer-policy refinement
`scorer/policy.py::check_edge_cases`'s `non_mane_transcript` predicate is refined so a pure
`reconciled_version_delta` (same base, matching SPDI) is **not** flagged, while any
`transcript_base_mismatch` still is. `check_out_of_scope_gene` stays always-on and unchanged in intent.
The reconciliation reads `record` + the normalizer's SPDI + config — never a hardcoded accession.

### 2.4 Output — persisted reconciliation report
The probe script writes a deterministic report: per-record disposition rollup, the version-delta count, the
30 out-of-scope NTHL1 IDs (bounded, sorted), the SPDI-invariance evidence. Persisted under `data/census/`.

---

## 3. Acceptance criteria (AC-C1…AC-C7)

- **AC-C1** (arithmetic + version facts): Probe 1 verifies `4339+30==4369`, `2249==2249`, all TSC records
  `.4`, all pins `.5`; cited.
- **AC-C2** (NTHL1 routing): the 30 NTHL1 records are characterized as chr16p13.3 TSC2-region inputs and
  each routes to `out_of_scope_gene` manual queue (`excluded_from_scorer=True`); **none** scored, **none**
  re-attributed to TSC2, **none** clinically classified.
- **AC-C3** (SPDI key): the canonical genomic SPDI is invariant to the `.4/.5` transcript version (Probe 3);
  reconciliation keys on SPDI + base accession, not the transcript string.
- **AC-C4** (version delta reconciled, base mismatch fails loud): a same-base `.4`-vs-`.5` record with
  matching SPDI is `reconciled_version_delta` and **not** routed to manual review; a base-accession
  mismatch or out-of-scope gene is fail-loud to the manual queue.
- **AC-C5** (fail-loud, never silent): an unreconcilable transcript/gene never gets a guessed/default MANE
  mapping; the normalizer's checksum/REF_MISMATCH fail-loud and manual-queue contract is preserved and
  reused (no new SPDI algebra).
- **AC-C6** (no fixture patch / no labels / no classification): no test fixture is patched; no benchmark
  labels are used; no direction/classification is emitted for any manual-queue row.
- **AC-C7** (committed-pipeline regression, baseline → corrected): a regression test loads the **real
  committed** `configs/acmg/tsc.yaml` (`non_mane_transcript: true`, TSC2-only `.5`) + `configs/ingest/tsc.yaml`
  and drives **representative real `.4` BIAS rows** through the actual `BiasTsvSource` → `policy` →
  `pipeline` path. It first **demonstrates the live baseline misroute** (TSC2 `.4` → `EDGE_CASE_ROUTED`,
  TSC1 `.4` → `OUT_OF_SCOPE_GENE`) and then the **corrected** behavior (**both TSC1 and TSC2** `.4`
  scored in-scope via `reconciled_version_delta`), while the **30 NTHL1 rows remain** manual
  (`excluded_from_scorer=True`). The
  defect is asserted as active/committed and is **never** described as hypothetical; the census 30-manual
  figure is **not** accepted as proof of correct routing.

---

## 4. DoR task specs (sequence)

1. `transcript-reconciliation-probe` — `scripts/probe_transcript_reconciliation.py` + tests (arithmetic,
   NTHL1 locus, SPDI-invariance) RED first, **plus the mandatory committed-pipeline regression** (Probe 4 /
   AC-C7) that drives real `.4` BIAS rows through the real `BiasTsvSource → policy → pipeline` path and first
   pins the live baseline misroute.
2. `transcript-reconciliation-config` — the per-gene MANE base/version + `spdi_equivalent` policy config +
   schema validation.
3. `transcript-reconciliation-policy` — `reconcile_transcript_identity` + the `non_mane_transcript`
   refinement; `check_out_of_scope_gene` stays always-on. The regression from step 1 must flip from
   baseline-misroute to corrected while the 30 NTHL1 rows stay manual.

## 5. Dependencies

- **Upstream:** none — decision C is independent (parallel with A and B).
- **Downstream:** decision D pins gene/transcript scope = TSC1/TSC2 MANE `.5` with SPDI reconciliation;
  NTHL1 excluded. D consumes this reconciliation for its scope.

## 6. Authorized outputs

- `configs/ingest/tsc.yaml` (add MANE base/version + reconciliation policy) or
  `configs/eval/transcript_reconciliation.yaml`.
- `src/raptor/scorer/policy.py` (refine `non_mane_transcript` only; `check_out_of_scope_gene` unchanged);
  a small reconciliation helper module if cleaner (`src/raptor/ingest/transcript_reconcile.py`).
- `scripts/probe_transcript_reconciliation.py`; the persisted report under `data/census/`.
- `tests/scorer/test_transcript_reconciliation.py`, `tests/ingest/test_nthl1_out_of_scope_routing.py`,
  `tests/scorer/test_committed_pipeline_transcript_regression.py` (the AC-C7 real-config / real-row /
  real-pipeline baseline-misroute → corrected regression; the 30 NTHL1 rows stay manual).

No other production/config/test file is edited. The normalizer's SPDI algebra is reused, not re-rolled. No
test fixture is patched.
