# RAPTOR — Evaluation

> **Status:** canonical consolidated evaluation authority doc · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (merged the legacy evaluation plan + rubric authority; retains ADR-0013 post-hoc/prospective lock) · **Review cadence:** per phase
>
> **Authority split inside this file:** **Part I — Evaluation protocol** governs purpose, benchmark construction, methodology, metrics, reporting, and limitations (*what is measured and how*). **Part II — Pre-registered acceptance rubric** governs thresholds, power, benchmark composition/pins, gate semantics, and authorization posture (*what counts as enough*).

---

## Authority & navigation

| Need | Canonical section | Maintained authority |
|---|---|---|
| Purpose, benchmark protocol, metrics, PRD mappings, reporting, limitations | [Part I — Evaluation protocol](#evaluation-part-i) | Evaluation methodology |
| The binding validation sequence | [Part I §1.1 — The validation gate](#evaluation-validation-gate) | Protocol authority |
| Pre-registered thresholds and power math | [Part II §1 — The thresholds](#evaluation-thresholds) and [Part II §2 — Statistical power](#evaluation-statistical-power) | Acceptance authority |
| Frozen benchmark composition and provenance pins | [Part II §3 — Benchmark composition](#evaluation-benchmark-composition) and [Part II §4 — Pinned snapshot provenance](#evaluation-snapshot-provenance) | Snapshot authority |
| Scope authorization, v2/v3 governance, prospective lock | [Part II §5b](#evaluation-v2-scope-authorization) and [Part II §7](#evaluation-rubric-v3) | Authorization authority |
| Related build governance | [STRATEGY.md Part II](STRATEGY.md#strategy-part-ii) | Gates / process |

## Table of contents

- [Part I — Evaluation protocol](#evaluation-part-i)
- [Part II — Pre-registered acceptance rubric](#evaluation-part-ii)

<a id="evaluation-part-i"></a>
## Part I — Evaluation protocol

> **Part I status:** DRAFT v0.1 · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (merged into the canonical evaluation authority doc) · **Review cadence:** per phase
>
> **Part I scope now:** the **frozen benchmark** + **Tier-1/2** metrics (PRD-01). Extensible to Tier-3 and cross-linkage (§6) — those sections remain stubs until those tiers exist (GP-7: don't spec what isn't built).
>
> **Part I method discipline:** pre-registered thresholds, a **held-out** test set never used for tuning, and **oracle-blind** checks alongside label comparison. Every acceptance criterion in a PRD resolves to a metric here; every build gate in STRATEGY Part II §4 that says "meets threshold" points here.

<a id="evaluation-objective"></a>
### 1. Objective

Quantify how well the deterministic layer (Tier-1/2) reproduces **best-available** variant labels,
establish the **frozen baseline** the harder tiers are measured against, and **gate** Tier-3 trust:
no Tier-3 value is claimed until Tier-1/2 clears its thresholds on the held-out set.

<a id="evaluation-validation-gate"></a>
#### 1.1 The validation gate — measured on KNOWNS, then applied to VUS *(binding sequence)*

**You cannot measure metrics on VUS** — a VUS has no ground-truth label. Validation is therefore done
on **known-classification** variants and only *then* applied to the unknowns:

```
KNOWN TSC1/TSC2 variants (P/LP + B/LB, high review status)   ← the answer key
        │  split (no leakage)
        ├─ train/dev  → calibrate config thresholds (per-gene freq, PP3/BP4 cutoffs)
        └─ held-out   → MEASURE precision / recall / concordance (thresholds frozen)
                          │
                   metrics clear pre-registered thresholds? (AC1b)
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

<a id="evaluation-known-set-scope"></a>
#### 1.2 Known-set scope — TSC2-first; extend for *power*, not for a better number

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
the fix is the **scorer/calibration**, not more genes. **Current pinned state:** the maintained benchmark
and rubric in Part II are now TSC1/TSC2-wide; this TSC2-first reasoning is preserved as the
anti-gerrymandering rule that widening is for power, never for a cosmetically better number.

<a id="evaluation-v3-posthoc-prospective"></a>
#### 1.3 Tiered v3 post-hoc re-adjudication and prospective registration (ADR-0013)

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

**Prospective outcome (2026-08-06):** `BLOCKED_DATA`. The exact frozen August URL returned HTTP
404. A same-named file existed at a different archive-root URL, but the locked contract forbids
substitution. No archive bytes, labels, rows, hashes or scores were accessed. See
[`data/census/tsc_prospective_validation_2026-08_blocked_data.json`](../data/census/tsc_prospective_validation_2026-08_blocked_data.json).

<a id="evaluation-benchmark"></a>
### 2. The frozen benchmark (ground truth — honestly, *proxy* labels)

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
- **Pinned current benchmark size** — see [Part II §3](#evaluation-benchmark-composition): **3,681** scoreable knowns after exclusions, with **2,577** held out from `clinvar_2026-07-07` under the frozen 0.7 hold-out split.
- **Historical provenance note:** an earlier draft protocol discussed a ~50-variant v1 benchmark; that draft state is superseded by the pinned snapshot above and is retained only as provenance for how the protocol evolved.
- **Statistical operationalization:** record the train/dev vs held-out **split sizes** and the P/LP vs
  B/LB **class balance**; define a **minimum held-out count per class** below which precision/recall are
  reported as **descriptive only (non-gating), with confidence intervals** — not a pass/fail gate. A
  small or sparse stratum can still fall below that minimum; each result must say so rather than imply
  significance. Variants the scorer cannot call are recorded as **no-call/abstain**, never forced.

<a id="evaluation-metrics"></a>
### 3. Metrics (Tier-1/2)

| Metric | Definition | Reported on |
|---|---|---|
| **Precision / Recall** | Tier-1/2-implied LP/LB vs benchmark label | held-out set |
| **Concordance** | % agreement overall + separately for pathogenic-direction and benign-direction | held-out set |
| **Per-criterion accuracy** | where a criterion has a checkable truth (e.g. PM2 vs gnomAD absence) | full set — **diagnostic only, non-gating, never used for tuning** |
| **Determinism** | record-identical output on re-run of pinned inputs (R-A11) | every run |

**Pre-registered thresholds:** adopted blind to held-out results and maintained in [Part II §1](#evaluation-thresholds) with the exact power and gate semantics in [Part II §2](#evaluation-statistical-power) and [Part II §5](#evaluation-gate-mapping). The protocol consumes those thresholds; it does not invent, fit, or relax them post hoc (GP-9/H13).

<a id="evaluation-implied-lplb"></a>
#### 3.1 "Tier-1/2-implied LP/LB" (eval-only)

For measurement only, criterion calls are combined into an **implied direction** — LP / LB / **no-call** —
by a deterministic rule (e.g. Tavtigian-2018 point/LR combination over the *automatable* criteria only).
This implied call is **non-authoritative**: it is used solely to compute AC1 metrics against benchmark
labels, and is **never shown as a classification, never crosses an external threshold, and never
substitutes for the human/oracle sign-off** (STRATEGY Part I §9). Abstentions are first-class (no forced call).

<a id="evaluation-prd01-map"></a>
#### 3.2 Acceptance-criteria → metric / gate mapping (PRD-01)

| PRD-01 AC | Eval metric / check | OP-MODEL gate | Pass rule |
|---|---|---|---|
| AC1a | precision/recall/concordance on held-out (§3) | G4 | computed + reported, min-count rule (§2) applied |
| AC1b | same, vs the pre-registered Part II §1 thresholds | G4 | exact 95% lower-bound gate + coverage semantics applied per Part II §2/§5 |
| AC2 | `source_ref` resolvable on 100% of records | G7 | 0 null/unresolvable |
| AC3 | determinism re-run diff (§4) | — | record-identical |
| AC4 | criterion-fires-≤once audit on canary (§4) | G3 | 0 double-counts |
| AC5 | edge-case fixtures route to manual (§4) | G5 | 0 silent auto-scores |
| AC6 | forbidden-path audit (§4) | G2 | no oracle/label read (manual audit until lint) |
| AC7 | config-schema / licensing tags / provenance / perf | G5/G7 | all checks pass |

<a id="evaluation-prd02-map"></a>
#### 3.3 Acceptance-criteria → check mapping (PRD-02 ingestion & normalization)

| PRD-02 AC | Check | OP-MODEL gate | Pass rule |
|---|---|---|---|
| AC1 | count reconciliation: input = normalized + manual-queue | G5 | 0 silent drops |
| AC2 | deterministic-content re-run diff (run metadata excluded) | — | content-identical |
| AC3 | frozen canary fixture: raw → expected `variant_id`/HGVS/SPDI | G3 | reproduces exactly |
| AC4 | `source_ref` pinned-snapshot-resolvable on 100% | G7 | 0 null/unresolvable |
| AC5 | forbidden-path audit | G2 | no oracle/label read (manual until lint) |
| AC6 | source-contract: real fixture passes, malformed fails loud | G5 | both hold |
| AC7 | config-schema / provenance / perf recorded | G5/G7 | checks pass; perf non-gating |

<a id="evaluation-prd03-map"></a>
#### 3.4 Acceptance-criteria → check mapping (PRD-03 KB schema & provenance ledger)

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

<a id="evaluation-protocol-run"></a>
### 4. Protocol — how a run is evaluated

- **Label comparison** on the held-out set → the metrics in §3.
- **Oracle-blind checks** (do *not* use the label): internal consistency (e.g. a BA1-common variant
  must not also be scored PVS1-strong), allele-frequency sanity, criterion-firing sanity. Laundering
  the answer can't pass a check that never sees the answer (R-A2/H1).
- **Canary set** — a fixed set of known-answer variants run **every** pipeline; drift → halt + alert (R-C1).
- **No trace-cribbing** — the scorer never reads the benchmark/label files; the G2 forbidden-path check (interim: **checker-run manual audit** until the lint script exists — STRATEGY Part II §10) (H1).
- **Determinism check** — re-run on pinned inputs must be record-identical (R-A11).

<a id="evaluation-reporting"></a>
### 5. Reporting

- Results are written to **`BENCHMARK_RESULTS.md`** (planned), **versioned by benchmark snapshot +
  code version**, with a per-run **"what changed"** diff (turn-22 visibility requirement).
- A result is only citable if it states: benchmark version, held-out size, metric, and threshold /
  authorization status (met / not-met / underpowered / not-estimable / threshold-not-yet-set, as
  applicable).

<a id="evaluation-extensibility"></a>
### 6. Extensibility *(stubs — not yet built, GP-7)*

- **Tier-3 (PS3 extraction):** RAPTOR-specific PS3 benchmark required; **AcmGENTIC ~96% is a
  reference baseline, not a transferred target** (STRATEGY Part I §8). Metric: extraction accuracy with the
  matching gate; per-premise citation-resolvability (GP-9).
- **Cross-linkage / gap-map:** **no gold standard exists** — evaluated as *cited, falsifiable
  hypotheses* only (GP-1/GP-2), reviewed by the Oracle; never scored as "discovery."

<a id="evaluation-limitations"></a>
### 7. Honest limitations

- Ground truth is **proxy** (best-available), not gold — TSC has no 3★ panel.
- **Distribution shift — the deepest threat (R-A2c).** The known variants used for validation are
  enriched for **truncating/null** variants (easy PVS1 calls); the VUS deployment set is enriched for
  **missense** (the hard cases). Metrics on knowns can therefore **overestimate** real VUS
  performance. Mitigations: **stratify** metrics by variant class (report missense-only P/R
  separately), weight the benchmark toward missense where labels allow, and treat the *missense*
  held-out number — not the overall — as the gating metric.
- The current frozen benchmark is materially larger than the early ~50-variant draft, but important strata can still be sparse or underpowered; a pass bounds risk, it does not prove generalisation. The exact pinned composition and power limits live in Part II §3/§7.
- Thresholds are now **pre-registered**, but any stratum or scope that remains `UNDERPOWERED`,
  `NO_CALLS`, `NOT_ESTIMABLE`, `BLOCKED_POLICY`, `PENDING_PROSPECTIVE`, or `NOT_AUTHORIZED` is still
  non-authoritative until its registered gate is actually met on eligible unseen data (Part II §5b/§7;
  RISK_REGISTER §9).
- **Predictor leakage/circularity:** CADD/REVEL/BIAS-2015 may have seen ClinVar labels in training;
  evaluating against ClinVar is partly circular. Track and, where possible, report on variants
  outside the predictors' training data.

<a id="evaluation-part-ii"></a>
## Part II — Pre-registered acceptance rubric

> **Part II status:** adopted blind to held-out results · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (merged into the canonical evaluation authority doc; includes ADR-0013 cross-reference)
>
> **Part II basis:** cited evidence base in [`reference/eval-rubric-evidence-base.md`](reference/eval-rubric-evidence-base.md); benchmark composition from the pinned ClinVar snapshot (§3). This section is the **pre-registered** go/no-go rubric the eval gate (PRD-06) checks before any VUS run.

<a id="evaluation-rubric-overview"></a>
### 0. What this is (and the one rule that governs it)

RAPTOR must clear a **pre-registered** performance bar on a held-out set of KNOWN TSC1/TSC2
variants before it may classify the ~6,700 TSC VUS (STRATEGY Part I §8 and [Part I §1.1](#evaluation-validation-gate)). "Pre-registered"
is load-bearing: the thresholds here are fixed **blind to held-out results** (R-A2 — thresholds are
never fit to the test set). They may be informed by the literature and by the benchmark's
**composition** (how many knowns per stratum — that is design, not fitting), never by its outcomes.

Only the **ACMG/AMP 2015 five-tier standard** (P/LP/VUS/LB/B) is used; nothing is invented.

<a id="evaluation-thresholds"></a>
### 1. The thresholds (adopt these)

The gate authorizes a VUS run **only** when the **missense** held-out stratum (the hardest, and the
R-A2c distribution-shift concern PRD-06 gates on) clears, in **both directions**, at the 95%
Clopper-Pearson **lower confidence bound**:

| Stratum | Metric | Pre-registered threshold (95% CI lower bound) | Powered by our benchmark? |
|---|---|---|---|
| **Missense** (gating) | Precision — pathogenic direction | **≥ 0.90** | yes (see §3) |
| **Missense** (gating) | Precision — benign direction | **≥ 0.90** | yes (benign n≈3,100) |
| **Missense** (gating) | Recall — pathogenic direction | **≥ 0.85** | yes |
| **Missense** (gating) | Recall — benign direction | **≥ 0.85** | yes |
| **Truncating** (secondary/reported) | Precision — both directions | **≥ 0.95** | pathogenic yes (n≈325); benign **no** (n≈1) |
| **Truncating** (secondary/reported) | Recall — pathogenic direction | **≥ 0.95** | yes |
| **All strata** | Min held-out count per class (else `UNDERPOWERED`) | **≥ 36** | — |

**Why 0.90, not 0.99, for the primary bar.** ACMG/AMP 2015 (Richards) *defines* Likely Pathogenic as
**>90%** posterior probability and Pathogenic as **>99%** — these are definitional, not invented
(Pejaver 2022 calibrated the same). A **0.99 lower-bound claim is statistically indefensible on any
realistic TSC benchmark**: a 95%-CI lower bound of 0.99 requires **≥368 clean calls per stratum with
zero errors** (§2). 0.90 is the minimum consistent with the LP definition and is comfortably powered.
IARC (Plon 2008) sets LP at **0.95** — stricter; adopted here for the **truncating** stratum where we
have the N to support it.

**Why asymmetric recall (missense 0.85, truncating 0.95).** Truncating/LoF variants carry PVS1 (Very
Strong) and are algorithmically near-deterministic in a tumor-suppressor pair like TSC1/TSC2;
missense can only reach LP by accumulating Supporting-strength lines and is structurally harder.
Published tools show the same gap: InterVar sensitivity **94.7% truncating vs 85.4% missense**
(Li 2017); CardioClassifier's only discordances were missense (Whiffin 2018). Demanding ≥0.95 recall
on missense would force over-calling and inflate false positives. Precision is held symmetric at
≥0.90 both directions because in **highly-penetrant TSC** a false "likely benign" (missed, treatable
diagnosis) is as harmful as a false "likely pathogenic" (lifelong surveillance + mTOR-inhibitor
exposure) — see evidence base §4.

<a id="evaluation-statistical-power"></a>
### 2. Statistical power (why these numbers, not higher)

Minimum held-out calls **n** in a stratum to support a precision **lower bound** at 95% CI
(Clopper-Pearson; FDA diagnostic-test guidance):

| Target lower bound | 0 errors | ≤1 error | ≤2 errors |
|---|---|---|---|
| ≥ 0.90 | n ≥ 36 | n ≥ 54 | n ≥ 70 |
| ≥ 0.95 | n ≥ 72 | n ≥ 110 | n ≥ 142 |
| ≥ 0.99 | n ≥ 368 | n ≥ 555 | n ≥ 720 |

**Mandatory disclosure (pre-registered):** we report the **point estimate + 95% CI** for every
stratum/direction; a stratum below the min-count is `UNDERPOWERED` (descriptive-only, never gating —
PRD-06 FR5). We do **not** pre-register a pass/fail bar a stratum cannot statistically support.

<a id="evaluation-benchmark-composition"></a>
### 3. Benchmark composition — the pinned snapshot (informs powering, blind to results)

Frozen from the pinned ClinVar snapshot (§4) via `scripts/build_tsc_benchmark.py` (deterministic;
real genomic-SPDI normalizer for the identity join; PRD-07 label/class/review mapping + PRD-06
exclusions + label hierarchy; seed `20260701`, holdout `0.7`). **These are actual frozen counts, not
estimates** — knowing them is design-time information (composition), blind to how the model performs.

**Benchmark (3,681 scoreable knowns after exclusions) → held-out (2,577):**

| Held-out stratum | Pathogenic (P/LP) | Benign (B/LB) |
|---|---|---|
| **Missense** (gating, R-A2c) | **51** | 103 |
| **Truncating** | 210 | 1 |
| Other (splice / synonymous / in-frame / no-`p.`) | 117 | 2,095 |
| **All** | 378 | 2,199 |

(Full benchmark, pre-split: missense P/LP = **75**, missense B/LB = 152, truncating P/LP = **319**,
truncating B = 1, other P/LP = 171, other B/LB = 2,963.)

<a id="evaluation-power-verdict"></a>
#### 3a. Power verdict (after adopting holdout 0.7 — see §3b)

- **Missense-pathogenic is now POWERED for 0.90:** at holdout **0.7** the gating stratum holds **51**
  held-out pathogenic missense (≥ the `min_count` 36, and ≥ the 36 needed for a **0-error 0.90**
  lower bound). It is *tight* — a single false call would need n ≥ 54 — and **0.95 stays out of
  reach** (needs 72 with 0 errors; the whole benchmark holds only 75 pathogenic missense). So the
  gate can honestly validate missense to the **ACMG-minimum 0.90**, not 0.95.
- **Truncating is robustly powered:** 210 held-out pathogenic → supports the **0.95** lower bound
  (needs ≥72 with 0 errors). Truncating classification can be validated to standard.
- **Benign direction is massively powered** (2,199 held-out) in missense/other; supports ≥0.95.
- **Truncating-benign cannot be validated** (n=1) — expected biology (benign LoF in a tumor
  suppressor is rare); report-only, never gated.

<a id="evaluation-governance-decision"></a>
#### 3b. Decision (adopted — governance)

**Adopted: option (1) now + option (2) as the path to 0.95.**

1. **✅ ADOPTED — held-out raised 0.3 → 0.7.** RAPTOR Tier-1/2 is a *deterministic* rule engine — it
   learns nothing from the benchmark, so there is no over-fitting to protect against; anti-circularity
   is preserved purely by pre-registering thresholds blind. The larger held-out puts **51**
   missense-pathogenic in the exam → **powers the 0.90 missense bar** with zero downside — the 30%
   remainder is only a development/sanity reserve, **not** a training set a rule engine could be
   starved of. `min_count_per_class` raised to **36** to match the 0.90 power floor.
2. **Future path to 0.95 — broaden known-pathogenic-missense sources.** Add the TSC1/TSC2 VCEP curated
   set (Symonds 2022), functional-assay-backed missense, and LOVD/TSC databases to raise N past 72.
   *The real path to robust (≥0.95) missense validation; a curation extension to Track A — tracked,
   not blocking the first run.*
3. **Not needed for missense (now powered);** truncating is hard-gated at 0.95 (already powered, 210
   held-out) once the per-stratum config extension lands (§5).

<a id="evaluation-snapshot-provenance"></a>
### 4. Pinned snapshot provenance (R-A11)

| Pin | Value |
|---|---|
| Source | ClinVar `variant_summary.txt.gz` (NCBI FTP, tab_delimited) |
| Snapshot date | **2026-07-07** (current weekly release at pin time) |
| NCBI-published md5 | `bd3720834b62733a6a1c81d7e1eef941` (verified on download) |
| sha256 (internal pin) | `5fe4fe10783391d01dc414dc5583a3e63487b67f8cd3c8429d59227cd5f4f37f` |
| labels_snapshot id | `clinvar_2026-07-07` |

<a id="evaluation-gate-mapping"></a>
### 5. How this maps to the gate (PRD-06) and what to pre-register

- **Pre-registered (DONE):** `configs/eval/tsc2.yaml` carries nested, per-stratum
  `oracle_thresholds` at 95% confidence: missense precision ≥0.90 and recall ≥0.85 for both
  pathogenic and benign directions; truncating precision/recall ≥0.95 for the pathogenic direction
  (truncating-benign remains report-only). The thresholds were adopted blind to held-out metrics.
  The gate uses exact Clopper-Pearson lower bounds and `min_count_per_class: 36`; the floor correction
  from 35 is mathematical (`LB(35/35)=0.899967<0.90`, `LB(36/36)>0.90`), not performance tuning.
  `split.holdout_fraction: 0.7` remains unchanged. Changing policy thresholds post-hoc breaks
  pre-registration (R-A2).
- **Adoption is a human act (DONE):** @dronasrinivas (acting domain owner) adopted + committed the
  pinned thresholds, blind to held-out results. This doc + the cited evidence base are the
  justification of record.

<a id="evaluation-v2-scope-authorization"></a>
#### 5b. v2 scope-specific authorization (preregistered 2026-07-14, before the corrected rerun)

- **What this is NOT:** a threshold change. Every value in §1/§5 above (missense 0.90/0.85,
  truncating 0.95/0.95, both at 95% confidence, `min_count_per_class: 36`) is unchanged and remains
  locked (`config._PINNED_STRATUM_THRESHOLDS`). §5 above already preregistered *separate reporting*
  (stratify, don't pool) — this subsection preregisters a *separate authorization rule*, which v1 never
  had (`gate.py` hardcodes `missense` as the sole binding/authorizing stratum).
- **The new rule (`configs/eval/tsc2.yaml` → `scope_authorization`, schema_version 2,
  `raptor.eval.scope_gate.decide_scope_gate`):** every `(stratum, direction)` scope is evaluated
  independently (no short-circuit); a scope is `VALIDATED` only when its registered threshold is `MET`
  on the 95% CI lower bound **and** held-out coverage is adequate. Full-spectrum VUS authorization still
  requires `missense:pathogenic`, `missense:benign`, **and** `truncating:pathogenic` all `VALIDATED`
  (semantics-locked, anti-cherry-pick — this cannot be narrowed to drop missense). Independently, a
  narrow `truncating_pathogenic_research_scope_validated` flag can be `True` on `truncating:pathogenic`
  alone — a research-only claim, never full-spectrum, never clinical.
- **Governance text is exact and separate from the disclaimer:** the truncating-only state emits the
  verbatim statement *"Full-spectrum VUS automation is not authorized. Evidence supports only the
  validated truncating-pathogenic scope; missense remains unvalidated."* A separate, mandatory,
  non-blank `research_use_disclaimer` — *"Research-evidence validation only; this authorizes no
  clinical classification, VUS worklist, or ClinVar submission."* — is never merged into that statement.
- **Known-outcome risk, acknowledged, not hidden:** the 2026-07-13 v1 run already showed
  truncating-pathogenic clearing 0.95/0.95 at adequate coverage before this rule was written, so this
  preregistration is **not** blind to that outcome (see ADR-0011 for the full risk discussion and its
  mitigations — no threshold changed, the rule only narrows scope, full-spectrum still requires
  missense, and validation must be re-established on a corrected rerun). This subsection records the
  rule, not a result: no PASS/VALIDATED claim is made here, and the 2026-07-13 v1 artifact is never
  relabeled (`schema=v1` stays `v1`; no v2 keys are added to it).
- **Versioned, not in-place:** a new `raptor.tsc.masked_holdout_gate.v2` schema/aggregate coexists with
  the frozen `...v1` one; `EvalReport.scope_gate` is optional/additive and excluded from `content_hash()`
  when absent, so v1 report hashes are unaffected.

<a id="evaluation-open-items"></a>
### 6. Open items
- ✅ **Post-split held-out N per stratum** appended (§3 — from the holdout-0.7 freeze).
- ✅ **Thresholds pre-registered** into `configs/eval/tsc2.yaml` (§5).
- ✅ **Gate fidelity implemented:** exact 95% Clopper-Pearson lower bounds, per-direction coverage,
  and nested per-stratum thresholds. A powered configured direction is evaluated even when an
  unrelated report-only direction is sparse.
- Confirm against the **TSC1/TSC2 VCEP specification** (Symonds 2022, *Genet Med* 24:1907) — the
  disease-specific gold standard; our high-confidence tier already privileges its 3-star calls.
- ✅ **Truncating-pathogenic hard gate implemented** at 0.95; truncating-benign remains report-only.
- ✅ **Scope-specific v2 authorization preregistered** (§5b, ADR-0011) — before the corrected rerun,
  not after. Requires a corrected rerun before any real VALIDATED/authorization claim.

<a id="evaluation-rubric-v3"></a>
### 7. Tiered v3 post-hoc axes and prospective registration (ADR-0013)

The corrected rerun referenced in §5b/§6 (R2, ADR-0012) executed and is **frozen**: v1's coarse
missense `FAIL` and v2's `full_spectrum_status=BLOCKED_POLICY`/`vus_authorized=false` are unchanged
and immutable. **None of the thresholds in §1/§5 changed** — missense 0.90/0.85, truncating
0.95/0.95, both at 95% confidence, `min_count_per_class: 36` remain exactly as pre-registered.

What changed is *how the frozen result is reported*. v1/v2 collapsed insufficient-data, failed
metrics, and policy exclusions into one `FAIL`/`BLOCKED_POLICY` value. **Tiered gate v3**
(`raptor.eval.tiered_gate.decide_tiered_gate`, config `configs/eval/tiered_gate_v3.yaml`, record
`data/census/tsc_tiered_readjudication_2026-07-21.json`) re-reports the same frozen numbers as
independent axes — run integrity, data sufficiency, conditional performance, policy parity,
correct-call coverage, scope evidence, and authorization — so that "51 pathogenic missense examples,
zero calls" (`NO_CALLS`) is distinguishable from "103 benign missense examples, 9 calls all correct,
below the powered floor" (`UNDERPOWERED`), and both are distinguishable from
`truncating:pathogenic`'s 210 actual / 189 called clearing 0.9807/0.9807 against the pre-registered
0.95/0.95 (`ADEQUATE`+`MET`, evidence `SUPPORTED_POSTHOC`). PM1 is scoped to apply only to
`missense:pathogenic`, correcting the v1/v2 defect where a missense-only exclusion read as blocking
the unrelated truncating scope.

**This is not a new pass/fail bar and not a validation.** v3 performs no new run, scoring,
annotation, benchmark read, network access, or data generation (see `no_new_evidence_statement` in
the record above), and every scope's `authorization_status` is `NOT_AUTHORIZED` or
`PENDING_PROSPECTIVE` — never `AUTHORIZED`.

**Prospective registration (pre-registered here, before any result exists):** the next real
evaluation of any v3 scope — including `truncating:pathogenic`, the only scope with
`SUPPORTED_POSTHOC` evidence — must run against the first eligible NCBI ClinVar GRCh38
`variant_summary` monthly archive dated on/after 2026-08-01, with its URL/official date/MD5/SHA-256
frozen *before* labels or scoring. Unavailable/invalid data yields `BLOCKED_DATA`, not an
outcome-dependent substitute. Until that run completes and clears the unchanged §1 thresholds on
unseen data, `research_scope_flags.truncating_pathogenic_research_scope_validated` remains `false`
and no scope is authorized.

That contract resolved to `BLOCKED_DATA` on 2026-08-06: the exact preregistered URL returned 404,
and the same filename at a different URL was not substituted. No archive content or labels were
downloaded.
