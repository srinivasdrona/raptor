# Slot 1 — TSC BS2 policy grounded in penetrance/age/mosaicism · planner/role prefix

You are the **planner** for one vertical RAPTOR policy blocker: **the BS2 disposition decision for TSC1/TSC2**
(PROGRAM.md item 6, `decision_dependency: bs2-policy`). BIAS's BS2 fired **34×** in the census and is
currently `deferred` with no *documented* rationale. Your job is to specify a contract that (1) grounds the
decision in **penetrance / age-of-onset / mosaicism** domain authority and the actual BIAS BS2 firing
signal, and (2) if that domain authority is **insufficient to license automated BS2 for TSC**, **preserves
the explicit `deferred` exclusion with a cited rationale — never invents an approval.** You write the
build/test contract (slot 2) and the preservation/inversion guard (slot 3). You do **not** write
production code or executable tests.

Emit an `INTENT` block before editing that names: the **user** (the eval/candidate policy that must decide
whether BS2 may ever be scored for TSC), the **artifact** (a documented BS2 disposition decision + a cited
authority-and-firing evidence review + a fail-closed "deferred needs a named decision + rationale"
invariant), the **validator** (the 34-firing characterization, the `get_bs2` source-condition read, the
primary-ClinGen authority review, and the disposition-invariance meta-test), the **falsifier** (any
promotion of BS2 to `allowed`/`included`/`automatable` without a real named authority; any `deferred`
record lacking a named `decision_dependency` + rationale; any grounding of the decision in benchmark
labels), and **why** a generic ACMG product cannot supply this (BS2 applicability is a **TSC-specific**
penetrance/age/mosaicism judgment, and the automatable signal is a property of *this pinned BIAS 3.0.0*
population test).

## The decision, framed honestly

BS2 (ACMG/AMP 2015): *observed in a healthy adult individual with full penetrance expected at an early
age*. applying it correctly for TSC turns on three disease-specific uncertainties. As of 2026-07-12 the
ClinGen TSC VCEP remains at **Develop Classification Rules** and no approved/published TSC-specific
BS2 CSpec was located; the points below are clinical caution grounded in the general criterion and
TSC disease sources, not an invented VCEP specification:

- **Penetrance** — classic pathogenic TSC1/TSC2 variants are highly penetrant; BS2's "healthy adult"
  argument only holds when reduced penetrance is excluded.
- **Age of onset** — TSC can present at any age; BS2 needs adults *well past* the expected onset, thoroughly
  phenotyped to rule out subtle features.
- **Mosaicism** — mosaicism is common in TSC (especially TSC2); an apparently-healthy variant carrier may be
  a low-level/subclinical mosaic, so BS2 must **not** be applied when mosaicism cannot be excluded.

BIAS's `get_bs2` is a **population-frequency test** (homozygous / hemizygous / control allele counts vs a
threshold) — it does **not** phenotype the "healthy adult," exclude reduced penetrance, or exclude
mosaicism. So even though the *source* of BS2's signal is label-independent (gnomAD/1000G controls, not the
ClinVar label), the *automatable evidence* does not, on its own, meet the VCEP's BS2 bar. That gap is the
crux of the decision.

## Evidence hierarchy (highest → lowest authority)

1. **Primary domain authority** — the ClinGen **TSC VCEP** BS2 specification (if published) and the ClinGen
   **SVI** BS2 recommendation. This is what could *license or withhold* automated BS2. **Retrieve and cite
   primary sources; do not fabricate specific thresholds.**
2. **Pinned BIAS source** — `benign_classifiers.py::get_bs2` (L116–176) + `constants.py` thresholds define
   exactly what triggers a BS2 firing and from what control source (label-independence proof, and proof
   that penetrance/age/mosaicism are **not** modeled).
3. **RAPTOR policy today** — `configs/eval/bias_lineage.yaml` (BS2 record: `label_independent_population`,
   disposition `deferred`, `decision_dependency: bs2-policy`); `src/raptor/eval/{lineage_policy,
   lineage_registry}.py` (the deferred-needs-a-named-decision invariants). BS2 is **not** in
   `included_criteria`/`automatable_criteria`.
4. **Dynamic incidence** — `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`criterion_firing.BS2 = 34`;
   `known_policy_gaps`: "BS2 fired 34 times … omitted … without a recorded rationale"). **Incidence
   characterizes the firing; it never licenses inclusion and is never the decision's ground.**

Lower tiers never override higher ones. **Benchmark/ClinVar labels are never the ground for this decision**
— grounding BS2 in how it correlates with the labels it will be graded against is circular (R-A2).

## Required source inspection (no-assumption rule)

- `D:\AIProjects\raptor-data\sources\BIAS-2015\src\bias_2015\benign_classifiers.py::get_bs2` (L116–176) and
  the `constants.py` BS2 thresholds / control-source loaders.
- `configs/eval/bias_lineage.yaml` (BS2 record) — must stay `deferred` unless a named authority approves.
- `src/raptor/eval/lineage_policy.py` (deferred ⇒ non-empty `decision_dependency` or raise),
  `src/raptor/eval/lineage_registry.py` (`deferred_included_without_decision`).
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`criterion_firing`, `known_policy_gaps`).
- Primary ClinGen TSC VCEP / SVI BS2 documents (via `web_fetch` on clinicalgenome.org / the VCEP
  publication) — cite exactly; record what authority exists **and** whether it is sufficient.

## Empirical probes BEFORE policy (non-negotiable ordering)

1. **34-firing characterization**: what population signal triggered each BS2 firing (homozygous /
   hemizygous / control-AC), the gene/consequence distribution, and any co-firing with pathogenic criteria
   (a BS2+PVS1 conflict is a red flag) — derived from the census / BIAS output, not invented.
2. **`get_bs2` source-condition read**: the exact firing condition + threshold + control source, proving
   (a) label-independence and (b) that penetrance/age/mosaicism are **not** modeled.
3. **Authority review**: retrieve the primary ClinGen TSC VCEP / SVI BS2 guidance; record the exact
   specification (penetrance/age/mosaicism requirements) and an **explicit sufficiency verdict** — is the
   *automatable BIAS signal* sufficient to meet it?

## The "insufficient authority ⇒ preserve deferred" rule (non-negotiable)

If the domain authority is insufficient to license *automated* BS2 for TSC — the expected outcome, because
`get_bs2`'s population test cannot phenotype, exclude reduced penetrance, or exclude mosaicism, and no
Oracle molecular geneticist is yet recruited (GP-3 open) — then BS2 **stays `deferred`** with a **non-empty,
cited rationale** naming the penetrance/age/mosaicism gap and the missing authority. **Do not invent an
`approved`/`allowed` disposition.** Approval, if ever, requires a separate named decision + Oracle/VCEP
sign-off that this task does not fabricate. No clinical classification of the 34 variants is produced.

Finish with a `VERIFICATION` block and the exact diff scope. Do not stage, commit, push, or modify
unrelated files, or the shared PROGRAM/STRATEGY/DECISIONS/RISK docs. Do not modify or delete the untracked
`docs/prd/PRD-04-candidate-evidence-packet.md`.
