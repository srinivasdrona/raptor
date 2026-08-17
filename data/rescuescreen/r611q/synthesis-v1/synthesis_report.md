# R611Q RescueScreen synthesis

**Status:** exploratory, literature-derived, not expert validated  
**Variant:** $TSC2$ $p.\mathrm{Arg611Gln}$  
**Evidence cutoff:** 2026-08-17  
**Source bundle:** [`../literature-v1`](../literature-v1)

## Decision

The evidence justifies an R611Q-specific **rescue feasibility investigation**, but it does not
select a rescue mechanism or authorize compound screening.

The strongest context-bound findings are:

1. reduced $\mathrm{TSC1}$ binding, complex formation, or complex-associated signal;
2. reduced steady-state $\mathrm{TSC2}$ abundance across several assay formats;
3. one direct Pam/MYCBP2-associated ubiquitination result;
4. impaired TSC-complex-dependent $\mathrm{mTORC1}$ suppression;
5. wild-type experimental structures that include residue $611$.

These findings support three computational hypotheses:

- local mutant stabilization;
- $\mathrm{TSC1}$-$\mathrm{TSC2}$ interface stabilization;
- distal allosteric stabilization.

The null hypothesis--no structurally plausible small-molecule rescue route--is retained with equal
status.

## What the evidence does not establish

No source demonstrates:

- direct R611Q misfolding, aggregation, a hydrophobic patch, or a defined degron;
- an R611Q-specific half-life or proteasome-dependent abundance rescue;
- intrinsic Rheb-GAP competence after abundance or complex restoration;
- a mutant R611Q structure;
- a validated Arg611-$\mathrm{TSC1}$ contact or ligandable pocket;
- direct compound binding, stabilization, complex rescue, or functional rescue.

## Assay-lineage interpretation

Publication count is not replication count. Much of the low-throughput functional evidence shares
Nellist/Erasmus constructs, positive-control reuse, or the same parental and 3H9-1B1 cell systems.
The Pam/MYCBP2 study is an independent biochemical lineage but imports the R611Q binding premise.
The cliPE and VAMP-seq measurements provide independent high-throughput evidence with distinct
calibration and fusion-assay limitations.

Tumor-derived `621-101` and `621-327` models carry R611Q plus loss of the other allele. They are
not heterozygous, isogenic R611Q models.

## Required structural work

Before considering compounds:

1. verify $NM\_000548.5$ / UniProt P49815 / PDB chain and residue-numbering equivalence;
2. inspect residue $611$ in PDB `7DL2` and `9CE3`, including modeled atoms, local density or
   quality, construct boundaries, alternate conformers, ligands, and assembly assumptions;
3. generate restrained wild-type and R611Q ensembles while keeping predictions explicitly
   non-authoritative;
4. compare local contacts, solvent exposure, interface geometry, flexibility, and pocket
   persistence;
5. require agreement from at least two pocket/interface methods;
6. retain a no-site/no-route outcome without relaxing criteria.

Cosolvent or enhanced sampling is a second-line analysis when conventional experimental-structure
ensembles cannot resolve pocket opening; it is not the MVP starting point.

## Required laboratory logic

The laboratory proposal must distinguish:

- protein-state rescue: abundance, half-life, ubiquitination, and proteasome dependence;
- physical target engagement: thermal methods as screens plus an orthogonal direct-binding method;
- complex rescue: $\mathrm{TSC1}$-$\mathrm{TSC2}$ native-complex measurement;
- target dependence: wild-type, R611Q, and $\mathrm{TSC2}^{-/-}$ conditions;
- functional preservation: Rheb-GTP or another GAP-proximal readout, with $p$-S6K/$p$-S6 only as
  downstream corroboration;
- nonspecific effects: aggregation, interference, reactivity, and cytotoxicity.

No universal $\Delta T_m$, docking-score, pocket-size, simulation-length, or top-ranked-fraction
threshold is authorized. Thresholds must be assay-specific and preregistered from controls and
variance.

## Next decision artifact

The next useful product is an **R611Q structural differential and intervention-site feasibility
report**, not a compound list. It should terminate in one or more of:

- `LOCAL_STABILIZATION_ROUTE_PLAUSIBLE`;
- `INTERFACE_STABILIZATION_ROUTE_PLAUSIBLE`;
- `DISTAL_ALLOSTERIC_ROUTE_PLAUSIBLE`;
- `NO_STRUCTURALLY_PLAUSIBLE_ROUTE`;
- `NOT_ESTIMABLE_FROM_AVAILABLE_STRUCTURE`.

Only a route with a reproducible site and an executable falsifying assay can proceed to a small
calibrated compound pilot.

## Governance boundary

This synthesis does not alter the Atlas catalog, promote an Atlas claim, change Gate 8, classify
the variant, authorize a RescueScreen stage, or recommend any compound or treatment.
