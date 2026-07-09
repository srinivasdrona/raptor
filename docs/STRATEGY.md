# RAPTOR — Vision & Strategy

> **Status:** DRAFT v0.1 · **Owner:** @dronasrinivas · **Last updated:** 2026-07-08 · **Review cadence:** monthly
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

**One-line summary:** *An auditable variant-evidence engine for rare disease — proven on TSC,
designed to generalise — that accelerates the researchers who resolve variants, and never replaces
their judgement.*

---

## 1. Vision

> **RAPTOR turns the world's public genetic and literature evidence into auditable, continuously
> updated variant-classification packets — starting with the TSC1/TSC2 genes behind Tuberous
> Sclerosis Complex — and surfaces the mechanistic links between related rare diseases as cited,
> falsifiable hypotheses.**

It is **not** a diagnostic, a treatment-recommendation system, or a regulated medical device. It is
an **enabler**: the infrastructure layer that curators, researchers, and clinical-translation teams
plug into to do their work faster and with a full evidence trail.

**Committed claim (build now):** a defensible TSC1/TSC2 variant-evidence engine, validated against
the best available expert labels, plus a bounded *gap-map* over established mTOR-pathway mechanism.

**North-star (long-term):** the same engine generalised across rare diseases — but only ever
shipping cross-disease links as *cited hypotheses with declared validation ceilings*, never as
"validated discovery."

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

### 2.2 The market & research landscape — real activity, but no synthesis layer

TSC affects an estimated **1–2 million people worldwide** (birth incidence ~1 in 6,000; prevalence
~1 in 6,000–10,000) and **~77,000–82,000 in Europe**. Research activity is genuine and multi-market
— but it is *cohort and correlation* work, not *automated, auditable, continuously-updated
classification*.

| Market | What exists | Key data points | Gap for RAPTOR |
|---|---|---|---|
| **Global / EU** | **TOSCA** international registry (Novartis-sponsored; Kingswood & de Vries, *Orphanet J Rare Dis* 2017) | ~2,093–2,214 patients · 170–250 sites · **31 countries**. **E-TSC** European registry active. | Registries hold phenotype, not systematic variant re-classification; not publicly queryable at variant level. |
| **Japan** | 4 active clinical groups + JMDC claims DB | Niida (Kanazawa) cohort n=283; Wataya-Kaneda (Osaka) 39 papers; regional prevalence 3.1–10.2/100k (undercounted). JMDC: 148 TSC patients, **no genetic data**. | Genotype-phenotype papers only; no pipeline; JMDC cannot classify variants. |
| **China** | 5 active clinical research groups | Fudan n=297 · Xiangya n=173 · PLA n=223 · PUMCH families · PKUPH (TOSCA link). | Genotype-phenotype correlation only; no automation. |
| **Methodology (any market)** | Published but sparse | Kim 2025 (*Eur J Hum Genet*); Garcia 2024 (TSC1/2 variant DB). mTOR papers 2015–26: **14,594**. | Retrospective, single-institution, not deployed or continuously updated. |

**Published papers on automated TSC variant classification (PubMed, 11-yr window): 0.**

### 2.3 Why the space is empty — structural, not accidental

The gap persists because of *incentives*, not capability. In brief (full analysis in the `pre-build/`
FYTSC session notes):

1. **Academic incentives** reward novel biology/algorithms, not "apply existing tools to an existing
   database and maintain it."
2. **No single group holds the full skill stack** — clinical genetics + bioinformatics + LLM
   engineering + disease domain — as an institutional entity.
3. **Commercial incentives** put variant reclassification upstream of the drug-revenue pathway.
4. **ClinGen's institutional fix is stalled** — the TSC VCEP exists but has 0 ClinVar submissions;
   human-speed curation cannot clear ~6,700 VUS.
5. **The enabling LLM capability is genuinely new** (~2025–26) — the "possible-but-not-yet-done"
   window is open.
6. **Everyone treats it as someone else's job.**

**Honest uncertainty:** absence of public signal across ClinVar, PubMed, GitHub, arXiv/bioRxiv,
ClinGen, and advocacy roadmaps is *strong* evidence of emptiness, not proof. A stealth or internal
effort cannot be ruled out.

---

## 3. Why TSC — and not another condition

TSC is the **starting point, not the destination.** It was chosen against explicit criteria:

| Selection criterion | How TSC scores |
|---|---|
| **Public data, no gatekeepers** | ClinVar, gnomAD, PMC, ClinGen — all open. |
| **Gateway / lynchpin mechanism** | Loss of TSC1/TSC2 → mTORC1 hyperactivation; transfers to adjacent mTORopathies (DEPDC5, PTEN, PIK3CA, NPRL2/3). |
| **Clinically actionable** | everolimus approved → a resolved variant can *indirectly* inform management **via qualified clinicians** (never by RAPTOR). |
| **Quantified, addressable gap** | 4,445 TSC2 VUS; 0 expert-panel reviews; top-10 VUS-burdened gene. |
| **Validatable** | Best-available expert / multi-submitter labels give a measurable benchmark. |
| **Blue ocean** | 0 published automated-classification papers; **no public deployed system found under the search protocol** (PubMed/ClinVar/GitHub/arXiv/bioRxiv/ClinGen) — absence of signal, not proof (§2.3). |
| **Solo-operator feasible** | Fits the available local + cloud compute fleet. |

The insight that makes TSC a *gateway*: the mechanism (mTOR) is shared across many rare diseases, so
the classification engine and the cross-linkage grammar built for TSC are reusable — the reason the
long-term north-star (§1) is credible rather than aspirational.

---

## 4. Target group & needs

*(Pichler: who is this for, and what need does it serve — never a patient-facing tool.)*

| Target group | Need RAPTOR serves |
|---|---|
| **ClinGen TSC VCEP / expert curators** | A ranked triage worklist: candidate VUS where deterministic evidence alone *suggests* a possible LP/LB threshold — **curator source-verification and mechanism judgement still required** (deterministic scoring ≠ finished ACMG call). |
| **Rare-disease researchers (mTOR field)** | A gap-map / contradiction-map: shared-mechanism disease pairs not yet connected in the literature; self-contradicting evidence flags. |
| **Clinical-translation & drug-repurposing teams** | Mechanistically-grounded, fully-cited repurposing *hypotheses* over established pathway biology. |
| **Diagnostic labs (single-submitter)** | Auditable, evidence-weighted second-pass on their ~40% single-submitter TSC classifications. |

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
Cure KG, ClinGen criteria are foundations, not competitors. RAPTOR's contribution is
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

---

## 6. Product solution — the three tiers

*(Pichler: the product, mapped to the guiding policy. Detail lives in ARCHITECTURE.md.)*

| Tier | What it does | Approach | **Validation ceiling (GP-1)** |
|---|---|---|---|
| **Tier 1 — Deterministic** | Automatable ACMG criteria (PVS1, PM2, BA1/BS1, PP3/BP4, PS1/PM5, BP7…) | BIAS-2015 + gnomAD/CADD/REVEL/SpliceAI; local CPU (~1,327 variants/sec) | **Measurable** vs *best-available proxy labels* — no TSC 3★ panel exists; see benchmark hierarchy (§7). |
| **Tier 2 — Computational** | Predictor scores, domain mapping, per-gene calibration | Scriptable batch (license-aware: CADD/SpliceAI non-commercial) | Measurable; deterministic and reproducible. |
| **Tier 3 — LLM extraction** | **PS3 functional evidence only (MVP)**; segregation/other criteria deferred; PM3/BP2 *trans* evidence N/A (TSC is autosomal-dominant) | Frontier models with **assay-validity rubric + variant-matching gate**; local models for abstract screening | **Per-premise citation-checkable** (AcmGENTIC ~96% PS3 is a *reference*, not a transferred guarantee). Ceiling: "assay says X, cited" — not "variant is pathogenic." |
| **Cross-linkage (north-star)** | mTORopathy links + gap-map | LLM as librarian over established mechanism | **Oracle-poor.** Premises citable; the *leap* and *set-completeness* are not. Ships as *hypothesis only*. |
| **Consensus / adjudication** | Bayesian combination (Tavtigian 2018 LRs) → posterior → human review queue | Deterministic math + human sign-off | No "final classification" without human sign-off (§9). |

---

## 7. Coherent Actions — roadmap

*(Rumelt: coordinated steps that implement the guiding policy. Sequenced, not exhaustive.)*

**Phase 0 — Foundation (now).**
- Lock a **frozen benchmark** (~50 variants), **version-frozen by date + source**. Label hierarchy: (1) ClinGen VCEP/3★ if any exist, (2) 2★ multi-submitter *concordant*, (3) curated literature DB, (4) manual expert adjudication. **Exclude conflicting/single-submitter labels** from the scored set and hold them out to prevent leakage. Track provenance to avoid **circular validation** if RAPTOR later influences VCEP curation (mechanics → EVAL_PLAN.md).
- Stand up the compute fleet: Snapdragon (Queen/orchestrator + SQLite state), EPYC + Xeon (Ollama batch workers).
- MVP pipeline skeleton: LiteLLM router + Prefect flow; surveillance → screening → extraction → integration.

**Phase 1 — Tier 1/2 on TSC2 (measurable half).**
- Run BIAS-2015 across all TSC1/TSC2 VUS; confirm TSC2 haploinsufficiency (ClinGen Dosage BED).
- Report precision/recall vs frozen benchmark. **Gate:** thresholds met before Tier 3 is trusted.
- Ship the VCEP triage worklist (highest-value, lowest-risk output).

**Phase 2 — Tier 3 literature extraction.**
- LitVar2 retrieval → abstract screening (local) → PS3 full-text extraction (frontier) with matching gate.
- Bayesian posterior + human-review queue. Provenance/freshness loop live (GP-5).

**Phase 3 — Cross-linkage gap-map (north-star, gated on oracle).**
- Recruit molecular-geneticist oracle (GP-3) **first**.
- Pre-register the evidence grammar (premise · leap · falsifier per link).
- Ship gap-map + contradiction-map as cited hypotheses.

**Phase 4 — Generalise & sustain.**
- Second gene/disease as a generalisation test; sustainability answer for any public tier.

---

## 8. Business goals — measures of success

*(Pichler: what success looks like. These are the KPIs PROGRAM.md rolls up.)*

| Dimension | Metric | Target posture |
|---|---|---|
| **Accuracy (Tier 1/2)** | Precision / recall vs frozen benchmark | Pre-defined thresholds; no Tier-3 trust until met. |
| **Extraction quality (Tier 3)** | PS3 extraction accuracy with matching gate | **RAPTOR-specific PS3 benchmark required**; AcmGENTIC (~96%) is a *reference baseline*, not a transferred target. |
| **Throughput** | VUS processed / week; triage-worklist size | Weekly operational batch. |
| **Freshness** | Lag between ClinVar/gnomAD/literature update and re-validation | Bounded, monitored. |
| **Human-review economics** | Suspended-for-review rate; reviewer time / decision | Falling over time. |
| **Adoption (leading)** | First real users (VCEP / lab / researcher) | Named wedge, not "published on GitHub." |

Decision outputs are framed as **3–5-point probabilistic estimates with the key drivers named**, not
single hard calls — the model must be explainable and defensible to expert, board, and regulatory
review.

---

## 9. Scope *(binding)*

**In scope**
- Auditable ACMG/AMP evidence assembly for TSC1/TSC2 VUS.
- Bounded mTOR-pathway cross-linkage *hypotheses* + gap/contradiction maps.
- Triage worklists, evidence packets, and provenance for downstream human experts.

**Explicitly out of scope**
- Medication-recommendation systems.
- Clinical decision support for individual patients.
- Regulated medical devices / Software-as-a-Medical-Device claims.
- **Any "final classification" without human sign-off.**
- Cross-disease claims presented as validated discovery rather than cited hypothesis.

**Two sign-off levels (not interchangeable):** the **operator** approves *internal* pipeline records
and the review queue; any **externally meaningful** proposed classification or ClinVar submission
requires a **qualified molecular geneticist / VCEP** (the GP-3 oracle). Operator approval alone never
produces an external classification.

---

## 10. Risks & honest tensions

> This is the distilled **top-tier** view. The exhaustive failure-mode analysis (51 modes across 8
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

**Honest tensions** (structural, not fully closable):

| Tension | Nature | Approach |
|---|---|---|
| **Validation asymmetry** | Tier 1/2 measurable; headline (cross-linkage) is not. | GP-1/GP-2: never sell the unmeasurable half as validated. |
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
| TSC2 VUS / total / expert-panel | 4,445 / 7,645 / **0** | ClinVar, Jun 2026 (re-verify at run) |
| ClinGen TSC VCEP ClinVar submissions | 0 | ClinVar, Jun 2026 |
| ClinVar VUS share | 2,355,835 / 4,274,341 (55.1%) | ClinVar, Jun 2026 |
| TSC global prevalence / birth incidence | ~1 in 6,000–10,000 / ~1 in 6,000 | Multiple reviews, 2024–25 |
| TSC patients worldwide / Europe | ~1–2 million / ~77,000–82,000 | Reviews; E-TSC (e-tsc.eu) |
| TOSCA registry | ~2,093–2,214 patients · 170–250 sites · 31 countries | Kingswood & de Vries, *Orphanet J Rare Dis* 2017 |
| mTOR papers 2015–2026 | 14,594 | PubMed E-utils, Jun 2026 |
| Automated TSC variant-classification papers | 0 | PubMed, 11-yr window |
| BIAS-2015 throughput / coverage | 1,327 variants/sec · 19/28 ACMG criteria | *Genome Medicine* 2025 |
| AcmGENTIC PS3 extraction | ~96% with matching gate | arXiv 2604.00075, Mar 2026 |

> **Freshness note:** ClinVar/gnomAD/PubMed figures are point-in-time (Jun 2026 session pulls) and
> must be re-verified at each run — see GP-5.

## Appendix B — Framework provenance

- **Product Vision Board** — Roman Pichler (Vision · Target Group · Needs · Product · Business Goals).
- **Kernel of Good Strategy** — Richard Rumelt, *Good Strategy / Bad Strategy* (2011):
  Diagnosis → Guiding Policy → Coherent Action.
