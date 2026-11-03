# $TSC2$ $p.\mathrm{Arg611Gln}$ contradiction and null-result report

**Cutoff:** 2026-08-17  
**Scope:** RescueScreen mechanism evidence only. No acceptance, classification, phenotype conclusion, or treatment interpretation.

## Overall result

No direct opposing $R611Q$ result was verified. The important tensions are assay dependence, grouped/control reuse, model-context confounding, and calibration changes—not a clean biological contradiction.

## 1. $TSC1$ binding and complex-associated abundance

- Direct co-immunoprecipitation support: PMID `18302728`.
- PMID `18230340` directly describes $R611Q$ as unable to form a hamartin complex in its COS-1 study.
- PMIDs `18854862`, `26703369`, and `39596632` support reduced $TSC1$/$TSC2$ signals, but signal is not identical to binding or complex mass.
- Most low-throughput evidence belongs to the Nellist/Erasmus lineage. It must not be counted as many independent replications.

No direct contradictory binding result was found.

## 2. Steady-state abundance versus stability

Direct lower abundance is reported in parental HEK293T assays (PMIDs `18854862`, `26703369`, `27216612`) and in the exact IGVF VAMP-seq row:

- variant: `ENSP00000219476.3:p.Arg611Gln`
- score: `-0.0226807654120319`
- standard error: `0.0934680941689553`
- class: `functionally_abnormal`

The Coevoets ICW format found only a slight reduction, whereas conventional cytosolic immunoblot found a consistent reduction. This is assay-format dependence, not opposing direction.

VAMP-seq measures steady-state GFP-fusion abundance. None of these sources measures endogenous folding or half-life.

## 3. Ubiquitination versus proteasomal turnover

PMID `18308511` directly shows that $TSC1$ blocks Pam/MYCBP2-associated ubiquitination of wild-type $TSC2$ and $R905Q$, but not $R611Q$.

That experiment did **not** measure $R611Q$ half-life, proteasome-dependent turnover, MG132 abundance rescue, a degron, aggregation, or misfolding. General HERC1 and Hsp90 mechanisms (PMIDs `16464865`, `29127155`) are indirect for $R611Q$.

## 4. $mTORC1$ suppression and the cliPE calibration tension

Low-throughput assays report impaired suppression of S6K/S6 phosphorylation (PMIDs `18302728`, `18854862`, `26703369`, `27216612`; grouped/control reuse in later papers).

The independent MaveDB row is `0.345544328`:

- 2024 thresholds: benign below `0.242`, abnormal above `0.477`; $R611Q$ is measured-indeterminate.
- 2026 cutoff: abnormal above `0.25`; the same score is abnormal.

This is a threshold-version change on one dataset, not two experiments and not a biological contradiction.

## 5. Rapalog response is not protein rescue

PMID `27216612` shows 10 nM everolimus lowering the $R611Q$-associated pS6K readout in transfected HEK293T cells. PMIDs `23555865` and `22719903` show rapamycin-sensitive downstream phenotypes in the $R611Q$-plus-LOH 621 lineage. PMID `38601768` reports a tumor response in an ovarian cancer carrying somatic $R611Q$ plus copy loss.

These observations show downstream pathway sensitivity. They do not show direct binding to tuberin, stabilization, restored $TSC1$ association, restored intrinsic GAP activity, or combination benefit.

## 6. Tumor and cell-line context

Carsillo patient 621 and 651 tumors carried $R611Q$ plus $TSC2$ LOH. `621-101` and `621-327` are tumor-derived descendants with biallelic inactivation. They are not heterozygous patient-cell models. Their reuse in PMIDs `23555865` and `22719903` is not independent allele replication.

Other direct tumor occurrences include SEGA copy-neutral LOH (PMID `29221145`), angiofibroma low-level somatic occurrence (PMID `24271014`), and ovarian tumor copy loss (PMID `38601768`).

## 7. Structure and pocket claims

PDB `7DL2` and `9CE3` model wild-type Arg611 in both $TSC2$ chains. `7DL2` is 4.4 Å globally; `9CE3` is 2.9 Å in RCSB. Neither is an $R611Q$ structure.

No verified source demonstrates:

- a defined Arg611-$TSC1$ salt bridge;
- an $R611Q$-created pocket;
- local ligandability or druggability;
- a fragment/compound hit;
- a ligand-bound structure.

## 8. Intrinsic GAP rescue

No study restored $R611Q$ abundance or forced complex formation before directly measuring Rheb GTP hydrolysis. PMID `18302728` cannot isolate intrinsic catalytic competence because little $R611Q$ was recovered through $TSC1$ immunoprecipitation. The 2026 transition-state preprint shows a general allosteric contribution of $TSC1$, reinforcing that abundance restoration alone cannot be assumed to restore catalysis.

## Boundary

This report adds no Atlas acceptance. Gate 8 remains `BLOCKED_HUMAN_REVIEW`; `accepted_claim_count=0`. All conclusions remain context-bound RescueScreen exploratory evidence.
