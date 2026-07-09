# RAPTOR PROGRAM STATUS

> Live status rollup. For *why* the project is shaped this way, see **[STRATEGY.md](STRATEGY.md)**
> (vision, scope, guiding policy), **[DECISIONS.md](DECISIONS.md)** (ADRs),
> **[ARCHITECTURE.md](ARCHITECTURE.md)** (runtime), and **[RISK_REGISTER.md](RISK_REGISTER.md)**
> (failure modes). This doc tracks *state*; those track *intent*.

## Operating Model — build loop

RAPTOR is built in a **design → build → review → eval → (back to design)** loop with a fixed
model-role split (see **[ADR-0003](DECISIONS.md#adr-0003--loop-operating-model-planner--doer--checker-across-three-model-families)**):

| Stage | Role | Model | Note |
|---|---|---|---|
| Design / plan | Planner | Claude Opus | writes task spec + acceptance criteria; no production code |
| Build | Doer | Claude Sonnet 5 | implements against the spec |
| Review / eval | Checker | GPT (5.x) | adversarial review vs acceptance criteria; pass or send back |

Rule: the **checker is always a different model family from the doer**; nothing is "done" until the
checker passes it against pre-stated acceptance criteria. *(Spec/verdict schema + gate automation are
pending `OPERATING_MODEL.md` — ADR-0003.)*

## Health Rollup
- Tier 1/2 (Deterministic): 🔴 NOT STARTED
- Tier 3 (LLM Extraction): 🔴 NOT STARTED
- Consensus/Adjudication: 🔴 NOT STARTED
- Validation Framework: 🔴 NOT STARTED

## Operations (Current Run)
- Last Batch Size: N/A
- Precision: N/A
- Recall: N/A
- Suspended (Human Review): N/A

## Priorities (This Week) — Phase 0 (STRATEGY.md §7)
1. Lock ~50-variant frozen benchmark from best-available TSC1/TSC2 expert / high-review-status labels
2. Build MVP pipeline skeleton: LiteLLM router + Prefect flow test
3. Stand up fleet: Snapdragon (Queen + SQLite state), EPYC + Xeon (Ollama batch workers)

## PRD backlog (feature specs — `docs/prd/`)

Per-feature PRDs, authored *just-in-time* for the feature about to be built (no speculative PRDs; no
index file until ≥3 exist).

| PRD | Feature | Phase | Status |
|---|---|---|---|
| PRD-01 | Tier-1/2 Deterministic ACMG Scorer | 1 | **Signed off · module built ✓** (`1d2444e`, 149 tests; arm's-length BIAS) |
| PRD-02 | Variant Ingestion & Normalization | 0 | **Signed off · module built ✓** (`a889710`, 125 tests) |
| PRD-03 | KB Schema & Provenance Ledger | 0 | **Signed off · module built ✓** (`b627073`) |
| PRD-04 | VCEP Triage Worklist | 1 | backlog |
| PRD-05 | Pipeline & Orchestration skeleton | 0 | backlog |
| PRD-06 | **Benchmark & Evaluation Harness** (build known-variant benchmark + train/dev/held-out split + P/R/concordance, class-stratified; **gates any VUS run**) | 1 | **Signed off · module built ✓** (`e026422`, PR #1, 222 tests; 7-round cross-family checker sign-off) |
| PRD-07 | **ClinVar Knowns → Benchmark Labels Loader** (Track A1: label-side `variant_summary` → `LabeledVariant` for PRD-06; reuses PRD-02 contract+normalizer; keeps scorer label-blind, H1) | 1 | **Signed off · module built ✓** (`499f479`, PR #3, 274 tests; 7-round checker sign-off) |

> **Validation gate (binding):** no classification is run on the ~6,700 TSC VUS until PRD-06 shows
> Tier-1/2 clears pre-registered thresholds on the **held-out known-variant** set — reported
> **stratified by variant class** (missense gated separately; R-A2c). See EVAL_PLAN §1.1.

## Path to first VUS run (post-PRD-06)

PRD-06 completes the **code** path to the gated run — no further module builds are on the critical
path. What remains are **three independent non-code tracks** that can run **in parallel**, then a
terminal join:

| # | Track | Type | Blocks on | Parallel? |
|---|---|---|---|---|
| A | **Benchmark data** — ingest real ClinVar TSC1/TSC2 *knowns* → frozen labeled benchmark (excl. conflicting/single-submitter/RAPTOR-influenced; label hierarchy) | data | **A1 loader built ✓ (PRD-07, `499f479`)**; A2 = ClinVar snapshot pull (governance) | ✅ independent |
| B | **x64 live-scoring infra** — BIAS-2015 (arm's-length, ADR-0007) + Nirvana (x64-only, ADR-0008) + local pinned UTA for `hgvs` | infra | x64 worker stand-up | ✅ independent |
| C | **Oracle thresholds (GP-3)** — pre-register precision/recall targets into `configs/eval/tsc2.yaml` (currently `{}` → gate reads `UNVERIFIED`) | governance | molecular-geneticist sign-off | ✅ independent |
| J | **Terminal join** — run PRD-06 eval on the held-out known set; gate must `PASS` (missense-stratified, **both directions** clear pre-registered thresholds) → authorizes the 6,700-VUS run | — | A ∧ B ∧ C | join |

> A/B/C share one upstream nicety (ingest the knowns once, reused by A and the eval), but have **no
> code dependency on each other**. The gate stays `UNVERIFIED` until C lands thresholds, and cannot
> `PASS` until A provides the benchmark and B produces real scores.

## Active Decisions & Bottlenecks
- (Resolved 2026-07-08) Loop-engineering operating model → planner/doer/checker, see ADR-0003.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Open) Cross-linkage oracle — recruit molecular geneticist before Phase 3 (STRATEGY.md GP-3; risk R-E1).
- (Open) Confirm worker vCPU allocation at deploy (EPYC/Xeon 8-vCPU VM vs full silicon).
- (Open) **Build core risk controls before trusting any automated output** — canary set, heartbeat/dead-man's switch, hard spend cap, source-contract tests, **answer-key/trace-cribbing lint, assertion-lock** (RISK_REGISTER.md §1; risks R-C1/R-A2/H1).
- (Open) ADR — reuse `biomcp` / `paper-search-mcp` MCP connectors for Tier-3 retrieval (ARCHITECTURE.md §8; gated on GP-10/GP-9).
- (Resolved) **Reference-data reproducibility (R-A11):** committed `scripts/fetch_reference.py`
  fetch-and-verify utility (`a80f759`, PR #2) so a fresh clone can reproduce the local pinned
  reference (chr9 `NC_000009.12` + chr16 `NC_000016.10`), checksums pinned in `configs/ingest/tsc.yaml`.
  AC3 `requires_reference` tests still skip on CI without the local data (expected).
- (Open) **Build-process hardening (in progress):** conformance kit + **promotion machinery LIVE** —
  `tests/kit/catalog.yaml` (findings registry, rule-of-2/3) + promoted invariants C1 (strict-whitelist
  `assert_never_emits`) / C2 (label-blindness `assert_no_label_leak`) wired into modules +
  `tests/kit/test_catalog_meta.py` (checker-gate0: fails the build if a promoted invariant is unwired).
  **ClinVar/HGVS golden corpus** (`tests/fixtures/clinvar_hgvs_golden.yaml` + cited
  `docs/reference/clinvar-hgvs-golden-corpus.md`) is the full-vocabulary loader oracle — it caught a
  real bare-`p.` parser bug on wiring. Remaining: kit-mypy (type gate), strict-first spec standard,
  C3 provenance promotion. Turns recurring bug-classes into *enforced* gates.
- (Open) **Environment:** Python 3.12.10 on Windows; **WSL2 Ubuntu 24.04.4 LTS (aarch64) ready**, venv **`raptor`** at `~/raptor` (Python 3.12.3, pytest 9.1.1, gcc 13.3/make). Code lives at `/mnt/d/AIProjects/raptor`; venv on Linux fs. Modules built via plan/build/check: **PRD-03 ✓, PRD-02 ✓, PRD-01 ✓, PRD-06 ✓ (all signed off)**; CI gate live ✓; reference-fetch script ✓. Next: the three parallel non-code tracks to the first VUS run (see *Path to first VUS run* above) — (A) real ClinVar knowns benchmark, (B) BIAS+Nirvana+UTA on x64 worker (ADR-0008), (C) Oracle thresholds (GP-3). Deferred: conformance-kit *governance* (catalog/promotion/meta-tests/mypy/gate-0); PRD-04/05; cross-machine fleet.
