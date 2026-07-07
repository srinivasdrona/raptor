# RAPTOR — Decision Log (ADRs)

> Architecture/strategy decisions for RAPTOR, in **MADR** format (Markdown Any Decision Records,
> [adr.github.io](https://adr.github.io/madr/)). Newest at top. An ADR is **immutable once Accepted** —
> to change a decision, add a new ADR that supersedes it. This log is the source of truth for *why*
> RAPTOR is the way it is; `STRATEGY.md` §5/§9 must stay consistent with the Accepted ADRs here.

**Index**

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0004](#adr-0004--runtime-stack-litellm--prefect--sqlite--ollama-no-ray-no-langgraph) | Runtime stack: LiteLLM + Prefect + SQLite + Ollama (no Ray, no LangGraph) | Accepted | 2026-07-08 |
| [ADR-0003](#adr-0003--loop-operating-model-planner--doer--checker-across-three-model-families) | Loop operating model: planner / doer / checker across three model families | Accepted | 2026-07-08 |
| [ADR-0002](#adr-0002--vision--strategy-doc-format-pichler-vision-board--rumelt-kernel) | Vision & strategy doc format: Pichler Vision Board + Rumelt Kernel | Accepted | 2026-07-08 |
| [ADR-0001](#adr-0001--strategic-framing-narrow-buildable-claim-with-broad-north-star) | Strategic framing: narrow-buildable claim with broad north-star | Accepted | 2026-07-08 |

---

## ADR-0004 — Runtime stack: LiteLLM + Prefect + SQLite + Ollama (no Ray, no LangGraph)

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @sdrona_microsoft

### Context

The runtime pipeline is unattended, weekly, and very low volume: the ~6,700 TSC1/TSC2 VUS (4,445
TSC2 + ~2,290 TSC1) score in ~seconds (BIAS-2015); most weeks bring 0–5 new papers at an *estimated*
~$0 cost (pending measured token/full-text volumes). It is a *linear DAG with conditional
gates* (surveillance → screening → extraction → integration → reporting), not a cyclic agent system.
Parallelism is limited to splitting one batch across two VMs. Prior session questions explicitly
challenged whether LangGraph (turn 9) and Ray (turn 14) are needed. `STRATEGY.md` GP-7 requires the
least complexity that mirrors reality; GP-6 requires config-driven routing.

### Considered options

1. **LiteLLM + Prefect only** (minimal).
2. LiteLLM + Prefect + **Ray** (distributed workers).
3. LiteLLM + Prefect + **LangGraph** (agent/loop state).

### Decision

Adopt **option 1**: `LiteLLM` (model gateway/routing over local Ollama + cloud Foundry, config-driven,
fallback, cost logging) + `Prefect` (weekly schedule, retries, run history, observability + "what
changed" diff) + `SQLite` (versioned KB/state on the Queen) + `Ollama` (local inference on
EPYC/Xeon). **Drop Ray** — the 2-VM batch split is a `ThreadPoolExecutor`; volume never justifies
distributed compute. **Drop LangGraph** — the runtime pipeline is a native Prefect DAG; the only loop
is the *build-time* planner/doer/checker (ADR-0003), which is a dev process, not a runtime component.

### Consequences

- **Good:** minimal moving parts; each component earns its place; config-driven routing satisfies
  GP-6; matches the low-volume reality and the session-recorded skepticism about LangGraph/Ray.
- **Bad / deferred:** if volume or parallelism grows materially (multi-gene, real-time), Ray and/or
  Postgres are revisited via a superseding ADR. SQLite assumes a single writer (the Queen).

### Confirmation

Satisfied when the weekly flow runs end-to-end under Prefect with all model calls routed through
LiteLLM and state persisted in `variants.db`. Encoded in `ARCHITECTURE.md` §4–§8.

---

## ADR-0003 — Loop operating model: planner / doer / checker across three model families

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @sdrona_microsoft

### Context

RAPTOR is built solo, unattended for long stretches, across a local + cloud model fleet. The open
bottleneck recorded in `PROGRAM.md` was *"how to structure loop engineering unattended."* Prior
projects (OpenCell) showed that a single model doing plan+build+review drifts and self-approves its
own work — the checker must be a *different* model family from the doer so review is adversarial, not
confirmatory (see `STRATEGY.md` GP-1).

### Decision

Adopt an explicit **design → build → review → eval → (back to design)** loop, with a fixed
model-role assignment across three families so no single model both produces and blesses work:

| Loop stage | Role | Model family | Responsibility |
|---|---|---|---|
| **Design / plan** | **Planner** | **Claude Opus** | Decompose work, write the task spec + acceptance criteria, keep context lean. Does not write production code. |
| **Build** | **Doer** | **Claude Sonnet 5** | Implement against the planner's spec. Owns the code change end-to-end. |
| **Review / eval** | **Checker** | **GPT (GPT-5.x)** | Adversarially review the doer's output against the spec + acceptance criteria; run/eval; pass or send back. |

Rules:
1. **The checker is always a different model family from the doer** — adversarial review, not self-review.
2. **Every loop iteration produces a written spec (planner) and a written verdict (checker).** No silent hand-offs.
3. **A change is not "done" until the checker passes it against pre-stated acceptance criteria** (ties to `STRATEGY.md` GP-1 validation ceilings and the §8 KPIs).
4. Model *roles* are fixed; specific model versions are configurable (per `STRATEGY.md` GP-6, in config, not hardcoded).

### Consequences

- **Good:** adversarial separation reduces self-approval drift; written spec+verdict give an audit
  trail; roles map cleanly onto the loop stages and onto the eval gates already in the strategy.
- **Bad / cost:** three model families per iteration is more expensive and higher-latency than a
  single agent; requires orchestration (LiteLLM routing) and hand-off artifact plumbing.
- **Open:** exact hand-off artifact schema (spec + verdict formats) and gate automation — to be
  specified in `OPERATING_MODEL.md` / `ARCHITECTURE.md`.

### Confirmation

Satisfied when a task has flowed planner → doer → checker with a persisted spec and verdict, and the
checker's pass is gated on acceptance criteria.

---

## ADR-0002 — Vision & strategy doc format: Pichler Vision Board + Rumelt Kernel

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @sdrona_microsoft

### Context

The strategy/vision doc must be sharp, defensible to board-level and regulatory review, and
recognizable to any human reviewer. Requirement: use a **well-established, citable standard**, not a
bespoke invented structure.

### Considered options

1. **Roman Pichler Product Vision Board** (Vision · Target Group · Needs · Product · Business Goals) — strong on product/user clarity, weak on strategic action.
2. **Rumelt Kernel of Good Strategy** (Diagnosis → Guiding Policy → Coherent Action) — strong on focus/action, light on product specifics.
3. **Combined** — Pichler for the vision layer, Rumelt for the strategy spine.

### Decision

Adopt **option 3 (combined)**. `STRATEGY.md` uses the Rumelt Kernel as its spine
(Diagnosis §2 → Guiding Policy §5 → Coherent Action §7) and Pichler's board elements for the vision
layer (Vision §1, Target Group/Needs §4, Product §6, Business Goals §8).

### Consequences

- **Good:** both recognized frameworks; a reviewer can map every section to a named standard
  (documented in `STRATEGY.md` Appendix B).
- **Bad:** slightly longer than a single-framework doc.

---

## ADR-0001 — Strategic framing: narrow-buildable claim with broad north-star

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @sdrona_microsoft

### Context

RAPTOR welds three claims of very different difficulty and validatability: (a) variant
classification (measurable vs expert labels), (b) cross-domain linkage (oracle-poor), (c)
pathway-linked "discovery" (the thing LLMs are worst at). The headline differentiator lives in the
*unmeasurable* half. The adversarial framing thread (`pre-build/raptor framing.md`) concluded the project is
defensible only if each layer declares what validates it.

### Considered options

1. **Narrow-buildable as the committed claim** (TSC2 evidence engine + gap-map), broad cross-disease synthesis as an explicit long-term north-star; **each layer declares its validation ceiling**.
2. **Broad "rare-disease synthesis engine" as the headline**, ceilings noted underneath.
3. **TSC-only**, defer all cross-disease framing.

### Decision

Adopt **option 1**. Prove the measurable half first (variant classification vs ClinVar/expert
labels); ship cross-disease links **only** as cited, falsifiable hypotheses; reserve the word
**"discovery"** for the **gap-map**, never for unconfirmed mechanism. Recruit a molecular-geneticist
oracle before the cross-linkage layer is trusted.

### Consequences

- **Good:** every claim is defensible to a hostile domain reviewer; differentiator (gap-map) is
  honest; measurable half anchors trust before the risky half.
- **Bad:** the fundable-sounding "collapses cross-domain discovery" headline is deliberately
  dropped; the north-star is explicitly *not* the current claim.
- Encoded as `STRATEGY.md` GP-1/GP-2/GP-3 and §9 Scope.
