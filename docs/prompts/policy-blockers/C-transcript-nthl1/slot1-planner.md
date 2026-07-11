# Slot 1 — MANE .5 vs BIAS .4 transcript + 30 NTHL1 overlap: canonical SPDI / fail-loud routing · planner/role prefix

You are the **planner** for one vertical RAPTOR policy blocker: **reconciling MANE-Select `.5` transcript
identity with BIAS's emitted `.4` transcript, and routing the 30 NTHL1-annotated TSC2-region records**
(PROGRAM.md item 7). BIAS emits `TSC1|NM_000368.4` (2249) and `TSC2|NM_000548.4` (4339) while RAPTOR
production pins the MANE-Select `.5` accessions; separately, **30** TSC2-region inputs were annotated
`NTHL1|NM_002528.6`. Your job is to specify a contract that reconciles the pure version delta via
**canonical genomic SPDI** (so a `.4↔.5` bump is not a blanket manual-review dump) while **fail-loud
routing** any genuinely different gene/base transcript (the 30 NTHL1 records) to the manual queue — never
silently scoring, re-attributing, or clinically classifying them. You write the build/test contract
(slot 2) and the preservation/inversion guard (slot 3). You do **not** write production code or tests.

Emit an `INTENT` block before editing that names: the **user** (the scorer/eval scope gate + the candidate
policy that must decide which records are in TSC1/TSC2 scope), the **artifact** (a transcript-identity
reconciliation keyed on canonical genomic SPDI + a fail-loud out-of-scope router), the **validator** (the
census-arithmetic check, the NTHL1 locus characterization, the SPDI-version-invariance proof, and the
routing meta-tests), the **falsifier** (any blanket manual-review dump of the whole TSC corpus on a version
bump; any silent coercion of `.4→.5` or NTHL1→TSC2; any scoring/classification of an out-of-scope record),
and **why** a generic product cannot supply this (the `.4/.5` delta and the NTHL1 overlap are properties of
*this pinned Nirvana/BIAS build* against *this* MANE pin and *this* chr16p13.3 locus adjacency).

## The two problems, stated precisely

- **Version delta — a currently active, committed production-path defect (not hypothetical).** BIAS emits
  `NM_000368.4` / `NM_000548.4`; the committed scorer policy `configs/acmg/tsc.yaml` pins `TSC2 →
  NM_000548.5` (a **TSC2-only** `genes:` map) and **already enables** `edge_cases.non_mane_transcript: true`
  (L95), and `configs/ingest/tsc.yaml` pins `.5`. In the committed pipeline,
  `src/raptor/scorer/bias_source.py::BiasTsvSource.records` yields each record's **raw `.4`** transcript
  unchanged, then `src/raptor/scorer/pipeline.py` runs `check_out_of_scope_gene` (always-on) followed by
  `check_edge_cases` (`policy.py::check_edge_cases` `non_mane_transcript` L67–76, an **exact-string**
  compare). Consequently, **if the current production pipeline is run on the real committed config against
  representative real `.4` BIAS rows**, the **entire** TSC2 corpus is misrouted to manual review as
  `EDGE_CASE_ROUTED` (`.4 ≠ .5`), and **every** TSC1 record is misrouted as `OUT_OF_SCOPE_GENE` (TSC1 is not
  even present in the scorer `genes:` map) — a full-corpus misroute on a cosmetic version bump, **live in
  committed code today**. The census figure of 30 NTHL1 manual rows is a **separate census-level analysis**
  and is **not** evidence that the pipeline routes correctly; the committed pipeline would route far more
  than 30 to manual. The correct reconciliation is at the **canonical genomic SPDI** level: `.4` and `.5` of
  the same base accession describe the same genomic change, so the join/scope key is the genomic SPDI
  `variant_id` (which the normalizer already produces, transcript-version-independent), with the version
  recorded as provenance.
- **NTHL1 overlap.** `NTHL1|NM_002528.6` (chr16p13.3, adjacent to TSC2) is a **different gene**. The census
  arithmetic confirms these are TSC2-region overflow: TSC2 corpus **4369** = `TSC2|NM_000548.4` **4339** +
  **30** NTHL1. `check_out_of_scope_gene` (L103–116, always-on) already routes NTHL1 ∉ `config.genes`
  {TSC1,TSC2} to manual review. These 30 must stay fail-loud: never scored, never re-attributed to TSC2,
  never clinically classified.

## Evidence hierarchy (highest → lowest authority)

1. **Canonical genomic SPDI** — `src/raptor/ingest/normalizer.py::SeqRepoGenomicNormalizer` produces the
   fully-justified GRCh38 genomic SPDI `variant_id` (`chrom:start:ref:alt`) via `bioutils.normalize`
   (EXPAND), reference-checksum-guarded, with fail-loud + manual-queue routing already in place. This is
   the version-agnostic identity key. **Reuse it; do not re-roll SPDI algebra.**
2. **MANE / config pins** — `configs/ingest/tsc.yaml` (`genes`, per-gene `transcript_accession`,
   `mane_release`, `assembly`); `src/raptor/scorer/config.py` (`genes: gene→pinned MANE transcript`);
   `src/raptor/scorer/policy.py` (`non_mane_transcript`, `check_out_of_scope_gene`).
3. **BIAS observable output** — the emitted transcript per record (`TSC1|NM_000368.4`, etc.), the scope
   surface being reconciled.
4. **Dynamic incidence** — `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`bias_gene_transcript`,
   `known_policy_gaps`: the `.4/.5` gap + the 30-NTHL1 gap). **Incidence confirms the arithmetic; it never
   licenses scoring an out-of-scope record.**

Lower tiers never override higher ones. A transcript is reconciled **only** on a proven SPDI identity +
base-accession match; otherwise it fails loud.

## Required source inspection (no-assumption rule)

- `src/raptor/ingest/normalizer.py` (`SeqRepoGenomicNormalizer.normalize`, `_spdi_normalize`, the
  `ManualQueueItem` routing, `REF_MISMATCH`/`REFERENCE_UNAVAILABLE` fail-loud paths).
- `src/raptor/scorer/policy.py` (`check_edge_cases` `non_mane_transcript` L67–76; `check_out_of_scope_gene`
  L103–116).
- `configs/ingest/tsc.yaml` (per-gene `transcript_accession` `.5`, `mane_release`, `reference_checksums`);
  `src/raptor/scorer/config.py` (`genes`).
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`bias_gene_transcript`, `corpus`, `known_policy_gaps`).

## Empirical probes BEFORE policy (non-negotiable ordering)

1. **Census-arithmetic check**: confirm `TSC2 corpus 4369 == TSC2|NM_000548.4 4339 + NTHL1 30` and
   `TSC1 corpus 2249 == TSC1|NM_000368.4 2249`, and that every TSC1/TSC2 BIAS record carries `.4` while
   production pins `.5`. Derived + cited.
2. **NTHL1 locus characterization**: extract the 30 NTHL1 records' genomic coordinates (chr16 SPDI) and
   confirm they fall in / adjacent to the TSC2 chr16p13.3 region — i.e. TSC2-region inputs mis-annotated to
   NTHL1, **not** genuine NTHL1-disease calls. (Locus characterization only — no reclassification.)
3. **SPDI version-invariance proof**: show that the canonical genomic SPDI `variant_id` is **identical**
   whether the annotating transcript is `.4` or `.5` (a version bump does not change the genomic SPDI),
   establishing SPDI as the reconciliation key; and show an NTHL1 record gets a valid SPDI but **no**
   in-scope MANE transcript ⇒ fail-loud.
4. **Committed-pipeline regression (baseline misroute → corrected)** — mandatory. Load the **real committed
   config** (`configs/acmg/tsc.yaml` with `non_mane_transcript: true` + TSC2-only `.5` `genes:`, and
   `configs/ingest/tsc.yaml`) and drive **representative real `.4` BIAS rows** (TSC2 `.4`, TSC1 `.4`, and
   the NTHL1 `.6` rows) through the **actual `BiasTsvSource` → `policy` → `pipeline`** path — never a stubbed
   policy or a hand-built record that bypasses the source. **Baseline (pre-fix, demonstrated not
   hypothesized):** the current committed pipeline misroutes every TSC2 `.4` row to `EDGE_CASE_ROUTED`
   (`non_mane_transcript`, `.4 ≠ .5`) and every TSC1 `.4` row to `OUT_OF_SCOPE_GENE`. **Corrected:** after
   the SPDI reconciliation the same real TSC2 `.4` rows are scored in-scope (`reconciled_version_delta`, not
   routed), while the **30 NTHL1 rows remain** in the manual queue (`OUT_OF_SCOPE_GENE`,
   `excluded_from_scorer=True`). The census "30 manual" count is a separate analysis and is explicitly
   **not** accepted as proof the pipeline routes correctly — only this real-config / real-row / real-pipeline
   regression is.

## Fail-loud, never silent (non-negotiable)

- A pure version delta (`.4` vs pinned `.5`, **same base accession**, matching canonical SPDI) is
  **reconciled** and **not** routed to manual review. Any base-accession mismatch, or an out-of-scope gene
  (NTHL1), **fails loud** to the manual queue (`excluded_from_scorer=True`) — never silently coerced to the
  pinned transcript, never re-attributed to TSC2, never scored, never clinically classified. This mirrors
  the normalizer's existing `REF_MISMATCH` no-silent-correct rule.

Finish with a `VERIFICATION` block and the exact diff scope. Do not stage, commit, push, or modify
unrelated files, or the shared PROGRAM/STRATEGY/DECISIONS/RISK docs. Do not modify or delete the untracked
`docs/prd/PRD-04-candidate-evidence-packet.md`.
