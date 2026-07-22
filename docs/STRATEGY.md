# RAPTOR — Strategy & Operating Model

> **Status:** DRAFT v0.3 — consolidated authority doc · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (merged the legacy operating-model authority into Part II; post-ADR-0013 authority consolidation) · **Review cadence:** monthly + rule-graduation on any new failure class
>
> **Authority split inside this file:** **Part I — Strategy** is the canonical statement of intent, scope, and success criteria (*why / what*). **Part II — Operating Model** is the canonical statement of development governance (*how*). If they disagree, Part I wins on intent; Part II wins on build mechanism.

---

## Authority & navigation

| Need | Canonical section | Maintained authority |
|---|---|---|
| Vision, diagnosis, product lines, roadmap, KPIs | [Part I — Strategy](#strategy-part-i) | Strategic intent / *why, what* |
| Binding strategic guardrails | [Part I §5 — Guiding Policy](#strategy-guiding-policy) and [Part I §9 — Scope](#strategy-scope) | Strategic authority |
| Build loop, RACI, hand-off contracts, gates, three-slot prompts, integrity/delegation/rule-graduation controls | [Part II — Operating Model](#strategy-part-ii) | Development governance / *how* |
| Binding build governance | [Part II §2 — Roles, model assignment & RACI](#operating-model-roles) and [Part II §4 — Gates](#operating-model-gates) | Process authority |
| Benchmark protocol and preregistered thresholds | [EVALUATION.md](EVALUATION.md#evaluation-part-i) / [Part II rubric](EVALUATION.md#evaluation-part-ii) | Evaluation authority |
| Accepted historical decisions | [DECISIONS.md](DECISIONS.md) | Immutable ADR record |
| Living failure modes and controls | [RISK_REGISTER.md](RISK_REGISTER.md) | ISO-31000-style risk authority |

## Table of contents

- [Part I — Strategy](#strategy-part-i)
- [Part II — Operating Model](#strategy-part-ii)
- [What lives elsewhere](#strategy-what-lives-elsewhere)

<a id="strategy-part-i"></a>
## Part I — Strategy

> **Part I status:** DRAFT v0.2 — *vertical TSC/mTOR reset* (see [ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)) · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (post-ADR-0013 reconciliation) · **Review cadence:** monthly
>
> **Part I format:** This section follows two established, citable standards — Roman Pichler's **Product Vision Board** (Vision · Target Group · Needs · Product · Business Goals) wrapped around Richard Rumelt's **Kernel of Good Strategy** (Diagnosis → Guiding Policy → Coherent Action, *Good Strategy / Bad Strategy*, 2011).

<a id="strategy-purpose"></a>
### 0. Purpose of this document

**What this is:** the single strategic anchor for RAPTOR. It states *why the project exists*, *why
TSC is the starting point*, *what will and will not be built*, and *how success is measured*.

**Who it serves:** any agent or human reviewer who needs to orient in one read — a contributor
picking up a task, a domain expert or funder evaluating the premise, or a future self checking for
drift.

**How to use it:** treat sections **5 (Guiding Policy)** and **9 (Scope)** as binding — a change
here is a strategy change and needs an explicit decision record. Everything else is evidence and
rationale supporting those two. Execution detail (PRD, architecture, data model, runbook) lives in
sibling docs (§11); Part II in this same file governs the build loop, while Part I stays the strategic layer. If Part I and a sibling disagree, Part I wins on *intent*; Part II and sibling docs win on *mechanism*.

**One-line summary:** *A vertical TSC/mTOR research-evidence product — an auditable engine that turns
public TSC1/TSC2 data into expert-reviewable candidate evidence packets, an evidence/assay/
contradiction atlas, and falsifiable research hypotheses — that accelerates the researchers who
resolve TSC variants, and never replaces their judgement. It is **not** a generic
variant-interpretation platform.*

---

<a id="strategy-vision"></a>
### 1. Vision

> **RAPTOR accelerates TSC/mTOR research by turning the public TSC1/TSC2 evidence base into
> auditable, continuously updated, expert-reviewable research artifacts — candidate evidence packets,
> an evidence/functional-assay/contradiction atlas, and falsifiable research-hypothesis packets — for
> the curators and researchers who resolve Tuberous Sclerosis Complex variants.**

It is **not** a diagnostic, a treatment-recommendation system, a regulated medical device, or a
**generic variant-interpretation platform**. It is a **vertical enabler**: the TSC-specific
research-evidence infrastructure that curators, researchers, and clinical-translation teams plug into
to do their TSC work faster and with a full evidence trail.

**Committed claim (build now):** a defensible TSC1/TSC2 candidate-evidence engine, validated against
the best available expert labels, plus a bounded evidence/functional-assay/contradiction **atlas**
over established mTOR-pathway mechanism.

**Gated extension (not the current claim):** selected *mTOR-related* conditions — each admitted
**one at a time** through an explicit gate (a fixed gene/disease/mechanism question, a named user, an
expert validator, and a falsifier), shipping cross-condition links only as *cited hypotheses with
declared validation ceilings*, never as "validated discovery." This supersedes the earlier
generalise-to-all-rare-disease "north-star" ([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)):
RAPTOR is a **vertical**, not a generic platform in waiting.

---

<a id="strategy-diagnosis"></a>
### 2. Diagnosis — why this is needed

*(Rumelt: name the challenge, with evidence, before proposing any approach.)*

<a id="strategy-core-problem"></a>
#### 2.1 The core problem: the VUS pile is large, clinically consequential, and unattended

A **Variant of Uncertain Significance (VUS)** is a genetic variant that testing has found but that
nobody can yet call pathogenic or benign. For a family, a VUS is a non-answer: the test ran, the
variant is real, and the clinician still cannot say what it means.

| Metric | Value | Source (re-verify at run — ClinVar updates weekly) |
|---|---|---|
| ClinVar germline-classified variants | 4,274,341 | ClinVar, Jun 2026 |
| — of which VUS | 2,355,835 (**55.1%**) | ClinVar, Jun 2026 |
| **TSC2** VUS | **4,445** (top-10 gene globally) | ClinVar, Jun 2026 |
| TSC2 total variants | 7,645 | ClinVar, Jun 2026 |
| **TSC2 expert-panel (3★) reviewed** | **0** | ClinVar, Jun 2026 |
| TSC1 VUS (approx.) | ~2,290 | ClinVar, Jun 2026 |
| TSC1+TSC2 VUS + conflicting classifications | ~6,700 VUS + ~2,200 conflicting | ClinVar, Jun 2026 |
| ClinGen TSC VCEP submissions to ClinVar | **0** | ClinVar, Jun 2026 |

**The clinical stakes are documented, not hypothetical.** Variant interpretation changes management
across disease areas, and specifically for TSC:

- **Farach 2024 (Pediatr Neurol, PREVeNT trial):** TSC2 genotype is associated with drug-resistant
  epilepsy — variant identity helps stratify who needs prompt, aggressive management. *(Strongest
  single TSC citation.)*
- **Togi 2022 (Int J Mol Sci):** TSC2 genotype–phenotype correlation informs surveillance intensity.
- **Mekahli 2024 (Nat Rev Nephrol, ERKNet consensus):** genetic stratification is codified in
  international TSC kidney-management guidelines.
- **everolimus (mTOR inhibitor) is approved for TSC** — so a *resolved* variant can, **after
  qualified clinical/expert review**, inform management. RAPTOR itself neither prescribes nor advises
  (§9); the point is that an unresolved VUS carries real downstream cost.

<a id="strategy-market-landscape"></a>
#### 2.2 The market & research landscape — capable general platforms exist; the TSC-specific vertical is under-served

> **Premise correction (2026-07 — [ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)).**
> An earlier version of this document claimed a **"blue ocean / no synthesis layer / no public
> deployed system."** That uniqueness claim is **withdrawn.** Capable general variant-interpretation
> and LLM/ACMG platforms exist (Deriva, Virtual Geneticist, Breakthrough Genomics, 3billion AIVARI,
> eVai, AAVC, VarChat, Golden Helix VSClinical, SeqOne DiagAI, Variant Bio). RAPTOR's case does **not** rest
> on being the only one — it rests on being a **vertical TSC/mTOR evidence program** with an open
> benchmark, auditability, and freshness. Detailed, source-classified competitor evidence lives in
> **[reference/competitive-landscape-2026-07.md](reference/competitive-landscape-2026-07.md)** (kept
> there to keep this doc lean).

TSC affects an estimated **1–2 million people worldwide** (birth incidence ~1 in 6,000; prevalence
~1 in 6,000–10,000) and **~77,000–82,000 in Europe**. Disease-registry research is genuine and
multi-market — but it is *cohort and correlation* work, not a *TSC-specific, auditable,
continuously-updated evidence program*.

| Market | What exists | Key data points | Gap for RAPTOR |
|---|---|---|---|
| **Global / EU** | **TOSCA** international registry (Novartis-sponsored; Kingswood & de Vries, *Orphanet J Rare Dis* 2017) | ~2,093–2,214 patients · 170–250 sites · **31 countries**. **E-TSC** European registry active. | Registries hold phenotype, not systematic variant re-classification; not publicly queryable at variant level. |
| **Japan** | 4 active clinical groups + JMDC claims DB | Niida (Kanazawa) cohort n=283; Wataya-Kaneda (Osaka) 39 papers; regional prevalence 3.1–10.2/100k (undercounted). JMDC: 148 TSC patients, **no genetic data**. | Genotype-phenotype papers only; no pipeline; JMDC cannot classify variants. |
| **China** | 5 active clinical research groups | Fudan n=297 · Xiangya n=173 · PLA n=223 · PUMCH families · PKUPH (TOSCA link). | Genotype-phenotype correlation only; no automation. |
| **Methodology (any market)** | Published but sparse | Kim 2025 (*Eur J Hum Genet*); Garcia 2024 (TSC1/2 variant DB). mTOR papers 2015–26: **14,594**. | Retrospective, single-institution, not deployed or continuously updated. |

**The one narrow, dated metric that survives** (correctly scoped): a **live PubMed E-utilities
search, verified 2026-06-16**, found **zero** results for four TSC-specific automated/systematic
variant-classification/reclassification queries over the 2015 / 2018–2026 windows — i.e. **no indexed
TSC-specific campaign was found, not that no capable platform exists.** Likewise, **TSC ClinGen/VCEP
submissions in ClinVar were zero** at that date — read as an **unresolved institutional/adoption
question, not automatic demand** (see [reference/competitive-landscape-2026-07.md](reference/competitive-landscape-2026-07.md); RISK_REGISTER R-A12).

<a id="strategy-under-served-vertical"></a>
#### 2.3 Why the TSC-specific vertical is under-served — structural, not "empty space"

The point is **not** that the space is empty — capable general platforms exist (§2.2). The point is
that the **TSC-specific, auditable, continuously-updated evidence vertical** is under-served, for
*incentive* reasons (fuller analysis in the `pre-build/` FYTSC session notes):

1. **Academic incentives** reward novel biology/algorithms, not "apply existing tools to an existing
   database and maintain it as a TSC service."
2. **Generic vendors optimise breadth**, not a single-disease, benchmark-backed, freshness-first TSC
   evidence program — their published TSC-specific validation is effectively nil.
3. **Commercial incentives** put variant reclassification upstream of the drug-revenue pathway.
4. **ClinGen's institutional fix is stalled** — the TSC VCEP exists but had **0 ClinVar submissions**
   at the 2026-06-16 verification date; human-speed curation has not cleared the ~6,600–6,700 VUS.
   This is an **adoption/institutional gap**, not evidence that RAPTOR is demanded.
5. **Everyone treats the TSC vertical as someone else's job.**

**Honest uncertainty:** absence of an *indexed TSC-specific* signal is evidence of an under-served
vertical, **not** evidence that no capable platform exists (that inference was the falsified premise)
and **not** proof of demand. A stealth or internal TSC effort likewise cannot be ruled out.

---

<a id="strategy-why-tsc"></a>
### 3. Why TSC — the vertical, and its gated mTOR extensions

TSC is the **core of the vertical, not a stepping-stone to a generic platform.** It was chosen
against explicit criteria:

| Selection criterion | How TSC scores |
|---|---|
| **Public data, no gatekeepers** | ClinVar, gnomAD, PMC, ClinGen — all open. |
| **Gateway / lynchpin mechanism** | Loss of TSC1/TSC2 → mTORC1 hyperactivation; supports *gated* extension to adjacent mTORopathies (DEPDC5, PTEN, PIK3CA, NPRL2/3) — one at a time, per GP-13. |
| **Clinically actionable** | everolimus approved → a resolved variant can *indirectly* inform management **via qualified clinicians** (never by RAPTOR). |
| **Quantified, addressable gap** | 6,618 TSC1/TSC2 VUS in the 2026-07-07 census (TSC1 2,249 · TSC2 4,369); 0 expert-panel reviews; top-10 VUS-burdened gene. |
| **Validatable** | Best-available expert / multi-submitter labels give a measurable benchmark held out for a gated eval. |
| **Under-served vertical** *(not "blue ocean")* | Capable **general** platforms exist (§2.2), but **no indexed TSC-specific automated campaign** was found under the search protocol at 2026-06-16, and TSC VCEP ClinVar submissions were 0 — an under-served vertical + adoption gap, not a uniqueness claim. |
| **Solo-operator feasible** | Fits the available local + cloud compute fleet. |

The insight that makes TSC *extensible*: the mechanism (mTOR) is shared with adjacent conditions, so
the TSC evidence engine and evidence grammar can be **reused for a selected mTOR-condition question
admitted one at a time through the GP-13 gate** — the reason the gated extension (§1) is credible
rather than an open-ended generic-platform ambition.

---

<a id="strategy-target-groups"></a>
### 4. Target group & needs

*(Pichler: who is this for, and what need does it serve — never a patient-facing tool.)*

| Target group | Need RAPTOR serves |
|---|---|
| **ClinGen TSC VCEP / expert curators** | A ranked **candidate evidence packet**: candidate VUS where deterministic evidence alone *suggests* a possible LP/LB direction — **eval-only and non-authoritative until leakage-safe validation + expert sign-off**; curator source-verification and mechanism judgement always required (deterministic scoring ≠ finished ACMG call). |
| **TSC/mTOR researchers** | A TSC **evidence / functional-assay / contradiction atlas**: where the assay evidence is, where it is missing, and which sources contradict each other — plus falsifiable **research-hypothesis packets** to act on. |
| **Functional / mTOR biologists** | Assay-coverage and assay-gap maps over TSC1/TSC2 — which residues/domains have PS3-grade functional data and which are dark. |
| **Clinical-translation teams (gated mTOR extension)** | Mechanistically-grounded, fully-cited *hypotheses* for a **single, gated** mTOR-condition question (GP-13) — never "same pathway therefore same drug." |
| **Diagnostic labs (single-submitter)** | Auditable, evidence-weighted second-pass over their single-submitter TSC classifications. |

**Not served (deliberately):** individual patients, prescribers seeking decisions, or any use that
would make RAPTOR clinical decision support. See §9.

---

<a id="strategy-guiding-policy"></a>
### 5. Guiding Policy *(binding)*

*(Rumelt: the overall approach that focuses effort and rules out alternatives.)*

**GP-1 — Every layer declares its validation ceiling.** No output ships without stating what would
falsify it and against what it is (or is not) validated. This is the single rule that keeps the
project honest.

**GP-2 — Prove the measurable half first; treat the differentiating half as hypothesis.** Variant
classification (measurable against expert labels) is built and validated *before* the cross-linkage
layer earns trust. Cross-disease links ship only as *cited, falsifiable hypotheses*; the word
**"discovery"** is reserved for the **gap-map**, never for unconfirmed mechanism.

**GP-3 — Recruit the domain oracle before the layer that needs it.** The cross-linkage layer is
oracle-poor: the literature grounds every *premise* but cannot validate the *inferential leap* or
*set-completeness*. A molecular geneticist is recruited as validating oracle **before** that layer is
trusted — not after.

**GP-4 — Reuse, don't rebuild.** BIAS-2015 (19/28 ACMG criteria), AcmGENTIC (PS3 extraction), Every
Cure KG and ClinGen criteria are foundations, while AAVC is a frozen external comparator (not an
oracle and, under its PolyForm Strict licence, not reusable code). RAPTOR's contribution is
*integration + scale + auditability + freshness*, not methodology novelty. **Reuse is not trust
transfer:** an inherited tool still earns its own local validation ceiling (GP-1) and benchmark
before its outputs are trusted for TSC.

**GP-5 — Provenance and freshness are first-class.** Every stored result records model, version,
prompt template version, evidence source, and timestamp. Stale synthesis is worse than none — it
launders outdated claims with fresh-looking citations — so re-validation is a designed-in loop, not
an afterthought.

**GP-6 — Config is the source of truth.** Rules, thresholds, and routing policy live in
human- and machine-readable config (YAML/TOML/MD); scripts *read* them. No policy logic hardcoded in
Python or notebooks. **Config is not self-authorizing:** it is versioned, schema-validated, and every
rule/threshold change is a reviewed decision (guards H6/H7) — "the config said so" is not a
justification (GP-8).

**GP-7 — Least complexity that mirrors reality.** Prefer the simplest architecture that meets the
requirement; escalate only on evidence.

**GP-8 — Rigor over compliance (adversarial honesty).** The operator's instructions do **not**
override the project's rigor. Any agent — or the operator — must challenge a request that is
illogical, unsupported, or erodes validation discipline, *including* a request to add, keep, or
expand something. Agreement-mode sycophancy (RISK_REGISTER H12) and doing work *merely because it
was asked* are defects, not courtesy. When challenged, re-derive from evidence, not from the last
stated preference. **"I did X because you asked" is never a sufficient justification; "I did X
because the evidence supports it" is.**

**GP-9 — Grounded execution ("no artifact, no action").** Nothing is executed or asserted without a
reference to a verifiable artifact — a Task Spec, an ADR, a data record with provenance, or a
**resolvable citation** (PMID / DB accession / file + text-span). Any claim, criterion,
classification, or decision that cannot name a resolvable source is **UNVERIFIED** and therefore
**non-authoritative**: it may not be shown as a result, cross a VUS→LP/LB threshold, or be submitted
externally. This does not *eliminate* hallucination — a model can still cite a real source that
doesn't support its claim — but it removes its *authority*: a fabricated or unresolvable reference is
rejected mechanically (citation resolver), a real-but-non-supporting one is caught by span-grounding,
and the residual — *wrong interpretation of a correctly-cited, span-grounded source* — is exactly what
GP-1's validation ceilings and GP-3's oracle govern. Implementation: [Part II §4](#operating-model-gates) (gate G7),
ARCHITECTURE §8 (referential integrity), RISK_REGISTER §1.

**GP-10 — Public-data-only & human-subjects boundary.** RAPTOR operates only on **public,
non-identifiable** data (ClinVar, gnomAD, PMC, ClinGen). No patient-level, lab-private, or
controlled-access data enters the system, and such data is **never** sent to third-party/cloud
models, without an explicit governed exception (consent / IRB / data-use agreement) recorded as a
decision. A controlled-access validation cohort is a *governed exception with its own record*, never a
default. (Guards privacy/human-subjects risk; see RISK_REGISTER R-B/R-G.)

**GP-11 — Enabler, not decision-maker (intended use & no overclaiming).** Every output *informs a
qualified human*; none is a diagnosis, a treatment decision, or clinical advice, and none is
patient-facing. No public or external claim (paper, README, demo, gap-map release) exceeds what the
layer's validation ceiling (GP-1) supports. The not-a-medical-device / not-CDS boundary (§9) is a
**design constraint on every feature**, not a footnote disclaimer.

**GP-12 — Stop honestly (explicit stop / pause / degrade conditions).** Halting beats shipping
unsafely, and the halt conditions are pre-declared, not improvised: freeze external output on any
wrong-classification incident (R-A1); **degrade** to the TSC evidence engine only if no oracle by the
Phase-3 gate (R-E1); pause the public tier if unfunded (R-F2); abort a run on spend-cap / canary /
heartbeat failure (R-C1/C3); and re-examine the project itself if the measurable half cannot beat
baseline (R-A2). Each condition names its owner and trigger in RISK_REGISTER.

**GP-13 — Vertical scope discipline (no vertical-washing) *(binding)*.** RAPTOR is a **vertical
TSC/mTOR research-evidence product, not a generic platform.** Every feature must name all five of:
(a) the specific **TSC/mTOR user** it serves, (b) the concrete **artifact** it produces, (c) the
**expert validator** who signs it off, (d) its **falsifier**, and (e) *why a generic
variant-interpretation / literature-agent / NGS product cannot supply it*. mTOR-related extensions are
admitted **one at a time** through an explicit gate — a fixed gene/disease/mechanism question carrying
all five of the above — never as an open scope. Relabeling generic ambition as "all things TSC/mTOR"
is **vertical-washing** and is out of scope (§9); this is the rule that keeps the reset from decaying
back into a horizontal platform (RISK_REGISTER R-D7; supersedes the generalise-to-all-rare-disease
framing of ADR-0001, per ADR-0010).

---

<a id="strategy-product-solution"></a>
### 6. Product solution — three vertical lines (built on one engine)

*(Pichler: the product, mapped to the guiding policy. Detail lives in ARCHITECTURE.md.)*

The vertical ships as **three product lines**, each with a named user, artifact, validator, and
validation ceiling (GP-13). All three run on the *same* reused deterministic + LLM engine; RAPTOR's
contribution is the **TSC-vertical evidence**, not new generic methodology (GP-4).

| # | Product line | What it delivers | **Validation ceiling (GP-1)** |
|---|---|---|---|
| **1** | **TSC deterministic evidence census + candidate packet** | The complete TSC1/TSC2 VUS census + per-variant **candidate evidence packet** (candidate LP/LB *direction* + full evidence trail) | **Eval-only, label-blind, non-authoritative** until ADR-0013's locked prospective validation PASSes, the production candidate policy is approved, and an expert signs off. *Never* a classification/reclassification (§8, PROGRAM.md). |
| **2** | **TSC evidence / functional-assay / contradiction atlas** | Where TSC evidence and PS3-grade functional assays exist, where they are missing, and which sources contradict each other | Premises citable/span-grounded; *coverage-completeness* is not guaranteed — ships as an **atlas of what exists**, not proof of what is true. |
| **3** | **Selected mTOR-condition hypothesis packets (gated)** | Falsifiable, fully-cited research-hypothesis packets for **one** gated mTOR-condition question at a time (GP-13) | **Oracle-poor.** Premises citable; the *leap* and *set-completeness* are not — ships as *cited hypothesis only*, after the GP-13 gate + oracle. |

These lines are delivered by the underlying **engine tiers** (mechanism, not product framing):

| Tier | What it does | Approach | **Validation ceiling (GP-1)** |
|---|---|---|---|
| **Tier 1 — Deterministic** | Automatable ACMG criteria (PVS1, PM2, BA1/BS1, PP3/BP4, PS1/PM5, BP7…) | BIAS-2015 + gnomAD/CADD/REVEL/SpliceAI; local CPU (~1,327 variants/sec) | **Measurable** vs *best-available proxy labels* — no TSC 3★ panel exists; see benchmark hierarchy (§7). |
| **Tier 2 — Computational** | Predictor scores, domain mapping, per-gene calibration | Scriptable batch (license-aware: CADD/SpliceAI non-commercial) | Measurable; deterministic and reproducible. |
| **Tier 3 — LLM extraction** | **PS3 functional evidence only (MVP)**; segregation/other criteria deferred; PM3/BP2 *trans* evidence N/A (TSC is autosomal-dominant) | Frontier models with **assay-validity rubric + variant-matching gate**; local models for abstract screening | **Per-premise citation-checkable** (AcmGENTIC ~96% PS3 is a *reference*, not a transferred guarantee). Ceiling: "assay says X, cited" — not "variant is pathogenic." |
| **mTOR extension (gated)** | Single gated mTOR-condition hypothesis packet (Line 3) | LLM as librarian over established mechanism, behind the GP-13 gate | **Oracle-poor.** Premises citable; the *leap* and *set-completeness* are not. Ships as *hypothesis only*. |
| **Consensus / adjudication** | Bayesian combination (Tavtigian 2018 LRs) → posterior → human review queue | Deterministic math + human sign-off | No "final classification" without human sign-off (§9). |

---

<a id="strategy-roadmap"></a>
### 7. Coherent Actions — roadmap

*(Rumelt: coordinated steps that implement the guiding policy. Sequenced, not exhaustive.)*

**Phase 0 — Foundation & census (substantially complete).**
- Frozen benchmark locked (`clinvar_2026-07-07`; PRD-06/07); label hierarchy: (1) ClinGen VCEP/3★ if any exist, (2) 2★ multi-submitter *concordant*, (3) curated literature DB, (4) manual expert adjudication. **Conflicting/single-submitter labels are excluded from the scored benchmark before the train/dev-vs-held-out split**; provenance tracked to avoid **circular validation** if RAPTOR later influences VCEP curation ([EVALUATION.md Part I §2](EVALUATION.md#evaluation-benchmark) and [Part II §3](EVALUATION.md#evaluation-benchmark-composition); ADR-0009).
- **First complete deterministic TSC1/TSC2 evidence census done** (6,618 VUS; internal, non-authoritative — PROGRAM.md). The x64 Nirvana/BIAS worker exists (ADR-0008); no MVP pipeline/orchestration skeleton was built — PRD-05 was never built and is now frozen (ADR-0010).

**Phase 1 — Held-out validation gate (measurable half; in progress).**
- The **label-free held-out VCF** was already emitted and scored on the x64 worker (BIAS-2015 v3.0.0 + Nirvana; 2,577 parsed records; ADR-0008) using the **full** comparator resources; the leakage-safe masked rerun (R2, [ADR-0012](DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)) has since **re-scored the masked resources** and run the ClinVar-derivation audit + PP3/BP4-disabled policy. *(Actual VUS production uses full comparator resources; held-out validation used masked resources.)*
- **Missense-stratified precision/recall have now been computed and gated (FAIL/BLOCKED_POLICY) on R2** — the frozen result is not, by itself, sufficient: [ADR-0013](DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)'s tiered v3 post-hoc re-adjudication corrects the *reporting* (missense `NO_CALLS`/`UNDERPOWERED` rather than a coarse FAIL; truncating-pathogenic `SUPPORTED_POSTHOC`) without generating new evidence. No candidate direction is trusted and no externally usable VUS worklist is released until the **prospective validation locked by ADR-0013** — the first NCBI ClinVar GRCh38 monthly archive dated on/after 2026-08-01, frozen before labels/scoring — PASSes, the production candidate policy is approved, and per-variant expert sign-off is complete.

**Phase 2 — Candidate evidence packet + atlas (Lines 1–2).**
- The **PRD-04 candidate evidence packet / output contract is active and unblocked now**; provisional representative/all-VUS packets may be built for internal review, but the full **externally usable** worklist ships **only after** the Phase-1 PASS + policy correction + expert approval (leakage-safe).
- Build the TSC **evidence / functional-assay / contradiction atlas** (PS3 coverage/gaps, contradictions). Provenance/freshness loop live (GP-5).

**Phase 3 — Selected mTOR-condition hypothesis packet (Line 3, gated).**
- Recruit the molecular-geneticist / functional-mTOR oracle (GP-3) **first**; admit **one** mTOR-condition question through the **GP-13 gate** (named user · artifact · validator · falsifier · why-not-generic).
- Pre-register the evidence grammar (premise · leap · falsifier) and ship as cited hypotheses only.

**Phase 4 — Adopt & sustain (vertical, not generalise-to-everything).**
- Name a first TSC adopter (VCEP / lab / researcher); sustainability answer for any public tier.
- *Not* a "generalise across all rare disease" phase — that framing is superseded (ADR-0010).

---

<a id="strategy-business-goals"></a>
### 8. Business goals — measures of success

*(Pichler: what success looks like. These are the KPIs PROGRAM.md rolls up.)*

| Dimension | Metric | Target posture |
|---|---|---|
| **Validated accuracy (Line 1 engine)** | Missense-stratified precision / recall vs the frozen held-out benchmark | Pre-registered thresholds; **PASS gates** externally usable packet/worklist release and VUS authorization. Internal non-authoritative expert-review packets may be prepared before PASS. |
| **Expert review yield** | Candidate packets **reviewed and accepted/rejected by an expert**; expert-agreement rate | The unit of success is an *expert-reviewed* packet, **not** a variant scored. |
| **Curator / research adoption** | Named TSC curators/researchers actually **using** packets or the atlas | Named wedge (VCEP / lab / researcher), not "published on GitHub." |
| **Research acted on** | Experiments / hypotheses the atlas or hypothesis packets **cause** (assays run, contradictions resolved, VUS re-examined) | Success = research *moved*, not artifacts *emitted*. |
| **Freshness** | Lag between ClinVar/gnomAD/literature update and re-validation | Bounded, monitored (GP-5). |
| **Extraction quality (Tier 3)** | PS3 extraction accuracy with matching gate | **RAPTOR-specific PS3 benchmark required**; AcmGENTIC (~96%) is a *reference baseline*, not a transferred target. |

**Explicitly *not* success metrics:** raw **VUS processed / week**, candidate-direction *counts*,
"agents spawned," or any volume figure — high throughput of **non-authoritative** output is not
progress and risks the *false-authority* failure (RISK_REGISTER R-G5).

Decision outputs are framed as **3–5-point probabilistic estimates with the key drivers named**, not
single hard calls — the model must be explainable and defensible to expert, board, and regulatory
review.

---

<a id="strategy-scope"></a>
### 9. Scope *(binding)*

**In scope**
- TSC1/TSC2 variant evidence and research gaps (auditable ACMG/AMP evidence assembly).
- Expert-reviewable **candidate evidence packets** (eval-only, non-authoritative until validated).
- TSC **functional-assay coverage/gaps and contradictions** (the atlas).
- **Selected mTORopathy extensions only** for a fixed gene/disease/mechanism question with a named
  user, expert validator, falsifier, and a reason generic engines are insufficient (GP-13).
- Integration / reuse of existing generic engines (BIAS-2015, Nirvana, KGs) — buy/reuse, don't rebuild.

**Explicitly out of scope**
- A **generic ACMG engine / variant-interpretation platform**.
- A **generic literature-agent stack**.
- A **generic NGS pipeline**.
- Patient-facing diagnosis / treatment; clinical decision support for individual patients.
- **Cross-gene ACMG evidence transfer** (evidence proven on TSC is not reused as-is on other genes).
- **"Same pathway therefore same drug"** claims.
- Broad **"all things TSC"** implementation scope (vertical-washing — GP-13).
- Regulated medical devices / Software-as-a-Medical-Device claims.
- **Any "final classification" without human sign-off.**
- Cross-disease claims presented as validated discovery rather than cited hypothesis.

**Two sign-off levels (not interchangeable):** the **operator** approves *internal* pipeline records
and the review queue; any **externally meaningful** proposed classification or ClinVar submission
requires a **qualified molecular geneticist / VCEP** (the GP-3 oracle). Operator approval alone never
produces an external classification.

---

<a id="strategy-risks"></a>
### 10. Risks & honest tensions

> This is the distilled **top-tier** view. The exhaustive failure-mode analysis (58 modes across 8
> categories — including category H imported from the OpenCell program — each with detection +
> mitigation + contingency) lives in **[RISK_REGISTER.md](RISK_REGISTER.md)**.
> The meta-risk for a solo, unattended system: **failing silently and not noticing** (R-C1) — the
> register is built around *detection first*.

**Six existential risks** (full treatment in the register):

| Risk | Nature | Mitigation |
|---|---|---|
| **Wrong classification reaches a family** (R-A1) | Trust is the product; one wrong call ends it. | Two-key sign-off; human gate; "hypothesis not verdict"; conservative thresholds. |
| **Validation is a mirage** (R-A2) | Benchmark overfit / circular labels make "it passed" meaningless. | Held-out split; freeze benchmark by date/source; exclude RAPTOR-touched labels. |
| **Silent failure in unattended runs** (R-C1) | Solo operator finds out weeks late. | Heartbeat/dead-man's switch; canary set every run; Prefect alerts. |
| **No domain oracle recruited** (R-E1) | Cross-linkage unvalidatable; PS3 strength unchecked. | Oracle-first gate (GP-3); else graceful degradation to TSC engine only. |
| **Built but unused / unfunded** (R-F1) | Dies regardless of quality. | Name a wedge (VCEP triage); Phase-4 sustainability answer. |
| **Perceived "AI practising medicine"** (R-G1) | Reputational + regulatory backlash. | Hard scope disclaimers (§9); enabler-not-CDS; no prescribing language. |

**Strategy-reset risks (2026-07 — from the vertical pivot; full rows in the register):**

| Risk | Nature | Mitigation |
|---|---|---|
| **Absence-of-output read as demand** (R-A12) | Zero indexed TSC campaigns / zero VCEP submissions taken as a market opening. | Treat as an *unresolved institutional/adoption* question, not demand; name a real adopter (R-F1). |
| **False authority from polished output** (R-G5) | Eval-only candidate packets *look* authoritative. | Non-authoritative labelling everywhere; no volume metrics (§8); human sign-off (§9). |
| **Commoditized generic engine** (R-F4) | A funded generic platform commoditizes the reused layer. | Moat is the TSC-vertical evidence, not generic ACMG; reuse/buy the engine (GP-4). |
| **Vendor substitution** (R-F5) | A vendor ships a TSC-capable vertical. | Differentiate on open benchmark + auditability + freshness; collaborate not compete. |
| **Vertical-scope creep** (R-D7) | "All things TSC/mTOR" re-inflates to a platform. | GP-13 gate (named user/artifact/validator/falsifier/why-not-generic); one mTOR extension at a time. |
| **Expert-oracle bottleneck** (R-E4) | Expert review rate-limits the whole vertical. | Rank for highest expert-value-per-hour; batch; recruit early (GP-3). |
| **Community/adoption dependency** (R-F6) | The vertical needs a TSC curator/research community that may not engage. | Named wedge; low-friction packets; sustainability answer (Phase 4). |

**Honest tensions** (structural, not fully closable):

| Tension | Nature | Approach |
|---|---|---|
| **Validation asymmetry** | Tier 1/2 measurable; the gated mTOR extension (Line 3) is not. | GP-1/GP-2/GP-13: never sell the unmeasurable half as validated; gate mTOR extensions one at a time. |
| **Operator-is-not-a-biologist** | Asset for codified variant work; liability for mechanistic synthesis. | Recruit domain oracle before the synthesis layer. |
| **Freshness as unbounded work** | ClinVar weekly, gnomAD ~18mo, literature daily. | Designed-in re-validation loop (GP-5); freshness is a KPI. |
| **Non-commercial data licensing** | CADD/SpliceAI/REVEL research-use-only; some users are commercial. | Licensing matrix; research-only vs redistributable output modes. |

---

<a id="strategy-what-lives-elsewhere"></a>
### 11. What lives elsewhere

Part I in this file is intentionally the *intent* layer; Part II covers build governance. Runtime,
status, risk, evaluation, and feature contracts live in siblings:

- **PROGRAM.md** — live status rollup, current-week priorities, health.
- **RISK_REGISTER.md** — exhaustive failure-mode analysis (detection + mitigation + contingency).
- **docs/prd/** — **one PRD per feature** (PRD-01 …), each a specific vertical slice; index deferred until ≥3 exist.
- **ARCHITECTURE.md** — fleet, LiteLLM/Prefect runtime, data model, model routing.
- **DECISIONS.md** — ADR-style record of every strategy/scope change to this doc.
- **EVALUATION.md** — benchmark protocol, preregistered rubric, gate semantics, reporting rules, and prospective-lock governance; **BENCHMARK_RESULTS.md** *(planned)* — results.
- **pre-build/** *(local-only, git-ignored)* — source research, session exports & adversarial framing this doc distils (FYTSC_1/2, raptor framing, infra & session notes).

---

<a id="strategy-appendix-a"></a>
### Appendix A — Key numbers (with sources)

| Metric | Value | Source |
|---|---|---|
| **TSC VUS census (deterministic, internal, non-authoritative)** | **6,618** total · TSC1 **2,249** · TSC2 **4,369** | `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (2026-07-07) |
| TSC2 VUS / total / expert-panel *(earlier ClinVar pull)* | 4,445 / 7,645 / **0** | ClinVar, Jun 2026 (different snapshot; re-verify at run) |
| ClinGen TSC VCEP ClinVar submissions | 0 | ClinVar, verified 2026-06-16 — *unresolved adoption question, not demand* |
| ClinVar VUS share | 2,355,835 / 4,274,341 (55.1%) | ClinVar, Jun 2026 |
| TSC global prevalence / birth incidence | ~1 in 6,000–10,000 / ~1 in 6,000 | Multiple reviews, 2024–25 |
| TSC patients worldwide / Europe | ~1–2 million / ~77,000–82,000 | Reviews; E-TSC (e-tsc.eu) |
| TOSCA registry | ~2,093–2,214 patients · 170–250 sites · 31 countries | Kingswood & de Vries, *Orphanet J Rare Dis* 2017 |
| mTOR papers 2015–2026 | 14,594 | PubMed E-utils, Jun 2026 |
| Indexed TSC-specific automated-classification campaigns found | 0 *(no indexed campaign found — **not** "no capable platform")* | PubMed E-utilities, verified 2026-06-16 (4 queries, 2015/2018–2026); see [reference/competitive-landscape-2026-07.md](reference/competitive-landscape-2026-07.md) |
| BIAS-2015 throughput / coverage | 1,327 variants/sec · 19/28 ACMG criteria | *Genome Medicine* 2025 |
| AcmGENTIC PS3 extraction | ~96% with matching gate | arXiv 2604.00075, Mar 2026 |

> **Freshness note:** ClinVar/gnomAD/PubMed figures are point-in-time (Jun 2026 session pulls) and
> must be re-verified at each run — see GP-5.

<a id="strategy-appendix-b"></a>
### Appendix B — Framework provenance

- **Product Vision Board** — Roman Pichler (Vision · Target Group · Needs · Product · Business Goals).
- **Kernel of Good Strategy** — Richard Rumelt, *Good Strategy / Bad Strategy* (2011):
  Diagnosis → Guiding Policy → Coherent Action.

<a id="strategy-part-ii"></a>
## Part II — Operating Model

> **Part II status:** DRAFT v0.1 · **Owner:** @dronasrinivas · **Last updated:** 2026-07-22 (added §7 parallel git-worktree delegation note) · **Review cadence:** monthly + rule-graduation on any new failure class
>
> **Part II format:** recognized building blocks, not a bespoke invention — **RACI** (responsibility assignment), Scrum **Definition of Ready / Definition of Done** (the hand-off gates), the **design→test-author→build→review→eval** agentic loop, and the **three-slot prompt architecture** proven in the operator's OpenCell program (`srinivasdrona/opencell`, dev blog 2026-06-01).

<a id="operating-model-purpose"></a>
### 0. Purpose & scope

This doc governs **how RAPTOR is built** (development-time process). It is *not* how RAPTOR runs —
that is `ARCHITECTURE.md`. It operationalizes **ADR-0003** plus **ADR-0005**
(planner/test-author/doer/checker) and is the
mechanism behind the build-loop risks in `RISK_REGISTER.md` category H (H1, H3, H4, H9, H10, H11, H12).

**Binding sections:** §2 (roles), §4 (gates). Changing either is a process change → log in
`DECISIONS.md`. **Governing principles: GP-8** — a task is done when the *evidence* says so, never
because it was asked for or looks green; **GP-9** — no execution without a referenced artifact
(every task carries a `motivating_reference`; every claim resolves to a source, or is `UNVERIFIED`).

---

<a id="operating-model-loop"></a>
### 1. The loop

A **unit of work** = one task: a vertical slice, one bug-class fix, or one doc. Each flows:

```
   ┌────────── design ──────────┐
   │ Planner (Opus) writes a    │
   │ Task Spec + acceptance     │
   │ criteria (Definition of    │
   │ Ready)                     │
   └──────────────┬─────────────┘
                  ▼
   ┌────── test authoring ──────┐
   │ Test-author (Gemini) turns │
   │ the spec into executable   │
   │ RED acceptance tests       │
   └──────────────┬─────────────┘
                  ▼
   ┌────────── build ───────────┐
   │ Doer (Sonnet 5) implements │
   │ against the spec; emits a  │
   │ VERIFICATION block         │
   └──────────────┬─────────────┘
                  ▼
   ┌──── review / eval ─────────┐        DO-NOT-MERGE / WITH-CHANGES
   │ Checker (GPT) runs the     │──────────────┐
   │ gates (Definition of Done) │              │ back to design with the
   └──────────────┬─────────────┘              │ named failure mode
                  │ CLEAN                       ▼
                  ▼                     (re-spec, don't patch blind)
        Operator merges + (if externally meaningful) Oracle sign-off
```

**Entry to a stage requires the prior stage's artifact.** No silent hand-offs (a spec, a
VERIFICATION block, and a verdict are all written and persisted).

<a id="operating-model-roles"></a>
### 2. Roles, model assignment & RACI *(binding)*

| Role | Model / who | Owns |
|---|---|---|
| **Planner** | Claude **Opus** | Decompose; write Task Spec + the acceptance-test *contract* (which ACs/invariants); long-range reasoning. **No production code, no test code** — stays context-clean. |
| **Test-author** | **Gemini** (3.x) | Turn the spec's ACs into executable, assertion-specific tests **from the spec only (never sees the doer's code)**. Delegated/detached so planner context stays clean. |
| **Doer** | Claude **Sonnet 5** | Implement against the spec to pass the pre-authored tests; may *add* but not weaken them; own the change end-to-end; emit VERIFICATION. |
| **Checker** | **GPT (5.x)** | Adversarially run the gates; re-run independently; pass or return with a *named* failure mode. |
| **Operator** | @sdrona (human) | Accountable for the whole loop; merges; approves internal records. |
| **Oracle** | molecular geneticist (GP-3) | Domain-truth sign-off for any externally-meaningful output. |

**RACI per stage** (R=responsible, A=accountable, C=consulted, I=informed):

| Stage | Planner | Test-author | Doer | Checker | Operator | Oracle |
|---|---|---|---|---|---|---|
| Design | **R** | C | C | C | **A** | C (domain tasks) |
| Test authoring | C | **R** | I | C | **A** | – |
| Build | C | I | **R** | I | **A** | – |
| Review/eval | I | I | C | **R** | **A** | C (domain tasks) |
| Merge / external sign-off | I | I | I | C | **R** | **A** (external only) |

**Hard rules**
1. **Checker family ≠ doer family** — adversarial review, not self-review (R-D1). GPT checks Sonnet's work; never Sonnet checks Sonnet.
2. **Test-author family ≠ doer family** — the tests must not share the code's blind spots (H2/H4 confirmation bias). Sonnet builds; **Gemini writes the tests**; GPT checks. Four families (Opus/Gemini/Sonnet/GPT) = maximal independence.
3. **The test-author writes from the spec only and never sees the doer's implementation** — tests encode the *requirement*, not the code.
4. Model *roles* are fixed; specific *versions* are config (GP-6), not hardcoded.
5. The **checker validates form, consistency, spec-conformance, and evidence — not domain truth.** Domain truth needs the Oracle (H11); acceptance criteria are typed accordingly (§3.1, §4 G4).

<a id="operating-model-escalation"></a>
#### 2.1 Escalation & disagreement

- **DO-NOT-MERGE is not operator-overridable** without a re-spec (a new Task Spec addressing the named failure mode).
- **Process disputes** (checker vs operator): a second checker instance adjudicates; the override rationale is logged in the work record.
- **Domain disputes** are resolved by the **Oracle**, never by the operator or an LLM (H11).
- **Contested oracle call:** if the operator or checker finds an artifact/evidence gap in an Oracle decision, it is escalated to a **second oracle** or labelled `UNVERIFIED`. The Oracle owns *domain truth*, but GP-9 still applies — "the expert said so" without a resolvable basis is UNVERIFIED, not authoritative.
- **Oracle unavailable:** any task carrying a `domain-truth` acceptance criterion is **blocked or labelled `UNVERIFIED`** and cannot be CLEAN (ties to STRATEGY graceful-degradation, R-E1).

<a id="operating-model-handoffs"></a>
### 3. Hand-off contracts

<a id="operating-model-task-spec"></a>
#### 3.1 Task Spec — Planner → Doer *(Definition of Ready)*

```yaml
task_id:            # kebab-case, stable
goal:               # one sentence, testable
motivating_reference: # the ADR / STRATEGY §/ RISK id this task serves — no task without one  [GP-9]
context_surface:    # the files/functions to touch (point, don't make the doer hunt)
reference_files:    # ≤ 4; none > ~2000 lines (else use a long-context doer)  [H9]
acceptance_criteria:# list; each: {text, type: mechanical | evidence-form | domain-truth}
                    #   domain-truth criteria cannot be CLEAN without Oracle sign-off  [H11]
preservation_set:   # test/assertion IDs that must NOT change; checker fails any diff touching them  [H3]
invert_failure_modes: # 1–3 named ways this could go wrong (Beat-4 / Munger inversion)
out_of_scope:       # explicit; prevents scope spiral
na_allowed:         # true/false — if a fix may be honestly infeasible
na_requires:        # if na_allowed: the specific missing input + what would unblock  [H8]
```

**Definition-of-Ready preflight (before the doer runs).** The operator (or checker) verifies the spec
is complete *and* a `prompt_manifest` is persisted:
`{slot1_id+hash, slot2_id+hash, slot3 content or slot3_na_reason, intent_block_present: true}`.
A spec missing `acceptance_criteria`, `context_surface`, or a complete manifest is **not Ready** — the
unit is rejected *before* build, not after. This preflight is how slot omission (H10) is actually
caught.

<a id="operating-model-doer-output"></a>
#### 3.2 Doer output — Doer → Checker

An **INTENT block** at turn 1 (restates the contract + a PM sanity-check sentence), the **change as a
persisted diff / patch / commit ID**, and a **VERIFICATION block**: evidence for *each* acceptance
criterion and *each* named failure mode, the test command + result, and the trace-cribbing lint
output. The doer's evidence is a *claim, not proof* — the checker re-verifies it (§3.3). A run that
ends with `finish_reason = token_cap` and no persisted diff/verdict is a **failure**, not a pass (H9).

<a id="operating-model-checker-verdict"></a>
#### 3.3 Checker Verdict — Checker → Operator *(Definition of Done)*

The checker **re-runs what it can** (tests, lints) and **inspects the diff** — it never passes on the
doer's word (ADR-0003 "review/eval"). Anything it cannot independently verify is **not CLEAN**.

```yaml
verdict:        CLEAN | WITH-CHANGES | DO-NOT-MERGE
gates:          {G1: .., G2: .., ..}   # per-gate result + CHECKER-run evidence
verified_by:    checker                # confirms the checker (not the doer) re-ran the checks
diff_or_commit: # the artifact reviewed (commit / patch id)              [H4]
test_ids:       # tests that back each acceptance criterion              [H4]
commands_run:   # exact commands the CHECKER executed
contrary_case:  # strongest reason this could still be wrong / challenged premise  [H12]
notes:          # named failure mode(s) if not CLEAN — actionable, specific
```

Scoring: any **DO-NOT-MERGE** on any gate ⇒ unit fails; **WITH-CHANGES** ⇒ return for fix. **Only
CLEAN — backed by checker-run evidence — is "done."** A missing `contrary_case` is itself
WITH-CHANGES (guards sycophancy, H12). "Looks green" is not a verdict.

<a id="operating-model-gates"></a>
### 4. Gates — Definition of Done *(binding)*

Adapted from OpenCell's 5-gate critique, extended with the RAPTOR failure modes:

| Gate | Passes only if… | Guards |
|---|---|---|
| **G1 · Preservation** | No test/assertion in the spec's `preservation_set` is weakened, loosened, or deleted; the checker inspects the test diff. | **H3** |
| **G2 · No trace-cribbing** | A **checker-run** script (canonical forbidden-path globs + config/env + alias/AST checks, scoped to the pipeline package) confirms production code cannot read any benchmark/label/oracle artifact. Doer-pasted `RULE-8-CLEAN` is **not** sufficient. *(Manual until the script/CI hook exists — §10.)* | **H1** |
| **G3 · Non-triviality** | Every new/changed test asserts a *specific expected non-zero signal* — no "empty == empty at tolerance" pass. | **H2, H4** |
| **G4 · Acceptance met** | The checker **independently** reruns/inspects evidence per criterion. *Mechanical* and *evidence-form* criteria pass on checker-run evidence; *domain-truth* criteria are **not CLEAN without Oracle sign-off** — labelled `UNVERIFIED` and blocked from external use. "Unable to verify" ⇒ not CLEAN. | R-D1, **H11** |
| **G5 · Fail-fast** | Missing input raises at construction/first call — never silently returns `{}`/zeros/placeholder. | **H5** |
| **G6 · Honest N/A** | Any "can't be done" cites the specific missing input + an unblock proposal — not a bare skip. | **H8** |
| **G7 · Grounding** | Every factual/quantitative claim in the artifact names a **resolvable** reference (ADR / data record / PMID / DB accession / file+span); the checker resolves a sample. An unresolvable or missing reference ⇒ the claim is `UNVERIFIED` and the unit is not CLEAN. | **GP-9, H13, R-A6** |

Every gate result cited in a CLEAN verdict must be **checker-run evidence**, not the doer's report.

<a id="operating-model-test-authorship"></a>
#### 4.1 Test-authorship separation *(pre-facto defense — the highest-leverage rule)*

The PRD-03 build shipped 78 green tests that hid 5 real bugs, because the **doer wrote the code and
its tests in one pass** — the tests inherited the code's blind spots (confirmation bias; RISK_REGISTER
H2/H4). Post-facto the different-family checker caught them, but the cheaper fix is pre-facto:

- **For foundational / high-assurance modules, a dedicated *test-author* agent (Gemini — a different
  family from the Sonnet doer *and* the GPT checker) writes the acceptance-test contract — the spec's
  AC1..N as executable, assertion-specific tests — *before* the doer builds, and *from the spec only*
  (never seeing the doer's code).** The **planner owns the test *contract* (which ACs/invariants to
  cover) but delegates the test *code*** — keeping the planner context-clean for long-range reasoning
  while still breaking the confirmation-bias loop at build time (the test author ≠ the code author).
  Why Gemini and not the best single test-writer (Claude): the doer is Claude-family, so a Claude
  test-author would re-share the blind spot; independence beats raw single-model quality here.
- **The doer implements to make those tests pass; it may *add* tests but must not weaken, modify, or
  delete the pre-authored ones** (G1 preservation still applies).
- **Test the real API/publish path, not direct-table SQL** — integration gaps hid the `run_id` bug.
- **Property-based invariants** (`hypothesis`, allowed as a dev-only dep) are preferred for core
  invariants (e.g. "no variant publishes without a source_ref") — harder to game than hand-picked
  examples.
- **Self-audit / lint tests must be proven to catch a *known injected* violation** — the GP-6 audit
  that missed its own `CREATE TEMP TABLE` violation would have failed this meta-test.
- **Local models are NOT used for foundational test authoring** (quality risk: a weaker author can't
  catch a stronger doer's bugs; ARM/Ollama immaturity; heavy models want the 64GB workers not the
  32GB Queen). Reserve local models (Qwen2.5-Coder-14B/32B) for Tier-3 screening and later
  low-stakes/bulk generation — see ADR-0005.

This does **not** retire the checker — it is defense-in-depth (pre-facto lowers introduction; the
checker catches the remainder), and it moves confirmation-bias risk onto the test author, so the
planner derives tests strictly from the spec's ACs and the checker still re-runs independently.

<a id="operating-model-three-slot-prompts"></a>
### 5. Prompt composition — three slots *(guards H10)*

Slots **1 and 2 are always present**; **slot 3 is required whenever the doer can modify existing code
or tests**, else the manifest records an explicit `slot3_na_reason`. Slot presence is proven by the
`prompt_manifest` (§3.1); the Ready preflight rejects a task with an unexplained missing slot.

| Slot | Scope | Content |
|---|---|---|
| **1 · Prefix** (generic) | every task | Deliberate-action + the **INTENT block** requirement: name the contract → point at the surface → verbalize expected outcome → **invert** (name Beat-4 failure modes) → act, then verify. |
| **2 · Task template** (domain) | per work class | The probes/rules specific to this class of work (e.g. ACMG scoring, Tier-3 extraction, config edits). Grows by rule-graduation (§7). |
| **3 · Preservation directive** (case) | per run, when the doer can rewrite existing code/tests | Name the *specific* prior failure mode and the *specific* assertions that must not change. |

<a id="operating-model-integrity-controls"></a>
### 6. Integrity controls

| Control | Guards | Status | Mechanic |
|---|---|---|---|
| Checker ≠ doer family | R-D1 | **live** | Structural rule (§2) — the only control that exists today. |
| Checker re-runs evidence | R-D1, H4 | manual | Checker executes tests/lints + inspects diff; unverifiable ⇒ not CLEAN (§3.3). |
| Checker-integrity probe | R-D1 | planned | Operator injects a known-bad diff from a stored probe corpus **monthly + on any checker-model change**; a miss ⇒ freeze merges + re-review everything since the last passing probe. |
| Adversarial `contrary_case` | **H12** | manual | Required verdict field; its absence is WITH-CHANGES. "Specificity without structured doubt scored 0.0" (OpenCell Gold arm). |
| Trace-cribbing lint | **H1** | planned | Checker-run script (§4 G2); pre-commit/CI target. |
| Zero-commit / cap-death detection | **H9** | manual | Failure = no persisted diff/verdict **and** no explicit N/A, or `finish_reason = token_cap`; decompose + re-fire. |
| Post-merge CLEAN audit | R-D2 | planned | Random re-check of merged CLEAN units; a wrong CLEAN reopens the unit **and** graduates a rule (§8). |
| Operator-fatigue guard | R-D5 | manual | No domain-impacting or external merge at the end of a long session; sleep-on-it for any reclassification-affecting change. |
| Model/version pinning | R-C6 | manual | Persist `{provider, model_id, version/date, prompt-hash}` per task; a mid-task model change forces a rerun / new task. |
| Property-based tests (**Hypothesis**) | H2/H4 | dev-dep | Core invariants as properties over generated inputs; auto-shrinks failures. Preferred over example-only tests for critical invariants (ADR-0005). |
| Mutation testing (**mutmut**) | H2/H4, R-D2 | planned | Selective, on core modules: inject mutations; a surviving mutant = a hollow test. The mechanical anti-hollow-green detector (ADR-0005). |
| Agent least-privilege | R-C5, R-G4 | policy | A delegated agent is **workspace-confined**; destructive or external ops (file delete, dependency install, remote/DB write, external submit) **require approval**; **auto-approve is never shipped** for these. *(Adopted from ai4s/open-science safety defaults.)* |
| VERIFIED/UNVERIFIED labelling | H13/R-A6 | manual | Every quantitative claim labelled; "I don't know" is allowed. |

<a id="operating-model-delegation"></a>
### 7. Delegation rules (guards H9)

- **One hypothesis / bug-class per task.** Enumerating 5+ failure modes in one task pushes a delegate
  into "write the plan, exit without doing it" — keep slot 3 to 1–3 named modes.
- **≤ 4 reference files; none > ~2000 lines.** A large reference file eats the budget before code is
  written; use a long-context doer for those.
- **Disable slow PreToolUse hooks before delegating** — per-tool-call hook latency causes stream
  disconnects and zero-commit deaths.
- **Detect and decompose:** a run with no persisted diff/verdict (or `finish_reason = token_cap`) is a **failure**, not a pass → split into narrower tasks and re-fire (H9).
- **Independent modules get their own `git worktree`.** Tasks that touch a distinct module/spec (e.g.
  `docs/project/specs/*.yaml`, `docs/prompts/*/manifest.json`) are assigned a dedicated worktree under
  `D:\AIProjects\raptor-worktrees\<name>` on its own branch — this is how this very reconciliation task
  runs (`raptor-worktrees\docs-reconcile`, branch `docs/reconcile-2026-07-22`). Parallel worktrees let
  independent delegated tasks run concurrently without one task's uncommitted state blocking another's,
  and keep each task's diff scoped and reviewable against a pinned base commit.

<a id="operating-model-rule-graduation"></a>
### 8. Rule-graduation loop (the core discipline)

The loop's job is **not** zero first-try failures — it is **zero *tolerated* recurrence**: a repeat of
a named class, *or a CLEAN later found wrong*, must trigger escalation. When such a failure appears:

1. Name it (add a row to `RISK_REGISTER.md` if genuinely new — GP-8 applicability audit first).
2. Append a **permanent rule** to the relevant slot-2 task template.
3. Where cheap, encode it as a **CI lint / pre-commit gate** (the G2 trace-cribbing `grep` is the
   first candidate).
4. Add a **checker gate** if it can't be linted mechanically.

Every rule is "paid for" by exactly one real failure. One failure → one durable rule.

<a id="operating-model-graduated-rules-v1"></a>
#### 8.1 Graduated rules v1 — from the PRD-03 (KB) build

The five DO-NOT-MERGE failure modes, generalised into permanent slot-2 rules (apply to every module):

1. **Grounding on *every* groundable table, incl. many-source ones.** If "≥1 child" can't be a
   declarative FK (e.g. `variants`→`variant_source_refs`), enforce it at **publish-time validation**
   *and* the write API — plus a negative test that an ungrounded row fails. *(bug 1)*
2. **Every FR that names an API/publish path gets an integration test on that path, not just
   direct-table SQL.** *(bug 2 — dropped `run_id`)*
3. **Ledger-is-source-of-truth: any projection table is written via a ledger event; its test
   reconstructs it by replay** (incl. secondary fields like approvals). *(bug 3)*
4. **Schema/DDL lives in SQL/config, never hardcoded in Python** — and the GP-6 audit catches
   `CREATE TEMP/TEMPORARY TABLE`, not just `CREATE TABLE`. *(bug 4)*
5. **The full runtime contract is *verified*, not assumed** (e.g. `synchronous=FULL`), with a test
   that fails on downgrade. *(bug 5)*
6. **Self-audit/lint tests must catch a known injected violation** before they count (meta-test). *(cross-cutting)*

Until `docs/prompts/` templates exist, these live here and are pasted into build prompts as slot 2.

<a id="operating-model-artifacts"></a>
### 9. Artifacts & locations

| Artifact | Lives in |
|---|---|
| Task specs + checker verdicts | session/work log per task (persisted, not silent) |
| Slot templates (1/2/3) | `docs/prompts/` (planned) |
| Graduated rules + CI lints | `docs/prompts/` + `scripts/` / pre-commit config (planned) |
| Process decisions | `DECISIONS.md` |

<a id="operating-model-honest-automation-status"></a>
### 10. Not yet automated (honest state)

- Gates are **checker-enforced by an LLM + operator eyeball**; **no gate is mechanically automated
  yet** — even the G2 trace-cribbing script/CI hook is *planned*, not built. Every §6 control marked
  `planned` does not exist today; only "checker ≠ doer family" is `live`. The manual cost is real
  (RISK_REGISTER R-D2/R-D3/R-D5).
- Spec/verdict **schemas and the `prompt_manifest` are conventions**, not yet validated by tooling.
- The checker-integrity probe and post-merge CLEAN audit (§6) are defined but **not yet scheduled/run**.
- **Nothing here is safe to trust unattended until the §6 `planned` controls ship** — consistent with
  RISK_REGISTER §9 (treat every green as provisional).

These gaps are why PROGRAM.md still lists the build-loop controls as *Open*.
