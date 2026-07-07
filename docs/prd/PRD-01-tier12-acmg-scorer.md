# PRD-01 — Tier-1/2 Deterministic ACMG Scorer

> **Status:** Draft · **Owner:** @sdrona_microsoft · **Phase:** 1 (STRATEGY §7) · **Last updated:** 2026-07-08
>
> **Format:** standard lean PRD (Context · Goals/Non-goals · Users · Functional · Non-functional ·
> Acceptance · Dependencies · Risks · Open questions). One feature per PRD; acceptance criteria are
> the source for the build-loop gates (OPERATING_MODEL §4) and the eval targets (EVAL_PLAN.md).
>
> **Links:** STRATEGY §6 (Tier 1/2) · GP-1, GP-4, GP-5, GP-6, GP-9 · RISK_REGISTER R-A3/A9/A10/A11,
> H1/H7, R-B2 · EVAL_PLAN.md (benchmark + metrics).

## 1. Context / problem

TSC1/TSC2 carry ~6,700 VUS with **0 expert-panel reviews**. The 19-of-28 ACMG/AMP criteria that are
*automatable from public data* (BIAS-2015) have never been applied systematically to TSC. This
feature computes that **deterministic evidence layer** — the measurable half (GP-2) that anchors the
whole system: it is the baseline every later tier is measured against, and the substrate the VCEP
triage worklist (PRD-04) is built from.

## 2. Goal & non-goals

**Goal:** for every normalized TSC1/TSC2 variant, compute the automatable ACMG criteria and emit a
deterministic, fully-provenanced evidence record, measurable against the frozen benchmark.

**Non-goals (explicit):**
- Tier-3 literature/PS3 evidence (separate PRD).
- Any *final* classification or VUS→LP/LB decision (human/oracle gated — STRATEGY §9).
- Cross-linkage / gap-map.
- The benchmark itself (EVAL_PLAN.md) and ingestion/normalization (PRD-02) — consumed, not built here.

## 3. Users & need

| User | Need this feature serves |
|---|---|
| VCEP curators | The deterministic evidence that ranks candidate VUS for triage (via PRD-04). |
| Eval harness | A reproducible **baseline** to measure Tier-3 / cross-linkage value against. |
| Later tiers | A criterion-level evidence substrate to add literature evidence onto. |

## 4. Functional requirements

- **FR1 — Consume normalized variants** (dep: PRD-02): HGVS/SPDI on a pinned MANE transcript + genome build.
- **FR2 — Run BIAS-2015** to compute the automatable criteria (PVS1, PM2, BA1/BS1, PP3/BP4, PS1/PM5, BP7, …).
- **FR3 — Integrate predictor sources** per criterion: gnomAD v4.1.1 (PM2/BA1/BS1), CADD/REVEL/SpliceAI (PP3/BP4/BP7).
- **FR4 — Criterion-level evidence model:** each ACMG criterion fires **at most once**, recorded as `{criterion, strength, source_ref, record/span}`; correlated predictors (CADD/REVEL/BIAS/domain) are **not double-counted** (RISK_REGISTER §1 criterion-level control).
- **FR5 — Emit evidence records** into the KB (dep: PRD-03) with full provenance and a **resolvable `source_ref`** on every criterion call (GP-9).
- **FR6 — Deterministic:** no LLM in this tier; same input → identical output.
- **FR7 — Per-gene calibration in config** (GP-6): thresholds, haploinsufficiency, per-gene frequency cutoffs in `configs/acmg/*.yaml`; no hardcoded values.
- **FR8 — Edge-case routing:** PVS1 terminal-exon, ambiguous transcript, and mosaicism-flagged variants route to **manual review**, never silent scoring (R-A3).

## 5. Non-functional requirements

- **Performance:** batch all ~6,700 TSC1/TSC2 VUS in seconds (BIAS-2015 ≈ 1,327 variants/s).
- **Provenance (GP-5):** every criterion call stores `{source, source_snapshot_version, tool_version, timestamp}`.
- **Licensing (R-B2):** CADD/SpliceAI/REVEL are research-use-only; tag every derived field in the licensing matrix.
- **Config-driven (GP-6):** all rules/thresholds in versioned, schema-validated config.
- **Reproducibility (R-A11):** record-for-record identical output on re-run of the same pinned inputs.

## 6. Acceptance criteria *(→ EVAL_PLAN.md; these become the OPERATING_MODEL gates)*

- **AC1 — Accuracy:** on the frozen benchmark **held-out** set, Tier-1/2-implied LP/LB vs best-available labels meets the pre-registered precision/recall thresholds (thresholds defined in EVAL_PLAN.md).
- **AC2 — Grounding (GP-9):** 100% of emitted records carry a resolvable `source_ref`; **0** null/unresolvable refs.
- **AC3 — Determinism (R-A11):** two runs on identical pinned inputs produce record-identical output.
- **AC4 — No double-counting:** audit shows each ACMG criterion fires ≤ once per variant; verified on the canary set.
- **AC5 — Edge-case safety (R-A3):** every enumerated edge case routes to manual review; **0** silent auto-scores in those classes.
- **AC6 — No trace-cribbing (H1):** the scorer never reads benchmark/label/oracle files (G2 lint clean).

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-02 · Variant ingestion & normalization | backlog | Yes (FR1) |
| PRD-03 · Provenance ledger & KB schema | backlog | Yes (FR5) |
| Frozen benchmark + metrics (EVAL_PLAN.md) | in progress | Yes (AC1) |
| BIAS-2015 install; ClinGen Dosage BED; gnomAD/CADD/REVEL/SpliceAI | not started | Yes |

## 8. Risks (see RISK_REGISTER for mitigations)

R-A3 (edge-case mis-application) · R-A9 (inherited reference-data errors) · R-A10 (build/transcript
mismatch) · R-A11 (non-reproducibility) · H1 (trace-cribbing) · H7 (config drift muting a criterion) ·
R-B2 (licensing leakage). **GP-4 note:** BIAS-2015 is reused, not rebuilt — but it earns its own
validation ceiling here (AC1), not trust-transfer.

## 9. Open questions

- Which of the 19/28 automatable criteria are in **v1** vs deferred?
- Per-gene thresholds + haploinsufficiency source: confirm ClinGen Dosage BED record for TSC2 (and TSC1).
- Final benchmark **label hierarchy** (EVAL_PLAN.md) — needed to make AC1 concrete.
