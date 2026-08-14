# RAPTOR — Decision Log (ADRs)

> Architecture/strategy decisions for RAPTOR, in **MADR** format (Markdown Any Decision Records,
> [adr.github.io](https://adr.github.io/madr/)). Newest at top. An ADR is **immutable once Accepted** —
> to change a decision, add a new ADR that supersedes it. This log is the source of truth for *why*
> RAPTOR is the way it is; `STRATEGY.md` §5/§9 must stay consistent with the Accepted ADRs here.
>
> **Authority note.** The maintained authority set now also includes `STRATEGY.md` Part II and
> `EVALUATION.md`; preserved ADR bodies may retain split-era citations as historical text, with the
> compatibility stubs and crosswalk below providing the current route.

**Index**

| ID | Title | Status | Date |
|----|-------|--------|------|
| [ADR-0018](#adr-0018--raptor-rescuescreen-a-gated-research-only-structural-rescue-track-downstream-of-reviewed-mechanism-evidence) | RAPTOR RescueScreen: a gated, research-only structural-rescue track downstream of reviewed mechanism evidence | Accepted | 2026-08-15 |
| [ADR-0017](#adr-0017--dual-atlas-panel-products-a-post-result-technical-coverage-panel-separated-from-a-still-blocked-independent-validation-panel) | Dual Atlas panel products: a post-result technical-coverage panel separated from a still-blocked independent-validation panel | Accepted | 2026-08-15 |
| [ADR-0016](#adr-0016--deterministic-offline-citation-resolver-and-phase-2-promotion-span-verification) | Deterministic offline citation resolver and Phase 2 promotion span verification | Accepted | 2026-07-27 |
| [ADR-0015](#adr-0015--atlas-internal-summaries-are-context-only-and-r611q-is-the-first-phase-2-anchor) | Atlas internal summaries are context-only and R611Q is the first Phase 2 anchor | Accepted | 2026-07-27 |
| [ADR-0014](#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary) | Generic Mechanism Atlas core with a versioned disease-pack boundary | Accepted | 2026-07-22 |
| [ADR-0013](#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock) | Tiered gate v3: post-hoc re-adjudication and prospective validation lock | Accepted | 2026-07-22 |
| [ADR-0012](#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun) | PP3/BP4 automated emission disabled for the current masked rerun | Accepted | 2026-07-21 |
| [ADR-0011](#adr-0011--scope-specific-research-authorization-gate-v2-truncating-pathogenic-research-scope-preregistered-separately-from-full-spectrum-vus) | Scope-specific research authorization gate (v2): truncating-pathogenic research scope preregistered separately from full-spectrum VUS | Accepted | 2026-07-14 |
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

## ADR ↔ risk crosswalk (maintained index)

> **Authority note.** ADRs are immutable accepted-history records. [`RISK_REGISTER.md`](RISK_REGISTER.md)
> is the living ISO-31000-style control record: likelihood, indicators, mitigation, contingency, and
> residual status may change without rewriting historical ADR bodies.

| ADR | Current risk linkage | Basis in current repo |
|---|---|---|
| **ADR-0018** | R-G1, R-G2, R-A6, R-B2, R-D7 | RescueScreen is a separately versioned, research-only lane whose entry gates, closed output vocabulary, no-go states and eight firewalls keep every computational output a hypothesis, forbid compound/treatment/combination recommendation and vendor procurement, bar docking scores from being read as affinity or efficacy, and require per-artifact licence verification instead of an "everything is open" assumption; the ACMG/classification and Atlas-promotion firewalls preserve ADR-0009/ADR-0015 and the ADR-0010 vertical boundary. |
| **ADR-0017** | R-A13, R-A15, R-A2, R-A14 | Splitting the technical-coverage engineering product from the independent-validation scientific product prevents post-result reinterpretation of the audited `INFEASIBLE_PANEL` run (R-A13), fixes an explicit machine-readable claim ceiling per product against authorization overclaim (R-A15), blocks the "relax P2/D3 after seeing the answer" validation mirage (R-A2), and records source scarcity as `BLOCKED_SOURCE_DIVERSITY` rather than as a failure or a licence to weaken constraints (R-A14). |
| **ADR-0016** | R-A2, R-A6, H1 | Deterministic offline resolver enforces ADR-0015 grounding: primary-source/dataset direct-leaf resolution + exact normalized-slice span verification with from-disk hash recompute, closing presence-only Gate 4 and truthy-boolean Gate 3 laundering while keeping acquisition out of scope (no network). |
| **ADR-0015** | R-A2, R-A6, H1 | Internal summaries may guide searches but cannot ground claims; primary-source exact-span admission prevents circular citation laundering while preserving unknown/conflicting/empty outcomes. |
| **ADR-0014** | R-A2, R-A12 | Generic-core / versioned-disease-pack boundary keeps mechanism evidence classification-free (R-A2 circularity) and preserves ADR-0010's vertical TSC/mTOR scope discipline (R-A12) while enabling internal cross-condition amortization; no second-disease claim until a portability experiment passes. |
| **ADR-0013** | R-A13, R-A14, R-A15 | Explicit risk rows cite ADR-0013's post-hoc / prospective-lock consequences. |
| **ADR-0012** | — | No standalone risk row names ADR-0012 today; current residue is tracked through the ADR-0013-linked rows above. |
| **ADR-0011** | R-A15 | Scope-authorization wording and the research-use disclaimer in `EVALUATION.md` Part II §5b define the overclaim boundary. |
| **ADR-0010** | R-A12, R-D7, R-E4, R-F4, R-F5, R-F6, R-G5 | Explicitly listed in ADR-0010 consequences and mirrored in the current register. |
| **ADR-0009** | R-A2, H1 | ADR-0009 bans direct-copy ClinVar criteria and masks comparator-dependent criteria to prevent answer-key circularity. |
| **ADR-0008** | R-B6 | Explicitly called out in ADR-0008 consequences and the current register. |
| **ADR-0007** | R-B1, R-B2, R-B6 | ADR-0007 sets the arm's-length / licensing boundary and treats BIAS output as a source contract; R-B6 operationalizes that boundary. |
| **ADR-0006** | R-A11 | Explicitly deferred to reproducibility work in ADR-0006 consequences. |
| **ADR-0005** | H2, H4, R-A10 | ADR-0005 is the separated-authorship / property-testing response to hollow-green and representation-equivalence risks. |
| **ADR-0004** | — | No direct current risk row cites ADR-0004; its consequences are architectural, not a named current risk mapping. |
| **ADR-0003** | R-D1 | Explicitly cited in the checker rubber-stamp / skipped-loop risk row. |
| **ADR-0002** | — | Document-format ADR only; no direct current risk row cites it. |
| **ADR-0001** | — *(partially superseded by ADR-0010)* | Historical strategy framing record; current linked risks are carried by ADR-0010 instead. |

---

## ADR-0018 — RAPTOR RescueScreen: a gated, research-only structural-rescue track downstream of reviewed mechanism evidence

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `design/panel-products-rescue-screen-2026-08`
- **Supersedes:** none. Additive and strictly downstream. Preserves ADR-0009 (no ClinVar/classifier
  leakage), ADR-0010 (vertical, non-clinical scope), ADR-0011 (scope-authorization boundary),
  ADR-0014 (generic core / disease-pack boundary), ADR-0015 (internal summaries are context-only;
  reported rescue observations are research evidence in their exact experimental context, never
  treatment advice) and ADR-0016 (exact-span grounding). Binds
  `docs/project/specs/structural-rescue-screen-v1.yaml` (rev 1).

### Context

Phase 2 grounding produced reviewed-in-principle mechanism statements about a TSC2 missense allele:
loss of hamartin/TSC1 complex formation in a reported system (PMID 18230340, DOI
10.1016/j.bbrc.2008.01.077); susceptibility to enhanced Pam/MYCBP2 ubiquitination with inability to
bind hamartin in that system (PMCID PMC2435383, PMID 18308511, DOI 10.1016/j.cellsig.2008.01.020);
general TSC1-dependent TSC2 stabilization plus HERC1 and Hsp70/Hsp90 proteostasis evidence (PMID
16464865; PMCID PMC5730846 / PMID 29127155); and residue-level coverage of position 611 in
experimental structure PDB 9CE3 (PDBe residue mapping; PMID 39565846, DOI 10.1126/sciadv.adr5807).

Those facts invite an obvious next question — could a small molecule stabilize the complex? — and
that question is exactly where a research-evidence project fails catastrophically if it is answered
casually. The available material does **not** support a defined Arg611–TSC1 salt bridge, does
**not** establish endogenous misfolding or rapid-degradation kinetics for the allele, and does
**not** establish that AlphaFold 3 reliably predicts the mutation-induced shift. A stabilizing
compound is a **hypothesis**. A stabilizer-plus-everolimus dose or toxicity benefit is
**unsupported** and would be a treatment claim.

The concrete failure modes are well known and mutually reinforcing: docking scores reported as
affinity; an uncalibrated ranking presented as a hit list; fixed thresholds copied from unrelated
papers (a 15 Å site radius, a 300–1000 Å³ pocket window, a top-0.1% cut, a −8.5 kcal/mol cutoff,
20×100 ns of simulation) used as if they were universal gates; a 10M-compound screen launched
because the library exists; "everything is open source" asserted over a stack whose licences
materially differ (AlphaFold 3's Apache-2.0 **code** does not license its **weights or outputs**;
ColabFold is not AF3; FoldX is licence-controlled; PremPS is a third-party web server; Enamine REAL
is commercial vendor data; ChEMBL is CC BY-SA 3.0; pocket, docking and MD tooling each carry
different terms; ZINC and UniProt terms need re-verification); vendor purchase links produced before
any assay gate; and an LLM-assembled pipeline called validated because it ran without crashing.

The alternative failure is equally real: refusing to plan this work at all, so it later happens
ad hoc, ungoverned, under deadline pressure.

### Considered options

1. **Do the screening work inside the Atlas pipeline.** Rejected: it would let computational
   structural output flow back into evidence status and, through it, toward classification —
   precisely the circularity ADR-0009/ADR-0015 exist to prevent.
2. **Refuse the direction entirely.** Rejected: the mechanism evidence legitimately raises a
   falsifiable question, and an unplanned lane is more dangerous than a gated one.
3. **Define a separate, separately versioned, research-only lane with hard entry gates, an ordered
   stage ladder, a closed earned-term vocabulary, explicit no-go states and non-negotiable
   firewalls.** Adopted.

### Decision

Adopt **option 3** as **RAPTOR RescueScreen**, specified in
`docs/project/specs/structural-rescue-screen-v1.yaml`.

1. **Four-valued mechanism ledger.** `SOURCE_REPORTED` records a narrow statement found in a
   cited source but not yet accepted by RAPTOR; `OBSERVED` is reserved for accepted/reviewed
   primary evidence with an exact verified span and its experimental context; the other states
   are `UNSUPPORTED` and `HYPOTHESIS`. The current $R611Q$ statements remain
   `SOURCE_REPORTED` because Gate 8 is blocked and the accepted-claim count is zero.
   `SOURCE_REPORTED` and `UNSUPPORTED` entries may not be used as accepted mechanism premises or
   upgraded by computation. Context travels with the statement: "in that system" is part of it.
2. **Five entry gates, all required, all currently `NOT_SATISFIED`.** A Gate 8-reviewed mechanism
   representation (else an explicit `MECHANISM_UNVERIFIED` stop); exact transcript/residue/structure
   mapping with residue arithmetic prohibited; experimental-structure coverage and uncertainty;
   a lawful per-artifact tool/data/licence registry; and a tractable construct and assay plan. There
   is no partial entry.
3. **Seven ordered stages.** Target/mechanism hypothesis → structure ensemble and provenance →
   pocket hypothesis and falsifier → **small calibrated pilot** docking → orthogonal rescoring and
   MD with convergence controls → compound hypothesis package → experimental assay cascade. A
   large-library or full-complex screen is never the default; it requires an explicit compute and
   storage budget plus a staged funnel with predeclared stage sizes and pass criteria.
4. **Closed, earned output vocabulary.** `STRUCTURAL_HYPOTHESIS`, `POCKET_HYPOTHESIS`,
   `COMPUTATIONAL_SCREENING_HIT`, `ORTHOGONALLY_REPLICATED_HIT`, `EXPERIMENTALLY_CONFIRMED_BINDER`,
   `COMPLEX_RESCUE_OBSERVED`, `FUNCTIONAL_RESCUE_OBSERVED` — each earned only at its stage, with the
   last three reachable only from wet-lab work. `lead`, `drug`, `therapy`, `predicted Kd` and
   `treatment candidate` are forbidden without separately specified evidence.
5. **Seven no-go states**, each terminal and each a legitimate publishable outcome: residue/interface
   unresolved, no plausible pocket, model disagreement, uncalibrated docking, licence incompatible,
   no tractable orthogonal assay, and aggregation/interference/toxicity. A no-go is never resolved
   by loosening parameters or switching to a friendlier method.
6. **Ordered assay cascade.** Abundance/turnover, ubiquitination and proteasome controls first;
   then at least two methodologically orthogonal direct-binding measurements (a thermal-shift or
   cellular thermal-stability readout alone is insufficient); then WT/mutant and selectivity
   comparisons, an inactive structural analog, aggregation/interference and cytotoxicity
   counter-screens, dose-response, and replicate and lot controls; then co-IP or an equivalent
   native-complex rescue readout; then a proximal Rheb-GAP/complex-state readout where feasible plus
   downstream p-S6K/p-S6. An everolimus combination matrix is **optional, exploratory, and only
   after single-agent rescue is observed and controlled**, with no synergy, dose-sparing,
   toxicity-reduction, feedback or clinical claim of any kind.
7. **Threshold discipline.** The quoted fixed numbers above are **rejected as universal gates**.
   They are admissible only as preregistered pilot parameters accompanied by a declared sensitivity
   range and its result; a parameter whose plausible range changes the conclusion means the
   conclusion does not survive.
8. **Licence registry, fail-closed.** Every tool, model, weight set, structure, library and derived
   dataset is registered and individually verified with version, licence, permitted use,
   redistribution/commercial status, locator and retrieval date. Absence of evidence of permission
   is not permission. Applicability of attribution, share-alike, non-commercial, redistribution and
   output restrictions is assessed per derived artifact; propagation is not assumed as a blanket
   legal rule.
9. **Eight firewalls.** RescueScreen may not alter or inform any ACMG evidence item or
   classification; may not promote or corroborate an Atlas claim; may not recommend a compound,
   treatment, therapy, dose or combination; may not report a docking, rescoring or simulation value
   as affinity, potency or efficacy; may not generate vendor purchase links before a complete,
   licence-cleared, assay-gated package; may not treat "it ran" as validation; must keep every
   computational result a hypothesis until its next gate; and may not produce clinical or
   patient-directed content.

### Consequences

- The lane is **designed and unreachable**: all five entry gates are `NOT_SATISFIED` today, chiefly
  because no named human reviewer is engaged and the accepted Atlas claim count is zero. That is the
  intended state, and it is visible rather than implicit.
- The durable task graph orders mechanism verification, structure/interface verification, the
  licence registry and assay feasibility strictly **before** any pilot docking, so screening cannot
  start early by accident. No task in the graph is marked complete.
- Honest negative outcomes become reportable products of the lane: no plausible pocket, model
  disagreement, insufficient structure coverage or no tractable assay each terminate the lane
  cleanly instead of being engineered around.
- The cost is deliberate slowness. Several gates may never open — for example if the interface is
  not resolvable at the needed quality, or if no orthogonal binding and complex-rescue assay pair is
  realistic for the construct. Not opening is the correct outcome, not a project failure.
- Backout is a straight revert of the spec, the ADR and its todos; nothing is implemented, and no
  code, data, protocol, registration, universe, map or run record is touched.

---

## ADR-0017 — Dual Atlas panel products: a post-result technical-coverage panel separated from a still-blocked independent-validation panel

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `design/panel-products-rescue-screen-2026-08`
- **Supersedes:** none. Additive. Preserves the audited 2026-08-06 `INFEASIBLE_PANEL` result and the
  frozen panel-selection protocol v1.0.4, its registration, universe lock v4 and identity-map lock
  v4 unchanged. Complements ADR-0014/ADR-0015/ADR-0016. Binds
  `docs/project/specs/atlas-panel-products-v1.yaml` (rev 1).

### Context

On 2026-08-06 the independently reviewed formal selector returned `INFEASIBLE_PANEL`
(`data/atlas/tsc2_phase2_panel_selection_run_2026-08-06.json`, SHA-256
`5f5b0918a24fcaa737877a15e393773f20c584c531517133e9c8b7e7574cfffd`). All 24 fixed-size attempts
across ladder levels L0–R7 completed **exhaustively** — maximum 714 nodes expanded against a
5,000,000 budget, no attempt `UNDETERMINED`, no relaxation step applied, zero members selected, and
a complete 35-row disposition audit. The infeasibility is therefore a property of the **substrate**,
not of the search: 32 of 35 records and all 37 attributable observations carried unknown lineage
and collapsed into a single `LG:UNKNOWN-POOL`, 10 of 35 identities were unresolved, and every
stratum had zero coverage at every attempted size.

That result blocked two different things at once, because one artifact had been asked to serve two
incompatible purposes. The **engineering** purpose was to exercise identity → source → span →
context → abstention across diverse situations and show the machinery behaves — including that it
abstains, blocks and reports contradictions correctly. The **scientific** purpose was to show the
mechanism ontology generalizes beyond the R611Q anchor on independently sourced, assay-diverse
evidence. Only the second needs source independence, because only the second makes a
generalization claim.

Bundling them created direct pressure to relax P2 (minimum established independent source groups)
and D3 (assay-kind concentration cap) so that "the panel" could exist. Doing that **after** seeing
the negative result would be outcome-dependent constraint selection: it converts a scientific gate
into a convenience knob and makes the original result unfalsifiable in retrospect. The frozen
protocol already forbids weakening constraints outside its ladder or substituting candidates after
this result.

Separately, a hash-selected six-variant technical repeatability cohort (`tsc2-gate-smoke-v1`,
`cohort_content_hash` `99462b30…9832388`) had already reproduced a deterministic Gates 1–7 pass and
a Gate 8 block in all six cases, with zero accepted claims and eight false-green inversion probes
each behaving as required. That is genuine engineering evidence, and the temptation to relabel it
as "the panel" is exactly the laundering this ADR must prevent.

### Considered options

1. **Re-run the frozen selector with P2/D3 relaxed.** Rejected: outcome-dependent constraint
   selection; destroys the evidential value of the negative result.
2. **Abandon panel work until sources expand.** Rejected: it needlessly blocks legitimate
   engineering verification that does not depend on source independence at all.
3. **Define two separately named, separately versioned products with different claim ceilings, one
   executable now and one explicitly blocked.** Adopted.

### Decision

Adopt **option 3**, specified in `docs/project/specs/atlas-panel-products-v1.yaml`.

- **Preserved result.** The 2026-08-06 run record, its dispositions and its digests are immutable.
  No product may edit, re-sign, re-hash or reinterpret it, reuse its run-record id, its selection
  seed `raptor-atlas-phase2-panel-v1`, or its protocol/registration pair; and no product may re-run
  the frozen selector or substitute candidates after this result.
- **Product 1 — `atlas-technical-coverage-panel`** (engineering). Claim ceiling
  `ENGINEERING_PIPELINE_BEHAVIOUR`, with machine-readable `generalization_claim: false` and
  `independent_validation: false`, and a mandatory disclosure that it was designed after, and with
  knowledge of, `INFEASIBLE_PANEL`. **P2 and D3 become measured-and-reported limitations rather than
  gates** — permitted *only* because the product disclaims independence and generalization — and
  silently dropping them is prohibited: every run must report actual source-group counts, lineage
  unknowns, per-assay-kind distribution and the two mandatory disclaimers. Nine controls remain
  fail-closed (TC-F1…TC-F9): identity resolution/replay, source access and licence admissibility,
  exact-span verification with from-disk hash recompute, R611Q anchor exclusion, dedupe/collision
  detection, complete disposition accounting, abstention fidelity, the named-human Gate 8, and the
  classification/leakage firewall. Membership is fixed **mechanically and pre-execution** under a
  new coverage protocol, new registration, new frame lock and a **new seed**, with no
  outcome-dependent replacement afterwards; seven situation strata (TCS-1…TCS-7) target what the
  machinery must do rather than evidence strength, and an unpopulated stratum is reported with its
  reason rather than filled by relabelling. Success is measured only as execution completeness,
  exact-span yield (reported jointly with the access/licence-blocked share), context completeness,
  contradiction handling, abstention fidelity and reproducibility; precision/recall/concordance
  against any label is a forbidden metric. The six-variant cohort is **cited as prior repeatability
  evidence and not relabelled**, and its six cases do not count toward any coverage metric.
- **Product 2 — `atlas-independent-validation-panel`** (scientific). Retains P1/P2/P3/D1/D2/D3/C3/C5
  at the frozen base thresholds as hard gates, plus multi-model-system and multi-assay-kind
  expectations, with lineage determined by verified mapping rather than by distinct author lists,
  journals or PMIDs, and unknown-lineage records excluded from independence accounting. Status is
  **`BLOCKED_SOURCE_DIVERSITY`**. Entry requires all of: a new frozen source registry with per-source
  licence and checksum pins; established lineage mapping; sufficient lawfully accessible,
  span-verifiable records; a new universe, protocol and registration; pre-registration before
  selection; and a candidate-free feasibility pre-check. Even a feasible panel remains research-only
  and Gate 8 reviewed, and authorizes no criterion, classification, worklist, submission or
  second-disease claim.
- **Firewall between the products (PS-1…PS-6).** Separate names — neither is "the contrast panel"
  and the unqualified phrase is not used — separate protocols, registrations, frame locks, seeds and
  run records; separate version namespaces; no claim inheritance; mandatory post-result disclosure;
  and, critically, **no evidence flow from the technical product to the scientific one**: a
  technical-panel artifact may not satisfy any independent-validation entry gate.
- **The asymmetry is recorded explicitly.** A green technical panel is fully consistent with the
  scientific panel remaining infeasible, because the two propositions are logically independent —
  the technical product is deliberately allowed to draw on concentrated, single-lineage substrate,
  and its membership is chosen *after* the negative result is known. Reading technical success as
  feasibility evidence is affirming the consequent. The spec names the prohibited sentences,
  including "the coverage panel succeeded, so the contrast panel is feasible" and
  "`INFEASIBLE_PANEL` was superseded".

### Consequences

- Engineering verification can proceed without touching a scientific gate, and the pressure to
  weaken P2/D3 is removed rather than resisted case by case.
- `INFEASIBLE_PANEL` keeps its full evidential force. The remedy it points at — registered,
  lineage-mapped, span-verifiable source expansion — is now a named prerequisite in the durable task
  graph rather than an aspiration.
- Every future citation of a panel metric must carry its product id and claim ceiling, which makes
  overclaim visible in review instead of plausible in prose.
- The cost is duplication: two protocols, two registrations, two frame locks and two run-record
  lineages, plus the discipline of never letting one product's artifact satisfy the other's gate.
  That duplication is the control, not an accident of it.
- Nothing is executed by this decision. Both products are design-only, no membership exists, no
  candidate is named, and `atlas-phase2-contrast-panel` remains blocked. Backout is a straight
  revert of the spec, the ADR and its todos.

---

## ADR-0016 — Deterministic offline citation resolver and Phase 2 promotion span verification

- **Status:** Accepted
- **Date:** 2026-07-27
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `track/atlas-citation-resolver-2026-07`
- **Supersedes:** none. Additive. Enforces ADR-0015 (internal summaries are context-only;
  every real claim needs a primary publication or direct dataset with an exact supporting
  span) and preserves ADR-0014 (generic core / versioned disease-pack boundary) and ADR-0009
  (no ClinVar/classifier leakage into mechanism evidence). Binds
  `docs/project/specs/atlas-citation-resolver-v1.yaml` (rev 1).

### Context

ADR-0015 fixed the grounding **policy** but not the **mechanism** that enforces it. As merged,
the Phase 1 promotion pipeline cannot honour that policy: `PromotionContext.citation_resolver`
is only a bare `Callable[..., bool]`, Gate 3 accepts any truthy return as "citation resolved",
and Gate 4 checks only that a span carries a locator — never that the quote actually matches a
real source. A synthetic true value or a locator string is enough to pass. That is exactly the
circular, presence-only laundering ADR-0015 forbids.

Phase 2 needs deterministic local resolution and real span verification **without** introducing
network acquisition, a source-refresh registry, or a full PubMed/PMC/LitVar ingestion pipeline,
and without weakening the frozen Phase 1 synthetic tests. It also must not block the Aug-2
application packaging. The open question was where to draw the boundary: what the resolver
verifies, what it deliberately excludes, and how the promotion gates change without a bypass.

### Decision

1. Add a **deterministic, offline, fail-closed** citation resolver (`src/raptor/atlas/citation.py`)
   that resolves normalized `PMID` / `PMCID` / `DOI` / `ACCESSION` identifiers against a versioned,
   hash-bound **local catalog** of locally-held public/permitted source artifacts. It performs **no
   network access of any kind**; a static AST guard (`assert_no_network_imports`) forbids network
   imports across the Atlas package. Source acquisition and text extraction are a **separate future
   adapter**, explicitly out of scope here.
2. A catalog source is **grounding-admissible** only if **all** hold: `role ==
   direct_evidence_leaf`; `source_type` in `{PRIMARY-LIT, DATASET}`; `permitted_use ==
   grounding_and_quote`; `verification == verified`; at least one supported canonical identifier;
   and verified raw content. Reviews, ClinVar, crosswalks, internal summaries and any
   context/provenance-only or not-yet-verified source may be **loaded** for context but can never
   satisfy grounding — `load_catalog` enforces structure only, while `resolve` enforces the full
   grounding predicate and fails closed (`AtlasCitationResolutionError`) for a non-grounding source.
   Internal handoffs are never admitted as a grounding leaf (ADR-0015).
3. The catalog has a canonical self-excluding content hash
   (`atlas.citation_catalog_content_hash.v1`) mirroring `atlas.pack_content_hash.v1`, is
   deep-frozen after load, and stores only **relative** artifact paths beneath an explicitly
   supplied external content root. `load_catalog(path_or_catalog_id, *, content_root)` accepts
   `str | os.PathLike[str]` for **both** arguments; the id-vs-path choice is stat-independent
   (a safe bare token is a repo-root catalog id, anything with path syntax or any `os.PathLike`
   is an explicit path) — this intentionally **diverges** from `pack.py` (str-only) while reusing
   the same containment principles. The library never reads the environment; path safety rejects
   absolute/drive/`..`/symlink/junction escape via resolved-realpath containment. Catalog-declared
   file hashes are **never trusted**: raw and extracted-text `sha256`/byte-length are always
   recomputed from disk, and drift fails closed.
4. Span verification is **exact**: the resolver verifies an `exact_quote` at a deterministic
   `text-char:<start>:<end>` character-offset locator against extracted UTF-8 text normalized by
   `atlas.text_norm.v1` (CRLF/CR→LF, Unicode NFC, no case-fold, no whitespace collapse). There is
   no fuzzy matching; missing, duplicate, mismatched or out-of-range spans fail. The resolver does
   not parse PDF/HTML/XML — it verifies a separately-generated extracted-text artifact plus the raw
   file hash. Dataset row/key locators are deferred out of v1.
5. `PromotionContext.citation_resolver` becomes a typed, `runtime_checkable` **`CitationResolver`
   protocol** (`resolve(identifier) -> ResolvedCitation`, `verify_span(resolved, span) ->
   VerifiedSpan`). Candidate `bib` fields carry **raw, scheme-less** payloads (`pmid` decimal
   digits, `pmcid` `PMC`+digits, `doi` bare `10.…`, `accession` `<namespace>:<opaque>`); Gate 3
   rejects a bare boolean/callable, constructs each prefixed identifier by concatenation (rejecting
   an already-prefixed/URL/whitespace/percent bib value structurally with `AtlasSchemaError` before
   the resolver), resolves every `direct_evidence_leaf` source into a per-candidate resolved-source
   map, cross-checks aliases/role/type, and requires **all** identifiers a source supplies to
   resolve to the same catalog source (no priority ordering); Gate 4 verifies each linked claim's
   exact span through that map. The public `normalize_identifier` stays flexible for direct callers.
   The eight-gate order and short-circuit are preserved, and the named-human Gate 8 review remains
   **after** deterministic verification — deterministic verification never replaces the human oracle.
6. Resolver/catalog failures raise distinct typed errors under a new `AtlasCatalogError` family
   (`AtlasCatalogSchemaError`, `AtlasCatalogHashError`, `AtlasCatalogPathError`,
   `AtlasCitationResolutionError`, `AtlasContentDriftError`, `AtlasSpanMismatchError`) so
   catalog/path, identifier, content-drift and span failures are individually catchable. This
   family is raised **only** by `citation.py` resolver/catalog operations — it is **not** a blanket
   type for all failures. Promotion Gate 3/4 **translate** a caught `AtlasCatalogError` into the
   existing Phase-1 `AtlasProvenanceError` / `AtlasSchemaError` (chained via `from exc`), and the
   static network-import guard continues to raise `AtlasLeakageError`. No silent fallback, no
   auto-repin.
7. Implementation tests are **fully synthetic** (no real PMID/PMCID/DOI, no real quote, no
   R611Q/Arg611 content, committed catalog template `sources: []`). Real R611Q source acquisition
   and a real catalog follow **after** this resolver is checker-clean, under a separate external,
   uncommitted content root with only public/appropriately-licensed, non-patient, non-paywalled
   content.

### Consequences

- Phase 2 grounding is honest: a claim can only promote when its source resolves to a real
  primary-literature/dataset leaf and its exact quote matches the verified source slice, plus the
  named-human Gate 8 sign-off. Presence-only Gate 4 and truthy-boolean Gate 3 are closed.
- The change is additive and does not alter Phase 1 hashing, profile, identity, pack, registry or
  export behavior; the only interface change is the `citation_resolver` type and Gate 3/4
  semantics. The frozen promotion tests are legitimately updated to inject a strict fake resolver
  object (not a bare boolean), which is the intended consequence of the protocol change, not a test
  weakening. Backout is a straight revert of the implementation commits.
- Network acquisition, continuous refresh, a source-registry platform, PDF parsing, fuzzy matching
  and dataset span grammars remain explicitly out of scope; they are future work behind the
  acquisition adapter. This keeps the slice small and non-blocking for the Aug-2 application.
- The resolver guarantees source **fidelity and identity** (right source, unmutated content, exact
  quote), not scientific **sufficiency**; whether a verified quote actually supports the claim
  remains the named human oracle's responsibility at Gate 8.

---

## ADR-0015 — Atlas internal summaries are context-only and R611Q is the first Phase 2 anchor

- **Status:** Accepted
- **Date:** 2026-07-27
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Supersedes:** the variant-specific `r611q_gate` prohibition in the TSC2 disease pack and Atlas starter spec. It does not supersede the Phase 1 synthetic-only boundary or ADR-0014.

### Context

The preliminary Atlas handoff contains proposed questions and mechanism narratives for
`TSC2 p.Arg611Gln (R611Q)`. Prior discussion does not make the variant scientifically
invalid or unsuitable as a pilot anchor. Treating the handoff itself as evidence, however,
would create circular grounding: an internal summary could be repeated as an accepted claim
without resolving the primary publication or direct dataset that supports it.

A variant-specific prohibition is the wrong abstraction. The same source-role rule must
apply to every real variant, whether or not it appeared in prior discussion.

### Decision

1. Use R611Q as the first Phase 2 end-to-end anchor.
2. Internal RAPTOR handoffs and derived summaries may seed research questions, candidate
   mechanisms, search terms and source leads.
3. Internal summaries are `context`/`query_seed` only. They cannot appear as
   `direct_evidence_leaf`, cannot ground an accepted claim and cannot substitute for an
   exact source span.
4. Every real Atlas claim, for every variant, must resolve to a primary publication or
   direct experimental dataset with an exact supporting span and assay/model context.
5. The engine may return supported, conflicting, unknown or empty results; it must not
   manufacture a mechanism narrative.
6. No variant-specific expectation is hardcoded in the generic core or disease pack.
7. R611Q establishes only the first vertical slice. A contrasting panel of known
   pathogenic, benign, conflicting and evidence-poor variants remains required before
   claiming ontology stability or generality.
8. Reported rescue or perturbation observations remain research evidence in their exact
   experimental context, never patient-specific mitigation or treatment advice.

### Consequences

- The TSC2 pack replaces `r611q_gate` with general internal-summary and primary-source
  grounding rules, and records R611Q only as pilot metadata.
- Discovery may use the handoff to formulate queries, but may not emit it as a proposed
  source or claim-grounding record.
- The handoff becomes useful as a post-extraction audit target: RAPTOR can record which
  proposed statements were independently supported, contradicted, unresolved or absent.
- Independent retrieval benchmarking, if later required, must be defined separately from
  the product-development anchor run; it does not restrict the operational Phase 2 pilot.
- The existing classification, clinical-use and treatment-recommendation prohibitions remain.

---

## ADR-0014 — Generic Mechanism Atlas core with a versioned disease-pack boundary

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `track/mechanism-atlas-2026-07`
- **Supersedes:** none. Additive; complements ADR-0010 (vertical TSC/mTOR strategy) and ADR-0009 (no classifier/ClinVar leakage into mechanism evidence). Binds the Mechanism Atlas starter spec (`docs/project/specs/mechanism-atlas-starter.yaml`, rev 6).

### Context

RAPTOR's monetizability depends on amortizing the evidence/provenance pipeline
across conditions rather than rebuilding it per disease. The Mechanism Atlas is
the first component where that amortization is at stake. The prior Atlas starter
spec and the reviewed Gemini tests hardcoded TSC2/mTORC1 assumptions into what
should be reusable machinery: a TSC2-only gene enum, an `NM_000548.5` transcript
constant, a `pathway_mtorc1` claim kind, an `mtorc1_state` mechanism layer, and
disease-specific source IDs and thresholds embedded in the core.

If those assumptions harden into the core, every future condition forks the
machinery and the pipeline cannot be amortized — the exact failure mode that makes
a bespoke tool rather than a reusable platform. At the same time, ADR-0010 falsified
the generic-platform uniqueness premise and bound RAPTOR to a **vertical TSC/mTOR,
evidence-first, non-clinical** strategy. We must therefore prevent TSC hardcoding in
the *internal* core **without** broadening the *scientific/product* pilot beyond TSC2
or implying a second disease is supported. This is an internal architecture
portability seam, not a pivot to a generic variant-classification platform.

The packet corpus is complete and frozen externally and code is merged on main. A
deterministic eight-case sample exists, but Phase 1 remains synthetic-only and Phase 2
real grounding still requires named human/oracle review.

### Considered options

1. **Keep TSC2/mTORC1 literals in the Atlas core.** Rejected: it forks the machinery
   per condition, defeats amortization, and lets disease specifics leak into reusable
   code and hashes.
2. **Broaden the core now into a generic multi-disease platform with several packs.**
   Rejected: it contradicts ADR-0010's vertical discipline, invites overclaim, and
   spends scope on unvalidated conditions.
3. **Split a condition-agnostic core from a single versioned, declarative disease
   pack; ship exactly one `tsc2` pack; gate any second disease behind a later
   portability experiment.** Adopted.

### Decision

Adopt **option 3**.

- **Generic core.** `src/raptor/atlas/` is condition-agnostic evidence/provenance
  machinery and MUST NOT contain literal `TSC1`/`TSC2`, `NM_000548.5`, `mTOR`/`mTORC1`,
  `R611Q`, disease-specific source IDs, disease-specific classifier thresholds, or
  ClinVar truth. A disease-literal static scan over the core enforces this.
- **Disease pack.** A versioned, declarative pack at
  `configs/atlas/packs/<pack_id>/pack.yaml` (schema `atlas.disease_pack.v1`, with
  `pack_id`, `pack_version`, self-excluded `pack_content_hash`) supplies allowed
  genes, assembly/transcript pins and reconciliation policy, namespaced mechanism
  ontology extensions (`<pack_id>:<name>` under a core seed parent), source-register
  metadata pins, disease-specific prohibitions, and pilot/evaluation metadata. It is
  configuration (GP-6), never code, and never a source of scoring truth. Phase 1 ships
  exactly one `tsc2` pack.
- **Pack binding.** The sole authoritative, hash-bound binding is the top-level
  `MechanismProfile.pack_binding` `{pack_id, pack_version, pack_content_hash}`, bound
  into **both** the evidence-core hash and the profile-envelope hash, so a profile
  cannot be silently reinterpreted under the wrong pack (wrong-pack recompute changes
  both hashes; fail-closed). `Provenance` carries **no** `pack_binding`.
  `RunMetadata.pack_binding_audit`, `DisMechRecord.pack_binding`, and candidate
  retrieval-provenance copies are non-authoritative, non-hashed audit copies that MUST
  equal the profile binding or fail (`AtlasSchemaError`).
- **Typed, fail-closed errors.** Core domain errors (`AtlasSchemaError`,
  `AtlasIdentityError`, `AtlasProvenanceError`, `AtlasSourceVerificationError`,
  `AtlasLeakageError`, `AtlasExportError`) are distinct from pack-validation errors
  (`AtlasPackError`). A malformed/hash-drifted/mis-namespaced pack fails closed as
  `AtlasPackError`; a *valid* pack whose constraint is violated raises a core domain
  error.
- **Loader API.** `load_disease_pack`, `validate_disease_pack`, `pack_content_hash`
  in `raptor.atlas.pack`; identity/ontology/source constraints and the promotion gate
  read the pack via dependency injection (`admit_identity(record, *, pack)`,
  `PromotionContext`).
- **No second-disease implication.** Core acceptance and a passing `tsc2` pack never
  imply another disease works. Whether the pipeline ports is a **hypothesis** to be
  tested by a later, design-only **portability experiment** (public/synthetic or
  approved evidence only, zero expected core behavioral diff, additions confined to a
  second pack/templates/fixtures, measured by reusable-test percentage and
  core-diff/onboarding effort). Its proposed targets are hypotheses, not achieved
  facts; failure means bespoke tooling, not platform validation. No second disease is
  named or selected in this track.

This decision authorizes only the internal architecture seam and a synthetic-only
Phase 1. It authorizes no clinical claim, no VUS worklist, no ClinVar submission, no
research-scope expansion, and no second-disease support.

### Consequences

- The Atlas core is reusable and disease-literal-free; the `tsc2` pack expresses all
  TSC2/mTORC1 specifics (e.g. `tsc2:pathway_mtorc1`, `NM_000548.5`, the R611Q gate).
- Profiles are self-describing about the pack they were built under and cannot be
  cross-interpreted without detection.
- The shipped product scope stays TSC-only (ADR-0010 unchanged); `STRATEGY.md` GP-13
  is clarified to state the internal seam is not vertical-washing.
- R611Q remains blocked for Phase 2 primary re-grounding; no real R611Q claims exist
  in Phase 1, and the `R611Q` literal lives only in the `tsc2` pack.
- The Discovery research lane stays an optional, out-of-process candidate-import
  source; its templates may take disease-pack context, its outputs are untrusted, and
  its failure cannot change accepted profiles.
- Repository extraction remains gated (see the spec `extraction_gate`); the portability
  experiment is the evidence that would justify or refuse it.
- The prior `c281fca` Atlas tests must be replaced/repaired to the rev-6 contract
  before implementation; tests may not be weakened to pass.

---

## ADR-0013 — Tiered gate v3 post-hoc re-adjudication and prospective validation lock

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `track/tiered-gate-v3-2026-07`
- **Supersedes:** v2's overloaded interpretation for future reporting; v1/v2 code and frozen artifacts remain immutable.

### Context

R2 completed successfully under ADR-0012, but the v1/v2 summaries conflated
insufficient called data, conditional performance and policy exclusions. Missense
pathogenic had 51 actual examples but zero calls; missense benign had 103 actual
examples but only nine calls, all correct. Calling both scopes simply `FAIL`
overstated what could be estimated. The global PM1 exclusion also blocked the
unrelated truncating-pathogenic scope despite that scope clearing its registered
0.95/0.95 thresholds at adequate coverage.

Rerunning unchanged scoring on the same data would add no evidence and would not
remove post-hoc bias. R2 must remain unchanged while any corrected interpretation
is explicitly versioned and labeled post-hoc.

### Considered options

1. Preserve the coarse v2 interpretation and continue. Rejected because it hides
   data insufficiency and leaks a missense criterion blocker into truncating.
2. Rerun identical scoring and issue a different decision. Rejected because
   identical inputs and scoring produce no new information.
3. Add an independent tiered v3 re-adjudication over frozen aggregate counts,
   with prospective authorization locked to unseen data.

### Decision

Adopt **option 3**. Tiered gate v3 reports independent axes for run integrity,
data sufficiency, conditional performance, policy parity, correct-call coverage,
scope evidence and authorization. Undefined conditional metrics remain null;
they are never coerced to zero.

PM1 applies only to `missense:pathogenic`. The frozen R2 interpretation becomes:

- missense pathogenic: `NO_CALLS` / `NOT_ESTIMABLE`, PM1 blocked;
- missense benign: `UNDERPOWERED` / `NOT_ESTIMABLE`;
- truncating pathogenic: `ADEQUATE` + `MET`, evidence `SUPPORTED_POSTHOC`;
- full spectrum: `NOT_VALIDATED` and `NOT_AUTHORIZED`;
- truncating-pathogenic authorization: `PENDING_PROSPECTIVE`;
- canonical research-scope validated flag remains false.

This is a post-hoc semantic correction only. It generates no evidence and
authorizes no clinical classification, VUS worklist, ClinVar submission or
research scope.

Prospective validation is locked to the first NCBI ClinVar GRCh38
`variant_summary` monthly archive dated on or after 2026-08-01. Its URL,
official date, MD5 and SHA-256 must be frozen before labels or scoring. If that
archive is unavailable or invalid, status is `BLOCKED_DATA`; no
outcome-dependent substitute is allowed.

**Recorded outcome (2026-08-06):** `BLOCKED_DATA`. The exact preregistered URL
returned HTTP 404. A same-named archive at a different URL was not substituted.
No archive bytes, labels, rows or scores were accessed.

### Consequences

- R2 and all v1/v2 code and records remain byte-identical.
- `data/census/tsc_tiered_readjudication_2026-07-21.json` is the versioned
  post-hoc interpretation; its prospective status is `PENDING`.
- Truncating-pathogenic evidence is described more accurately but is not
  authorized until a future unseen-data run and new owner decision.
- Packet generation may continue as non-authoritative review preparation; it
  cannot cite v3 as prospective validation.

---

## ADR-0012 — PP3/BP4 automated emission disabled for the current masked rerun

- **Status:** Accepted
- **Date:** 2026-07-21
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `track/pp3bp4-resolution-2026-07`
- **Supersedes:** none. Additive alongside ADR-0009 and preserves ADR-0011 unchanged.

### Context

RAPTOR has verified published REVEL score intervals for PP3/BP4, but the current activation artifact
does not yet identify the exact predictor and dbNSFP releases: both remain `confirm-pending`.
Training overlap with the TSC benchmark is `UNKNOWN`, transportability is `BLOCKED_DATA`, and
permitted use remains pending. These are recorded in
`configs/eval/pp3bp4_candidate_policy.json`; the candidate policy remains proposed and shadow-only.

Counting those predictor calls automatically in the masked rerun would therefore let an unresolved
implementation mapping and unresolved leakage risk change classifications and gate metrics. Blocking
the entire rerun until every activation prerequisite is resolved would protect against that risk but
would continue delaying the critical-path census and packet work. PP3/BP4 must remain represented for
manual review and future activation rather than being deleted from the evidence model.

### Considered options

1. **Approve explicit `disabled_manual` mode for this rerun.** Suppress automated PP3/BP4 calls,
   preserve and count the suppressed evidence, and retain both criteria in the vocabulary and lineage
   for manual review.
2. **Enable corrected REVEL-backed PP3/BP4 now.** Rejected: exact release compatibility, permitted
   use, training overlap, and transportability have not met the recorded activation checklist.
3. **Keep the policy proposed and block the rerun.** Rejected: PP3/BP4 can be removed from automated
   scoring without changing the immutable upstream evidence, so blocking unrelated downstream work
   is unnecessary.

### Decision

Adopt **option 1** for the current masked rerun. Approve
`configs/eval/bp4pp3_predictor_policy.json` with `mode: disabled_manual` in a separate, status-only
commit after verifying its production, evaluation, lineage, packet, and runtime-bundle hashes.

In this mode:

- PP3/BP4 are absent from production `included_criteria`, evaluation `automatable_criteria`, and
  packet candidate-direction points.
- PP3/BP4 remain in the ACMG vocabulary and BIAS can-fire lineage with `deferred` dispositions for
  manual review.
- Every automated PP3/BP4 call is suppressed and reported; the run must record zero scored PP3/BP4
  calls.
- Approval authorizes only use of this disabled/manual evidence mode. It does **not** authorize VUS
  classification, a research scope, a clinical claim, a worklist, or a ClinVar submission.
- ADR-0011's metric-driven gate and scope gate remain authoritative and unchanged.

Corrected or REVEL-enabled PP3/BP4 remains `BLOCKED_POLICY`. Activation requires a new owner decision
after the exact predictor/data releases, permitted use, leakage status, and transportability evidence
meet the activation checklist, followed by new hash pins and a fresh masked rerun.

### Consequences

- The existing immutable 2,577-row masked BIAS evidence can be reused with downstream suppression on
  the ARM machine; this decision does not require x64 reannotation.
- The rerun is intentionally conservative and may undercall missense computational evidence. Its
  result describes the approved disabled/manual policy, not a future PP3/BP4-enabled system.
- Suppression counts and affected variant counts remain auditable in the terminal envelope and gate
  aggregate; malformed or mixed envelope shapes fail closed.
- A future activation restores automated PP3/BP4 and packet candidate-direction points only through a
  separately approved, hash-bound policy revision.

---

## ADR-0011 — Scope-specific research authorization gate (v2): truncating-pathogenic research scope preregistered separately from full-spectrum VUS

- **Status:** Accepted
- **Date:** 2026-07-14
- **Deciders:** @dronasrinivas (operator, acting domain owner)
- **Track:** `track/scope-specific-gate-2026-07`
- **Supersedes:** none. Purely additive alongside ADR-0009/PRD-06's v1 held-out gate, which stays unchanged.

### Context

The v1 masked held-out gate (`raptor.eval.gate.decide_gate`, PRD-06) binds a single VUS-authorization
decision on the `missense` stratum and short-circuits: if missense fails, no other stratum's verdict
(including `truncating`) is even reported. The 2026-07-13 v1 run is `status=FAIL,
binding_stratum=missense, vus_authorized=false` — full-spectrum VUS automation is correctly withheld.
But that pooled, single-stratum design cannot express a real and useful fact already visible in that
run's numbers: truncating-pathogenic cleared its own preregistered 0.95/0.95 threshold at adequate
coverage, while missense did not. Today's gate has no way to report — let alone separately authorize —
a narrower, non-clinical, research-only claim scoped to truncating-pathogenic alone.

### Considered options

1. **Additive v2 gate + models + config + schema marker** (`decide_scope_gate`, `DirectionVerdict`,
   `ScopeGateDecision`, `EvalConfig.scope_authorization`, schema `raptor.tsc.masked_holdout_gate.v2`).
2. **Make `decide_gate` schema-version-dispatch internally.** Rejected: fixing the metric-before-coverage
   evaluation order to preserve both axes would flip v1's missense verdict semantics (`FAIL` could
   read differently), silently relabeling the immutable v1 decision path and its already-published
   2026-07-13 artifact.
3. **Do nothing until the corrected rerun.** Rejected: the authorization *rule* itself (which scopes may
   independently authorize what) is a policy decision that must be preregistered **before** that rerun,
   not invented after seeing its numbers — exactly the discipline this program has followed for every
   other threshold (EVAL_RUBRIC.md §5).

### Decision

Adopt **option 1**. `decide_gate`/`GateDecision`/`StratumVerdict` and the 2026-07-13 v1 artifact are
frozen and byte-unchanged. A new, additive `decide_scope_gate` (`src/raptor/eval/scope_gate.py`)
evaluates **every** configured `(stratum, direction)` scope independently, with no short-circuit,
and reports two orthogonal axes per scope: `metric_status` (did the 95% Clopper-Pearson lower bound
clear its Oracle-registered threshold?) and `coverage_adequate` (did held-out coverage clear
`min_count_per_class`?). A scope is `VALIDATED` only when a threshold is registered, `metric_status ==
"MET"`, and `coverage_adequate` — never on a pooled/`overall` metric.

A new, additive, versioned config block (`configs/eval/tsc2.yaml` → `scope_authorization`,
`schema_version: 2`) preregisters:

- **`full_spectrum.requires`**, semantics-locked (anti-cherry-pick) to exactly
  `{missense:pathogenic, missense:benign, truncating:pathogenic}` — full-spectrum VUS automation still
  requires the hard missense scope; this rule cannot be narrowed away post-hoc.
- **`truncating_pathogenic_research_scope_validated`** — a narrow, independently-computable research
  scope flag requiring only `truncating:pathogenic` to be `VALIDATED`.
- **Exact governance statements** for each resolvable state, most notably (verbatim, never
  paraphrased): *"Full-spectrum VUS automation is not authorized. Evidence supports only the validated
  truncating-pathogenic scope; missense remains unvalidated."*
- A **separate, mandatory, non-blank `research_use_disclaimer`** — *"Research-evidence validation only;
  this authorizes no clinical classification, VUS worklist, or ClinVar submission."* — kept out of the
  governance statement text (never merged into it) so it cannot be truncated away.

`EvalReport.scope_gate` is optional/additive; `content_hash()` excludes it entirely when `None`, so
every existing v1 report hash (and `external_report_hashes` continuity) is unaffected. A new
`build_aggregate_v2` (schema `raptor.tsc.masked_holdout_gate.v2`) derives its primary verdict fields
from `scope_gate`, never from pooled `metrics`; `build_aggregate` (v1, schema `...v1`) is untouched.

### Non-blind / post-hoc-risk acknowledgment (must not be hidden)

**This preregistration is not blind to the truncating-pathogenic outcome.** The 2026-07-13 v1 run
already showed truncating-pathogenic clearing 0.95/0.95 at adequate coverage before this rule was
written — an auditor can fairly call adopting "truncating-pathogenic may independently authorize a
truncating-only research scope" **after** seeing that number a form of post-hoc/cherry-picked
rule-making, not a genuinely blind preregistration. This is accepted as a real, named limitation, not
argued away, for four reasons that jointly bound the risk:

1. **No threshold changed.** The truncating 0.95/0.95 precision/recall pair, `gating: true`, and
   pathogenic-only direction were preregistered in `tsc2.yaml` **before** the v1 run and remain
   pinned/locked (`config._PINNED_STRATUM_THRESHOLDS`) — nothing was lowered or invented to manufacture
   this result.
2. **The rule only narrows what a pass can mean.** It grants no new capability: it is explicitly
   research-only, explicitly non-clinical, and explicitly not full-spectrum (the disclaimer and the
   `TRUNCATING_PATHOGENIC_ONLY` statement say so verbatim). It cannot be used to authorize VUS scoring,
   clinical classification, or a ClinVar submission.
3. **The hard full-spectrum requirement cannot be quietly dropped.** `full_spectrum.requires` is
   semantics-locked to still include `missense:pathogenic`/`missense:benign` — this preregistration
   cannot be exploited to narrow full-spectrum authorization down to truncating alone.
4. **Validation must still be re-established on a corrected rerun.** No `data/census/*.json` is written
   by this track; no real gate is executed; v1's actual truncating numbers are never hardcoded into any
   test or into this rule (Group A/B tests use only synthetic `Metrics`). The 2026-07-13 v1 artifact is
   never relabeled — it remains `schema=v1, status=FAIL, binding_stratum=missense, vus_authorized=false`
   and carries no v2 keys (enforced by `tests/eval/test_scope_gate_v1_preservation.py`).

This ADR is deliberately explicit about the non-blindness above **as the primary control**: an honest,
recorded acknowledgment of the risk is preferred over silently asserting the preregistration is blind
when it is not. No PASS/VALIDATED claim about the corrected rerun is made here or anywhere in this
track — this ADR records the rule, not a result.

### Consequences

- A future corrected masked-holdout rerun can report — and, if it clears the same locked thresholds at
  adequate coverage, independently authorize — a `truncating_pathogenic_research_scope_validated`
  research-only claim, separate from (and never implying) full-spectrum VUS authorization.
- `README.md`/`docs/PROGRAM.md` "current status" are **not** updated by this ADR — that only happens
  after the corrected rerun actually executes and produces a genuine, non-cherry-picked result.
- No evidence-policy or predictor-policy approval status changes; the BP4/PP3 predictor-policy block on
  the rerun (`configs/eval/bp4pp3_predictor_policy.json`, status pending) is untouched.

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
