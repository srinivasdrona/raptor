# PRD-06 — Benchmark & Evaluation Harness

> **Status:** Ready (v1 increment — build contract §10) · **Owner:** @sdrona_microsoft · **Phase:** 1 (STRATEGY §7) · **Last updated:** 2026-07-09
>
> **Format:** standard lean PRD; acceptance criteria feed the build-loop gates (OPERATING_MODEL §4) and
> are the mechanical realization of EVAL_PLAN (this PRD *builds* what EVAL_PLAN specifies).
>
> **Links:** EVAL_PLAN §1.1/§2/§3/§4/§7 (the methodology this implements) · STRATEGY §9 (human/oracle
> sign-off) · GP-2, GP-3, GP-7, GP-9 · RISK_REGISTER R-A2/R-A2c/R-E1, H1/H13 (eval-integrity) · PRD-01
> (produces the criterion calls scored here) · PRD-03 (KB the evidence is read from).

## 1. Context / problem

RAPTOR must **not** classify the ~6,700 TSC VUS until Tier-1/2 is shown to reproduce **known**
classifications on a held-out set (EVAL_PLAN §1.1 — the binding validation gate). That measurement is a
buildable module: construct a frozen benchmark of known variants, combine the scorer's criterion calls
into an eval-only implied direction, compute class-stratified metrics, and **gate** the VUS run on the
result. Today there is no such harness, so "are we good enough to run?" has no auditable answer.

This is the **gate that stands between the scorer and the 6,700 VUS.** It is also the module most
exposed to **eval-integrity failure** (category H): a harness that launders the answer, tunes on
held-out, or invents a threshold produces a *hollow green* that is worse than no gate.

## 2. Goal & non-goals

**Goal:** given (a) a set of **known-classification** TSC2 variants with best-available labels and (b)
the scorer's per-variant criterion calls (PRD-01 evidence), produce a **frozen benchmark**, a
**no-leakage train/dev vs held-out split**, **class-stratified metrics** (precision/recall/concordance,
missense reported separately), and an **auditable gate decision** — computed reproducibly and reported
with full provenance.

**Non-goals (explicit):**
- Computing ACMG criteria (PRD-01) or *final* classifications (human/oracle only — STRATEGY §9).
- Setting the pass thresholds — those are **pre-registered by the Oracle** (GP-3); the harness consumes
  them, never fits them.
- Running the live scoring pipeline (BIAS+Nirvana on the x64 worker — ADR-0008) or ingesting the real
  ClinVar snapshot — those are deferred deploy-time steps; the harness is built + validated offline.
- Tier-3 / cross-linkage evaluation (EVAL_PLAN §6 stubs — GP-7).

## 3. Users & need

| User | Need |
|---|---|
| The program (VUS gate) | An auditable **go / no-go** on running the scorer over the 6,700 VUS. |
| Oracle (GP-3) | Metrics + threshold-status to make the trust decision; a place their pre-registered thresholds are consumed (never fit). |
| Later tiers | The frozen Tier-1/2 baseline every harder tier is measured against. |

## 4. Functional requirements

- **FR1 — Benchmark builder:** from a **labels source** (best-available: ClinGen VCEP/3★ → 2★
  multi-submitter concordant → curated-literature-with-citation → Oracle adjudication) build the benchmark
  set, applying the **label hierarchy** (EVAL_PLAN §2) and **exclusions** (conflicting, single-submitter,
  and **any label RAPTOR influenced** → circular, R-A2). Freeze by **labels snapshot id + date**; every
  benchmark row carries source + snapshot + date (GP-9).
- **FR2 — No-leakage split:** deterministic split into **train/dev** (threshold calibration) and a
  **frozen held-out** test; the same variant identity never spans both; the split is a pure function of
  a pinned seed + benchmark snapshot (reproducible, R-A11). Record split sizes + per-class balance.
- **FR3 — Implied-direction combiner (eval-only):** combine a variant's **automatable** criterion calls
  into an implied **LP / LB / no-call** using the **Tavtigian-2018 point system** (Very Strong=8,
  Strong=4, Moderate=2, Supporting=1; pathogenic positive, benign negative; sum → category by
  pre-set point cutoffs). **Abstain (no-call) is first-class** — never a forced call. This call is
  **non-authoritative**: used only for metrics, never shown as a classification, never crosses an
  external threshold (STRATEGY §9). The point values + cutoffs live in `configs/eval/*.yaml` (GP-6).
- **FR4 — Metrics:** precision, recall, concordance (overall **and** separately for pathogenic-direction
  and benign-direction) on the **held-out** set; **class-stratified** — **missense reported separately**
  (R-A2c). No-calls are recorded as abstain, excluded from precision/recall denominators, and reported.
- **FR5 — Min-count rule:** per-class held-out counts below a configured minimum are reported as
  **descriptive only (non-gating), with confidence intervals** — not pass/fail (EVAL_PLAN §2). The gate
  never fires on an under-powered stratum.
- **FR6 — Gate decision:** compare the **missense-stratified held-out** metric against **Oracle
  pre-registered thresholds**. Emit one of: `PASS` (meets thresholds, above min-count), `FAIL` (below),
  `UNVERIFIED` (thresholds **not set** → GP-9/H13: never invent a target; never emit PASS), or
  `UNDERPOWERED` (below min-count). **A VUS run is authorized only on `PASS`.**
- **FR7 — Oracle-blind checks:** checks that do **not** read the label — internal consistency (e.g. a
  BA1-firing variant must not also be scored PVS1; direction contradictions), allele-frequency sanity,
  criterion-firing sanity. Laundering the label cannot pass a check that never sees it (R-A2/H1).
- **FR8 — Trace-cribbing separation (H1):** the harness reads labels; the **scorer must not**. The
  benchmark/label files are read **only** by the benchmark builder, never on the scoring path — enforced
  by construction (labels never flow into scorer inputs) and a forbidden-path audit.
- **FR9 — Deterministic + provenanced:** identical pinned inputs → record-identical benchmark, split,
  metrics, and gate decision (R-A11); run metadata excluded from the determinism hash. Every output
  carries provenance (labels snapshot, code version, config pins).
- **FR10 — Reporting:** write a `BENCHMARK_RESULTS`-style report **versioned by benchmark snapshot + code
  version**, stating benchmark version, held-out size (per class), each metric, and **threshold status
  (met / not-met / not-yet-set)**. A result is citable only if it states all four (EVAL_PLAN §5).

## 5. Non-functional requirements

- **Config-driven (GP-6):** Tavtigian point values + category cutoffs, min-count thresholds, split seed,
  the (initially empty) Oracle threshold block, and the automatable-criteria set — all in
  `configs/eval/*.yaml`, schema-validated; nothing hardcoded.
- **Reproducibility (R-A11):** benchmark, split, metrics, gate are pure functions of pinned inputs.
- **Provenance (GP-5/GP-9):** labels snapshot id/date, code version, config pins on every artifact.
- **Eval integrity (category H):** no held-out tuning; no invented thresholds; no scorer access to
  labels; oracle-blind checks alongside label comparison.

## 6. Acceptance criteria *(→ become OPERATING_MODEL gates; realize EVAL_PLAN §3/§4)*

- **AC1 — Combiner correctness (independent oracle):** a frozen fixture of `{criterion-call set →
  expected implied direction + points}`, with expected values from **Tavtigian-2018's published worked
  examples / point rules** (an independent authority, *not* the implementation), is reproduced exactly;
  includes at least one **no-call/abstain** case.
- **AC2 — No leakage (R-A2):** no variant identity appears in both train/dev and held-out; the split is
  deterministic under the pinned seed; a variant whose label RAPTOR influenced, or that is
  conflicting/single-submitter, is **excluded** from the scored set.
- **AC3 — Metrics correctness:** precision/recall/concordance match a **hand-computed confusion matrix**
  on a frozen fixture; **missense stratum is reported separately**; no-calls are excluded from
  P/R denominators and counted as abstain.
- **AC4 — Min-count rule (EVAL_PLAN §2):** a stratum below the configured minimum is reported
  **descriptive + CI, non-gating**; the gate does **not** fire on it.
- **AC5 — Gate honesty (GP-9/H13):** with thresholds **unset**, the gate returns **`UNVERIFIED`**, never
  `PASS`; with thresholds set, `PASS`/`FAIL` follow the **missense-stratified held-out** metric (R-A2c);
  **VUS authorization is emitted only on `PASS`.** No threshold is invented.
- **AC6 — Trace-cribbing separation (H1):** the scoring path reads no benchmark/label/oracle file; labels
  enter only the benchmark builder — proven structurally + by the forbidden-path audit.
- **AC7 — Determinism (R-A11):** benchmark + split + metrics + gate are record-identical on re-run of
  pinned inputs (run metadata excluded).
- **AC8 — Oracle-blind checks (R-A2):** the consistency/sanity checks run without reading labels and flag
  a deliberately inconsistent fixture (e.g. BA1 + PVS1 on one variant).
- **AC9 — Provenance/reporting (GP-9):** every artifact carries labels-snapshot + code-version + config
  pins; the report states benchmark version, per-class held-out size, metrics, and threshold status.

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-01 · scorer criterion calls (evidence) | **built** | Yes (FR3) — consumed from the KB / a fixture evidence set |
| PRD-03 · KB (read evidence) | **built** | Yes (FR3/FR8) |
| Best-available **labels source** (ClinVar snapshot / curated) | not started | Yes (FR1) — **fixtures for dev**; live snapshot deferred |
| **Live scoring of knowns** (BIAS+Nirvana, x64 worker) | deferred (ADR-0008) | Yes for a **real** gate run — not for the offline build |
| **Oracle pre-registered thresholds** (GP-3) | not started | Yes (AC5 `PASS`/`FAIL`) — until then the gate is honestly `UNVERIFIED` |

> **Buildable vs validated:** the harness is **built + validated offline now** against fixtures with an
> independent oracle. A **real gate run** — and therefore VUS authorization — additionally needs the
> live knowns pipeline (deps 3–4) and the Oracle thresholds (dep 5). Ship the ruler; the measurement is
> gated on data + Oracle.

## 8. Risks (see RISK_REGISTER)

R-A2 (circular validation / overfit) · **R-A2c** (distribution shift — the reason the gate is
missense-stratified) · R-E1 (validated-vs-buildable conflation) · H1 (trace-cribbing) · H13 (fabricated
target) · R-A11 (non-reproducibility). **GP-3:** the Oracle sets thresholds; the harness never fits
them. **GP-9:** no VUS run without a `PASS` from real data + set thresholds.

## 9. Open questions

- **Exact Tavtigian point cutoffs** for LP/LB/no-call in `configs/eval/` — pinned from the 2018 paper
  before build (they are config, not code; FR3).
- **Min-count threshold** per class — a defensible default (config), refined with the Oracle.
- **Labels source of record** for v1 knowns (ClinVar 2★-concordant vs a curated TSC set) — a data
  decision; the builder is source-agnostic given the label hierarchy.

## 10. Build contract (v1 increment) — resolves §9; feeds the loop

> Planner-authored. Test-author writes tests to this surface; the 3-slot doer implements; GPT checker
> re-verifies; the **conformance kit** (`raptor.testkit`) is wired from the start. `confirm`/empty pins
> (Tavtigian cutoffs pinned; Oracle thresholds intentionally empty) do not block the offline build.

### 10.1 Scope of this increment
- **Built + validated offline now:** FR1–FR10 against **fixtures** (a synthetic known-variant evidence
  set + a labels fixture); AC1–AC9. Gene scope **TSC2**.
- **Deferred (real gate run, not code):** the **live knowns** (real ClinVar ingest + BIAS/Nirvana
  scoring on the x64 worker) and **Oracle thresholds**. Until both, the gate returns `UNVERIFIED` — by
  design, not by omission.
- **Independent oracle for tests:** Tavtigian-2018 point rules/worked examples (AC1) + hand-computed
  confusion matrices (AC3) — never the implementation's own output.

### 10.2 Config → `configs/eval/tsc2.yaml` (FR5/GP-6; nothing hardcoded)
| Key | Value | Note |
|---|---|---|
| `automatable_criteria` | list (PVS1, PM2, PP3, BA1, BS1, BP4, …) | which criteria feed the combiner |
| `tavtigian_points` | `{very_strong:8, strong:4, moderate:2, supporting:1}` | pinned from 2018 paper |
| `tavtigian_cutoffs` | `{P:>=10, LP:6..9, LB:-6..-1, B:<=-7}` (VUS/no-call otherwise) | `confirm` vs paper |
| `min_count_per_class` | e.g. `20` | below → descriptive/CI, non-gating (FR5) |
| `split` | `{seed: <pinned>, holdout_fraction: 0.3}` | deterministic (FR2) |
| `oracle_thresholds` | **empty** (`{}`) until GP-3 sets them | gate → `UNVERIFIED` while empty (AC5) |
| `labels_snapshot` | id/date (fixture for dev) | provenance (FR1) |

### 10.3 Module layout + public API (the test contract) — `src/raptor/eval/`
- **`config.py`** — `EvalConfig` (frozen) + `load_config(path)`; schema-validates, raises on missing pin.
- **`model.py`** — `LabeledVariant` (variant_id, label∈{P,LP,LB,B}, review_status, submitter_count,
  source, snapshot, raptor_influenced:bool, variant_class e.g. missense/truncating/other),
  `BenchmarkRow`, `ImpliedCall` (variant_id, implied∈{LP,LB,no_call}, points), `Metrics`
  (precision/recall/concordance + counts, per stratum), `GateDecision`
  (status∈{PASS,FAIL,UNVERIFIED,UNDERPOWERED}, stratum, reason, vus_authorized:bool).
- **`benchmark.py`** — `build_benchmark(labeled, config) -> list[BenchmarkRow]`: apply label hierarchy +
  exclusions (conflicting/single-submitter/raptor_influenced) + freeze (FR1).
- **`split.py`** — `split_benchmark(rows, config) -> (train_dev, holdout)`: deterministic, no-leakage (FR2).
- **`combine.py`** — `implied_direction(criterion_calls, config) -> ImpliedCall`: Tavtigian points (FR3);
  abstain first-class.
- **`metrics.py`** — `compute_metrics(implied, benchmark, config) -> dict[str, Metrics]` keyed by stratum
  (`overall`, `missense`, `truncating`, …); min-count rule tags a stratum descriptive/non-gating (FR4/FR5).
- **`gate.py`** — `decide_gate(metrics, config) -> GateDecision`: missense-stratified vs
  `oracle_thresholds`; empty thresholds → `UNVERIFIED`; `vus_authorized = (status == PASS)` (FR6/AC5).
- **`checks.py`** — `oracle_blind_checks(evidence) -> list[Finding]`: consistency/sanity without labels (FR7).
- **`harness.py`** — `run_eval(config, labeled, evidence_source) -> EvalReport`: benchmark → split →
  combine (held-out) → metrics → gate → checks → report. **Labels flow ONLY here/benchmark, never into
  `evidence_source`** (FR8). `EvalReport.content_hash()` excludes run metadata (FR9).
- **`report.py`** — `EvalReport` + `render()` → the versioned results text (FR10).

Evidence is read via the PRD-03 KB (`effective_evidence_at` / a read accessor) or an injected fixture
evidence source; **labels are a separate input** and never reach the evidence source (H1).

### 10.4 Conformance kit (wired from the start)
`tests/eval/test_kit_conformance_eval.py` wires `raptor.testkit.invariants`:
- **determinism** (`run_eval` content_hash stable across runs);
- **fail-loud-propagation** (a malformed labels/contract input raises, not swallowed);
- **no-state-change-on-failure** if it writes to the KB;
- plus a harness-specific **no-leakage** property (train/dev ∩ held-out = ∅ over generated benchmarks)
  and a **gate-honesty** property (thresholds-unset ⇒ never `PASS`) — candidates for promotion into the
  kit if they recur (kit-catalog, deferred).

### 10.5 Anti-circularity (this module IS the eval integrity boundary)
- **AC1 combiner oracle = Tavtigian-2018**, not frozen self-output.
- **AC3 metrics oracle = hand-computed confusion matrix.**
- **The harness reads labels; the scorer never does** (FR8/AC6) — the single most important separation
  in the system; tested structurally (labels object never passed to the evidence source) + audit.
- **Held-out never tunes** (FR2/AC2); **thresholds never fit** (FR6/AC5, `UNVERIFIED` while empty).
