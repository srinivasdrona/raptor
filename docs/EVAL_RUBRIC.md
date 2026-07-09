# RAPTOR Eval Rubric — Pre-Registration Thresholds (TSC1/TSC2)

> **Status:** RECOMMENDATION for adoption · **Owner:** @dronasrinivas · **Last updated:** 2026-07-09
> **Basis:** cited evidence base in [`reference/eval-rubric-evidence-base.md`](reference/eval-rubric-evidence-base.md);
> benchmark composition from the pinned ClinVar snapshot (§3). This document is the
> **pre-registered** go/no-go rubric the eval gate (PRD-06) checks before any VUS run.

## 0. What this is (and the one rule that governs it)

RAPTOR must clear a **pre-registered** performance bar on a held-out set of KNOWN TSC1/TSC2
variants before it may classify the ~6,700 TSC VUS (STRATEGY H/EVAL_PLAN §1.1). "Pre-registered"
is load-bearing: the thresholds here are fixed **blind to held-out results** (R-A2 — thresholds are
never fit to the test set). They may be informed by the literature and by the benchmark's
**composition** (how many knowns per stratum — that is design, not fitting), never by its outcomes.

Only the **ACMG/AMP 2015 five-tier standard** (P/LP/VUS/LB/B) is used; nothing is invented.

## 1. The thresholds (adopt these)

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
| **All strata** | Min held-out count per class (else `UNDERPOWERED`) | **≥ 35** | — |

**Why 0.90, not 0.99, for the primary bar.** ACMG/AMP 2015 (Richards) *defines* Likely Pathogenic as
**>90%** posterior probability and Pathogenic as **>99%** — these are definitional, not invented
(Pejaver 2022 calibrated the same). A **0.99 lower-bound claim is statistically indefensible on any
realistic TSC benchmark**: a 95%-CI lower bound of 0.99 requires **≥367 clean calls per stratum with
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

## 2. Statistical power (why these numbers, not higher)

Minimum held-out calls **n** in a stratum to support a precision **lower bound** at 95% CI
(Clopper-Pearson; FDA diagnostic-test guidance):

| Target lower bound | 0 errors | ≤1 error | ≤2 errors |
|---|---|---|---|
| ≥ 0.90 | n ≥ 35 | n ≥ 53 | n ≥ 90 |
| ≥ 0.95 | n ≥ 72 | n ≥ 109 | n ≥ 175 |
| ≥ 0.99 | n ≥ 367 | n ≥ 555 | n ≥ 880 |

**Mandatory disclosure (pre-registered):** we report the **point estimate + 95% CI** for every
stratum/direction; a stratum below the min-count is `UNDERPOWERED` (descriptive-only, never gating —
PRD-06 FR5). We do **not** pre-register a pass/fail bar a stratum cannot statistically support.

## 3. Benchmark composition — the pinned snapshot (informs powering, blind to results)

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

### 3a. Power verdict (after adopting holdout 0.7 — see §3b)

- **Missense-pathogenic is now POWERED for 0.90:** at holdout **0.7** the gating stratum holds **51**
  held-out pathogenic missense (≥ the `min_count` 35, and ≥ the 35 needed for a **0-error 0.90**
  lower bound). It is *tight* — a single false call would need n ≥ 53 — and **0.95 stays out of
  reach** (needs 72 with 0 errors; the whole benchmark holds only 75 pathogenic missense). So the
  gate can honestly validate missense to the **ACMG-minimum 0.90**, not 0.95.
- **Truncating is robustly powered:** 210 held-out pathogenic → supports the **0.95** lower bound
  (needs ≥72 with 0 errors). Truncating classification can be validated to standard.
- **Benign direction is massively powered** (2,199 held-out) in missense/other; supports ≥0.95.
- **Truncating-benign cannot be validated** (n=1) — expected biology (benign LoF in a tumor
  suppressor is rare); report-only, never gated.

### 3b. Decision (adopted — governance)

**Adopted: option (1) now + option (2) as the path to 0.95.**

1. **✅ ADOPTED — held-out raised 0.3 → 0.7.** RAPTOR Tier-1/2 is a *deterministic* rule engine — it
   learns nothing from the benchmark, so there is no over-fitting to protect against; anti-circularity
   is preserved purely by pre-registering thresholds blind. The larger held-out puts **51**
   missense-pathogenic in the exam → **powers the 0.90 missense bar** with zero downside — the 30%
   remainder is only a development/sanity reserve, **not** a training set a rule engine could be
   starved of. `min_count_per_class` raised to **35** to match the 0.90 power floor.
2. **Future path to 0.95 — broaden known-pathogenic-missense sources.** Add the TSC1/TSC2 VCEP curated
   set (Symonds 2022), functional-assay-backed missense, and LOVD/TSC databases to raise N past 72.
   *The real path to robust (≥0.95) missense validation; a curation extension to Track A — tracked,
   not blocking the first run.*
3. **Not needed for missense (now powered);** truncating is hard-gated at 0.95 (already powered, 210
   held-out) once the per-stratum config extension lands (§5).

## 4. Pinned snapshot provenance (R-A11)

| Pin | Value |
|---|---|
| Source | ClinVar `variant_summary.txt.gz` (NCBI FTP, tab_delimited) |
| Snapshot date | **2026-07-07** (current weekly release at pin time) |
| NCBI-published md5 | `bd3720834b62733a6a1c81d7e1eef941` (verified on download) |
| sha256 (internal pin) | `5fe4fe10783391d01dc414dc5583a3e63487b67f8cd3c8429d59227cd5f4f37f` |
| labels_snapshot id | `clinvar_2026-07-07` |

## 5. How this maps to the gate (PRD-06) and what to pre-register

- **Pre-registered (DONE):** `configs/eval/tsc2.yaml` `oracle_thresholds: {precision: 0.90, recall:
  0.85}` committed **blind to held-out results** (no BIAS/Nirvana scores exist yet — Track B unrun).
  The gate applies each to BOTH directions and gates on the missense stratum (PRD-06 FR6/AC5);
  `min_count_per_class: 35`, `split.holdout_fraction: 0.7`. Changing these post-hoc breaks
  pre-registration (R-A2).
- The **truncating** ≥0.95 target is **reported** in the eval output today; hard-gating it as a
  second stratum needs a small PRD-06 config extension (per-stratum `oracle_thresholds`) — tracked as
  a follow-up, not required for the first authorized run (missense is the binding constraint).
- **Adoption is a human act (DONE):** @dronasrinivas (acting domain owner) adopted + committed the
  pinned thresholds, blind to held-out results. This doc + the cited evidence base are the
  justification of record.

## 6. Open items
- ✅ **Post-split held-out N per stratum** appended (§3 — from the holdout-0.7 freeze).
- ✅ **Thresholds pre-registered** into `configs/eval/tsc2.yaml` (§5).
- The gate currently checks the **point-estimate** precision/recall against the threshold, not the
  95% CI **lower bound** this rubric frames; `min_count_per_class: 35` is the underpowered floor that
  approximates it. Making the gate compute the Clopper-Pearson lower bound is a tracked PRD-06
  fidelity follow-up.
- Confirm against the **TSC1/TSC2 VCEP specification** (Symonds 2022, *Genet Med* 24:1907) — the
  disease-specific gold standard; our high-confidence tier already privileges its 3-star calls.
- Hard-gate the truncating stratum at 0.95 (needs the PRD-06 per-stratum config extension).
