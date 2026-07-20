# RAPTOR Mechanism Atlas — preliminary handoff

> **Status:** PRELIMINARY / UNAPPROVED / UNVERIFIED DESIGN INPUT  
> **Source:** Sanitized from the local `pre-build/raptor-mechanism-atlas-handoff.md` discussion.  
> **Activation:** None. This document authorizes no classification, assay, intervention or treatment claim.

## Purpose

Define a strict internal RAPTOR module for synthesizing mechanistic evidence about
TSC2 missense variants. The module should answer:

1. What has been directly observed?
2. What mechanism classes remain plausible?
3. What evidence contradicts each hypothesis?
4. Which assay gaps prevent discrimination?
5. What remains explicitly unknown?

The near-term product is a provenance-rich mechanism profile, not therapy,
clinical interpretation or a deterministic phenotype prediction.

## Boundary decision

- Build inside RAPTOR as `RAPTOR Mechanism Atlas`.
- Keep classification evidence and mechanism synthesis as separate outputs.
- Define explicit module inputs, outputs, schemas and leakage guards.
- Extract to a separate repository only after reuse is demonstrated.

Possible extraction evidence:

1. the ontology survives multiple TSC2 variants;
2. it works for another gene;
3. the API is independent of RAPTOR;
4. another consumer exists; or
5. independent release, team or licensing needs emerge.

## Initial scope

1. Start with TSC2.
2. Use a bounded panel spanning pathogenic, benign, conflicting and VUS examples.
3. Include `TSC2 p.Arg611Gln (R611Q)` as an initial case card only after its
   identity and evidence are independently re-grounded.
4. Do not expand to TSC1 or another mTORopathy until the TSC2 pilot passes its
   stop/go criteria.

The raw handoff proposed beginning with R611Q. That is useful for continuity but
creates single-case overfitting risk; the ontology must be challenged by contrasting
examples before it is considered stable.

## Candidate mechanism classes

These are ontology seeds, not established facts:

1. RNA or splicing defect presenting as a missense annotation
2. Reduced protein abundance or instability
3. Misfolding with residual function
4. Complex-formation defect
5. Mislocalization
6. Catalytic or functional-site impairment
7. Dominant-negative or interference mechanism
8. Hypomorphic partial loss

Mechanisms may be multi-label and context-dependent. `unknown` and `conflicting`
are valid outcomes.

## Candidate evidence model

Each variant mechanism profile should be able to represent:

- canonical variant identity and transcript;
- evidence packet references;
- RNA/splicing evidence;
- protein abundance/stability evidence;
- TSC1–TSC2 complex evidence;
- localization evidence;
- pathway-state and mTORC1 evidence;
- cell type, model organism, tissue and assay context;
- phenotype observations without deterministic inference;
- candidate mechanism classes and confidence;
- supporting and contradicting claims;
- missing assay gaps;
- source citations and exact spans;
- explicit unknowns;
- optional literature-backed rescue-class hypotheses, never recommendations.

## R611Q validation ceiling

The local handoff discussed R611Q as potentially involving altered TSC2 function,
stability, TSC1 interaction, mTOR suppression or hypomorphic loss, while noting
splicing and dominant-negative possibilities.

**None of those statements is authoritative here.** Before the case card is admitted:

1. normalize and verify the exact variant/transcript;
2. verify ClinVar and primary-literature claims independently;
3. distinguish germline, somatic, mosaic and inferred zygosity;
4. verify protein abundance, complex, localization and pathway claims from the
   applicable assay/model;
5. represent unsupported mechanisms as hypotheses;
6. prohibit intervention/rescue language unless a direct published experiment
   supports the exact relationship.

## Prior-art starting points

The design phase should inventory:

- Dutch/European TSC functional-assay work, including Nellist and
  Hoogeveen-Westerveld programs;
- later TSC2 missense functional maps;
- MaveDB or other accessible functional datasets;
- ClinVar and gene-specific databases;
- existing TSC mechanism synthesis in Monarch/DisMech;
- assay, tissue and model limitations;
- negative and contradictory evidence.

Every claim must resolve to a primary source or remain `UNVERIFIED`.

## Phased build

### Phase 1 — design and case-card contract

- module charter;
- ontology v0;
- evidence schema;
- R611Q re-grounding plan;
- contrast-panel selection;
- assay-gap representation;
- stop/go criteria.

### Phase 2 — bounded TSC2 pilot

- 5–10 variant profiles;
- pathogenic, benign, conflicting and VUS representation;
- independent source-span validation;
- tests for unknowns, contradictions and context;
- classification/mechanism leakage guards.

### Phase 3 — TSC2 Atlas

- revised ontology based on pilot failures;
- stable module API;
- evidence and mechanism-profile schemas;
- deterministic validation;
- documented extraction seam;
- optional one-way DisMech-compatible export.

### Phase 4 — expansion gate

Only consider TSC1, another gene or repository extraction after the TSC2 pilot
demonstrates a stable, useful ontology and another concrete consumer.

## Hard prohibitions

- No patient-specific clinical interpretation.
- No treatment recommendation.
- No mechanism claim inferred from amino-acid substitution alone.
- No phenotype prediction from molecular effect alone.
- No classifier score imported as mechanism truth.
- No mechanism profile imported back into ACMG scoring without a separately
  approved evidence policy.
- No cross-disease expansion for grant optics.
- No unsupported rescue claim.

## Next implementation artifacts

After the production-faithful masked rerun:

1. planner-authored module charter and task spec;
2. Gemini-authored schema/contract tests;
3. Sonnet implementation of the internal module skeleton;
4. GPT-5.4 checker verdict;
5. bounded pilot only after the schema and leakage guards are clean.

