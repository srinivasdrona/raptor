# RAPTOR — Decision Log (ADRs)

> Architecture/strategy decisions for RAPTOR, in **MADR** format (Markdown Any Decision Records,
> [adr.github.io](https://adr.github.io/madr/)). Newest at top. An ADR is **immutable once Accepted** —
> to change a decision, add a new ADR that supersedes it. This log is the source of truth for *why*
> RAPTOR is the way it is; `STRATEGY.md` §5/§9 must stay consistent with the Accepted ADRs here.

**Index**

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0010](#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy) | Generic-platform uniqueness premise falsified; vertical TSC/mTOR research-evidence strategy | Accepted | 2026-07-10 |
| [ADR-0009](#adr-0009--clinvar-derived-acmg-criteria-direct-copy-banned-pp5bp6ps4-transitive-deferred-to-audit) | ClinVar-derived ACMG criteria: direct-copy banned (PP5/BP6/PS4), transitive deferred to audit | Accepted | 2026-07-10 |
| [ADR-0008](#adr-0008--tier-12-annotation-pipeline-bias-2015--nirvana-runs-on-an-x64-worker-not-the-arm-queen) | Tier-1/2 annotation pipeline (BIAS-2015 + Nirvana) runs on an x64 worker, not the ARM Queen | Accepted | 2026-07-08 |
| [ADR-0007](#adr-0007--bias-2015-integrated-at-arms-length-only-agpl) | BIAS-2015 integrated at arm's-length only (AGPL) | Accepted | 2026-07-08 |
| [ADR-0006](#adr-0006--scope-published_state_hash-to-ac3-defer-full-cross-db-canonical-fingerprint) | Scope `published_state_hash()` to AC3; defer full cross-DB canonical fingerprint | Accepted | 2026-07-08 |
| [ADR-0005](#adr-0005--test-strategy-separated-authorship-model-diversity-frameworks--domain-truth-data) | Test strategy: separated authorship, model diversity, frameworks & domain truth-data | Accepted | 2026-07-08 |
| [ADR-0004](#adr-0004--runtime-stack-litellm--prefect--sqlite--ollama-no-ray-no-langgraph) | Runtime stack: LiteLLM + Prefect + SQLite + Ollama (no Ray, no LangGraph) | Accepted | 2026-07-08 |
| [ADR-0003](#adr-0003--loop-operating-model-planner--doer--checker-across-three-model-families) | Loop operating model: planner / doer / checker across three model families | Accepted | 2026-07-08 |
| [ADR-0002](#adr-0002--vision--strategy-doc-format-pichler-vision-board--rumelt-kernel) | Vision & strategy doc format: Pichler Vision Board + Rumelt Kernel | Accepted | 2026-07-08 |
| [ADR-0001](#adr-0001--strategic-framing-narrow-buildable-claim-with-broad-north-star) | Strategic framing: narrow-buildable claim with broad north-star | Accepted | 2026-07-08 |

---

## ADR-0010 — Generic-platform uniqueness premise falsified; vertical TSC/mTOR research-evidence strategy

- **Status:** Accepted
- **Date:** 2026-07-10
- **Deciders:** @dronasrinivas (operator)
- **Supersedes (in part):** [ADR-0001](#adr-0001--strategic-framing-narrow-buildable-claim-with-broad-north-star) — the *differentiation* ("blue ocean") and *generalise-across-rare-disease north-star* framing only. ADR-0001's layered-validation-ceiling decision (GP-1/GP-2/GP-3) **stands**.

### Context

ADR-0001 framed RAPTOR as a narrow-buildable TSC claim with a **broad cross-disease north-star**, and
STRATEGY.md leaned on a **"blue ocean / no synthesis layer / no public deployed system"**
differentiation. Two things changed:

1. **The uniqueness premise was falsified.** A grounded competitor scan found multiple capable
   variant-interpretation / LLM-ACMG platforms (Deriva, Virtual Geneticist, Breakthrough Genomics,
   3billion AIVARI, eVai, VarChat, Golden Helix VSClinical, SeqOne DiagAI, Variant Bio — sources and
   claim-type classification in `docs/reference/competitive-landscape-2026-07.md`). The only claim that
   survives is narrow and dated: a **PubMed E-utilities search verified 2026-06-16** found **no
   indexed TSC-specific automated-classification campaign**, and **TSC VCEP ClinVar submissions were
   0** — an under-served vertical + unresolved *institutional/adoption* question, **not** "no capable
   platform exists" and **not** automatic demand.
2. **The first complete deterministic TSC1/TSC2 evidence census was executed** (6,618 VUS;
   `data/census/tsc_vus_clinvar_2026-07-07_stats.json`) — internal, eval-only, non-authoritative
   candidate directions, not classifications.

Continuing to justify RAPTOR by uniqueness, or to hold a generalise-to-all-rare-disease north-star,
is no longer defensible (GP-8).

### Considered options

1. **Vertical TSC/mTOR research-evidence product** — withdraw the uniqueness claim, freeze horizontal
   platform expansion, finish the deterministic TSC evidence program, reuse/buy generic engines, and
   gate any mTOR extension one at a time.
2. **Double down as a generic rare-disease variant-interpretation platform** — compete head-on with
   funded vendors on breadth. Rejected: no differentiated advantage, high burn, contradicts GP-4/GP-7.
3. **Abandon the effort because competitors exist** — rejected as competitor-overreaction; it discards
   a valuable open TSC benchmark/census and the auditability/freshness discipline.

### Decision

Adopt **option 1**:

- **The generic-platform uniqueness diagnosis is falsified** and withdrawn from STRATEGY.md.
- **Freeze horizontal/platform expansion** — no generic ACMG engine, generic literature-agent stack,
  or generic NGS pipeline (STRATEGY §9); freeze PRD-05/generic orchestration and generic Tier-3
  platform work (PROGRAM.md).
- **Retain and finish the deterministic TSC evidence program** — census done; the held-out validation
  gate (ADR-0009 audit + PRD-06 PASS) still governs any authoritative output.
- **Vertical TSC/mTOR research-evidence strategy** — the product is expert-reviewable candidate
  evidence packets, a TSC evidence/functional-assay/contradiction atlas, and gated mTOR-condition
  hypothesis packets (STRATEGY §1/§6).
- **Reuse/buy generic engines** (GP-4); the moat is the TSC-vertical evidence, not generic methodology.
- **Expansion / user / oracle gates** — new binding **GP-13**: every feature names a TSC/mTOR user,
  artifact, expert validator, falsifier, and why a generic product cannot supply it; mTOR extensions
  are admitted one at a time; a domain oracle is recruited before the layer that needs it (GP-3).

### Consequences

- (+) The strategy no longer depends on a falsified uniqueness claim; it rests on a defensible
  vertical contribution (open benchmark, auditability, freshness) that survives competitor existence.
- (+) Scope is bounded: GP-13 + §9 out-of-scope stop "all things TSC/mTOR" vertical-washing.
- (+) Preserves the sunk assets (census, benchmark, deterministic engine) without over-claiming them.
- (−) Drops the fundable-sounding "generalise across rare disease" headline (as ADR-0001 already
  cautioned) and the "blue ocean" story.
- (−) Adds governance load: each mTOR extension needs a full GP-13 gate + oracle before it ships.
- **History preserved:** ADR-0001 remains immutable; only its differentiation/north-star framing is
  superseded. New/updated risks: R-A12, R-D7, R-E4, R-F4/F5/F6, R-G5 (RISK_REGISTER.md).

---

## ADR-0009 — ClinVar-derived ACMG criteria: direct-copy banned (PP5/BP6/PS4), transitive deferred to audit

- **Status:** Accepted
- **Date:** 2026-07-10
- **Deciders:** @dronasrinivas (Oracle)

### Context

The frozen benchmark (EVAL_PLAN §2) uses **ClinVar-derived labels**. The Tier-1/2 scorer is
**BIAS-2015 v3.0.0** (ADR-0007/0008). The first real x64-devbox BIAS output (2026-07) revealed which
of BIAS's per-criterion rationales are **sourced from ClinVar's own classifications** — grading such a
criterion against ClinVar labels reads the answer key (R-A2 circularity). Two distinct kinds surfaced:

- **Direct copy** — the criterion reads the *variant's own* ClinVar assertion: **PP5** ("reported
  pathogenic in ClinVar"), **BP6** ("reported benign in ClinVar"), and **PS4** — BIAS v3.0.0 falls
  back to counting ClinVar submitters ("No GWAS data found. N independent ClinVar submitters
  classify…") when no GWAS/case-control data exists, which for a rare Mendelian disorder is nearly
  always. (PP5/BP6 are also ClinGen-SVI-2018-deprecated.)
- **Transitive / aggregate (comparator-dependent)** — the criterion reads *other* variants' ClinVar
  data. **Static criterion lineage identifies five:** **PS1** (same amino-acid change previously
  reported pathogenic), **PM5** (same-residue variant reported pathogenic), **PM1** (domain ClinVar
  pathogenic/benign rate), **PP2** (gene missense pathogenic/benign proportions), and **BP1** (gene-level
  truncating-vs-missense proportions). These are how the criteria legitimately work in ACMG
  practice; excluding them strips real evidence — notably PS1/PM5, prime **missense** signal (the gated
  stratum). Held-out validation must **mask** the held-out variants from these comparator resources;
  actual VUS production legitimately uses the **full** comparator resources.

### Considered options

1. **Ban only the direct-copy criteria now (PP5/BP6/PS4); decide the transitive bucket with data** —
   build an automated ClinVar-derivation guard, run it on the full held-out to get real firing counts,
   then rule on PS1/PM5/PM1/PP2/BP1.
2. **Ban every ClinVar-touching criterion** (maximal purity) — safest against circularity but strips
   legitimate missense evidence and likely lowers measured missense recall.
3. **Keep transitive as legitimate ACMG** and instead enforce held-out independence.
4. **Re-annotate with ClinVar stripped from Nirvana** (data-level) — bulletproof but breaks
   eval=production parity, is the bluntest instrument, and costs a devbox re-run (see the Option-C
   analysis in-session).

### Decision

Adopt **option 1**. **PP5, BP6, and PS4** are added to `eval.config.FORBIDDEN_CRITERIA` (structurally
banned from `automatable_criteria` at load *and* skipped in the combiner — case/whitespace-robust) and
removed from both `configs/eval/tsc2.yaml` (`automatable_criteria`) and `configs/acmg/tsc.yaml`
(`included_criteria`) so eval and production stay identical. The **transitive / comparator-dependent**
criteria (PS1/PM5/PM1/PP2/BP1, per static criterion lineage)
are **deferred**: an automated ClinVar-derivation guard/audit (built next, via the loop) enumerates
every ClinVar-sourced *scored* criterion on the full held-out output; the Oracle then rules on the
comparator-dependent bucket **with real firing counts in hand**, not blind. Held-out validation reruns
on comparator resources with the held-out variants **masked**; VUS production uses the full resources.

**Audit outcome (2026-07-10).** The source-derived BIAS-3.0.0 policy establishes 28 rationale slots,
19 internally can-fire criteria, and 9 internal stubs. It corrects the prior coincidental registry:
BS3/BS4 are stubs; PS3/BS2 can fire but remain deferred. The full 2,577-row held-out audit recorded
PS1=116, PM5=13, PM1=0, PP2=0, BP1=0 and failed closed on PS1/PM5. Zero incidence does not revise
static lineage: masked validation resources remain required for all five comparator-dependent
criteria. Aggregate record: `data/census/tsc_bias_lineage_audit_2026-07-10.json`.

**Engineering follow-through (2026-07-12).** RAPTOR now has deterministic upstream masking +
conservation-audit tooling for all five comparator-dependent criteria, a canonical-SPDI BIAS adapter,
and an exact lower-confidence-bound gate. The external BIAS generators have **not** yet rebuilt the
masked resources and no final gate has run. Separately: the BP4/PP3 aggregation defect is corrected at
the arm's-length wrapper (7,985 real firings, zero undecidable); BS2 remains deferred after a 34-firing
review; TSC transcript version deltas require canonical-SPDI provenance and NTHL1 remains out-of-scope.
The production criterion-strength map is populated but explicitly **unapproved**, with null cutoffs and
null candidate direction. These controls prepare measurement; they do not authorize a classification.

#### Evaluation-only BP4/PP3 correction approval (2026-07-13)

The domain owner approved the arm's-length BP4/PP3 correction **only for the
masked held-out evaluation**. The approval is bound to:

- aggregation spec SHA-256:
  `2c89bb17dea68fc9ed294eee2108bdd528e551eb4882b47cc4a400d683aca2ae`;
- correction-bundle SHA-256:
  `19aa2ed835c05bcd3615ea1744fd654d33ca1c81d77abd852e89fcb7707e2c45`;
- policy artifact: `configs/eval/bp4pp3_predictor_policy.json`.

The real-corpus probe found 7,985 fired BP4/PP3 rows and zero undecidable
rationales, so the observable BIAS output is sufficient for deterministic
reconstruction. This approval does **not** approve the production
criterion-strength map, candidate-direction cutoffs, variant classifications,
ClinVar submissions, or clinical use. The current masked evaluation also
excludes PM1 after a zero-support/global-reproduction mismatch; therefore even
a numeric gate pass must not authorize full VUS scoring.

**Executed outcome (2026-07-13).** The masked 2,577-row terminal evaluation
returned **FAIL** on the binding missense stratum; `vus_authorized=false`.
Missense pathogenic precision/recall lower bounds were `0.6042/0.7131` and
benign precision/recall lower bounds were `0.8378/0.7632`, below the
pre-registered `0.90/0.85` thresholds. Overall performance cannot average away
that result. No threshold is relaxed post hoc. The next validation work is
missense error/abstention analysis plus expert review, followed by a newly
pinned rerun; production policy, external worklists, and submissions remain
blocked. Aggregate source of record:
`data/census/tsc_masked_holdout_gate_2026-07-13.json`.

### Consequences

- (+) Closes the unambiguous direct-copy leak before benchmark metrics. Removing circular evidence may
  move precision and recall in different directions; the justification is **measurement validity**,
  not a guaranteed conservative numeric bias.
- (+) Keeps eval = production (both exclude PP5/BP6/PS4), so the gate faithfully measures the deployed
  classifier.
- (−) Loses BIAS's case-control PS4 — negligible for TSC (BIAS produces PS4 almost exclusively via the
  ClinVar fallback for a rare disorder).
- (−) The transitive question stays open until the full-held-out audit; the first gate run is blocked
  on that audit + ruling.
- **Follow-up:** `ps4-clinvar-circularity` (done here), `gate-ci-lower-bound`, and the ClinVar-
  derivation guard/audit (the mechanized full-output audit) — see session todos.

---

## ADR-0008 — Tier-1/2 annotation pipeline (BIAS-2015 + Nirvana) runs on an x64 worker, not the ARM Queen

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas

### Context

PRD-01 (Tier-1/2 scorer) reuses **BIAS-2015** (GP-4), which requires **Illumina Nirvana** (annotator)
+ **.NET 6** + multi-GB annotation data to turn a VCF into the annotated JSON it scores. **Nirvana
has no official ARM64 build** (x64 Linux/macOS/Windows only) and is **proprietary** (cannot recompile
for aarch64). The primary dev/build machine (the "Queen") is a Snapdragon **aarch64**. QEMU emulation
of Nirvana on ARM is unsupported, slow, and fragile.

### Decision

The **BIAS-2015 + Nirvana annotation pipeline runs on an x64 host** (an EPYC/Xeon fleet worker or a
cloud x64 VM), which also hosts the multi-GB Nirvana/BIAS data. The **ARM Queen** runs only RAPTOR's
own pure-Python scorer **wrapping/policy layer** and orchestration. RAPTOR's scorer reaches the
pipeline through a **BIAS port** (PRD-01 build contract); the machine boundary lands at that port.

### Consequences

- (+) Solves three problems at once: ARM incompatibility, AGPL arm's-length isolation (ADR-0007 — a
  separate process on a separate host is the strongest boundary), and keeping GBs off the Queen.
- (+) Matches the fleet model (STRATEGY/ARCHITECTURE): heavy x64 annotation on workers, light
  orchestration on the Queen.
- (−) Adds a cross-machine hop for Tier-1/2 (previously assumed single-machine). Mitigated: the live
  pipeline is **deferred** — PRD-01 v1 builds+validates the wrapping layer against BIAS's own
  expected-output fixtures (independent oracle); the x64 worker integration is a later step.
- **Risk:** R-B6 (annotation-host x64 dependency / cross-machine coupling) — see RISK_REGISTER.

---

## ADR-0007 — BIAS-2015 integrated at arm's-length only (AGPL)

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas

### Context

BIAS-2015 (bitscopic) is the reused Tier-1/2 ACMG engine (GP-4), **dual-licensed AGPL-3.0 / commercial**
(free for academic use). AGPL is strong copyleft with a **network clause (§13)**: if code that
`import`s BIAS forms a *combined work* and is offered to users **over a network**, the complete source
of the **combined work** (i.e. RAPTOR itself) must be released under AGPL. That would foreclose any
future commercial/proprietary licensing of RAPTOR and force RAPTOR's source disclosure the moment it
is offered as a VCEP service — a one-way door incompatible with RAPTOR's clinical ambitions.

### Decision

RAPTOR integrates BIAS-2015 **at arm's-length only**: invoke it as a **separate program** (its CLI /
a service on a separate host — ADR-0008), exchanging data via files (VCF/JSON/TSV). RAPTOR **never
imports BIAS-2015 modules** and never copies its source into the RAPTOR tree. The boundary is the
PRD-01 **BIAS port** (a clean data interface). This is "mere aggregation" (FSF arm's-length doctrine)
— RAPTOR keeps its own license, unencumbered by AGPL.

### Consequences

- (+) RAPTOR's licensing stays free of AGPL copyleft; future commercial/proprietary options preserved.
- (+) The port boundary also enables ADR-0008 (run BIAS on an x64 worker) and swapping annotators
  (BIAS supports Nirvana **or** VEP) without touching RAPTOR core.
- (−) No in-process calls to BIAS internals; all interaction is through its documented CLI/output
  contract (which is a data boundary, not a stable API — pin the BIAS version, treat output as a
  source-contract like R-B1).
- **GP-10/R-B2:** commercial *deployment* of BIAS still requires Bitscopic's commercial license — a
  procurement item, tracked, not a code concern for academic build/validation.

---

## ADR-0006 — Scope `published_state_hash()` to AC3; defer full cross-DB canonical fingerprint

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas

### Context

PRD-03 AC3 requires detecting a partial/failed publish — a **same-DB before/after** hash comparison.
During the build, `published_state_hash()` was additionally engineered as a **cross-DB canonical
logical fingerprint** (two different DBs with the same logical content hash equal). That stronger
property proved to be a deep serialization problem: six checker rounds each found a real but
progressively narrower cross-DB edge case (ledger-order, evidence_id, source_ref_id + snapshot_id,
content-rank tie-breaking, snapshot scope, `str()` type-coercion, and finally JSON-TEXT key-order).
The surrogate-leak *class* was verified closed (complete registry); the remaining gap is JSON-column
key-order canonicalization. **Every one of these edge cases affects only cross-DB comparison — none
affects AC3** (within one DB across a failed publish, values do not change).

### Decision

**Scope the binding contract of `published_state_hash()` to AC3 (same-DB atomic-publish detection),
which is fully met (100 tests green).** The cross-DB canonical fingerprint is retained as a
**best-effort** capability with **one documented known limitation** — JSON TEXT columns other than
`ledger.payload` (`provenance`, `approvals`, `config_pins`, `strength_vocab`) are hashed raw, so
different DBs whose JSON differs only by key order may hash differently. **Full JSON canonicalization
(a `_JSON_COLUMNS` registry) is DEFERRED** to the reproducibility work (R-A11), where a cross-DB
"same logical KB?" check would actually be consumed. A **hard stop** was invoked after round 6 to
prevent open-ended iteration on a property nothing yet depends on (GP-7).

### Consequences

- **Good:** PRD-03 signs off on its actual ACs without further iteration; the ~95%-complete
  fingerprint + its property tests (Gemini-authored) are kept and green; the gap is documented in
  code (`published_state_hash` docstring) + PRD-03 §10, not hidden (anti-H4).
- **Bad / deferred:** the cross-DB fingerprint is not fully canonical yet; anything that later relies
  on it for reproducibility (R-A11) must first finish JSON canonicalization.
- **Process note:** the six-round saga validated the loop — the different-family checker + Gemini's
  schema-enumerated tests caught defects the doer's own 78→100 green suite never did. It also showed
  the value of a pre-committed **hard stop** to convert an open-ended rabbit hole into a bounded,
  documented scope decision.

### Confirmation

Satisfied: AC3 tests green; the known limitation is documented in `store.py` and PRD-03 §10; a
follow-up (R-A11 JSON canonicalization) is tracked.

## ADR-0005 — Test strategy: separated authorship, model diversity, frameworks & domain truth-data

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas
- **Refines:** ADR-0003 (adds a 4th role + test-tooling to the loop)

### Context

The PRD-03 (KB) build shipped 78 green tests that hid 5 real bugs, caught only by the different-family
checker. Root cause: the doer wrote code **and** tests in one pass, so the tests inherited the code's
blind spots (confirmation bias — RISK_REGISTER H2/H4). The checker is post-facto; we want pre-facto
defenses, and to keep the planner's context clear of operational test-writing.

### Decision

1. **Separated test authorship with model diversity.** For foundational/high-assurance modules a
   dedicated **test-author agent = Gemini** writes the acceptance tests **from the spec only** (never
   seeing the doer's code), *before* the doer builds. Roles now span **four families** — planner
   (Opus) · test-author (Gemini) · doer (Sonnet) · checker (GPT) — so the test-author differs from
   both the doer and the checker. Gemini is chosen for **family-independence** (the doer is Claude, so
   a Claude test-author would re-share the blind spot) and its spec/doc-driven strength — not because
   it is the single best test-writer (Claude is). The **planner owns the test *contract*** (which
   ACs/invariants) but **delegates the test *code***, staying context-clean.
2. **Local models are NOT used for foundational test authoring.** A weaker author can't catch a
   stronger doer's bugs; Windows-ARM Ollama is CPU-bound; heavy models want the 64GB workers, not the
   32GB Queen. Reserve local models (**Qwen2.5-Coder-14B/32B**) for Tier-3 abstract screening and
   later low-stakes/bulk generation.
3. **Adopt two SE frameworks** (dev-only deps): **Hypothesis** (property-based tests for core
   invariants — ~50× more mutant-killing than examples, and harder to game) and **mutation testing**
   (`mutmut`, run selectively on core modules) as the *mechanical* anti-hollow-green control — it
   fails when tests don't catch injected mutations.
4. **Domain truth-data & reusable fixtures — scoped honestly.** RAPTOR *classifies* variants, it does
   **not call** them, so variant-**calling** benchmarks (GIAB, hap.py, vcfeval, nf-test) are **out of
   scope**. Reuse instead: **`biocommons/hgvs` test vectors** (independent normalization fixtures →
   seed PRD-02 AC3, breaking the self-verification circularity), **`bitscopic/BIAS-2015` test suite**
   (how the 19/28 ACMG criteria are validated → PRD-01), **GA4GH normalization *concepts*** for
   representation equivalence (R-A10), and **ClinGen/ClinVar expert labels** as classification truth
   (already the EVAL_PLAN label hierarchy).

### Consequences

- **Good:** attacks the confirmation-bias root cause pre-facto; keeps planner context clean; mutation
  testing gives a mechanical hollow-green detector; independent domain fixtures remove AC3 circularity.
- **Cost:** one more agent per foundational build (slower + more spend) — applied to foundational
  modules only; lighter for low-risk ones (GP-7). Mutation testing is slow → selective, not every run.
- **Open:** whether the test-author sees the *checker's* prior verdicts on re-runs (leaning yes, to
  target regressions) without seeing the doer's code.

### Confirmation

Satisfied when a foundational module's acceptance tests are authored by Gemini from the spec, the
Sonnet doer passes them without weakening, `hypothesis` covers the core invariants, and `mutmut` on
the core module reports no surviving mutants in the critical paths.

## ADR-0004 — Runtime stack: LiteLLM + Prefect + SQLite + Ollama (no Ray, no LangGraph)

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas

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
- **Deciders:** @dronasrinivas

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
- **Deciders:** @dronasrinivas

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

- **Status:** Accepted · **Superseded in part by** [ADR-0010](#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy) (the "blue ocean" differentiation + generalise-across-rare-disease north-star framing only; the layered-validation-ceiling decision below **stands**)
- **Date:** 2026-07-08
- **Deciders:** @dronasrinivas

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
