# RescueScreen evidence-readiness summary: $\mathrm{TSC2}$ $p.\mathrm{Arg611Gln}$

> **Research-only handoff — 2026-08-21**
> **Current decision:** `DO_NOT_START_RESCUESCREEN_STAGE_WORK`

## Status

| Field | Current state |
|---|---|
| Discovery shelf | `rescuescreen-r611q-v1` |
| Shelf accounting | 70 indexed documents; these are representations, **not** 70 independent publications |
| Structure pack | `data/rescuescreen/r611q/structure-readiness-v1/` |
| Atlas Gate 8 | `BLOCKED_HUMAN_REVIEW` |
| Accepted Atlas claims | 0 |
| Entry gates | `EG-1` through `EG-5`: all `NOT_SATISFIED` |
| First entry blocker | `EG-1` / `MECHANISM_UNVERIFIED` |
| Stage execution authorized | `false` |
| Current lane decision | `DO_NOT_START_RESCUESCREEN_STAGE_WORK` |

This is an evidence-readiness handoff, not an Atlas acceptance, classification,
compound result, treatment statement, or authorization to execute RescueScreen.

### Authoritative repository artifacts

| Subject | Repository-relative path |
|---|---|
| Frozen literature baseline | `data/rescuescreen/r611q/literature-v1/` |
| Literature inventory and evidence matrix | `data/rescuescreen/r611q/literature-v1/master_source_inventory.json`; `data/rescuescreen/r611q/literature-v1/mechanism_evidence_matrix.json` |
| Synthesis baseline and assay logic | `data/rescuescreen/r611q/synthesis-v1/` |
| Structure-readiness pack | `data/rescuescreen/r611q/structure-readiness-v1/` |
| Gate 8 status packet | `data/atlas/runs/2026-08-03/r611q_gate_result.json` |
| Entry-gate configuration | `configs/rescuescreen/entry_gates.yaml` |
| Stage and vocabulary contract | `docs/project/specs/structural-rescue-screen-v1.yaml` |

## Corpus accounting and version boundary

The Discovery shelf contains **70 indexed documents**, not 70 independent
publications. It deliberately indexes source cards, lawful full texts,
institutional manuscripts, dataset records, structure/identity records, manifests,
and README/support files. A source card and its full text are two representations
of one source; manifests describe the corpus and are not additional evidence.

| Independent source class | Count | Notes |
|---|---:|---|
| $\mathrm{R611Q}$-focused publication records | 33 | Literature baseline records; direct, grouped/control, structural, clinical, and access-gap roles are separated below. |
| Foundational predecessor publications | 5 | Nellist 2001 references 9–13; context for complex/chaperone, ubiquitination, and phosphorylation rather than direct $\mathrm{R611Q}$ evidence. |
| Direct datasets | 2 | MaveDB cliPE and IGVF VAMP-seq; the associated publications must not be double-counted as independent experiments. |
| Identity/structure records | 4 | dbSNP, UniProt, PDB `7DL2`, and PDB `9CE3`. |
| Duplicate representations/support files | Remaining indexed documents | Cards, lawful full texts, institutional manuscripts, manifests, and README files duplicate or describe the sources above. |

### Source-version drift

`literature-v1` and `synthesis-v1` are frozen at **2026-08-17**. The
Discovery shelf was updated through **2026-08-21** and adds the institutional
full text for Nellist 2001 (`PMID:11741832`) plus the five foundational
predecessors (`PMID:10585443`, `PMID:9580671`, `PMID:9809973`,
`PMID:11175345`, and `PMID:11290735`). They are **not yet repinned** into
`literature-v1` or `synthesis-v1`. This is a provenance/version gap, not a
biological contradiction and not an Atlas-claim upgrade.

## What must be true before any stage can start

### Entry gates

| Gate | Requirement | Current status and exact blocker | Evidence needed to close |
|---|---|---|---|
| `EG-1` | Gate 8-reviewed, exact-span mechanism representation for $\mathrm{TSC2}$ $p.\mathrm{Arg611Gln}$ with assay/model context | `NOT_SATISFIED` / `MECHANISM_UNVERIFIED`: Gate 8 is `BLOCKED_HUMAN_REVIEW`; accepted claims are 0; source-reported entries are not `OBSERVED`. | Named-human Gate 8 review and registered acceptance of the relevant exact, contextualized primary-evidence spans. |
| `EG-2` | Exact reference-transcript, protein, residue, PDB-chain, and construct mapping; no offset arithmetic | `NOT_SATISFIED` / `MAPPING_UNVERIFIED`: pack crosswalk is useful context but does not prove exact RefSeq-to-construct equivalence. | Human-reviewed, retrieval-pinned residue-level mapping across `$NM_000548.5$`, `$NP_000539.2$`, UniProt `P49815`, each PDB entity/chain, and construct numbering. |
| `EG-3` | Human-reviewed experimental structure coverage and uncertainty assessment | `NOT_SATISFIED` / `STRUCTURE_COVERAGE_INSUFFICIENT`: coverage/quality context exists but no reviewed assessment is registered. | Copy-specific assessment of modelled regions, local quality, construct limits, alternate conformers, ligands/ions/detergents, assembly assumptions, and uncertainty. |
| `EG-4` | Complete, per-artifact, lawful tool/data/model-weight/library/license registry | `NOT_SATISFIED` / `LICENCE_INCOMPATIBLE`: no verified registry exists. | Hash-bound registry with artifact/version, license text and locator, permitted use, output/redistribution restrictions, retrieval date, and human verification for every intended input. |
| `EG-5` | Reviewed tractable construct and orthogonal assay plan | `NOT_SATISFIED` / `NO_TRACTABLE_ASSAY`: no registered construct/assay feasibility plan exists. | Feasible wild-type, $\mathrm{R611Q}$, and control constructs plus named direct-binding, native-complex, and functional assays with controls. |

All five gates are conjunctive. A partial pass does not authorize a provisional
start; even `READY_FOR_S1_REVIEW` would not make
`stage_execution_authorized` true.

### Evidence required at each ordered stage

| Stage | Required evidence/artifact before or at the stage | Falsifier or no-go |
|---|---|---|
| `S1` | A narrowly stated, falsifiable structural hypothesis tied only to `OBSERVED` claims; explicit unsupported assumptions excluded. | `MECHANISM_UNVERIFIED` if the hypothesis cannot be grounded after Gate 8 review. |
| `S2` | Experimental structure ensemble with entries, chains, residue ranges, copy-specific quality, ligand inventory, construct/assembly provenance, retrieval dates, and licenses. Predicted models, if ever used, are non-authoritative comparators. | `RESIDUE_OR_INTERFACE_UNRESOLVED` if coverage/quality is insufficient. |
| `S3` | A pocket/interface hypothesis supported across the ensemble by **at least two independent methods**, with persistence, disagreement, and a preregistered falsifier recorded. | `NO_PLAUSIBLE_POCKET` if absent, nonpersistent, or method-disagreed. |
| `S4` | A **small calibrated pilot** only: preregistered settings, property-matched decoys, and lawful controls/actives where available; enrichment is measured rather than assumed. | `UNCALIBRATED_DOCKING` if no calibration exists or enrichment is indistinguishable from chance. |
| `S5` | Orthogonal rescoring that does not share the pilot scoring lineage, plus replicate molecular dynamics with convergence diagnostics and uncertainty. | `MODEL_DISAGREEMENT` for method disagreement or non-convergent replicas. |
| `S6` | Compound-hypothesis package only: complete computational provenance, license record for every input, versioned availability pin, assay plan, controls, and an explicit statement that it remains a hypothesis. | `LICENCE_INCOMPATIBLE` or incomplete package. No purchase list, recommendation, or procurement output. |
| `S7` | Ordered wet-lab cascade with route-specific controls; computation alone cannot produce a wet-lab output term. | `AGGREGATION_INTERFERENCE_OR_TOXICITY`, or another complete negative/no-go result. |

The required `S7` assay cascade is:

| Tier | Minimum evidence needed |
|---|---|
| `AC-1` | Matched wild-type and $\mathrm{R611Q}$ abundance, half-life/turnover, ubiquitination, and proteasome-dependence measurements. |
| `AC-2` | At least two methodologically orthogonal direct-binding measurements; thermal shift or CETSA alone is insufficient. |
| `AC-3` | Wild-type/mutant comparison, inactive analog, declared counter-screens, aggregation/interference/reactivity checks, cytotoxicity/viability, dose response, independent replicates, and independent lots. |
| `AC-4` | Native complex rescue, such as co-immunoprecipitation, with matched $\mathrm{TSC1}$ and $\mathrm{TSC2}$ abundance controls. |
| `AC-5` | A proximal complex-state or $\mathrm{Rheb}$-GAP-proximal readout where feasible, with $p$-$\mathrm{S6K}$/$p$-$\mathrm{S6}$ only as downstream corroboration and wild-type, $\mathrm{R611Q}$, and $\mathrm{TSC2}$-null target-dependence controls. |
| `AC-6` | **Optional only after controlled single-agent rescue is observed at `AC-4` and `AC-5`.** It remains exploratory and cannot support synergy, dose-sparing, toxicity, feedback, clinical, or treatment claims. |

No universal pocket-volume, distance, docking-score, simulation-length, or
$\Delta T_m$ threshold is authorized. Any future parameter must be
preregistered, calibrated for this system, sensitivity-tested, and falsifiable.

## Evidence ledger: current, context-bound representation

The labels below are descriptive evidence contexts, not accepted Atlas claims.
`Direct $\mathrm{R611Q}$` means the allele or an exact allele-specific row was
tested; it does not imply independent replication, clinical relevance, or
causality. `Grouped/control` must not be restated as a new allele-isolated
measurement. `Inference` is deliberately non-evidentiary.

| Topic | Direct $\mathrm{R611Q}$ evidence | Grouped/control evidence | General mechanism or structural context | Current interpretation |
|---|---|---|---|---|
| Identity | Exact `$NM_000548.5:c.1832G>A$`, `$NP_000539.2:p.Arg611Gln$`, and `NC_000016.10:2070570:G:A` cross-reference (`dbSNP:rs28934872`; `UniProt:P49815/VAR_005650`). | — | `P49815` reference residue $611$ is Arg. | Identity is source-recorded; structure mapping still requires `EG-2` review. |
| $\mathrm{TSC1}$–$\mathrm{TSC2}$ binding/chaperone | Nellist 2001 (`PMID:11741832`), direct co-IP/control evidence (`PMID:18302728`), and COS-1 complex result (`PMID:18230340`). | Reduced associated signals/comparator reuse: `PMID:18854862`, `PMID:26703369`, `PMID:39596632`. | Predecessors `PMID:10585443`, `PMID:9580671`, and `PMID:9809973` establish complex/chaperone context. | Direct support is strongest for impaired complex/chaperone behavior in named engineered systems; later signal assays are not binding measurements. |
| Phosphorylation | Nellist 2001 reports an association of affected variants with phosphorylation/complex outcomes. | Variants were separately tested, then concordant outcomes were grouped. | `PMID:11290735` is general phosphorylation–interaction context, not $\mathrm{R611Q}$ testing. | **Associated and mechanistically unresolved**; do not place phosphorylation as a proven upstream causal step. |
| Abundance | Lower steady-state abundance: `PMID:18854862`, `PMID:26703369`, `PMID:27216612`; exact IGVF VAMP-seq row `IGVFFI9747KART`. | `PMID:21309039`, `PMID:39596632` reuse/control context. | VAMP-seq is GFP-fusion steady-state abundance, not folding or half-life. | Supports lower abundance in stated assays; does not demonstrate misfolding, a degron, or turnover kinetics. |
| Ubiquitination/proteostasis | `PMID:18308511`: $\mathrm{TSC1}$ did not block Pam/MYCBP2-associated ubiquitination of $\mathrm{R611Q}$ in HEK293T. | — | `PMID:11175345` (predecessor), `PMID:16464865` (HERC1), and `PMID:29127155` (Hsp90) are general context. | One direct laboratory result; no $\mathrm{R611Q}$ half-life, MG132/proteasome rescue, degron, aggregation, or folding measurement. |
| $\mathrm{mTORC1}$ function | Abnormal $\mathrm{S6K\text{-}T389}$/$p$-$\mathrm{S6}$ readouts: `PMID:18302728`, `PMID:18854862`, `PMID:26703369`, `PMID:27216612`; cliPE exact score in `MaveDB:urn:mavedb:00001201-a-1`. | `PMID:21309039`, `PMID:22719903`, `PMID:39596632`; shared lineage is recorded. | The same cliPE score is indeterminate under the 2024 thresholds and abnormal under the 2026 cutoff. | Impaired downstream suppression is supported, with lineage and calibration dependence; it does not isolate abundance, complex formation, or intrinsic GAP competence. |
| Clinical/tumor occurrence | `PMID:10823953`, `PMID:15595939`, `PMID:16032769`, `PMID:16981987`, `PMID:24271014`, `PMID:29221145`, `PMID:31083211`, `PMID:32313033`, `PMID:32555378`, `PMID:38601768`, `PMID:40225170`. | `621-101`/`621-327` in `PMID:22719903` and `PMID:23555865` are descendants of the $621$ tumor lineage. | Tumor contexts may contain LOH/copy loss. | Occurrence/two-hit context only; not a rescue mechanism, therapy result, or heterozygous patient-cell model. |
| Structural coverage | Wild-type $p.\mathrm{Arg611}$ is modelled in PDB `7DL2` and `9CE3`. | — | `PMID:33436626`, `PMID:39565846`, PDB/PDBe/UniProt resources. | Structural context only; no mutant structure or local intervention-site conclusion. |
| Contradictions/nulls | No direct opposing $\mathrm{R611Q}$ result was verified. | Assay-format difference for abundance and calibration difference for cliPE are retained. | `PMID:11741832`, `PMID:15483652`, and `PMID:22903760` had prior access gaps in the frozen baseline. | Tensions are lineage, assay, model, access, and calibration limits—not a verified biological contradiction. |
| Unsupported/unmeasured | No direct $\mathrm{R611Q}$ misfolding, aggregation, hydrophobic exposure, degron, half-life, proteasome-dependent rescue, restored intrinsic $\mathrm{Rheb}$-GAP activity, mutant structure, contact, pocket, ligandability, binding compound, or rescue. | — | General mechanisms and wild-type coordinates cannot fill these gaps. | These are `UNSUPPORTED`/`NOT_MEASURED`, never premises for computation. |

### Correct causal reading

The strongest **current, source-reported working hierarchy** is:

$$
\text{impaired }\mathrm{TSC1}\text{--}\mathrm{TSC2}\text{ interaction/chaperone behavior}
\;\to\;
\text{loss of }\mathrm{TSC1}\text{-mediated protection}
\;\to\;
\text{Pam/MYCBP2-associated ubiquitination and lower abundance}
\;\to\;
\text{impaired }\mathrm{mTORC1}\text{ suppression}.
$$

This is a context-bound evidence sequence, **not** an accepted causal proof. Its
links have different directness and laboratory independence. In particular,
phosphorylation is associated with complex/chaperone outcomes but remains
mechanistically unresolved. Nellist 2001 expressed and evaluated individual
variant constructs, including $p.\mathrm{Arg611Gln}$, then grouped variants
with concordant outcomes; the grouping supports a shared phenotype class, not
an identical molecular cause or effect magnitude for every variant.

## Structural-readiness facts

All statements in this section are wild-type structural context from
`structure-readiness-v1`; none establishes an $\mathrm{R611Q}$ structural
mechanism.

| Fact | `7DL2` | `9CE3` |
|---|---|---|
| UniProt crosswalk | `P49815` residue $611$ maps to $\mathrm{TSC2}$ entity 2, author residue $611$, label residue $562$, in both copies: author/asym A/B and B/C. | `P49815` residue $611$ maps to $\mathrm{TSC2}$ entity 1, author residue $611$, label residue $619$, in both copies: author/asym A/A and B/B. |
| Deposited residue | Wild-type `ARG`; 11 expected heavy-atom records; occupancy `1.00`. | Wild-type `ARG`; 11 expected heavy-atom records; occupancy `1.00`. |
| Copy-specific validation | Q-scores `0.303` and `0.268`; residue inclusion `1.0000` and `0.8182`, respectively. | Q-scores `0.454` and `0.483`; residue inclusion `0.8182` and `1.0000`, respectively. |
| Resolution context | Repository global resolution: `$4.4\,\text{\AA}$`; the associated article reports `$4.4\,\text{\AA}$` globally with local refinements. | Repository global resolution: `$2.9\,\text{\AA}$`; the article reports a `$2.8\,\text{\AA}$` average nominal composite. These are different reporting contexts, not a contradiction. |
| Deposited inventory | Zero ligands and zero waters. | Zero ligands and zero waters. |

Zero deposited ligands/waters is an inventory observation; it **does not**
imply non-ligandability. Neither entry is an $\mathrm{R611Q}$ mutant
structure. The pack contains no coordinate contact calculation and therefore
does not establish an $\mathrm{Arg611}$–$\mathrm{TSC1}$ contact or salt bridge,
a pocket, or ligandability. It also does not assign a Q-score threshold or
average copy-specific values.

## Prioritized gaps and stop conditions

### Mandatory before `S1`

| Priority | Gap | Required closure |
|---|---|---|
| 1 | Gate 8 claim review | Named-human review of exact, context-carrying primary spans; accepted claims cannot be inferred from the shelf. |
| 2 | Literature/synthesis repin | Rebuild and hash-pin literature/synthesis versions that incorporate the verified Nellist 2001 institutional manuscript and all five predecessors, preserving source roles and licenses. |
| 3 | `EG-2` human review | Register reviewed reference-to-UniProt-to-PDB construct/chain/residue mappings without offset arithmetic. |
| 4 | `EG-3` human review | Register copy-specific experimental coverage, local uncertainty, construct/assembly, ligand/solvent inventory, and limitations. |
| 5 | Complete license registry | Verify every intended tool, weight, source, derived dataset, and later library individually; unresolved permission fails closed. |
| 6 | Construct/assay feasibility | Demonstrate a tractable construct and a discriminating plan for orthogonal binding, complex formation, and functional readouts. |

### Later authorized computation — unreachable now

| Later work only after all entry gates | Evidence condition |
|---|---|
| Restrained wild-type and $\mathrm{R611Q}$ ensembles | Explicitly non-authoritative mutant-model comparator; provenance and uncertainty retained. |
| Interface/contact, solvent-exposure, flexibility, and pocket comparison | Must not assume an $\mathrm{Arg611}$ salt bridge or a pocket. |
| Two-method pocket evidence across an ensemble | Persistence and method disagreement are preregistered; `NO_PLAUSIBLE_POCKET` remains a successful terminal result. |
| Calibrated pilot/decoys | Small, preregistered, lawful pilot with property-matched decoys and calibration—not a scale-up. |
| Orthogonal rescoring/MD | Independent scoring lineages, replicated simulations, convergence diagnostics, and declared uncertainty. |
| Compound-hypothesis provenance | Full input/parameter/license/availability/assay/falsifier record; no recommendation, vendor list, or procurement. |

### Wet-lab measurements

| Measurement gap | Decision it can inform |
|---|---|
| Matched abundance, translation chase, half-life, ubiquitination, and proteasome perturbation | Whether a reproducible $\mathrm{R611Q}$ protein-state defect exists. |
| Orthogonal direct target engagement | Whether a later hypothesis has physical binding support rather than a thermal/cellular proxy only. |
| Native $\mathrm{TSC1}$–$\mathrm{TSC2}$ complex measurement | Whether a later effect restores complex formation without harming wild type. |
| Wild-type, $\mathrm{R611Q}$, and $\mathrm{TSC2}$-null target-dependence controls | Whether a pathway change is route-specific rather than a nonspecific downstream effect. |
| $\mathrm{Rheb}$-GTP/GAP-proximal readout plus $p$-$\mathrm{S6K}$/$p$-$\mathrm{S6}$ | Whether any controlled complex/protein-state change preserves proximal function. |
| Aggregation, interference, reactivity, viability, inactive-analog, dose, lot, and replication controls | Whether an apparent effect is artifact/toxicity rather than route-specific rescue. |

### Terminal and no-go outcomes

| No-go state | Required response |
|---|---|
| `MECHANISM_UNVERIFIED`, `MAPPING_UNVERIFIED`, or `STRUCTURE_COVERAGE_INSUFFICIENT` | Stop before stages; do not substitute predictions or stronger prose. |
| `NO_PLAUSIBLE_POCKET` or `RESIDUE_OR_INTERFACE_UNRESOLVED` | Record the result; do not relax detection or coverage requirements. |
| `UNCALIBRATED_DOCKING` or `MODEL_DISAGREEMENT` | Stop the affected hypothesis; ranks, method agreement, and non-convergence are not binding evidence. |
| `LICENCE_INCOMPATIBLE` or `NO_TRACTABLE_ASSAY` | Stop for the resource/hypothesis; no assumed-open or compute-first fallback. |
| `AGGREGATION_INTERFERENCE_OR_TOXICITY` | Report artifact/toxicity as the result; no rescue inference. |

## Vocabulary and non-negotiable reporting boundaries

### Evidence and earned-output vocabulary

| Term | Meaning here |
|---|---|
| `SOURCE_REPORTED` | Narrow cited statement with context, awaiting the full Atlas acceptance path. All current mechanism claims remain here. |
| `OBSERVED` | Reserved for accepted/reviewed primary evidence with exact spans and context. **None is currently accepted for this lane.** |
| `UNSUPPORTED` / `NOT_MEASURED` | Not established in the stated scope; may not be promoted by citation chaining or computation. |
| `HYPOTHESIS` | A falsifiable proposition, never a presumed mechanism or result. |
| `STRUCTURAL_HYPOTHESIS`, `POCKET_HYPOTHESIS`, `COMPUTATIONAL_SCREENING_HIT`, `ORTHOGONALLY_REPLICATED_HIT` | Closed, stage-earned terms only; none is earned now. |
| `EXPERIMENTALLY_CONFIRMED_BINDER`, `COMPLEX_RESCUE_OBSERVED`, `FUNCTIONAL_RESCUE_OBSERVED` | `S7`-only terms requiring the ordered experimental controls; none is earned now. |

### Prohibited overclaims

Do not imply accepted Atlas claims, classification, a defined
$\mathrm{Arg611}$ salt bridge/contact, mutant misfolding, a degron, turnover
kinetics, intrinsic GAP rescue, a ligandable pocket, a binder, rescue, affinity,
potency, efficacy, `lead`, `drug`, `therapy`, treatment, dose, combination
benefit, synergy, toxicity reduction, feedback mitigation, or patient benefit.
Docking/simulation values are ranking artifacts, never affinity or efficacy.

## References appendix

### Claim-bearing records grouped by mechanism role

| Mechanism role | Identifiers |
|---|---|
| Direct $\mathrm{R611Q}$ complex/chaperone and phosphorylation association | `PMID:11741832`, `DOI:10.1093/hmg/10.25.2889`; `PMID:18230340`, `DOI:10.1016/j.bbrc.2008.01.077`; `PMID:18302728`, `PMCID:PMC2291454`, `DOI:10.1186/1471-2350-9-10`. |
| Grouped/control complex or functional context | `PMID:18854862`, `PMCID:PMC2986163`, `DOI:10.1038/ejhg.2008.184`; `PMID:21309039`, `DOI:10.1002/humu.21451`; `PMID:26703369`, `PMCID:PMC4843954`, `DOI:10.1002/humu.22951`; `PMID:31799751`, `PMCID:PMC7154745`, `DOI:10.1002/humu.23963`; `PMID:32555378`, `PMCID:PMC7303179`, `DOI:10.1038/s41598-020-66588-4`; `PMID:39596632`, `PMCID:PMC11593644`, `DOI:10.3390/genes15111432`. |
| Abundance and direct datasets | `IGVF:IGVFFI9747KART`, `DOI:10.65695/IGVFDS5595BTYJ`, `IGVFDS5595BTYJ`; `PMCID:PMC12871146`, `DOI:10.64898/2026.01.16.699909`; `MAVEDB:urn:mavedb:00001201-a-1`, row `#62`; `PMID:38895336`, `PMCID:PMC11185720`, `DOI:10.1101/2024.06.07.597916`. |
| Ubiquitination/proteostasis | `PMID:18308511`, `PMCID:PMC2435383`, `DOI:10.1016/j.cellsig.2008.01.020`; `PMID:16464865`, `DOI:10.1074/jbc.C500451200`; `PMID:29127155`, `PMCID:PMC5730846`, `DOI:10.15252/embj.201796700`. |
| $\mathrm{mTORC1}$ and tumor-lineage downstream context | `PMID:27216612`, `PMCID:PMC4878062`, `DOI:10.1186/s13041-016-0222-6`; `PMID:22719903`, `PMCID:PMC3376142`, `DOI:10.1371/journal.pone.0038589`; `PMID:23555865`, `PMCID:PMC3612076`, `DOI:10.1371/journal.pone.0060014`; `DOI:10.64898/2026.07.14.738392`. |
| Clinical/tumor occurrence and two-hit context | `PMID:10823953`, `PMCID:PMC18562`, `DOI:10.1073/pnas.97.11.6085`; `PMID:15595939`, `DOI:10.1111/j.1600-0404.2004.00366.x`; `PMID:16032769`, `DOI:10.1002/pd.1197`; `PMID:16981987`, `PMCID:PMC1592085`, `DOI:10.1186/1471-2350-7-72`; `PMID:24271014`, `PMCID:PMC3959815`, `DOI:10.1093/hmg/ddt597`; `PMID:29221145`, `PMCID:PMC5707039`, `DOI:10.18632/oncotarget.20764`; `PMID:31083211`, `PMCID:PMC6531247`, `DOI:10.1097/MD.0000000000015545`; `PMID:32313033`, `PMCID:PMC7170856`, `DOI:10.1038/s41598-020-62759-5`; `PMID:38601768`, `PMCID:PMC11004469`, `DOI:10.3389/fonc.2024.1357980`; `PMID:40225170`, `PMCID:PMC11918493`, `DOI:10.1155/2023/4899372`. |
| Structural/identity context | `DBSNP:rs28934872`; `UNIPROT:P49815/VAR_005650`; `PDB:7DL2`, `PMID:33436626`, `PMCID:PMC7804450`, `DOI:10.1038/s41467-020-20522-4`; `PDB:9CE3`, `PMID:39565846`, `PMCID:PMC11578170`, `DOI:10.1126/sciadv.adr5807`. |
| Foundational predecessors | `PMID:10585443`, `DOI:10.1074/jbc.274.50.35647`; `PMID:9580671`, `DOI:10.1093/hmg/7.6.1053`; `PMID:9809973`; `PMID:11175345`, `DOI:10.1038/sj.onc.1204009`; `PMID:11290735`, `DOI:10.1074/jbc.c100136200`. |

### Underlying-corpus index

Every record is retained here. `Occurrence/context/access-gap` means it has no
current standalone mechanistic contribution and must not be omitted or silently
upgraded.

| Record | Type | Current contribution |
|---|---|---|
| `DOI:10.64898/2026.01.16.699909` / `PMCID:PMC12871146` | Focused publication | Direct VAMP-seq abundance row; cliPE recalibration/context. |
| `DOI:10.64898/2026.07.14.738392` | Focused publication | General $\mathrm{TSC1}$ allosteric/GAP context; no $\mathrm{R611Q}$ test. |
| `PMID:10823953` | Focused publication | Tumor occurrence/two-hit context. |
| `PMID:11741832` | Focused publication | Direct $\mathrm{R611Q}$ chaperone/complex and phosphorylation-associated evidence. |
| `PMID:12205112` | Focused publication | Occurrence/context; no allele-isolated result extracted. |
| `PMID:15483652` | Focused publication | Access-gap/same-lineage context; exact allele span not yet verified in frozen baseline. |
| `PMID:15595939` | Focused publication | Clinical occurrence. |
| `PMID:16032769` | Focused publication | Clinical occurrence. |
| `PMID:16464865` | Focused publication | General $\mathrm{TSC1}$–HERC1 proteostasis context. |
| `PMID:16981987` | Focused publication | Clinical occurrence. |
| `PMID:18230340` | Focused publication | Direct engineered-system complex result. |
| `PMID:18302728` | Focused publication | Direct co-IP and downstream function/control evidence. |
| `PMID:18308511` | Focused publication | Direct Pam/MYCBP2-associated ubiquitination. |
| `PMID:18854862` | Focused publication | Direct abundance/downstream readouts; shared lineage. |
| `PMID:21309039` | Focused publication | Grouped/control functional context. |
| `PMID:22719903` | Focused publication | Tumor-lineage downstream context, not an independent allele model. |
| `PMID:22903760` | Focused publication | Access-gap/same-lineage context; exact allele span not verified. |
| `PMID:23555865` | Focused publication | Tumor-lineage downstream context, not a controlled allele experiment. |
| `PMID:24271014` | Focused publication | Tumor occurrence. |
| `PMID:26703369` | Focused publication | Direct abundance/downstream control evidence; shared lineage. |
| `PMID:27216612` | Focused publication | Direct supplied-plasmid abundance/downstream evidence; not protein rescue. |
| `PMID:29127155` | Focused publication | General $\mathrm{TSC1}$–Hsp90 proteostasis context. |
| `PMID:29221145` | Focused publication | Tumor occurrence/two-hit context. |
| `PMID:31083211` | Focused publication | Clinical occurrence. |
| `PMID:31799751` | Focused publication | Grouped/control comparator context. |
| `PMID:32313033` | Focused publication | Clinical occurrence. |
| `PMID:32555378` | Focused publication | Clinical occurrence plus reused comparator context. |
| `PMID:33436626` | Focused publication | Wild-type structural context for `7DL2`. |
| `PMID:38601768` | Focused publication | Tumor occurrence/downstream-response context; not rescue evidence. |
| `PMID:38895336` | Focused publication | cliPE program; deduplicate against MaveDB. |
| `PMID:39565846` | Focused publication | Wild-type structural context for `9CE3`. |
| `PMID:39596632` | Focused publication | Grouped/control signal and downstream-comparator context. |
| `PMID:40225170` | Focused publication | Clinical occurrence. |
| `PMID:10585443` | Foundational predecessor | Tuberin–hamartin chaperone/solubility context; not $\mathrm{R611Q}$-specific. |
| `PMID:9580671` | Foundational predecessor | Physical interaction/coiled-coil context; not $\mathrm{R611Q}$-specific. |
| `PMID:9809973` | Foundational predecessor | Endogenous interaction/localization context; not $\mathrm{R611Q}$-specific. |
| `PMID:11175345` | Foundational predecessor | $\mathrm{TSC1}$-associated protection from ubiquitination; not $\mathrm{R611Q}$-specific. |
| `PMID:11290735` | Foundational predecessor | Phosphorylation–interaction context; not $\mathrm{R611Q}$-specific. |
| `MAVEDB:urn:mavedb:00001201-a-1` | Direct dataset | Exact cliPE score; calibration-version dependent. |
| `IGVF:IGVFFI9747KART` | Direct dataset | Exact GFP-fusion steady-state abundance row; not folding/half-life. |
| `DBSNP:rs28934872` | Identity record | Variant identity only. |
| `UNIPROT:P49815/VAR_005650` | Identity record | Sequence/annotation identity only. |
| `PDB:7DL2` | Structure record | Wild-type residue coverage only; no contact/pocket inference. |
| `PDB:9CE3` | Structure record | Wild-type residue coverage only; no contact/pocket inference. |

## Readiness conclusion

**Signed off for evidence curation and human review only.** The current
evidence is sufficient to preserve a context-bound, falsifiable research
question, but not to start RescueScreen. Do not perform docking, pocket
selection, compound screening, simulation, procurement, or treatment inference
until Gate 8 and `EG-1` through `EG-5` are independently satisfied and
registered.
