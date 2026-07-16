# RAPTOR PP3/BP4 computational-predictor policy recommendation

| Field | Value |
|---|---|
| Status | **PROPOSED / UNAPPROVED** |
| Date | 2026-07-17 |
| Scope | TSC1/TSC2 missense computational evidence; research use only |
| Decision owner | RAPTOR domain owner |
| Current implementation | `configs/eval/predictor_aggregation.yaml`; `src/raptor/eval/predictor_aggregation.py` |
| Current approval state | `configs/eval/bp4pp3_predictor_policy.json` remains `pending` |
| Historical result | The 2026-07-13 v1 held-out result remains unchanged and is not reinterpreted by this memo |

> **Reading rule.** This document records RAPTOR's recommended future policy. It does not approve
> a predictor, change a threshold, activate a scorer, classify a variant, authorize a VUS worklist,
> or approve clinical use.

---

## 1. Recommendation

RAPTOR should **not** use the current BIAS/RAPTOR `max_plus_consensus` reconstruction as
score-authoritative PP3/BP4 evidence merely because it is deterministic or reconstructs an inferred
BIAS implementation intent.

For automated PP3/BP4 evidence, RAPTOR should use one of two defensible models:

1. **Preferred:** one predictor, selected before seeing variant scores or other evidence, with its
   version and independently calibrated PP3/BP4 score intervals pinned in policy; or
2. **Alternative:** a frozen composite (including BIAS) treated as one new predictor and calibrated
   end-to-end on leakage-controlled data before any strength is activated.

Until one model satisfies the activation requirements in section 8:

- BIAS per-tool reconstruction remains an **audit/shadow-analysis layer**;
- its reconstructed strength does not authorize automated PP3/BP4 scoring;
- disagreements and indeterminate scores produce no PP3/BP4 criterion, not a fallback-tool search;
- `configs/eval/bp4pp3_predictor_policy.json` remains unapproved.

## 2. Why the current reconstruction is insufficient

The arm's-length RAPTOR wrapper solves a real reproducibility problem:

- BIAS initializes `best_score = 0` but does not update it in the PP3/BP4 aggregation loops;
- PP3 can therefore depend on iteration behavior and over-apply a consensus bump;
- BP4's written consensus guard cannot execute as intended;
- RAPTOR can reconstruct the individual predictor scores from the emitted rationale and preserve
  both emitted and reconstructed values.

This establishes **what the software did and what a plausible implementation repair would do**. It
does not establish the clinical likelihood ratio of the repaired composite.

The current `max_plus_consensus` specification also contains policy choices, not only bug repair:

- it applies a consensus bump when multiple tools tie at the maximum;
- BP4 currently permits that bump from supporting strength (`bump_min_score: 1`);
- it preserves BP4 moderate rather than reproducing BIAS's promotion of moderate to strong;
- it caps PP3 and BP4 at configured strength ceilings.

No primary source identified in section 3 validates that complete combination rule as an ACMG/AMP
evidence-strength model.

## 3. External evidence and established practice

### 3.1 ACMG/AMP 2015

Richards et al. introduced PP3/BP4 as computational evidence and required that correlated algorithms
not be counted as independent criteria. PP3 or BP4 is applied only once per variant.

- Richards S, Aziz N, Bale S, et al. *Standards and guidelines for the interpretation of sequence
  variants: a joint consensus recommendation of the ACMG and AMP.* Genet Med. 2015;17:405-424.
  DOI: [10.1038/gim.2015.30](https://doi.org/10.1038/gim.2015.30);
  [PMC4544753](https://pmc.ncbi.nlm.nih.gov/articles/PMC4544753/).

### 3.2 ClinGen SVI quantitative calibration

Pejaver et al. found that developer score intervals and the original requirement for consensus among
multiple predictors lacked quantitative support. They calibrated **individual tools** using local
likelihood ratios, independent score intervals, an explicit indeterminate region, training-overlap
exclusions, a temporally held-out validation set, and one-sided 95% confidence bounds.

- Pejaver V, Byrne AB, Feng BJ, et al.; ClinGen SVI Working Group. *Calibration of computational
  tools for missense variant pathogenicity classification and ClinGen recommendations for PP3/BP4
  criteria.* Am J Hum Genet. 2022;109:2163-2177.
  DOI: [10.1016/j.ajhg.2022.10.013](https://doi.org/10.1016/j.ajhg.2022.10.013);
  PMID: 36413997; [PMC9748256](https://pmc.ncbi.nlm.nih.gov/articles/PMC9748256/);
  [ClinGen summary](https://www.clinicalgenome.org/docs/calibration-of-computational-tools-for-missense-variant-pathogenicity-classification-and-clingen-recommendations-for-pp3-bp4-cri/).

### 3.3 ClinGen implementation guidance

Stenton et al. provide the clearest operational guidance:

- use one computational prediction tool;
- select it before seeing scores and preferably before other evidence;
- do not cherry-pick a predictor;
- use established thresholds until superseded by validated gene/region-specific guidance;
- avoid double-counting correlated evidence;
- cap combined PP3 and PM1 evidence at Strong.

- Stenton SL, Pejaver V, Harrison SM, Brenner SE; ClinGen SVI Working Group.
  *Assessment of the evidence yield for the calibrated PP3/BP4 computational recommendations.*
  Genet Med. 2024. PMID: 39030733;
  [PMC11560577](https://pmc.ncbi.nlm.nih.gov/articles/PMC11560577/), Box 1.

### 3.4 What is established versus variable

**Established:**

- preselect the tool and version;
- use calibrated, frozen thresholds;
- preserve an indeterminate/no-evidence zone;
- apply PP3 or BP4 once;
- do not count correlated tools independently;
- do not select the most favorable tool after observing outputs;
- revalidate changed models and thresholds.

**Variable/local:**

- which predictor is selected;
- whether general or gene-specific calibration is sufficient;
- the exact score intervals;
- whether a specifically validated gene-level composite is used;
- how splice and protein-effect predictors are routed.

Some older or gene-specific VCEP specifications retain multi-tool concordance. Such a combination is
not transferable to RAPTOR unless that exact frozen combination has independent TSC1/TSC2 validation.

## 4. RAPTOR target policy

### 4.1 Predictor selection

RAPTOR should predeclare one primary predictor per molecular-effect policy before reading a variant's
score:

- **missense protein-effect policy:** one predictor with published or RAPTOR-validated intervals;
- **splice-effect policy:** a separately specified splice predictor under a consequence-routing rule;
- **other predictors:** provenance-rich shadow outputs only unless separately approved.

The final predictor is **not selected by this memo**. REVEL, BayesDel, MutPred2, and VEST4 are examples
with published ClinGen calibration; applicability to TSC1/TSC2, licensing, available versions,
training overlap, and transcript handling still require an explicit selection record.

The policy must not:

- choose whichever predictor gives the strongest evidence for a variant;
- use one tool for PP3 and another opportunistically for BP4;
- fall back to another predictor when the primary tool is indeterminate;
- add component tools on top of a meta-predictor such as REVEL;
- use agreement among uncalibrated tools as a strength multiplier.

### 4.2 Evidence strength and no-call behavior

- A score maps to PP3, BP4, or no computational criterion using frozen intervals.
- The indeterminate interval is a valid result and remains a no-call.
- Higher-than-supporting evidence is allowed only when the selected predictor and exact interval
  satisfy a cited calibration with its uncertainty bound.
- PP3 and BP4 are mutually exclusive for one predictor result.
- PP3/BP4 evidence is emitted once per variant.

### 4.3 Interaction with other evidence

- Combined PP3 and PM1 evidence is capped at Strong, following Stenton et al.
- Frequency features embedded in a predictor must not be counted again as independent population
  evidence without a documented dependence analysis.
- Splice predictions must not be counted both as computational evidence and as a fulfilled
  loss-of-function consequence without the applicable PVS1/splicing framework.
- MAVE and other functional-assay results remain orthogonal functional evidence candidates
  (PS3/BS3), not direct PP3/BP4 calibration labels.

## 5. Status of the BIAS composite

BIAS may remain useful in two roles:

1. **Audit role:** reconstruct and expose each predictor, emitted strength, corrected mechanical
   aggregation, rationale, and divergence.
2. **Candidate composite role:** a frozen score function that may be calibrated as one predictor.

It must not move from the first role to the second by owner judgment alone. A composite activation
requires the empirical controls in section 8.

The current evaluation-only correction approval in `docs/DECISIONS.md` is a historical record tied
to a prior hash. This recommendation does not delete or rewrite that record. It states that a future
approval must distinguish:

- parser/reconstruction fidelity;
- mechanical repair;
- predictor-selection policy;
- strength calibration;
- production authorization.

## 6. How AI agents should implement this policy

AI agents reduce manual workload; they do not convert correlated predictions into independent
evidence.

A production-quality agent workflow should use:

1. **Consequence router:** selects the preapproved effect policy without reading predictor outcomes.
2. **Evidence collector:** fetches the pinned predictor/version output and provenance.
3. **Policy executor:** applies frozen intervals and the indeterminate zone deterministically.
4. **Dependence auditor:** checks meta-predictor components, population-feature reuse, PM1 interaction,
   and training/benchmark overlap.
5. **Independent checker:** reproduces the criterion and evidence strength from the same artifacts.
6. **Human policy owner:** approves protocol versions and exceptions, not every routine variant.

Agents must not:

- change tools or thresholds online;
- optimize thresholds against the current held-out result;
- ask several agents/models to vote and treat agreement as independent evidence;
- silently replace missing evidence with another predictor;
- promote a shadow result into production.

Every agent decision must include resolvable references to the tool version, policy version, raw score,
threshold interval, transcript/consequence route, and checker result.

## 7. Validation design

### 7.1 Individual predictor

Before activation, verify:

- the published calibration applies to the exact tool/version and variant type;
- known training variants and component-tool training overlap are removed from validation;
- score intervals reproduce their expected likelihood ratios on an independent set;
- one-sided confidence bounds meet the intended ACMG/AMP evidence strength;
- the indeterminate interval and missing-score behavior are explicit;
- performance transports to TSC1/TSC2 or a limitation is recorded.

### 7.2 Custom BIAS/RAPTOR composite

Treat the complete frozen composite as one model:

- freeze component tools, versions, thresholds, aggregation, tie handling, caps, and missingness;
- calibrate the composite output, not each component independently and then add the results;
- separate calibration, validation, and final external test sets;
- remove constituent-tool training overlap;
- measure interval likelihood ratios with uncertainty bounds;
- test TSC1/TSC2 transportability and consequence-specific behavior;
- preserve a no-evidence interval;
- preregister before the terminal held-out run.

Clinical-label calibration still requires leakage-safe clinical labels. MAVE can assess functional
concordance but does not independently establish PP3/BP4 clinical strength.

## 8. Activation requirements

No PP3/BP4 policy becomes active until all are present:

- [ ] one named policy model: selected individual predictor or frozen composite;
- [ ] exact model/tool and data versions;
- [ ] license and permitted-use record;
- [ ] consequence/transcript routing rule;
- [ ] cited, frozen score intervals for PP3/BP4/no-evidence;
- [ ] training-overlap and benchmark-leakage audit;
- [ ] independent validation with likelihood ratios and confidence bounds;
- [ ] TSC1/TSC2 transportability assessment;
- [ ] double-count controls, including PP3+PM1;
- [ ] deterministic tests and independent checker approval;
- [ ] explicit owner approval bound to content hashes;
- [ ] corrected masked held-out rerun without threshold changes.

If any item is missing, PP3/BP4 remains shadow evidence or routes the variant to manual review.

## 9. Immediate implications

1. Do not reapprove the current combined BP4/PP3 `max_plus_consensus` bundle unchanged as
   score-authoritative evidence.
2. Preserve reconstruction and materiality outputs for audit.
3. Split future work into:
   - reconstruction/mechanical-fidelity track;
   - predictor-selection and calibration track;
   - production-authorization track.
4. Select and validate the individual-predictor or composite strategy before the next
   score-authoritative held-out rerun.
5. Correct any documentation that presents deterministic reconstruction as equivalent to external
   clinical calibration.

## 10. Relation to existing artifacts

| Artifact | What it currently establishes | What it does not establish |
|---|---|---|
| `configs/eval/predictor_aggregation.yaml` | Reconstructable BIAS aggregation specification | Clinical validity of max-plus-consensus |
| `src/raptor/eval/predictor_aggregation.py` | Deterministic rationale parsing and reconstruction | Calibrated PP3/BP4 likelihood ratios |
| `configs/eval/bp4pp3_predictor_policy.json` | Hash-bound approval gate; currently pending | Production or clinical approval |
| `docs/DECISIONS.md` evaluation-only approval | Historical approval for a prior evaluation bundle | Approval of the current hash or future policy |
| `configs/acmg/strength_policy.yaml` | Unapproved handling of BIAS/RAPTOR vocabulary mismatches | Predictor-selection or calibration policy |
| This memo | RAPTOR's proposed target policy and activation requirements | An active decision or completed validation |

