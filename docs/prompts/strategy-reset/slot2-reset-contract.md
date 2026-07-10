# Slot 2 — TSC/mTOR vertical strategy reset

## Goal

Revise RAPTOR's authoritative intent/status after the original generic-platform uniqueness premise was
falsified and the first complete deterministic TSC VUS evidence census was executed.

Modify only:

- `docs/STRATEGY.md`
- `docs/PROGRAM.md`
- `docs/DECISIONS.md`
- `docs/RISK_REGISTER.md`

Create only:

- `docs/reference/competitive-landscape-2026-07.md`

Preserve the existing recognized strategy format (Pichler Vision Board + Rumelt kernel) and MADR
decision log. This is a **revision**, not a wholesale rewrite.

## Accepted operator decisions

- Complete the deterministic TSC1/TSC2 evidence program.
- Freeze generic variant-interpretation/literature-agent/platform expansion.
- RAPTOR is a vertical TSC research-evidence product with carefully gated extensions to selected
  mTOR-related conditions.
- The vision is to accelerate TSC/mTOR research by producing expert-reviewable evidence packets,
  evidence/assay gap maps, contradiction maps, and falsifiable research-hypothesis packets.
- Build PRD-04's candidate evidence packet/output contract now; apply it to the full VUS worklist only
  after leakage-safe validation and expert approval.
- Recruit complementary validators: molecular geneticist/clinical variant scientist; practising
  paediatric neurologist; functional mTOR expert before cross-condition mechanism claims.
- Continue adversarial red-teaming. Do not claim "go-to platform for all things TSC" as present fact.

## Measured census facts

Source of record:

- `data/census/tsc_vus_clinvar_2026-07-07_stats.json`

Required distinctions:

- 6,618 total VUS: TSC1 2,249; TSC2 4,369.
- 5,645 source-corpus missense, 893 other, 80 truncating.
- 6,618/6,618 scored by pinned Nirvana/BIAS; zero duplicate/parser errors.
- Current **eval-only, internal, non-authoritative** candidate directions:
  238 LP review; 1,333 LB review; 5,017 unresolved; 30 annotation/manual.
- Missense-containing BIAS consequences:
  81 LP review; 1,196 LB review; 4,377 unresolved.
- Predicted LoF:
  145 LP review; 2 unresolved.
- Evidence-pattern compression:
  238 LP candidates span 20 exact strength patterns; six cover 90%.
  1,333 LB candidates span 10 patterns; BP4 Strong + PM2 Supporting covers 1,222 (92%).
  This pattern result is a session analysis over the external raw TSV; cite it as a reproducible
  internal analysis, not validated truth, and do not promote it to a benchmark result.
- Never call these reclassifications or 24% resolution.

## Premise falsification / competitors

The old diagnosis "no synthesis layer / blue ocean / no public deployed system" must be explicitly
withdrawn. Preserve only the narrow, dated metric:

- Live PubMed E-utilities search, verified 2026-06-16, found zero results for four TSC-specific
  automated/systematic variant-classification/reclassification queries over 2015/2018–2026.
- This means no indexed TSC-specific campaign was found—not no capable platform exists.
- TSC ClinGen/VCEP submissions found in ClinVar: zero at that verification date; interpret as an
  unresolved institutional/adoption question, not automatic demand.

Ground the competitive reference note using primary sources:

- Deriva: https://deriva.ai/why-deriva
- Deriva variant interpretation: https://deriva.ai/solutions/variant-interpretation
- Deriva TIMMDC1 ASO: https://deriva.ai/solutions/aso-eligibility-automation
- Virtual Geneticist white paper:
  https://vg.btgenomics.com/assets/img/pdf/VirtualGeneticist_WhitePaper_April25_02.pdf
- Breakthrough LLM/ACMG launch:
  https://www.prnewswire.com/news-releases/breakthrough-genomics-showcases-largest-interpreted-literature-database-and-unveils-new-ai-capabilities-at-ashg-2025-302588432.html
- 3billion AIVARI:
  https://3billion.io/news/llm-powered-variant-interpretation-3billions-aivari-wins-best-presentation-at-ksmgg-2025
- 3billion/GEBRA history: https://3billion.io/company and https://3billion.io/gebra
- eVai ACMG research: https://pmc.ncbi.nlm.nih.gov/articles/PMC8847497/
- VarChat: https://pmc.ncbi.nlm.nih.gov/articles/PMC11055464/
- Golden Helix VSClinical:
  https://www.goldenhelix.com/platform/varseq/clinical-interpretation
- SeqOne DiagAI: https://www.medrxiv.org/content/10.1101/2025.02.04.25321641v3
- Variant Bio Inference:
  https://www.prnewswire.com/news-releases/variant-bio-launches-inference-the-worlds-first-agentic-ai-genomic-drug-discovery-platform-302653399.html

Classify vendor metrics as vendor/company claims unless independently published. Note:

- Deriva public validation is narrow (single PPP1CB case) and target ClinVar masking is undisclosed.
- Virtual Geneticist's white paper reports n=219 ranking, 71 negative-case reanalysis with seven new
  diagnoses, and 800 WES processed in five hours; company white paper/ASHG presentation, not a broad
  independent peer-reviewed validation.
- 3billion is a public rare-disease diagnostics company founded 2016, not a recent startup; GEBRA/AIVARI
  are newer products.

## STRATEGY.md revisions

Update at least:

- status/date;
- one-line summary and Vision;
- diagnosis/competitive landscape;
- target group;
- binding Guiding Policy: add a vertical-scope rule—every feature names TSC/mTOR user, artifact,
  validator, and why a generic product cannot supply it;
- product solution:
  1. TSC deterministic evidence census and candidate packet;
  2. TSC evidence/functional-assay/contradiction atlas;
  3. selected mTOR-condition hypothesis packets after explicit gate;
- coherent actions/roadmap;
- success metrics focused on expert review, curator/research adoption, experiments/hypotheses acted on,
  freshness—not variants processed or agents spawned;
- binding scope/out-of-scope;
- risks/tensions.

Do not remove validation ceilings, public-data boundary, human sign-off, or stop conditions.

## New vertical scope

In scope:

- TSC1/TSC2 variant evidence and research gaps;
- expert-reviewable candidate evidence packets;
- TSC functional-assay coverage/gaps and contradictions;
- selected mTORopathy extensions only for a fixed gene/disease/mechanism question with a named user,
  expert validator, falsifier, and reason generic engines are insufficient;
- integration/reuse of existing generic engines.

Out:

- generic ACMG engine/platform;
- generic literature-agent stack;
- generic NGS pipeline;
- patient-facing diagnosis/treatment;
- cross-gene ACMG evidence transfer;
- "same pathway therefore same drug" claims;
- broad "all things TSC" implementation scope.

## PROGRAM.md revisions

- Mark the internal deterministic census complete.
- Current metrics remain non-authoritative; held-out gate still pending.
- Record PR #12/Task A merged (`253c9fd`).
- Replace generic-platform priorities with:
  1. BIAS criterion lineage;
  2. held-out-masked BIAS validation bundle;
  3. ClinVar audit;
  4. canonical adapter;
  5. Clopper-Pearson gate;
  6. BS2 policy;
  7. transcript/NTHL1 resolution;
  8. production candidate policy;
  9. PRD-04 output contract;
  10. expert validation and named adopter.
- Distinguish output-contract work now from full worklist only after PASS.
- Freeze PRD-05/generic orchestration and generic Tier-3 platform work.

## DECISIONS.md

Add newest **ADR-0010** in MADR format. It supersedes the relevant differentiation/roadmap parts of
ADR-0001 but does not erase history. Decision:

- original generic-platform uniqueness diagnosis falsified;
- freeze horizontal platform expansion;
- retain/finish deterministic TSC evidence program;
- vertical TSC/mTOR research-evidence strategy;
- reuse/buy generic engines;
- expansion/user/oracle gates.

## RISK_REGISTER.md

Surgically update/add:

- commoditized generic-engine risk;
- vendor/platform obsolescence/substitution;
- vertical-scope creep ("all things TSC");
- absence-of-output versus absence-of-demand ambiguity;
- expert-oracle bottleneck;
- polished non-authoritative output creating false authority;
- community/adoption dependency.

## Quality checks

- All internal relative links resolve.
- No stale "blue ocean/no system/no synthesis layer" claim remains unqualified.
- No candidate direction is called a classification/reclassification.
- No vendor metric is presented as independent validation without evidence.
- Keep the revision concise; put detailed competitor evidence in the new reference note rather than
  bloating STRATEGY.md.
