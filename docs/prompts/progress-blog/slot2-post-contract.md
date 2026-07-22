# Slot 2 — Progress post: before the first score

## Output

Create only:

- `docs/blog/2026-07-10-before-the-first-score.md`

Use this title:

> **Before the First Score: Building an Honest TSC Variant Benchmark**

Target 1,400–2,200 words. Audience: software engineers, rare-disease researchers, curators, funders,
and technically literate non-geneticists. Tone: direct, reflective, technically precise; explain
biology terms briefly without flattening uncertainty.

## Core thesis

This is a **pre-results engineering checkpoint**, not a performance announcement. RAPTOR has built the
measurement instrument and label-free path to the held-out exam; it has **not** yet measured precision/
recall, passed the gate, classified the ~6,700 VUS, or produced any externally meaningful genetic
classification. Publishing now timestamps the benchmark, thresholds, leakage decisions, and failure
conditions before results exist.

## Required structure

1. **Deck / status box** — date, "pre-results", one-sentence product boundary.
2. **Why publish before scoring?** — pre-registration and anti-retrospective storytelling.
3. **What RAPTOR is building** — auditable TSC1/TSC2 evidence packets + VCEP triage, human sign-off;
   never diagnosis/treatment/final autonomous classification.
4. **What is complete** — concise milestone table:
   - PRD-01 scorer, PRD-02 ingest, PRD-03 KB, PRD-06 harness, PRD-07 known-label loader;
   - kit-promotion machinery + ClinVar/HGVS parser corpus;
   - pinned ClinVar 2026-07-07 benchmark;
   - pre-registered thresholds/holdout;
   - operator-confirmed x64 8-variant BIAS/Nirvana smoke test;
   - PRD-08 Task A label-free export on the feature branch.
5. **The benchmark we actually have** — 3,681 scoreable knowns; 2,577 held-out / 1,104 development
   reserve at 0.7; missense pathogenic held-out 51; truncating pathogenic 210. Explain why 70% held-out
   does not starve training: Tier 1/2 is deterministic and learns no benchmark parameters.
6. **What nearly produced a hollow green**:
   - direct ClinVar answer-copy criteria PP5/BP6/PS4; PS4 discovered from real BIAS v3 rationale;
   - ADR-0009 bans them in eval and production;
   - PM1/PM5/PP2 transitive/aggregate ClinVar dependence remains UNVERIFIED pending full-output counts;
   - therefore terminal eval remains blocked.
7. **The label-free exam boundary** — all 2,577 canonical SPDI IDs round-trip through VCF and the real
   normalizer; VCF/manifest counts 2,577, no truth fields, hashes:
   - VCF `4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d`
   - manifest `9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4`
   Explain that full BIAS scoring has not happened yet.
8. **The build process also failed—and improved** — summarize without model marketing:
   - multi-round checker loops found real issues;
   - promotion kit converts recurring code invariants into gates;
   - monolithic test-author prompts produced repeated fixture/contract misses;
   - persisted hashed three-slot prompts materially improved the doer pass;
   - GPT checker found a short-anchor spec gap, which was promoted into PRD + independent RED regression;
   - final Task-A evidence: 21 targeted, 399 passed/1 skipped, checker CLEAN, real 2,577 export conserved.
9. **What this does not prove / adversarial ledger** — explicit bullets:
   - no held-out precision/recall yet;
   - ClinVar is a best-available proxy, not TSC expert-panel ground truth (no 3-star panel in frozen set);
   - strong class imbalance and one truncating-benign known;
   - point-estimate gate vs Clopper-Pearson lower-bound fidelity remains open;
   - full x64 scoring and PM1/PM5/PP2 ruling pending;
   - no VUS run, no clinical claim, qualified human still required.
10. **Next falsifiable milestone** — x64 scores label-free VCF → audit counts → Oracle ruling → canonical
    adapter → PRD-06 gate PASS/FAIL. State what FAIL means: no authorized VUS run, re-examine engine.

## Grounding sources

Read and link claims to these repository artifacts (do not merely list them at the end):

- `docs/STRATEGY.md` Part I §§1, 5, 6, 7, 9
- `docs/PROGRAM.md`
- `docs/EVALUATION.md` Part I §§1–7 and Part II §§1–6
- `docs/DECISIONS.md` ADR-0007, ADR-0008, ADR-0009
- `docs/prd/PRD-06-benchmark-eval-harness.md`
- `docs/prd/PRD-08-live-eval-evidence-adapter.md`
- `data/benchmark/tsc_clinvar_2026-07-07_stats.json`
- `configs/eval/tsc2.yaml`
- `configs/eval/export.yaml`
- relevant commit history through local `4965104` and merged `2766e33`

Use relative Markdown links. A short Sources / Reproducibility section is allowed, but substantive claims
must also cite inline.

## Required distinctions

- Call the small `tests/fixtures/clinvar_hgvs_golden.yaml` a **parser/vocabulary corpus**, not the model
  performance benchmark.
- Call the 3,681-known / 2,577-held-out set the **frozen known-variant benchmark**.
- "Smoke-tested" means eight variants only; never upgrade it to "validated x64 pipeline".
- Latest PRD-08 Task A is on `feature/prd08-live-eval-bridge`, not yet merged/pushed. Say so.
- The full label-bearing benchmark remains out of repo by design; only aggregate stats and reproducible
  scripts/pins are committed.
