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

> *Module built ≠ live run executed.* The Tier-1/2 code path and the validation harness are **built and
> signed off**; the **gated held-out eval has not yet been run**, so no VUS classification is authorized.

- Tier 1/2 (Deterministic): 🟡 **MODULE BUILT** (PRD-01 scorer `1d2444e`; arm's-length BIAS port) — *live x64 held-out scoring not yet run*
- Tier 3 (LLM Extraction): 🔴 NOT STARTED (Phase 2)
- Consensus/Adjudication: 🔴 NOT STARTED
- Validation Framework: 🟡 **BUILT + PRE-REGISTERED** (PRD-06 harness `e026422`, PRD-07 loader `499f479`, frozen benchmark `2e3477f`, thresholds `8662499`) — *terminal held-out eval not yet run*

## Operations (Current Run)

> No held-out eval has been scored yet — metrics stay **N/A** until the full 2,577-variant held-out set
> is scored on the x64 worker (terminal join).

- Last Batch Size: N/A
- Precision: N/A
- Recall: N/A
- Suspended (Human Review): N/A

## Priorities (This Week) — terminal join to the first VUS run

The three parallel tracks (A benchmark · B x64 smoke infra · C oracle thresholds) are **done**; the
critical path is now the single-threaded **terminal join** (see *Path to first VUS run*):
1. Build the **real arm's-length eval `EvidenceSource` adapter** + an **automated ClinVar-derivation guard/audit** (ADR-0009 follow-up).
2. Emit the **label-free full held-out VCF** (2,577 variants; H1 anti-circularity boundary — no labels cross to the x64 worker).
3. Score the 2,577 held-out variants on the **x64 devbox** (BIAS-2015 v3.0.0 + Nirvana; ADR-0008).
4. Run the **ClinVar-derivation audit** on the full output → real PM5/PM1/PP2 firing counts → **Oracle ruling** on the transitive bucket (ADR-0009).
5. Run the **terminal PRD-06 held-out eval**; gate must return **PASS** (missense-stratified, both directions ≥0.90 precision / ≥0.85 recall) — only a PASS authorizes the first ~6,700-VUS run, then the PRD-04 triage worklist.

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

## Path to first VUS run

The three parallel tracks (A benchmark · B x64 scoring infra · C oracle thresholds) are **done**. What
remains is the **terminal join**: a small amount of eval-side code (the arm's-length `EvidenceSource`
adapter + the automated ClinVar-derivation guard/audit — ADR-0009), the label-free held-out scoring
run on x64, the transitive-criteria audit + Oracle ruling, then the gated PRD-06 held-out eval.

| # | Track | Type | Status |
|---|---|---|---|
| A | **Benchmark data** — real ClinVar TSC1/TSC2 *knowns* → frozen labeled benchmark (excl. conflicting/single-submitter/low-review; label hierarchy) | data | **DONE ✓** — frozen snapshot `clinvar_2026-07-07`; **3,681** scoreable knowns → **2,577** held-out / **1,104** dev reserve at `holdout 0.7` (PR #7 `2e3477f`, Track A2; A1 loader PRD-07 `499f479`) |
| B | **x64 live-scoring infra** — BIAS-2015 (arm's-length, ADR-0007) + Nirvana (x64-only, ADR-0008) | infra | **Smoke-tested ✓ (operator-confirmed)** — BIAS-2015 v3.0.0 + Nirvana 3.18.1 produced an 8-record TSV that passed `BiasTsvSource`'s 18-column contract with identity preserved. Large external artifacts intentionally out of repo; versions/hashes live in the operator's external reports (handoff bundle PR #8 `3556548`) |
| C | **Oracle thresholds (GP-3)** — pre-register precision/recall targets into `configs/eval/tsc2.yaml` | governance | **DONE ✓** — `oracle_thresholds {precision: 0.90, recall: 0.85}` pre-registered *blind* to held-out results; `min_count_per_class: 35`, `split.holdout_fraction: 0.7` (PR #10 `8662499`) |
| J | **Terminal join** — build the eval adapter + derivation guard, emit label-free held-out VCF, score 2,577 on x64, audit transitive PM5/PM1/PP2 → Oracle ruling, run PRD-06 held-out eval; gate must `PASS` (missense-stratified, **both directions**) → authorizes the ~6,700-VUS run | code + eval | **PENDING** — see *Priorities* above; A ∧ B ∧ C are met |

> A/B/C are complete and had **no code dependency on each other**. Thresholds are now pre-registered
> (C done), so the gate no longer reads `UNVERIFIED` for a missing target — but it **cannot `PASS`
> until real held-out scores exist** (terminal join) and the transitive-ClinVar audit + Oracle ruling
> on PM5/PM1/PP2 land (ADR-0009).

## Active Decisions & Bottlenecks
- (Resolved 2026-07-08) Loop-engineering operating model → planner/doer/checker, see ADR-0003.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Resolved 2026-07-10) **ClinVar direct-copy circularity** → **PP5/BP6/PS4 banned** from `automatable_criteria` (eval == production; structurally rejected in `eval.config.FORBIDDEN_CRITERIA`); transitive **PM5/PM1/PP2 deferred** to the full-held-out audit — ADR-0009 (PR #11 `2766e33`). Real BIAS v3.0.0 output showed PS4 falls back to counting ClinVar submitters for rare Mendelian variants.
- (Open) **Full-output circularity audit** — build the mechanized ClinVar-derivation guard that enumerates every ClinVar-sourced *scored* criterion on the full held-out output; the Oracle then rules on PM5/PM1/PP2 with **real firing counts** in hand before the gate run (ADR-0009). *On the terminal-join critical path.*
- (Open) **Gate fidelity — Clopper-Pearson lower bound** — the gate currently checks the **point estimate**, not the 95% CI lower bound the rubric frames; `min_count_per_class: 35` is the underpowered floor that approximates it. Making the gate compute the Clopper-Pearson lower bound is a tracked PRD-06 follow-up (EVAL_RUBRIC §6).
- (Open) **Per-stratum truncating 0.95 gate** — truncating ≥0.95 (210 held-out, powered) is **reported, not gated**; hard-gating it needs a PRD-06 per-stratum `oracle_thresholds` extension (EVAL_RUBRIC §5). Missense (≥0.90) is the binding constraint.
- (Open) **Loader GRCh38 assembly filter** — confirm the PRD-07 knowns loader strictly filters to the GRCh38 assembly (the freeze script already filters GRCh38+TSC1/TSC2; harden the loader-side guard).
- (Open) Cross-linkage oracle — recruit molecular geneticist before Phase 3 (STRATEGY.md GP-3; risk R-E1).
- (Open) Confirm worker vCPU allocation at deploy (EPYC/Xeon 8-vCPU VM vs full silicon).
- (Open) **Build core risk controls before trusting any automated output** — canary set, heartbeat/dead-man's switch, hard spend cap, source-contract tests, **answer-key/trace-cribbing lint, assertion-lock** (RISK_REGISTER.md §1; risks R-C1/R-A2/H1).
- (Open) ADR — reuse `biomcp` / `paper-search-mcp` MCP connectors for Tier-3 retrieval (ARCHITECTURE.md §8; gated on GP-10/GP-9).
- (Open) **Backlog — PRD-04 (VCEP triage worklist) / PRD-05 (pipeline & orchestration skeleton)** — deferred until a gate PASS authorizes the first VUS run.
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
- (Open) **Environment:** Python 3.12.10 on Windows; **WSL2 Ubuntu 24.04.4 LTS (aarch64) ready**, venv **`raptor`** at `~/raptor` (Python 3.12.3, pytest 9.1.1, gcc 13.3/make). Code lives at `/mnt/d/AIProjects/raptor`; venv on Linux fs. Modules built via plan/build/check: **PRD-03 ✓, PRD-02 ✓, PRD-01 ✓, PRD-06 ✓, PRD-07 ✓ (all signed
  off)**; CI gate live ✓; reference-fetch script ✓. The three parallel non-code tracks are now **done**
  — (A) real ClinVar knowns benchmark frozen (`2e3477f`), (B) BIAS-2015 v3.0.0 + Nirvana smoke-tested
  on the x64 devbox (operator-confirmed, ADR-0008), (C) Oracle thresholds pre-registered (`8662499`).
  Next: the **terminal join** (see *Path to first VUS run* / *Priorities*) — eval `EvidenceSource`
  adapter + ClinVar-derivation audit, label-free held-out VCF, x64 scoring of the 2,577 held-out
  variants, Oracle transitive ruling, then the gated PRD-06 held-out eval. Deferred: conformance-kit
  *governance* (kit-mypy/strict-first/C3 provenance/gate-0); PRD-04/05; cross-machine fleet.
