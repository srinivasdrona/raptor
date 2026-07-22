# RAPTOR — Architecture

> **Status:** DRAFT v0.1 · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (added §6a as-built modules; deployment-status note in §7) · **Review cadence:** monthly
>
> **Format:** Structured to the **arc42** template ([arc42.org](https://arc42.org)) with **C4-model**
> diagram levels (Context → Container → Component; Simon Brown, [c4model.com](https://c4model.com)).
> Sections not yet relevant are marked *(deferred, GP-7)*. This doc describes *mechanism*; strategy +
> build-governance intent lives in [STRATEGY.md](STRATEGY.md), evaluation authority lives in
> [EVALUATION.md](EVALUATION.md), decisions in [DECISIONS.md](DECISIONS.md), and status in
> [PROGRAM.md](PROGRAM.md).

---

## 1. Introduction & goals

RAPTOR is an unattended, weekly, low-volume evidence pipeline that assembles auditable ACMG/AMP
variant-classification packets for TSC1/TSC2 VUS, and surfaces mTOR-pathway cross-links as cited
hypotheses. Architecture must serve five quality goals (§10):

1. **Auditability** — every result carries model, version, prompt version, source, timestamp.
2. **Freshness** — bounded lag between source updates and re-validation.
3. **Cost discipline** — local models absorb volume; cloud touches only what passes screening (~$0 most weeks).
4. **Explainability & configurability** — rules/thresholds/routing in config, not code (GP-6).
5. **Human-in-the-loop safety** — no "final classification" without **qualified sign-off**: operator for internal records, molecular geneticist/VCEP for any external classification (STRATEGY Part I §9, GP-11).

## 2. Constraints

| Constraint | Source | Implication |
|---|---|---|
| Solo operator, unattended for long stretches | STRATEGY.md | Orchestration must self-run, retry, and report failures. |
| Azure **2 concurrent cloud sessions** cap | Fleet notes | Local models absorb volume; cloud calls serialized/queued via gateway. |
| Non-commercial data licenses (CADD, SpliceAI, REVEL) | Data sources | Research-use only; keep licensing boundary explicit. |
| Least complexity (GP-7) | STRATEGY.md | No component added without a concrete, demonstrated need. |
| Config is source of truth (GP-6) | STRATEGY.md | Rules/thresholds/routing in YAML/TOML, read by scripts. |

## 3. Context & scope (C4 — Level 1)

```
                    ┌──────────────────────────────────────────┐
   Public sources   │                                          │   Human
   ┌─────────────┐  │                RAPTOR                     │  ┌──────────────┐
   │ ClinVar FTP │─▶│   (weekly evidence pipeline + KB)         │─▶│ Operator /   │
   │ gnomAD      │  │                                          │  │ curator      │
   │ PMC OA      │─▶│   in:  variants + literature             │  │ (review queue│
   │ LitVar2 /   │  │   out: evidence packets, posteriors,     │  │  + sign-off) │
   │ PubTator    │  │        gap-map, "what changed" diff      │  └──────────────┘
   │ ClinGen     │─▶│                                          │
   └─────────────┘  └───────────────┬──────────────────────────┘
                                     │ (proposed classifications, once VCEP-reviewed)
                                     ▼
                              ClinVar submissions
```

**In scope:** ingestion, deterministic scoring, LLM extraction, Bayesian integration, versioned KB,
review queue, weekly diff. **Out of scope:** patient-facing UI, prescribing, autonomous
reclassification (see STRATEGY.md Part I §9).

## 4. Solution strategy — the runtime stack

**Decision (ADR-0004): `LiteLLM + Prefect + SQLite + Ollama`. No Ray, no LangGraph.**

| Concern | Choice | Why (session-grounded) | Rejected alt. |
|---|---|---|---|
| Model routing (local + cloud) | **LiteLLM** gateway | One OpenAI-compatible endpoint; config-driven routing, fallback, cost logging (GP-6); bypasses Azure cap via local. | — |
| Orchestration / schedule | **Prefect** flows | Weekly schedule, retries, run history, observability for unattended runs + "what changed" diff. | plain cron (no observability) |
| State / knowledge base | **SQLite** (`variants.db`) on Queen | Single-writer, file-based, versioned evidence records; zero ops. | Postgres *(deferred)* |
| Local inference | **Ollama** on EPYC + Xeon | `qwen3-coder:30b` (MoE) for abstract screening + summaries. *(~60–80 t/s is an unbenchmarked estimate — confirm on actual vCPU.)* | — |
| Distributed compute | **none** | 2-VM batch split = `ThreadPoolExecutor`; volume is a weekend batch. | **Ray** — overkill (GP-7), turn-14 |
| Agent/loop state at runtime | **none** | Runtime is a linear DAG with gates = native Prefect. | **LangGraph** — unneeded (GP-7), turn-9 |

> **Two distinct loops — do not conflate:**
> - **Runtime data pipeline** (this doc) — linear DAG, orchestrated by Prefect.
> - **Build-time loop** — planner (Opus) → test author (Gemini) → doer (Sonnet 5) → checker (GPT), a
>   *development* process (ADR-0003/ADR-0005), orchestrated by the operator + Copilot CLI +
>   delegation, **not** a runtime component.

## 5. Building block view (C4 — Level 2: Containers)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ SNAPDRAGON LAPTOP (ARM, 32GB, NPU) — QUEEN / ORCHESTRATOR                  │
│  ├─ Prefect flows            (surveillance → screening → extraction → …)   │
│  ├─ LiteLLM gateway          (routes to local Ollama + cloud Foundry)      │
│  ├─ variants.db (SQLite)     (VUS, evidence chains, posteriors, versions)  │
│  ├─ Bayesian engine          (Tavtigian 2018 LR combination — pure Python) │
│  ├─ local model via Ollama   (qwen ~9B: evidence summaries, gap flagging)  │
│  └─ human review queue       (threshold crossings → operator sign-off)     │
└───────────────┬───────────────────────────────────────────────────────────┘
   SSH tunnels  │  (Ollama :11434 port-forwarded; no inbound ports; VS Code Tunnels)
   ┌────────────┼───────────────────────────────┐
   ▼            ▼                                ▼
┌────────────────────┐  ┌────────────────────┐  ┌────────────────────────────┐
│ EPYC 7763 worker   │  │ XEON 8370C worker  │  │ i7 DESKTOP (data host)     │
│ ├ Ollama           │  │ ├ Ollama (AVX-512, │  │ ├ LitVar2 / PMC fetching   │
│ │  qwen3-coder:30b │  │ │  faster screening)│  │ └ large dataset staging    │
│ ├ BIAS-2015 (Tier1)│  │ ├ BIAS-2015 (∥)    │  └────────────────────────────┘
│ └ ClinVar/gnomAD   │  │ └ LitVar2 batch    │
└────────────────────┘  └────────────────────┘
                                   │  Cloud (via LiteLLM → Foundry)
                                   ▼
              Claude (PS3 full-text extraction) · GPT/Gemini (selective)
```

> **Deploy-time check:** `pre-build/FYTSC_1.md` recorded EPYC/Xeon as *8-vCPU VMs*; the infra notes later
> recorded full silicon (64c / 32c) after image verification. **Confirm actual vCPU allocation at
> deploy** — it changes model-size choices on the workers.

## 6. Runtime view — the pipeline

**One-time init:** ClinVar FTP pull → **variant normalization** (HGVS/SPDI, MANE transcript, genome
build, transcript version) → BIAS-2015 across all ~6,700 TSC1/TSC2 VUS → LitVar2 lookup → one-time
PS3 extraction on existing literature → integrate → versioned KB → human review of crossings.

**Weekly flow (Prefect, Mon 02:00):**

| Phase | Trigger | Where | Model |
|---|---|---|---|
| 1 · Surveillance | always (~5 min) | Snapdragon | none (HTTP) |
| 2 · Screening | only if new papers | EPYC + Xeon (split) | `qwen3-coder:30b` (local) |
| 3 · Extraction | only if papers pass screening | Snapdragon → cloud | Claude (PS3), via LiteLLM |
| 4 · Integration | only if new evidence | Snapdragon | Python (Bayesian) |
| 5 · Reporting | always | Snapdragon | local qwen (summaries) |

**Special triggers (non-weekly):** gnomAD release → re-eval PM2/BA1/BS1; VCEP curation → adopt as a
label **and flag any benchmark overlap** (avoid circular validation — §11); retraction → remove
evidence + recompute; new SVI guidance → re-weight criteria; preprint → provisional (low weight),
auto-upgrade on publication.

## 6a. As-built evidence/eval modules (additive to the runtime stack)

> **Status:** DRAFT v0.1 · **Last updated:** 2026-07-22. The items below are implemented, committed
> code — distinct from the accepted-but-undeployed runtime stack in §4-§7.

- **`raptor.census`** (`raptor.census.strata` + `raptor.census.aggregate`, driven by
  `raptor.census.cli`) — the packet-free census aggregation package. It emits the current
  non-identifying, non-authoritative candidate-direction census
  (`data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`) under the PP3/BP4-disabled
  `manual` policy (ADR-0012). The CLI fails closed on an unapproved/drifted predictor policy or bound
  config hash, a non-pinned `--historical-stats` path, a malformed provenance hash, or an
  unresolvable git commit, and never overwrites an existing artifact.
- **Tiered gate v3** (`raptor.eval.tiered_gate.decide_tiered_gate`,
  `raptor.eval.config.load_tiered_authorization`, config `configs/eval/tiered_gate_v3.yaml`, built via
  `scripts/build_tiered_readjudication.py`) — an additive, standalone post-hoc re-adjudication layer
  (ADR-0013) over the frozen R2 masked-holdout aggregate. It is deliberately kept separate from the
  policy-bound `configs/eval/tsc2.yaml` (which stays byte-identical at its approved SHA-256 and never
  gains a `tiered_authorization` block); the tiered config is semantics-locked and validated by strict
  recursive equality against a pinned constant, so any drift in the criterion-scope map or thresholds
  fails closed. It performs no new run, scoring, annotation, benchmark read, network access, or data
  generation — see `no_new_evidence_statement` in `data/census/tsc_tiered_readjudication_2026-07-21.json`.

## 7. Deployment view (C4 — Level 3 boundary)

> **Accepted architecture vs actual deployment status.** §4-§6 describe the **accepted** runtime
> architecture (ADR-0004: LiteLLM + Prefect + SQLite + Ollama). As of this writing **no component in
> §4-§6 has been deployed as a running service** — Prefect is not scheduling any flow, no Ollama
> gateway is live, and `variants.db` does not yet exist. All work to date (census, R2 masked
> held-out gate, tiered v3 re-adjudication, calibration packets) has been produced by
> **operator-invoked CLI scripts and Python modules** (§6a) run directly, not by the Prefect runtime
> pipeline. Do not read §4-§6 as evidence of a live weekly run; deployment remains a separate,
> not-yet-scheduled milestone.

- **Transport:** SSH port-forward of each worker's Ollama (`:11434` → Queen `:11435/:11436`); VS Code
  Tunnels as fallback. **No inbound ports exposed** (Azure VMs implied).
- **Schedule:** Prefect deployment (preferred) or Windows Task Scheduler as fallback.
- **Secrets:** cloud API keys in local env / secret store on Queen only; never in repo or config
  committed to git (see §8).

## 8. Cross-cutting concepts

- **Provenance & freshness (GP-5):** every evidence record stores `{model, version, prompt_version,
  source, source_snapshot_version, env/dependency-versions, originating_session, timestamp}`;
  **event-sourced immutable inputs** — derived
  classifications recompute from them, never mutate in place. Versioned per-variant records
  (`v1.0 → v1.1 → v2.0`) with posterior deltas and approvals. **Retraction/stale semantics:** a
  retracted or superseded source invalidates its evidence and triggers posterior recompute + audit
  diff. Freshness lag is a KPI.
- **Config as source of truth (GP-6):** `configs/models/routing.yaml` (LiteLLM routing — **replaces**
  any MODEL_ROUTING_POLICY doc), `configs/acmg/*.yaml` (criteria weights, per-gene thresholds).
- **Variant normalization (first-class stage):** all variants normalized to HGVS/SPDI on a pinned
  MANE transcript + genome build **before** scoring or literature matching; alias/transcript-version
  handling explicit. Prevents silent mismatches across ClinVar, BIAS-2015, and LitVar2.
- **Criterion-level evidence model (no double-counting):** each ACMG criterion fires **at most once**,
  with provenance + strength; the Bayesian step (Tavtigian LRs) consumes *criterion-level calls*, not
  raw overlapping features (CADD/REVEL/BIAS/domain), so correlated predictors don't inflate posteriors.
- **Runtime evidence verifier (≠ build-time checker):** PS3 extractions pass a *deterministic*
  citation + variant-matching + source-span check, optional second-model adjudication, then human
  review for threshold crossings. This is a **runtime** component; the build-time GPT checker
  (ADR-0003) never validates evidence.
- **Referential integrity (GP-9 — "no artifact, no action"):** the schema requires a **non-null,
  resolvable `source_ref`** on every evidence row, criterion call, and classification; a row without
  one **fails fast**. A **citation resolver** checks each cited PMID/accession/URL against the real
  source (LitVar2/PMC/ClinVar) and rejects unresolvable references (kills fabricated citations). Each
  Tier-3 claim carries the **verbatim supporting span + offset**; a span that doesn't contain the
  claim is rejected. Anything unreferenced is `UNVERIFIED` and cannot cross a VUS→LP/LB threshold or
  be submitted. Residual (real, cited, span-grounded but mis-interpreted) → Oracle (GP-3).
- **Full-text / copyright / cloud policy:** automated full-text extraction is restricted to
  rights-cleared sources (PMC OA); non-OA papers are queued for manual review, not sent to cloud
  models. Abstract-only evidence is marked as such.
- **Licensing boundary:** non-commercial annotations (CADD/SpliceAI/REVEL) are research-use-only; the
  KB tracks a per-field licensing matrix and can emit **research-only** vs **redistributable** output
  modes so lab/commercial users aren't handed restricted data.
- **Cost model (estimate, pending measured volumes):** local absorbs volume filtering; cloud only on
  the screened subset → ~$0 most weeks, ~$0.04–0.50 on weeks with new papers.
- **Human-in-the-loop (two levels):** any VUS → LP/LB crossing enters the review queue. The
  **operator** approves *internal* pipeline records; any **externally meaningful** proposed
  classification or ClinVar submission requires a **qualified molecular geneticist / VCEP**
  (STRATEGY.md Part I §9). Solo-operator approval never produces an external classification.
- **Failure / rollback / idempotence:** every run has a run-ID; workers write to **run-scoped staging
  tables**; results **publish atomically** only after validation, into an **immutable evidence
  ledger**. A failed/partial run rolls back its staging without corrupting the KB.
- **Security:** authenticated SSH tunnels only; secrets in the OS keychain / Queen secret store,
  **never in git, config, provenance, logs, crash reports, or exports**; non-commercial data kept
  within research-use boundary.
- **Data-egress transparency (GP-10/GP-11):** a plain-language, versioned **egress map** records
  exactly what each stage sends to which model/provider (e.g. abstracts + PMIDs → local Ollama;
  rights-cleared full-text spans → a named cloud model) and what **never leaves**. No new data class
  reaches any provider without updating the map. *(Practice adopted from ai4s/open-science.)*
- **Connector reuse (GP-4, candidate — needs ADR):** `biomcp` (variants / PubMed / ClinicalTrials) and
  `paper-search-mcp` (arXiv / PubMed / Crossref / bioRxiv) are existing MCP servers that overlap the
  Tier-3 retrieval layer; evaluate reusing them instead of hand-rolled clients. Gate on GP-10 (they
  make external calls) and GP-9 (must return resolvable citations).

## 9. Architecture decisions

See [DECISIONS.md](DECISIONS.md). Directly relevant: **ADR-0004** (runtime stack), **ADR-0003**
(build-time loop), **ADR-0001** (framing / validation ceilings).

## 10. Quality requirements

| Quality | Scenario | Target |
|---|---|---|
| Auditability | Any classification | Full evidence chain + provenance reproducible. |
| Freshness | ClinVar weekly update | Reflected within one weekly run. |
| Reliability | Unattended weekly run fails | Prefect retries + failure alert to operator. |
| Cost | Typical week | ~$0; bounded on paper-heavy weeks. |
| Reproducibility | Same inputs | Deterministic Tier 1/2 output. |

## 11. Risks & technical debt

| Risk | Mitigation |
|---|---|
| Worker vCPU allocation smaller than assumed | Confirm at deploy; fall back to smaller local model. |
| SQLite single-writer contention if parallel writes grow | Queen is sole writer; revisit Postgres only if needed. |
| Cloud provider/session-cap throttling | LiteLLM fallback + queueing; local-first routing. |
| Prompt/model drift changing extraction quality | Version prompts; **runtime evidence verifier** (deterministic citation/variant-match + optional 2nd-model adjudication + human review — *distinct from the build-time checker*); eval benchmark. |
| Circular validation via VCEP feedback | Freeze benchmark by date/source; provenance + hold-out set. |
| Non-commercial licensing blocks some users | Per-field licensing matrix; research-only vs redistributable output modes. |
| Correlated-evidence double-counting | Criterion-level evidence model (§8); each ACMG criterion fires once. |

## 12. Glossary

*(deferred — see STRATEGY.md and `pre-build/FYTSC_1.md` for VUS/ACMG/PS3/BIAS-2015/AcmGENTIC definitions.)*
