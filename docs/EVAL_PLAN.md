# RAPTOR — Evaluation Plan

> **Status:** DRAFT v0.1 · **Owner:** @sdrona_microsoft · **Last updated:** 2026-07-08 · **Review cadence:** per phase
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

## 3. Metrics (Tier-1/2)

| Metric | Definition | Reported on |
|---|---|---|
| **Precision / Recall** | Tier-1/2-implied LP/LB vs benchmark label | held-out set |
| **Concordance** | % agreement overall + separately for pathogenic-direction and benign-direction | held-out set |
| **Per-criterion accuracy** | where a criterion has a checkable truth (e.g. PM2 vs gnomAD absence) | full set |
| **Determinism** | record-identical output on re-run of pinned inputs (R-A11) | every run |

**Pre-registered thresholds:** **not yet set.** They will be fixed *with the Oracle (GP-3) before
Tier-1/2 is trusted*, and recorded here. Per GP-9/H13 no target numbers are invented in advance — an
empty threshold is honest; a fabricated one is a defect.

## 4. Protocol — how a run is evaluated

- **Label comparison** on the held-out set → the metrics in §3.
- **Oracle-blind checks** (do *not* use the label): internal consistency (e.g. a BA1-common variant
  must not also be scored PVS1-strong), allele-frequency sanity, criterion-firing sanity. Laundering
  the answer can't pass a check that never sees the answer (R-A2/H1).
- **Canary set** — a fixed set of known-answer variants run **every** pipeline; drift → halt + alert (R-C1).
- **No trace-cribbing** — the scorer never reads the benchmark/label files; enforced by the G2 lint (H1).
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
- The v1 benchmark (~50) is **small**; a pass bounds risk, it does not prove generalisation.
- Thresholds are **unset** pending the Oracle; until then, every Tier-1/2 result is `UNVERIFIED`
  against a target (GP-9) and treated as provisional (RISK_REGISTER §9).
