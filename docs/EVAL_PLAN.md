# RAPTOR — Evaluation Plan

> **Status:** DRAFT v0.1 · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (added §1.3 tiered v3 post-hoc/prospective registration, ADR-0013) · **Review cadence:** per phase
>
> **Scope now:** the **frozen benchmark** + **Tier-1/2** metrics (PRD-01). Extensible to Tier-3 and
> cross-linkage (§6) — those sections are stubs until those tiers exist (GP-7: don't spec what isn't built).
>
> **Method discipline:** pre-registered thresholds, a **held-out** test set never used for tuning,
> and **oracle-blind** checks alongside label comparison. Every acceptance criterion in a PRD resolves
> to a metric here; every gate in OPERATING_MODEL §4 that says "meets threshold" points here.

---

## 1. Objective

Quantify how well the deterministic layer (Tier-1/2) reproduces **best-available** variant labels,
establish the **frozen baseline** the harder tiers are measured against, and **gate** Tier-3 trust:
no Tier-3 value is claimed until Tier-1/2 clears its thresholds on the held-out set.

### 1.1 The validation gate — measured on KNOWNS, then applied to VUS *(binding sequence)*

**You cannot measure metrics on VUS** — a VUS has no ground-truth label. Validation is therefore done
on **known-classification** variants and only *then* applied to the unknowns:

```
KNOWN TSC1/TSC2 variants (P/LP + B/LB, high review status)   ← the answer key
        │  split (no leakage)
        ├─ train/dev  → calibrate config thresholds (per-gene freq, PP3/BP4 cutoffs)
        └─ held-out   → MEASURE precision / recall / concordance (thresholds frozen)
                          │
                   metrics clear pre-registered thresholds? (AC1b, Oracle-set)
                          │ yes                                   │ no
                          ▼                                       ▼
   run scorer on the ~6,700 VUS  →  PROPOSALS,             stop; recalibrate /
   human-reviewed, never auto-final (§9)                   widen benchmark / reassess
```

**Note — Tier-1/2 is a deterministic ACMG rule engine, not a trained model.** "train/dev" calibrates
*configurable thresholds*, not weights; the held-out discipline still applies because threshold
calibration can overfit. **No VUS is classified until the gate is passed.** The benchmark-construction
+ metric harness that runs this is a buildable module — **PRD-06 (Benchmark & Evaluation Harness)**,
which **gates** any VUS run.

### 1.2 Known-set scope — TSC2-first; extend for *power*, not for a better number

A recurring instinct is "if metrics are weak, add more variants." For a **deterministic** scorer this
is a category error worth stating explicitly:

- **More known variants → tighter confidence intervals (precision), NOT a better metric.** The scorer
  is fixed rules; adding data measures it more precisely, it does not make it more accurate.
- **Broadening across genes cannot rescue a poor TSC2 result — it averages it away.** A metric pooled
  over many genes can look healthy while TSC2 missense is bad (**R-A2c** distribution shift). That is a
  hollow green (category H). **The gate is always the TSC2-specific held-out (missense-stratified),
  even if the known set is broadened.**
- **The legitimate reason to extend is statistical power, concentrated on the *benign* side.** Disease
  genes like TSC2 carry many P/LP knowns but **thin B/LB**, so specificity gets a wide CI. If TSC2's
  known set is too small to measure precisely, extend the *known* set — other well-curated genes, or
  **gnomAD common variants as proxy-benign** — **for power / generality**, still reporting the
  TSC2-specific gate.
- **The engine is gene-agnostic** (ACMG criteria are general), so extending is a config +
  reference-data addition, not a rewrite — but not free (each gene adds its chromosome sequence, MANE
  transcript, and gene-specific criteria: PM1 hotspot, PP2/BP1 missense-mechanism, PVS1 LoF-mechanism).

**Sequence:** TSC2-first end-to-end; extend the known set **only if** TSC2 power is insufficient
(wide specificity CI), **never** to move an unacceptable number. If TSC2 metrics are genuinely poor,
the fix is the **scorer/calibration**, not more genes.

### 1.3 Tiered v3 post-hoc re-adjudication and prospective registration (ADR-0013)

The R2 masked held-out run (ADR-0012) and its v1/v2 interpretation are **frozen and immutable**:
v1's coarse missense `FAIL` and v2's `full_spectrum_status=BLOCKED_POLICY`/`vus_authorized=false`
remain exactly as scored, and neither is ever relabeled or overwritten by a later result.

**Tiered gate v3** (`data/census/tsc_tiered_readjudication_2026-07-21.json`, ADR-0013) is an
**additive, post-hoc re-adjudication** of that same frozen aggregate — it performs no new run,
scoring, annotation, benchmark read, network access, or data generation. It reports independent axes
instead of one coarse pass/fail:

| Axis | Purpose |
|---|---|
| Run integrity | Did the pinned pipeline execute cleanly (unchanged from R2)? |
| Data sufficiency | Is `min(actual, called)` at/above the powered floor (`ADEQUATE`/`UNDERPOWERED`/`NO_CALLS`)? |
| Conditional performance | Precision/recall lower bound *given* adequate data (`MET`/`NOT_ESTIMABLE`/`NOT_APPLICABLE`) |
| Policy parity | Is the scope blocked by an unrelated policy exclusion, e.g. PM1 (`CLEAR`/`BLOCKED`) |
| Correct-call coverage | `called/actual` ratio, reported even when not gating |
| Scope evidence status | `SUPPORTED_POSTHOC` / `UNDERPOWERED` / `NOT_APPLICABLE` |
| Authorization | `NOT_AUTHORIZED` / `PENDING_PROSPECTIVE` |

Undefined conditional metrics remain `null` — they are **never coerced to zero**, which is what let
v1/v2 conflate "zero calls" with "failed." PM1 applies only to `missense:pathogenic`; it must not
leak into the unrelated `truncating:pathogenic` scope (the v1/v2 defect ADR-0013 corrects).

**Post-hoc boundary (binding):** v3 is a semantic re-interpretation only. It generates no evidence,
authorizes no clinical classification, VUS worklist, ClinVar submission, or research scope, and does
not, by itself, satisfy the AC1b Oracle-threshold gate below — a scope's evidence being
`SUPPORTED_POSTHOC` is not the same as that scope being validated.

**Prospective registration (locked before any labels/scoring):** the next real validation of any v3
scope must run on the first eligible NCBI ClinVar GRCh38 `variant_summary` monthly archive dated
on/after 2026-08-01. Its URL, official date, MD5, and SHA-256 must be frozen *before* labels or
scoring occur — this is a **pre-registration**, not a result. If that archive is unavailable or
invalid, status is `BLOCKED_DATA`; no outcome-dependent substitute is permitted. Until that run
completes, every v3 scope's authorization remains `PENDING_PROSPECTIVE` or `NOT_AUTHORIZED`.

## 2. The frozen benchmark (ground truth — honestly, *proxy* labels)

TSC has **0 expert-panel (3★) reviews**, so there is no gold standard. The benchmark uses the
best-available labels, ranked, and is **frozen by date + source snapshot**.

**Label hierarchy** (highest first):
1. ClinGen VCEP / 3★ — if any ever exist.
2. 2★ multi-submitter **concordant** (no conflicts).
3. Curated literature database (e.g. Garcia 2024) with a citation.
4. Manual expert adjudication (recorded, by the Oracle — GP-3).

**Construction rules:**
- **Held-out split** — a train/dev portion and a **frozen held-out test**; the scorer and its config
  are **never tuned on the held-out test**; results are reported on held-out only (guards R-A2 overfit).
- **Exclusions** — conflicting and single-submitter labels are excluded from the *scored* set; any
  label RAPTOR has influenced is excluded to prevent **circular validation** (R-A2).
- **Provenance** — every benchmark label records source + snapshot version + date (GP-9).
- **Size (v1) ≈ 50 variants** — *acknowledged limitation*: small and not fully representative; passing
  it is necessary, not sufficient. Expansion plan tracked as the benchmark grows.
- **Statistical operationalization:** record the train/dev vs held-out **split sizes** and the P/LP vs
  B/LB **class balance**; define a **minimum held-out count per class** below which precision/recall are
  reported as **descriptive only (non-gating), with confidence intervals** — not a pass/fail gate. A
  ~50-variant benchmark will often be below that minimum; each result must say so rather than imply
  significance. Variants the scorer cannot call are recorded as **no-call/abstain**, never forced.

## 3. Metrics (Tier-1/2)

| Metric | Definition | Reported on |
|---|---|---|
| **Precision / Recall** | Tier-1/2-implied LP/LB vs benchmark label | held-out set |
| **Concordance** | % agreement overall + separately for pathogenic-direction and benign-direction | held-out set |
| **Per-criterion accuracy** | where a criterion has a checkable truth (e.g. PM2 vs gnomAD absence) | full set — **diagnostic only, non-gating, never used for tuning** |
| **Determinism** | record-identical output on re-run of pinned inputs (R-A11) | every run |

**Pre-registered thresholds:** **not yet set.** They will be fixed *with the Oracle (GP-3) before
Tier-1/2 is trusted*, and recorded here. Per GP-9/H13 no target numbers are invented in advance — an
empty threshold is honest; a fabricated one is a defect.

### 3.1 "Tier-1/2-implied LP/LB" (eval-only)

For measurement only, criterion calls are combined into an **implied direction** — LP / LB / **no-call** —
by a deterministic rule (e.g. Tavtigian-2018 point/LR combination over the *automatable* criteria only).
This implied call is **non-authoritative**: it is used solely to compute AC1 metrics against benchmark
labels, and is **never shown as a classification, never crosses an external threshold, and never
substitutes for the human/oracle sign-off** (STRATEGY §9). Abstentions are first-class (no forced call).

### 3.2 Acceptance-criteria → metric / gate mapping (PRD-01)

| PRD-01 AC | Eval metric / check | OP-MODEL gate | Pass rule |
|---|---|---|---|
| AC1a | precision/recall/concordance on held-out (§3) | G4 | computed + reported, min-count rule (§2) applied |
| AC1b | same, vs Oracle thresholds | G4 | **BLOCKED** until thresholds pre-registered (GP-3) |
| AC2 | `source_ref` resolvable on 100% of records | G7 | 0 null/unresolvable |
| AC3 | determinism re-run diff (§4) | — | record-identical |
| AC4 | criterion-fires-≤once audit on canary (§4) | G3 | 0 double-counts |
| AC5 | edge-case fixtures route to manual (§4) | G5 | 0 silent auto-scores |
| AC6 | forbidden-path audit (§4) | G2 | no oracle/label read (manual audit until lint) |
| AC7 | config-schema / licensing tags / provenance / perf | G5/G7 | all checks pass |

### 3.3 Acceptance-criteria → check mapping (PRD-02 ingestion & normalization)

| PRD-02 AC | Check | OP-MODEL gate | Pass rule |
|---|---|---|---|
| AC1 | count reconciliation: input = normalized + manual-queue | G5 | 0 silent drops |
| AC2 | deterministic-content re-run diff (run metadata excluded) | — | content-identical |
| AC3 | frozen canary fixture: raw → expected `variant_id`/HGVS/SPDI | G3 | reproduces exactly |
| AC4 | `source_ref` pinned-snapshot-resolvable on 100% | G7 | 0 null/unresolvable |
| AC5 | forbidden-path audit | G2 | no oracle/label read (manual until lint) |
| AC6 | source-contract: real fixture passes, malformed fails loud | G5 | both hold |
| AC7 | config-schema / provenance / perf recorded | G5/G7 | checks pass; perf non-gating |

### 3.4 Acceptance-criteria → check mapping (PRD-03 KB schema & provenance ledger)

| PRD-03 AC | Check | OP-MODEL gate | Pass rule |
|---|---|---|---|
| AC1 | insert without valid `source_refs` FK (NULL or malformed) rejected | G7 | both rejected |
| AC2 | UPDATE/DELETE rejected on every history table; correction = new event | G1 | proven per table |
| AC3 | failed run → published-state hash = last-good; success = atomic | G5 | no partial state |
| AC4 | replay to watermark reconstructs v1.0→v1.1→v2.0 | G3 | each reconstructable |
| AC5 | storage determinism with pinned fixture rule | — | record-identical |
| AC6 | row missing a provenance field rejected | G7 | rejection proven |
| AC7 | Tier-3 evidence + cross-linkage stub rows insert, no migration | G3 | no schema change |
| AC8 | manual_queue conforms to PRD-02 FR6; scorer-includable row fails | G5 | both hold |
| AC9 | migrations + runtime contract verified; forbidden-path audit | G2/G5 | checks pass |

## 4. Protocol — how a run is evaluated

- **Label comparison** on the held-out set → the metrics in §3.
- **Oracle-blind checks** (do *not* use the label): internal consistency (e.g. a BA1-common variant
  must not also be scored PVS1-strong), allele-frequency sanity, criterion-firing sanity. Laundering
  the answer can't pass a check that never sees the answer (R-A2/H1).
- **Canary set** — a fixed set of known-answer variants run **every** pipeline; drift → halt + alert (R-C1).
- **No trace-cribbing** — the scorer never reads the benchmark/label files; the G2 forbidden-path check (interim: **checker-run manual audit** until the lint script exists — OPERATING_MODEL §10) (H1).
- **Determinism check** — re-run on pinned inputs must be record-identical (R-A11).

## 5. Reporting

- Results are written to **`BENCHMARK_RESULTS.md`** (planned), **versioned by benchmark snapshot +
  code version**, with a per-run **"what changed"** diff (turn-22 visibility requirement).
- A result is only citable if it states: benchmark version, held-out size, metric, and threshold
  status (met / not-met / threshold-not-yet-set).

## 6. Extensibility *(stubs — not yet built, GP-7)*

- **Tier-3 (PS3 extraction):** RAPTOR-specific PS3 benchmark required; **AcmGENTIC ~96% is a
  reference baseline, not a transferred target** (STRATEGY §8). Metric: extraction accuracy with the
  matching gate; per-premise citation-resolvability (GP-9).
- **Cross-linkage / gap-map:** **no gold standard exists** — evaluated as *cited, falsifiable
  hypotheses* only (GP-1/GP-2), reviewed by the Oracle; never scored as "discovery."

## 7. Honest limitations

- Ground truth is **proxy** (best-available), not gold — TSC has no 3★ panel.
- **Distribution shift — the deepest threat (R-A2c).** The known variants used for validation are
  enriched for **truncating/null** variants (easy PVS1 calls); the VUS deployment set is enriched for
  **missense** (the hard cases). Metrics on knowns can therefore **overestimate** real VUS
  performance. Mitigations: **stratify** metrics by variant class (report missense-only P/R
  separately), weight the benchmark toward missense where labels allow, and treat the *missense*
  held-out number — not the overall — as the gating metric.
- The v1 benchmark (~50) is **small**; a pass bounds risk, it does not prove generalisation.
- Thresholds are **unset** pending the Oracle; until then, every Tier-1/2 result is `UNVERIFIED`
  against a target (GP-9) and treated as provisional (RISK_REGISTER §9).
- **Predictor leakage/circularity:** CADD/REVEL/BIAS-2015 may have seen ClinVar labels in training;
  evaluating against ClinVar is partly circular. Track and, where possible, report on variants
  outside the predictors' training data.
