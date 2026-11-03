# RescueScreen $TSC2$ $p.\mathrm{Arg611Gln}$ literature synthesis

**Evidence cutoff:** 2026-08-17  
**Inventory:** 33 publications, 2 direct datasets, and 4 identity/structure records.  
**Status:** exploratory evidence synthesis only; no clinical interpretation and no Atlas acceptance.

## What is directly observed for $R611Q$

1. **Reduced $TSC1$ association/complex behavior in engineered systems.** Direct co-IP support is present in PMID `18302728`; PMID `18230340` describes the allele as unable to form the hamartin complex. Later assays repeatedly show reduced $TSC1$ and/or $TSC2$ signals, but signal is not a direct binding measurement.
2. **Lower steady-state $TSC2$ abundance in several assays.** PMIDs `18854862`, `26703369`, and `27216612` report lower $R611Q$ signal. The released IGVF VAMP-seq row independently classifies the GFP-fusion abundance result as `functionally_abnormal` with score `-0.0226807654120319`.
3. **Pam/MYCBP2-associated ubiquitination.** PMID `18308511` shows that co-expressed $TSC1$ fails to block Pam-associated ubiquitination of $R611Q$ in HEK293T cells.
4. **Impaired downstream $mTORC1$ suppression in low-throughput assays.** S6K-T389 and phospho-S6 readouts are abnormal in the cited HEK293/MEF systems.
5. **An endogenous cliPE score exists.** MaveDB row `#62` is `0.345544328`. It is indeterminate under the 2024 two-threshold calibration and abnormal under the 2026 single cutoff.
6. **Repeated clinical and tumor occurrence.** $R611Q$ appears in multiple cohorts/cases and in several tumors with LOH/copy loss. These observations establish occurrence and two-hit contexts, not a rescue mechanism.
7. **Wild-type structural coordinates cover residue 611.** PDB `7DL2` and `9CE3` model Arg611 in $TSC2$ chains A and B.

## Grouped attribution and control reuse

- $R611Q$ is frequently a known inactive/pathogenic comparator rather than a new study allele.
- PMID `39596632` groups $R611Q$ with two other variants for reduced $TSC1$/$TSC2$ signals; no allele-specific magnitude is stated in that sentence.
- PMIDs `31799751`, `32555378`, and `39596632` share the 3H9-1B1 double-knockout line.
- The parental-cell papers share Nellist/Erasmus constructs and assay ancestry.
- PMID `27216612` was performed by another laboratory, but its $R611Q$ plasmid came from Mark Nellist.
- MaveDB and PMID `38895336` are one cliPE program. The 2026 paper recalibrates that same score and adds an independent VAMP-seq experiment.
- `621-101` and `621-327` are derivatives of the patient-621 tumor lineage, not independent or heterozygous allele models.

Publication count must therefore not be equated with independent replication count.

## Indirect or general $TSC2$ biology

- HERC1 exclusion by $TSC1$ and Hsp90 co-chaperone biology support general $TSC2$ proteostasis, but neither mechanism was shown specifically for $R611Q$.
- Wild-type structures explain TSC-complex architecture and general GAP biochemistry, but do not establish the $R611Q$ conformation.
- The 2026 transition-state study shows that $TSC1$ contributes allosterically to GAP competence; it does not test $R611Q$.
- Rac1/ROS, miRNA, tumor-dissemination, and clinical response findings are valid in their reported systems but are not evidence of protein stabilization.

## Unsupported or not measured

The corpus does **not** establish:

- direct $R611Q$ misfolding, aggregation, exposed hydrophobic surface, or a defined degron;
- endogenous or construct-specific $R611Q$ half-life and proteasome-dependent turnover;
- restored intrinsic Rheb-GAP activity after abundance/complex rescue;
- an experimentally defined Arg611-$TSC1$ salt bridge;
- an $R611Q$ mutant structure;
- a ligandable/druggable pocket near residue 611;
- direct compound binding, thermal stabilization, complex rescue, or functional rescue;
- synergy, dose reduction, reduced toxicity, or feedback mitigation with everolimus.

Everolimus/rapamycin suppression of pS6K, pS6, miRNA, xenograft, or tumor readouts is downstream pathway inhibition—not evidence that mutant tuberin was stabilized.

## Assay and laboratory lineage dependence

The strongest low-throughput functional evidence is concentrated in the Nellist/Erasmus lineage and two assay generations: parental HEK293/HEK293T overexpression and 3H9-1B1 double-knockout re-expression. The Ramesh Pam ubiquitination experiment is independent but imports the binding premise. The cliPE and VAMP-seq programs add methodologically independent high-throughput evidence, with calibration and fusion-assay limitations. Tumor-derived 621 models add a separate biological context but are biallelic and non-isogenic.

## Search and access limits

Original full-text spans remain incomplete for PMIDs `11741832`, `15483652`, and `22903760`. Several readable PMC records have no confirmed open-content license. The exact IGVF VAMP row was retrieved and hash-pinned, but the file record does not expose an explicit reuse license. The search was bounded to frozen/named sources and verified citation tracing available by 2026-08-17. No direct contradiction was found, but this is not proof that none exists.

## RescueScreen and Atlas boundary

This bundle is a RescueScreen exploratory evidence product. It does not start the structural-rescue lane, satisfy its entry gates, promote an Atlas claim, or alter any classification. Atlas Gate 8 remains `BLOCKED_HUMAN_REVIEW`, and `accepted_claim_count=0`.

## Bottom line

A context-bound evidence chain supports impaired complex behavior, lower steady-state abundance, Pam-associated ubiquitination, and impaired downstream $mTORC1$ regulation for $R611Q$. The key RescueScreen premise remains uncertain: it is not known whether the allele is directly misfolded, whether a druggable structural site exists, or whether stabilizing/forcing the complex would restore intrinsic GAP activity. Those questions require new controlled measurements, not stronger wording of the existing literature.
