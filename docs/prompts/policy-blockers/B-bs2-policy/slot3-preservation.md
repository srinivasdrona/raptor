# Slot 3 — Preservation & inversion guard (BS2 policy)

## Preserve (semantics that must not change)

- **BS2 stays `deferred`.** Its `validation_disposition` and `production_disposition` remain `deferred`
  with `decision_dependency: bs2-policy`. This task documents the rationale; it does **not** change the
  disposition.
- **Lineage class ≠ approval.** BS2's `label_independent_population` lineage means its *source* is not the
  ClinVar label — it does **not** grant `allowed`, inclusion, or automation. Source-independence is never
  laundered into policy approval (the central lineage-slot-3 guard, re-asserted here).
- **Deferred cannot self-resolve.** A `deferred` record must carry a non-empty `decision_dependency`
  **and** (newly required) a non-empty `decision_rationale`; `load_lineage_policy` fails closed otherwise.
- **Registry / audit invariants.** BS2 not in `included_criteria`/`automatable_criteria`; scoring it trips
  `lineage_registry.deferred_included_without_decision`; the can-fire set (19), registry, and audit are
  otherwise byte-unchanged. The frozen lineage preservation set (oracle, `bias_lineage.yaml` structure) is
  respected — only the BS2 `decision_rationale` field is added.
- **Labels boundary (R-A2/H1).** The decision is grounded in domain authority + the firing
  characterization, never in benchmark/ClinVar labels; no label/held-out file is opened to justify it.
- **Probes precede the record.** The 34-firing characterization, the `get_bs2` source read, and the
  primary-authority review are produced **before** the disposition is recorded.

## Reconciliations the doer MAY make (not weakening — documenting the owed decision)

- Adding the required `decision_rationale` field to the BS2 lineage record (disposition unchanged).
- Strengthening `load_lineage_policy` so any `deferred` record must carry both a `decision_dependency` and
  a `decision_rationale` (a fail-closed *tightening*, never a relaxation).
- Writing `docs/reference/bs2-tsc-penetrance-mosaicism-review.md` with primary ClinGen citations.

## Prohibited (inventing approval, or weakening the deferral)

- Do **not** promote BS2 to `allowed`/`approved`/`included`/`automatable`, or score it, on the basis of its
  label-independent lineage class or its 34 firings.
- Do **not** invent an approval, an Oracle sign-off, or a VCEP endorsement that does not exist — if
  authority is insufficient, **preserve the deferral**.
- Do **not** ground the decision in benchmark/ClinVar labels (how BS2 correlates with the labels it would be
  graded against is circular, R-A2).
- Do **not** treat "fired 34×" or a high control-count as evidence BS2 is safe to automate — incidence
  never licenses inclusion.
- Do **not** fabricate specific VCEP penetrance/age/mosaicism thresholds; cite the primary source or record
  the gap honestly.
- Do **not** clinically classify any of the 34 BS2 variants.
- Do **not** leave a `deferred` record without a named `decision_dependency` + `decision_rationale`.
- Do **not** patch a test fixture to make the deferral "pass".

## Highest-risk inversion failures

1. **Lineage-laundering — source-independence read as approval.** Setting BS2 to `allowed`, or silently
   moving it into `included`/`automatable`, because its population/control source is label-independent.
   BS2's source is label-independent but its *automatable evidence* cannot meet the VCEP's phenotyping /
   penetrance / non-mosaic bar. **Guard:** AC-B4/AC-B5 — disposition stays `deferred`; inclusion trips
   `deferred_included_without_decision`.
2. **Inventing approval.** Recording an `approved` disposition (or asserting a nonexistent Oracle/VCEP
   endorsement) to unblock scoring. **Guard:** AC-B3/AC-B4 — approval requires a cited authority +
   separate named sign-off this task does not fabricate; the expected branch preserves deferral.
3. **Label-grounded decision.** Justifying BS2 by its concordance with ClinVar/benchmark labels. **Guard:**
   AC-B6 — decision grounded in authority + firing characterization only; no label file reachable.
4. **Silent self-resolution.** A `deferred` BS2 record with no `decision_dependency` or no
   `decision_rationale` that quietly reads as "resolved". **Guard:** AC-B4 — strengthened
   `load_lineage_policy` fails closed; the deferral must name what it waits on and why.
5. **Mosaicism blind spot.** Approving BS2 without accounting for TSC's high mosaicism rate (a subclinical
   mosaic carrier looks "healthy" and would spuriously satisfy a population-count BS2). **Guard:**
   AC-B2/AC-B4 — the rationale must name the mosaicism (and penetrance/age) gap that BIAS's population test
   does not close.

No production code, tests, strategy, program, or risk documents are modified by this planning task. The
untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
