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

TSC1/TSC2 carry ~6,700 VUS with **0 expert-panel reviews** (TSC2 alone: 4,445). The 19-of-28 ACMG/AMP
criteria that are *automatable from public data* (BIAS-2015) have never been applied systematically to
TSC. This feature computes that **deterministic evidence layer** — the measurable half (GP-2) that
anchors the whole system: the baseline every later tier is measured against, and the substrate the
VCEP triage worklist (PRD-04) is built from.

**v1 scope: TSC2 only** (aligns with STRATEGY §7 Phase-1 "Tier 1/2 on TSC2"); **TSC1 is a fast-follow**
once TSC2 clears its gates. The v1 ACMG criterion set = the BIAS-2015-automated criteria, with the
**exact included/deferred list pinned in `configs/acmg/` before build** (see §9).

## 2. Goal & non-goals

**Goal:** for every normalized **TSC2** variant (v1), compute the automatable ACMG criteria and emit a
deterministic, fully-provenanced evidence record, measurable against the frozen benchmark. *(TSC1 fast-follow.)*

**Non-goals (explicit):**
- Tier-3 literature/PS3 evidence (separate PRD).
- Any *final* classification or VUS→LP/LB decision (human/oracle gated — STRATEGY §9).
- Cross-linkage / gap-map.
- The benchmark itself (EVAL_PLAN.md) and ingestion/normalization (PRD-02) — consumed, not built here.

> *"Tier-1/2-implied LP/LB" (used in AC1) is an **eval-only, non-authoritative** mapping from criterion
> calls to an implied direction — defined in EVAL_PLAN §3.1. It is never shown as a classification and
> never crosses an external threshold (STRATEGY §9).*

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
- **FR8 — Edge-case routing:** PVS1 terminal-exon, ambiguous/non-MANE transcript, **splice-region**, and mosaicism-flagged variants route to **manual review**, never silent scoring (R-A3). Each predicate is defined in `configs/acmg/edge_cases.yaml` and covered by named canary fixtures (EVAL_PLAN §4).

## 5. Non-functional requirements

- **Performance:** the BIAS-2015 scoring step batches all TSC2 VUS (~4,445) in seconds (≈ 1,327 variants/s). *Assumes locally-cached, pinned predictor sources;* the **integrated** scorer's wall-clock (predictor lookups + provenance writes) has its own measured target + benchmark command — not assumed from BIAS alone.
- **Provenance (GP-5):** every criterion call stores `{source, source_snapshot_version, tool_version, timestamp}`.
- **Licensing (R-B2):** predictor annotations (CADD/SpliceAI/REVEL) are non-commercial/research-use per the **canonical licensing matrix (ARCHITECTURE §8)**; every derived field is tagged to that matrix (single source of truth).
- **Config-driven (GP-6):** all rules/thresholds in versioned, schema-validated config.
- **Reproducibility (R-A11):** record-for-record identical output on re-run of the same pinned inputs.

## 6. Acceptance criteria *(→ EVAL_PLAN.md; these become the OPERATING_MODEL gates)*

- **AC1a — Metrics computed:** precision/recall/concordance are computed and reported on the frozen **held-out** set for Tier-1/2-implied LP/LB vs best-available labels (EVAL_PLAN §3), with the minimum-count rule (EVAL_PLAN §2) applied.
- **AC1b — Trust gate (blocked on Oracle):** the accuracy gate passes **only** once the Oracle (GP-3) has pre-registered thresholds and held-out metrics meet them. Until then AC1b is `BLOCKED` — the feature is *buildable* but not *validated* (§7, R-E1). No target number is invented (GP-9/H13).
- **AC2 — Grounding (GP-9):** 100% of emitted records carry a resolvable `source_ref`; **0** null/unresolvable refs.
- **AC3 — Determinism (R-A11):** two runs on identical pinned inputs produce record-identical output.
- **AC4 — No double-counting:** audit shows each ACMG criterion fires ≤ once per variant; verified on the canary set.
- **AC5 — Edge-case safety (R-A3):** every predicate in `edge_cases.yaml` (terminal-exon, non-MANE transcript, splice-region, mosaicism) routes its named canary fixtures to manual review; **0** silent auto-scores in those classes.
- **AC6 — No trace-cribbing (H1):** the scorer reads no benchmark/label/oracle file — verified by the G2 forbidden-path check (**checker-run manual audit until the G2 lint script exists**, OPERATING_MODEL §10; that script is a dependency, §7).
- **AC7 — NFR checks:** config schema-validates with **no hardcoded thresholds** (GP-6); every predictor field carries a licensing tag (R-B2); every criterion call has complete provenance fields (GP-5); the integrated-scorer performance benchmark meets its stated wall-clock target.

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-02 · Variant ingestion & normalization | backlog | Yes (FR1) — or a minimal stub input schema + fixtures for scorer-only dev |
| PRD-03 · Provenance ledger & KB schema | backlog | Yes (FR5) — or a minimal evidence-record schema stub |
| Frozen benchmark + split (EVAL_PLAN.md) | in progress | Yes (AC1a) |
| **Oracle-pre-registered thresholds** (GP-3) | not started | Yes (AC1b) — validation blocked until set |
| G2 trace-cribbing lint script | planned | AC6 *mechanical* check (interim: manual audit) |
| BIAS-2015 install; ClinGen Dosage BED; gnomAD/CADD/REVEL/SpliceAI | not started | Yes |

> **Buildable vs validated:** PRD-01 can be **built and unit-tested** against minimal PRD-02/03 stub
> interfaces + fixtures; it cannot be **validated** (AC1b) until the benchmark is frozen and the Oracle
> sets thresholds. Ship the build; gate the trust.

## 8. Risks (see RISK_REGISTER for mitigations)

R-A3 (edge-case mis-application) · R-A9 (inherited reference-data errors) · R-A10 (build/transcript
mismatch) · R-A11 (non-reproducibility) · H1 (trace-cribbing) · H7 (config drift muting a criterion) ·
R-B2 (licensing leakage). **GP-4 note:** BIAS-2015 is reused, not rebuilt — but it earns its own
validation ceiling here (AC1), not trust-transfer.

## 9. Open questions

- **Enumerate the exact v1 ACMG criteria** (included vs deferred) in `configs/acmg/` — required before the PRD is Ready.
- Per-gene thresholds + haploinsufficiency source: confirm ClinGen Dosage BED record for TSC2.
- **Frozen benchmark snapshot + held-out split** (EVAL_PLAN §2) and **Oracle-set thresholds** (AC1b) — the two items that make the accuracy gate concrete. *(The label hierarchy itself is already defined in EVAL_PLAN §2.)*
