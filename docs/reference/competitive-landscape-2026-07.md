# RAPTOR — Competitive & Premise-Falsification Reference (2026-07)

**Purpose:** Ground the vertical TSC/mTOR strategy reset ([ADR-0010](../DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy))
in primary sources. This note holds the *detailed* competitive evidence so
[STRATEGY.md](../STRATEGY.md) stays lean; STRATEGY Part I §2/§3/§10 point here.

**Status:** Reference · **Owner:** @dronasrinivas · **Compiled:** 2026-07-10 · **Narrow-metric verification date:** 2026-06-16

> **Reading rule (GP-9 / RISK_REGISTER H13):** every vendor number below is a **vendor/company claim**
> unless it resolves to an independent, peer-reviewed publication. A press release, white paper, or
> conference-abstract award is a *marketing/vendor claim*, not independent validation. This note
> classifies each source's *type* so no metric is silently promoted to "validated."

---

## 1. What was falsified — and what survives

### 1.1 Withdrawn claim (do not repeat)

The prior strategy asserted a **"blue ocean / no synthesis layer / no public deployed system"**
uniqueness. That claim is **withdrawn**. Several capable, publicly described variant-interpretation
platforms and LLM/ACMG products exist (§2). "No indexed TSC-specific campaign was found" was
over-generalised into "no capable platform exists"; that inference does not hold.

### 1.2 The one metric that survives (narrow, dated, and correctly scoped)

- **PubMed E-utilities search, verified 2026-06-16:** zero results for four TSC-specific
  automated/systematic variant-classification/reclassification queries over the 2015 / 2018–2026
  windows. **Interpretation:** no *indexed, TSC-specific* automated-classification campaign was found —
  **not** that no capable platform exists, and **not** that the work is impossible.
- **TSC ClinGen / VCEP submissions in ClinVar: zero** at that verification date. **Interpretation:**
  an **unresolved institutional / adoption question** (human-speed curation has not cleared the TSC
  VUS pile), **not** automatic demand for RAPTOR. Absence of output ≠ absence of demand *or* of
  capability (RISK_REGISTER R-A12).

---

## 2. Competitive landscape — capable platforms exist

General-purpose variant-interpretation and LLM/ACMG activity is real and multi-vendor. None of the
sources below is a TSC-specific, continuously-updated, auditable evidence program with an open
benchmark — but each is a capable adjacent product, and several could extend toward TSC. Source
*type* is labelled explicitly.

| Vendor / product | What it is | Reported claim(s) | Source type | Primary source |
|---|---|---|---|---|
| **Deriva** | AI variant-interpretation + ASO-eligibility automation | General clinical variant interpretation; TIMMDC1 ASO-eligibility automation | **Vendor** (company site) | [why-deriva](https://deriva.ai/why-deriva) · [variant interpretation](https://deriva.ai/solutions/variant-interpretation) · [ASO eligibility](https://deriva.ai/solutions/aso-eligibility-automation) |
| **Virtual Geneticist** (BTGenomics) | LLM-assisted WES/WGS interpretation | White paper: **n=219 ranking**; **71 negative-case reanalysis → 7 new diagnoses**; **800 WES processed in ~5 hours** | **Vendor white paper / ASHG presentation** | [white paper (Apr 2025)](https://vg.btgenomics.com/assets/img/pdf/VirtualGeneticist_WhitePaper_April25_02.pdf) |
| **Breakthrough Genomics** | Interpreted-literature DB + new AI/ACMG capabilities | "Largest interpreted literature database"; new AI capabilities unveiled at ASHG 2025 | **Vendor press release** | [PRNewswire (ASHG 2025)](https://www.prnewswire.com/news-releases/breakthrough-genomics-showcases-largest-interpreted-literature-database-and-unveils-new-ai-capabilities-at-ashg-2025-302588432.html) |
| **3billion — AIVARI / GEBRA** | LLM-powered variant interpretation | AIVARI won **best presentation at KSMGG 2025**. 3billion is a **public rare-disease diagnostics company founded 2016** (not a recent startup); GEBRA / AIVARI are newer products | **Vendor** (award abstract + company pages) | [AIVARI (KSMGG 2025)](https://3billion.io/news/llm-powered-variant-interpretation-3billions-aivari-wins-best-presentation-at-ksmgg-2025) · [company](https://3billion.io/company) · [GEBRA](https://3billion.io/gebra) |
| **eVai** | ACMG classification engine | ACMG-criteria automation study | **Peer-reviewed** | [PMC8847497](https://pmc.ncbi.nlm.nih.gov/articles/PMC8847497/) |
| **AAVC** (Ozcelik Lab) | Source-available automated ACMG classifier + population-scale result release | README claims 99.3% FDA concordance and ~710K/1.38M VUS resolved; pinned release independently contains 750,318 P/LP/B/LB calls among 1,354,015 source VUS | **Project claim + CC-BY dataset; no benchmark protocol or peer-reviewed validation found** | [repository](https://github.com/OzcelikLab/AAVC) · [Zenodo release](https://doi.org/10.5281/zenodo.17201194) · [RAPTOR audit](aavc-prior-art-audit-2026-07.md) |
| **VarChat** | LLM literature-summarisation for variants | Variant-literature synthesis | **Peer-reviewed** | [PMC11055464](https://pmc.ncbi.nlm.nih.gov/articles/PMC11055464/) |
| **Golden Helix VSClinical** | Commercial ACMG clinical interpretation (VarSeq) | Guided ACMG/AMP interpretation workflow | **Vendor** (product page) | [VSClinical](https://www.goldenhelix.com/platform/varseq/clinical-interpretation) |
| **SeqOne DiagAI** | AI-assisted diagnostic interpretation | Diagnostic-yield / interpretation claims | **Preprint (not yet peer-reviewed)** | [medRxiv 2025.02.04.25321641v3](https://www.medrxiv.org/content/10.1101/2025.02.04.25321641v3) |
| **Variant Bio — Inference** | Agentic AI for genomic **drug discovery** (adjacent, not classification) | "World's first agentic AI genomic drug-discovery platform" | **Vendor press release** | [PRNewswire](https://www.prnewswire.com/news-releases/variant-bio-launches-inference-the-worlds-first-agentic-ai-genomic-drug-discovery-platform-302653399.html) |

### 2.1 Claim-quality caveats (do not overstate the competition either)

- **Deriva:** the *public* validation is narrow — a **single PPP1CB case** — and the **target-ClinVar
  masking is undisclosed**, so its accuracy claims cannot be independently assessed. Vendor claim.
- **Virtual Geneticist:** the n=219 / 71-reanalysis / 800-WES figures come from a **company white
  paper and ASHG presentation**, **not** a broad, independent, peer-reviewed validation.
- **3billion:** a **public rare-disease diagnostics company founded 2016** — not a recent startup;
  AIVARI/GEBRA are newer products, and the KSMGG "best presentation" is a **conference award**, not an
  independent validation.
- **eVai / VarChat:** peer-reviewed, but **generic** (not TSC-specific) and not continuously-updated
  auditable programs.
- **AAVC:** material generic prior art. Its September-2024 release contains 4,532 TSC VUS and
  machine-calls 808 outside VUS, but the outputs are a separate dataset—not expert-reviewed ClinVar
  submissions. Its 99.3% claim has no published benchmark identities/masking protocol, and its code
  uses ClinVar-derived criteria extensively; see the [script-reproduced overlap and code audit](aavc-prior-art-audit-2026-07.md).
- **SeqOne DiagAI:** a **preprint** — treat as provisional until peer review.
- **Variant Bio Inference:** **drug discovery**, adjacent to variant classification; a press-release
  positioning claim.

---

## 3. Implication for RAPTOR positioning

1. **Withdraw the uniqueness claim.** RAPTOR's defensibility is **not** "we are the only one." Do not
   restate "blue ocean / no system / no synthesis layer" anywhere as present fact.
2. **Preserve the assets.** The open TSC benchmark/census, the deterministic evidence program, and the
   auditability/freshness discipline remain valuable regardless of how many general platforms exist.
   Do not abandon TSC assets because competitors exist (RISK_REGISTER R-F3 contingency).
3. **Reposition the contribution** as **vertical TSC/mTOR disease-evidence and research
   infrastructure** — expert-reviewable candidate evidence packets, an evidence/functional-assay/
   contradiction atlas, and gated mTOR-condition hypothesis packets — not a generic
   variant-interpretation platform competing head-on with the vendors above.
4. **Reuse, don't rebuild** the generic layer (STRATEGY GP-4): a commoditizing generic engine is a
   *dependency to buy/reuse*, and the moat is the TSC-vertical evidence, not generic ACMG methodology
   (RISK_REGISTER R-F4).

> **Freshness note:** vendor pages and the PubMed/ClinVar metric are point-in-time (verification
> 2026-06-16; landscape compiled 2026-07-10) and must be re-checked at each strategy review (GP-5).
