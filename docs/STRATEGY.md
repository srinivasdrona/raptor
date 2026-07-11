# RAPTOR — Vision & Strategy

> **Status:** DRAFT v0.2 — *vertical TSC/mTOR reset* (see [ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)) · **Owner:** @dronasrinivas · **Last updated:** 2026-07-10 · **Review cadence:** monthly
>
> **Format:** This document follows two established, citable standards — Roman Pichler's
> **Product Vision Board** (Vision · Target Group · Needs · Product · Business Goals) wrapped around
> Richard Rumelt's **Kernel of Good Strategy** (Diagnosis → Guiding Policy → Coherent Action,
> *Good Strategy / Bad Strategy*, 2011). Nothing here invents a bespoke structure.

---

## 0. Purpose of this document

**What this is:** the single strategic anchor for RAPTOR. It states *why the project exists*, *why
TSC is the starting point*, *what will and will not be built*, and *how success is measured*.

**Who it serves:** any agent or human reviewer who needs to orient in one read — a contributor
picking up a task, a domain expert or funder evaluating the premise, or a future self checking for
drift.

**How to use it:** treat sections **5 (Guiding Policy)** and **9 (Scope)** as binding — a change
here is a strategy change and needs an explicit decision record. Everything else is evidence and
rationale supporting those two. Execution detail (PRD, architecture, data model, runbook) lives in
sibling docs (§11), **not** here. If this doc and a sibling disagree, this doc wins on *intent*; the
sibling wins on *mechanism*.

**One-line summary:** *A vertical TSC/mTOR research-evidence product — an auditable engine that turns
public TSC1/TSC2 data into expert-reviewable candidate evidence packets, an evidence/assay/
contradiction atlas, and falsifiable research hypotheses — that accelerates the researchers who
resolve TSC variants, and never replaces their judgement. It is **not** a generic
variant-interpretation platform.*

---

## 1. Vision

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

## 2. Diagnosis — why this is needed

*(Rumelt: name the challenge, with evidence, before proposing any approach.)*

### 2.1 The core problem: the VUS pile is large, clinically consequential, and unattended

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

### 2.2 The market & research landscape — capable general platforms exist; the TSC-specific vertical is under-served

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

### 2.3 Why the TSC-specific vertical is under-served — structural, not "empty space"

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

## 3. Why TSC — the vertical, and its gated mTOR extensions

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

## 4. Target group & needs

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

## 5. Guiding Policy *(binding)*

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
GP-1's validation ceilings and GP-3's oracle govern. Implementation: OPERATING_MODEL §4 (gate G7),
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

## 6. Product solution — three vertical lines (built on one engine)

*(Pichler: the product, mapped to the guiding policy. Detail lives in ARCHITECTURE.md.)*

The vertical ships as **three product lines**, each with a named user, artifact, validator, and
validation ceiling (GP-13). All three run on the *same* reused deterministic + LLM engine; RAPTOR's
contribution is the **TSC-vertical evidence**, not new generic methodology (GP-4).

| # | Product line | What it delivers | **Validation ceiling (GP-1)** |
|---|---|---|---|
| **1** | **TSC deterministic evidence census + candidate packet** | The complete TSC1/TSC2 VUS census + per-variant **candidate evidence packet** (candidate LP/LB *direction* + full evidence trail) | **Eval-only, label-blind, non-authoritative** until the held-out gate PASSes and an expert signs off. *Never* a classification/reclassification (§8, PROGRAM.md). |
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

## 7. Coherent Actions — roadmap

*(Rumelt: coordinated steps that implement the guiding policy. Sequenced, not exhaustive.)*

**Phase 0 — Foundation & census (substantially complete).**
- Frozen benchmark locked (`clinvar_2026-07-07`; PRD-06/07); label hierarchy: (1) ClinGen VCEP/3★ if any exist, (2) 2★ multi-submitter *concordant*, (3) curated literature DB, (4) manual expert adjudication. **Conflicting/single-submitter labels are excluded from the scored benchmark before the train/dev-vs-held-out split**; provenance tracked to avoid **circular validation** if RAPTOR later influences VCEP curation (EVAL_PLAN.md; ADR-0009).
- **First complete deterministic TSC1/TSC2 evidence census done** (6,618 VUS; internal, non-authoritative — PROGRAM.md). The x64 Nirvana/BIAS worker exists (ADR-0008); no MVP pipeline/orchestration skeleton was built — PRD-05 was never built and is now frozen (ADR-0010).

**Phase 1 — Held-out validation gate (measurable half; in progress).**
- The **label-free held-out VCF** was already emitted and scored on the x64 worker (BIAS-2015 v3.0.0 + Nirvana; 2,577 parsed records; ADR-0008) using the **full** comparator resources; the remaining leakage-safe steps are to **regenerate the ClinVar-derived comparator resources (PS1/PM5/PM1/PP2/BP1) with the held-out variants masked**, **re-score** on the masked resources, and run the **ClinVar-derivation audit** + Oracle ruling (ADR-0009). *(Actual VUS production uses full comparator resources; held-out validation must use masked resources.)*
- Report **missense-stratified** precision/recall vs the frozen benchmark — **not yet computed**; the **PRD-06 gate must PASS** (both directions) before any candidate direction is trusted or any externally usable VUS worklist is released.

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

## 8. Business goals — measures of success

*(Pichler: what success looks like. These are the KPIs PROGRAM.md rolls up.)*

| Dimension | Metric | Target posture |
|---|---|---|
| **Validated accuracy (Line 1 engine)** | Missense-stratified precision / recall vs the frozen held-out benchmark | Pre-registered thresholds; **PASS gates** any candidate-packet release or VUS run. |
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

## 9. Scope *(binding)*

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

## 10. Risks & honest tensions

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

## 11. What lives elsewhere

This doc is intentionally the *intent* layer. Mechanism and status live in siblings:

- **PROGRAM.md** — live status rollup, current-week priorities, health.
- **RISK_REGISTER.md** — exhaustive failure-mode analysis (detection + mitigation + contingency).
- **docs/prd/** — **one PRD per feature** (PRD-01 …), each a specific vertical slice; index deferred until ≥3 exist.
- **ARCHITECTURE.md** — fleet, LiteLLM/Prefect runtime, data model, model routing.
- **OPERATING_MODEL.md** — the build loop: planner/doer/checker hand-off contracts + gates.
- **DECISIONS.md** — ADR-style record of every strategy/scope change to this doc.
- **EVAL_PLAN.md** — benchmark definition + metrics every PRD measures against; **BENCHMARK_RESULTS.md** *(planned)* — results.
- **pre-build/** *(local-only, git-ignored)* — source research, session exports & adversarial framing this doc distils (FYTSC_1/2, raptor framing, infra & session notes).

---

## Appendix A — Key numbers (with sources)

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

## Appendix B — Framework provenance

- **Product Vision Board** — Roman Pichler (Vision · Target Group · Needs · Product · Business Goals).
- **Kernel of Good Strategy** — Richard Rumelt, *Good Strategy / Bad Strategy* (2011):
  Diagnosis → Guiding Policy → Coherent Action.
