# BS2 (TSC1/TSC2) penetrance/age/mosaicism review — decision: deferred (2026-07)

| Field | Value |
|---|---|
| Status | Reference / decision support, non-clinical, non-authoritative |
| Decision | **Decision: deferred** — BS2 stays `deferred` (`validation_disposition`/`production_disposition`), `decision_dependency: bs2-policy` |
| Verdict | **Verdict: insufficient for automated BS2** — the automatable BIAS-3.0.0 `get_bs2` population signal does not meet the ClinGen penetrance/age/mosaicism bar for TSC |
| BIAS code reviewed | `benign_classifiers.get_bs2` (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`, pinned `bias_version: 3.0.0`) |
| RAPTOR corpus | ClinVar 2026-07-07, 6,618 TSC1/TSC2 VUS (`tsc_vus_input.bias_output.tsv`) |
| Machine-readable aggregate | [`data/census/tsc_bs2_firing_report_2026-07-12.json`](../../data/census/tsc_bs2_firing_report_2026-07-12.json) |
| Reproducer | [`scripts/probe_bs2_firings.py`](../../scripts/probe_bs2_firings.py) |
| Policy record | [`configs/eval/bias_lineage.yaml`](../../configs/eval/bias_lineage.yaml) `records.BS2` |

> **Reading rule:** this memo characterizes a firing signal and reviews domain authority; it does
> **not** classify, score, or promote any of the 34 BS2-firing variants. Incidence characterizes
> the firing — it never licenses inclusion. The decision below is grounded in domain authority
> (ClinGen) and the firing characterization only; it is never grounded in ClinVar/benchmark labels.

## 1. Executive conclusion

**BS2 stays `deferred`.** ClinGen's Tuberous Sclerosis Complex Variant Curation Expert Panel has not
published an approved, gene-specific ACMG/AMP specification for BS2 (or any criterion) in TSC1/TSC2,
and the pinned BIAS-3.0.0 `get_bs2` evaluator is a population/control-count test that cannot, on its
own, satisfy the general ACMG/AMP BS2 requirement of a thoroughly-phenotyped, non-mosaic, fully-penetrant
adult past the expected age of onset. Absent that authority — and absent a recruited molecular-geneticist
Oracle (GP-3 open) — the automatable BS2 signal is **insufficient** to license scoring or automation of
BS2 for TSC. **Decision: deferred.** No promotion to `allowed`/`included`/`automatable` is made or implied
by this review.

## 2. Probe 1 — the 34 firings, characterized

`scripts/probe_bs2_firings.py` was run against the committed, real, 18-column
`BiasTsvSource`-contract output `tsc_vus_input.bias_output.tsv` (6,618 TSC1/TSC2 VUS rows). The report
reconciles exactly to the census's `criterion_firing.BS2 = 34`
(`data/census/tsc_vus_clinvar_2026-07-07_stats.json`). Aggregate, non-identifying rollups only — no
per-variant chromosome/position/ref/alt row is included in the persisted report:

| Rollup | Value |
|---|---:|
| Total rows scanned | 6,618 |
| Total BS2 firings | **34** |
| Gene distribution | TSC1: 29, TSC2: 5 |
| Pathogenic-family co-fires | PM2: 30, PP3: 4 (no PVS1/PS/co-fire) |
| `healthy_individual_counts` (population/control AC parsed from the firing rationale) | min 6, median 20, max 6,115; 34 values total |

Every one of the 34 firings uses the autosomal-dominant heterozygous form of `get_bs2`'s rationale
("`BS2: Observed in {N} healthy individuals for autosomal dominant disease tuberous sclerosis exceeding
LOEUF({gene}:{loeuf})-based threshold ({threshold}).`") — none uses the recessive-homozygous or X-linked
form, consistent with TSC1/TSC2's autosomal-dominant inheritance. 30 of the 34 co-fire PM2 ("absent from
controls") in the *same* record for a *different* consequence path — not a logical conflict, since PM2 and
BS2 are mutually exclusive on a single allele-count axis and BIAS evaluates them independently per record;
no BS2+PVS1/PS1-4 co-fire was observed in this corpus. This rollup characterizes the firing; it does not
by itself establish that any individual firing reflects a truly non-mosaic, fully-phenotyped healthy adult.

## 3. Probe 2 — `get_bs2` source-condition read

`benign_classifiers.get_bs2` (L116-176) fires purely on population/control data:

- **Trigger:** for an autosomal-dominant `clingen_gene_validity` entry (TSC1/TSC2's inheritance model),
  BS2 fires when `controls_ac`, `gnomad_all_ac`, or `onekg_all_ac` (gnomAD/1000 Genomes control allele
  counts) meets or exceeds a `constants.py` `loeuf_thresholds[...]["bs2_dominant_allele_threshold"]`
  (a gene-constraint/LOEUF-tiered integer, e.g. 8 for the most-constrained tier), gated by a `loeuf > 0.7`
  early-exit and an optional `bs2_af_threshold` allele-frequency cutoff.
- **Control source:** gnomAD `controlsAllAc`/`allAc` and 1000 Genomes `allAc` — external population
  databases, entirely independent of the variant's own ClinVar assertion (label-independent; this is
  **not** R-A2 circularity, consistent with the `label_independent_population` lineage class already
  recorded in `configs/eval/bias_lineage.yaml`).
- **What it does NOT do:** `get_bs2` has no code path that reads a phenotyping record, an age field, a
  clinical-exam result, or a mosaicism/VAF (variant allele fraction) signal. It counts alleles in a
  population database and compares to a frequency-derived threshold — nothing more. It cannot establish
  that any of the individuals contributing to `controls_ac`/`gnomad_all_ac`/`onekg_all_ac` is (a) an
  adult, (b) past the expected TSC age of onset, (c) thoroughly phenotyped to exclude subtle/subclinical
  TSC features, or (d) constitutionally (non-mosaic) germline for the variant.

This confirms both facts the disposition decision turns on: (a) BS2's *source* is label-independent, and
(b) BS2's *automatable evidence* does not model penetrance, age of onset, or mosaicism.

## 4. Probe 3 — primary ClinGen authority review

### 4.1 The general ACMG/AMP 2015 BS2 definition (primary, verified)

Richards S, et al. *Standards and guidelines for the interpretation of sequence variants: a joint
consensus recommendation of the American College of Medical Genetics and Genomics and the Association for
Molecular Pathology.* Genet Med. 2015;17(5):405-424
([PMC4544753](https://pmc.ncbi.nlm.nih.gov/articles/PMC4544753/), Table 4) defines BS2 verbatim:

> BS2 — "Observed in a healthy adult individual for a recessive (homozygous), dominant (heterozygous), or
> X-linked (hemizygous) disorder with full penetrance expected at an early age"

This is the *general* criterion; the general framework does not by itself authorize any gene/disease's
automated use of BS2 — gene/disease-specific refinement is the explicit purpose of ClinGen Variant
Curation Expert Panels (VCEPs) and the (now-retired) Sequence Variant Interpretation (SVI) Working Group.

### 4.2 ClinGen TSC VCEP status (primary, verified — the authority gap)

The ClinGen **Tuberous Sclerosis Complex Variant Curation Expert Panel**
([clinicalgenome.org/affiliation/50171/](https://www.clinicalgenome.org/affiliation/50171/), fetched
2026-07-12) is a registered ClinGen affiliation ("Membership spans many fields, including genetics,
medical, academia, and industry"), but its **Expert Panel Status is "Develop Classification Rules"** — it
has **not** reached the "Provisional" or "FDA-recognized"/published stage. No downloadable, approved
ACMG/AMP specification document (of the kind published for, e.g., the ClinGen Mitochondrial Disease
Expert Panel, `clinicalgenome.org/affiliation/50027/`) is posted for TSC1/TSC2. **There is currently no
published, citable TSC-specific BS2 threshold, penetrance/age cutoff, or mosaicism-exclusion protocol
to apply.** This is an honestly-recorded authority gap, not a fabricated threshold.

### 4.3 ClinGen SVI Working Group (primary, verified — general guidance, no TSC/BS2-specific document found)

The ClinGen Sequence Variant Interpretation (SVI) Working Group — the body that historically issued
criterion-specific refinements (e.g., PS4, PM2, BA1/BS1) — **was retired in April 2025**
([clinicalgenome.org/working-groups/sequence-variant-interpretation/](https://www.clinicalgenome.org/working-groups/sequence-variant-interpretation/),
fetched 2026-07-12), with its guidance folded into the aggregated "ClinGen Variant Classification
Guidance" page. No SVI (or VCEP) document specifically refining BS2's application in the presence of
mosaicism, or specifically for TSC1/TSC2, was located through this review. Absent such a document, the
general ACMG/AMP BS2 definition's own text (§4.1: "healthy adult", "full penetrance", "early age") is the
only citable ACMG/AMP-tier authority, and it is the *general* framework, not a TSC-specific license.

### 4.4 Clinical domain facts grounding the penetrance/age/mosaicism gap (supporting, verified)

GeneReviews — *Tuberous Sclerosis Complex* (Northrup H, Krueger DA, et al.; NCBI Bookshelf
[NBK1220](https://www.ncbi.nlm.nih.gov/books/NBK1220/), fetched 2026-07-12) documents that TSC is highly
but *variably* expressive and markedly age-dependent in its penetrance of individual features — e.g.
lymphangioleiomyomatosis (LAM) is reported in "approximately 30%-40% of females with TSC," rising to "up
to 80% of women with TSC by age 40 years," and renal angiomyolipomas/cysts accumulate with age rather than
presenting uniformly at birth. This is the clinical basis for the VCEP/SVI-level caution (§4.1-4.3) that a
"healthy adult" observation is only informative once the adult is *well past* the age at which the
relevant TSC features would be expected to appear, and once mosaicism (which can produce a subclinical or
false-negative "healthy" phenotype in a true pathogenic-variant carrier) has been excluded — neither of
which `get_bs2`'s population/control-count test (§3) can establish.

### 4.5 Explicit sufficiency verdict

**Verdict: insufficient for automated BS2.** The automatable BIAS-3.0.0 `get_bs2` signal is a
population/control-allele-count test with no phenotyping, age, or mosaicism model (§3). No approved,
citable ClinGen TSC VCEP or SVI specification exists that would license its automated application to
TSC1/TSC2 (§4.2-4.3), and the general ACMG/AMP BS2 text itself requires exactly the phenotyping/age/
mosaicism guarantees BIAS's test cannot provide (§4.1, §4.4). This gap — not the 34-firing incidence, and
not any correlation with ClinVar labels — is the ground for the disposition below.

## 5. Recorded disposition

**Decision: deferred.** `configs/eval/bias_lineage.yaml` `records.BS2` keeps `validation_disposition:
deferred` and `production_disposition: deferred`, `decision_dependency: bs2-policy` (unchanged), and now
carries a required, non-empty `decision_rationale` naming the penetrance/age/mosaicism gap and the missing
authority (§4.2-4.3), cited to Probes 2-3 above. `src/raptor/eval/lineage_policy.py`'s
`load_lineage_policy` is strengthened so that any `deferred` record that declares a `decision_rationale`
key may never leave it blank (fail-closed; a deferral may never silently self-resolve). BS2 remains absent
from `configs/acmg/tsc.yaml`'s `included_criteria` and `configs/eval/tsc2.yaml`'s `automatable_criteria`;
scoring it still trips `raptor.eval.lineage_registry.deferred_included_without_decision`.

**No approval is invented.** If ClinGen's TSC VCEP later reaches "Provisional"/published status with an
approved BS2 specification, and a molecular-geneticist Oracle (GP-3) signs off that the automatable BIAS
signal (or an augmented version of it) meets that specification for TSC, that would be a **separate,
named decision** with its own sign-off record — not a byproduct of this review, and not something this
task fabricates.

## 6. What this review does NOT do

- It does not score, include, automate, or clinically classify any of the 34 BS2-firing variants.
- It does not promote BS2 to `allowed`/`approved`/`included`/`automatable` on the basis of its
  label-independent lineage class or its 34 firings — source-independence is not policy approval.
- It does not ground the disposition in ClinVar/benchmark labels — the ground is domain authority (§4)
  and the firing characterization (§2-3) only.
- It does not fabricate a TSC-specific VCEP/SVI penetrance, age, or mosaicism threshold; §4.2-4.3 record
  the authority gap honestly.
