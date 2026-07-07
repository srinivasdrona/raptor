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
| PRD-01 | Tier-1/2 Deterministic ACMG Scorer | 1 | **Signed off** |
| PRD-02 | Variant Ingestion & Normalization | 0 | **Signed off** |
| PRD-03 | KB Schema & Provenance Ledger | 0 | **Signed off** |
| PRD-04 | VCEP Triage Worklist | 1 | backlog |
| PRD-05 | Pipeline & Orchestration skeleton | 0 | backlog |

## Active Decisions & Bottlenecks
- (Resolved 2026-07-08) Loop-engineering operating model → planner/doer/checker, see ADR-0003.
- (Resolved 2026-07-08) Runtime architecture depth → LiteLLM + Prefect + SQLite + Ollama; no Ray/LangGraph, see ADR-0004 / ARCHITECTURE.md.
- (Open) Cross-linkage oracle — recruit molecular geneticist before Phase 3 (STRATEGY.md GP-3; risk R-E1).
- (Open) Confirm worker vCPU allocation at deploy (EPYC/Xeon 8-vCPU VM vs full silicon).
- (Open) **Build core risk controls before trusting any automated output** — canary set, heartbeat/dead-man's switch, hard spend cap, source-contract tests, **answer-key/trace-cribbing lint, assertion-lock** (RISK_REGISTER.md §1; risks R-C1/R-A2/H1).
- (Open) ADR — reuse `biomcp` / `paper-search-mcp` MCP connectors for Tier-3 retrieval (ARCHITECTURE.md §8; gated on GP-10/GP-9).
- (Open) **Environment:** Python 3.12.10 installed on Windows; **WSL not yet installed** (needs an elevated `wsl --install` + reboot by the operator). Per operator instruction, **module builds (PRD-01/02/03) are deferred until WSL is set up and the operator confirms**; code to be written OS-portable. Cross-machine fleet = deferred (Tier-3 only; not needed for Tiers 1/2).
