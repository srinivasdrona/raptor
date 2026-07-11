# Slot 2 — BS2 policy contract: probes, decision record, config, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the source
> surfaces in slot 1 only**, before the doer. The doer implements to pass (may add, not weaken). Facts are
> derived from the pinned BIAS source (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`), the census, and
> **primary ClinGen authority**; each claim cites its source. Census incidence characterizes the firing —
> it never licenses inclusion. **Benchmark labels are never the ground for this decision.**

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 What BIAS BS2 actually is
`benign_classifiers.py::get_bs2` (L116–176) fires on a **population-frequency / control-count** test
(homozygous / hemizygous / control allele counts vs a `constants.py` threshold), sourced from
gnomAD/1000G control cohorts + disease/inheritance context (`configs/eval/bias_lineage.yaml` BS2 record:
`label_independent_population`; slot-2 lineage §0.6). Two facts follow and must be proven from source:
- **(a) Label-independent source** — the signal is the population control counts, **not** the ClinVar
  label. This is *not* R-A2 circularity.
- **(b) Penetrance/age/mosaicism are NOT modeled** — `get_bs2` does not phenotype the "healthy" carrier,
  exclude reduced penetrance, or exclude mosaicism. It is a frequency test, nothing more.

### 0.2 What ACMG/ClinGen require for BS2 in TSC (retrieve + cite primary sources)
BS2 (ACMG/AMP 2015) applies only for a healthy adult *well past the expected age of onset*, *thoroughly
phenotyped*, with *high penetrance* and *germline (non-mosaic)* status established. For TSC specifically:
- **Penetrance** — classic pathogenic TSC1/TSC2 variants are highly penetrant; BS2's argument fails under
  reduced penetrance.
- **Age of onset** — TSC presents at variable ages; BS2 needs adults past onset with subtle features
  excluded.
- **Mosaicism** — common in TSC (esp. TSC2); an apparently-healthy carrier may be a subclinical mosaic ⇒
  BS2 must not be applied when mosaicism cannot be excluded.

The doer **retrieves the primary ClinGen TSC VCEP BS2 specification and the SVI BS2 recommendation**
(`clinicalgenome.org` / the VCEP publication) and records the exact requirements verbatim-cited — **no
fabricated thresholds**.

### 0.3 The gap that decides the disposition
`get_bs2`'s population test (0.1b) **cannot** satisfy the VCEP's phenotyping / penetrance / non-mosaic
requirements (0.2). Therefore, absent a named authority + Oracle sign-off (GP-3 is open), the *automatable*
BS2 signal is **insufficient** to license scoring — the expected verdict is **preserve `deferred`**.

---

## 1. Empirical probes (run BEFORE the disposition is recorded)

### 1.1 Probe 1 — the 34 firings, characterized
`scripts/probe_bs2_firings.py <bias_output.tsv> --output <report.json>` (or a test-owned analyzer over the
census output): per-firing `{variant_id, gene, consequence, bs2_signal (homozygous/hemizygous/control-AC
as parsed from the rationale), co_fired_criteria}`, plus rollups: gene distribution, count co-firing any
pathogenic-family criterion (BS2+PVS1/PS/PM/PP conflicts flagged). Derived from the census/output; the
total must reconcile to **34** (`criterion_firing.BS2`). Persisted.

### 1.2 Probe 2 — `get_bs2` source-condition read
A documented extraction (cited to L116–176 + `constants.py`) of the exact firing condition, threshold, and
control source, establishing 0.1(a) label-independence and 0.1(b) no penetrance/age/mosaicism modeling.

### 1.3 Probe 3 — primary authority review
A retrieved-and-cited summary of the ClinGen TSC VCEP BS2 specification + SVI BS2 recommendation, with an
**explicit sufficiency verdict**: is the automatable BIAS BS2 signal sufficient to meet the specification
for TSC? Recorded in the decision memo (§2.2) with primary citations.

---

## 2. The disposition decision (recorded; deferred is preserved unless authority is sufficient)

### 2.1 Config — `configs/eval/bias_lineage.yaml` BS2 record (annotation only; disposition unchanged)
The BS2 record's `validation_disposition` and `production_disposition` **stay `deferred`** with
`decision_dependency: bs2-policy`. This task adds a **required, non-empty** `decision_rationale` to the BS2
record (new field, schema-validated) that names the penetrance/age/mosaicism gap + the missing authority,
citing Probes 2–3. **No promotion** to `allowed`/`included`/`automatable`. The lineage `load_lineage_policy`
invariant is *strengthened*: a `deferred` record must carry **both** a non-empty `decision_dependency`
**and** a non-empty `decision_rationale`, else raise `LineagePolicyError` (fail-closed — a deferral may
never silently self-resolve or sit rationale-less).

### 2.2 Decision memo — `docs/reference/bs2-tsc-penetrance-mosaicism-review.md`
A cited evidence memo (in the style of `docs/reference/aavc-prior-art-audit-2026-07.md`) capturing: the 34-
firing characterization (Probe 1), the `get_bs2` source read (Probe 2), the primary ClinGen TSC VCEP / SVI
BS2 authority + sufficiency verdict (Probe 3), and the recorded disposition (`deferred`, with the named
`bs2-policy` dependency + the penetrance/age/mosaicism rationale). If — and only if — the authority review
found the automatable signal sufficient, the memo records the **separate named approval + Oracle sign-off**
required before any promotion; this task does **not** fabricate that approval.

### 2.3 What this task does NOT do
- It does **not** score, include, automate, or clinically classify any of the 34 BS2 variants.
- It does **not** flip BS2 to `allowed`/`approved` on the basis of its label-independent lineage class
  (source-independence ≠ policy approval).

---

## 3. Acceptance criteria (AC-B1…AC-B6)

- **AC-B1** (firing characterization): the Probe 1 report reconciles to 34 BS2 firings, records the
  population signal + gene distribution + any pathogenic co-fires; derived, not invented.
- **AC-B2** (source read): `get_bs2`'s firing condition + control source are documented with anchors
  (L116–176 + `constants.py`), proving label-independence AND that penetrance/age/mosaicism are unmodeled.
- **AC-B3** (authority): the ClinGen TSC VCEP / SVI BS2 authority is recorded with **primary citations** and
  an explicit sufficiency verdict (no fabricated thresholds).
- **AC-B4** (deferred preserved / no invented approval): with authority insufficient (expected), BS2
  stays `deferred`, keeps `decision_dependency: bs2-policy`, and carries a **non-empty `decision_rationale`**
  naming penetrance/age/mosaicism + the authority gap; the strengthened `load_lineage_policy` raises on a
  `deferred` record missing rationale or dependency. **No** `allowed`/`included`/`automatable` promotion.
- **AC-B5** (invariants preserved): BS2 is not in `included_criteria`/`automatable_criteria`; scoring it
  still trips `lineage_registry.deferred_included_without_decision`; the lineage can-fire/registry/audit
  behavior is otherwise unchanged; **no clinical classification** of the 34 variants.
- **AC-B6** (no label grounding / no fixture patch): the decision is grounded in domain authority + firing
  characterization, **never** in benchmark/ClinVar labels; no test fixture is patched.

---

## 4. DoR task specs (sequence)

1. `bs2-firing-probe` — `scripts/probe_bs2_firings.py` + its test; reconcile to 34.
2. `bs2-authority-review` — retrieve + cite ClinGen TSC VCEP / SVI BS2; write the sufficiency verdict.
3. `bs2-disposition` — add the required `decision_rationale` to the BS2 lineage record; strengthen
   `load_lineage_policy` (deferred ⇒ rationale + dependency); write `docs/reference/bs2-tsc-penetrance-
   mosaicism-review.md`.

## 5. Dependencies

- **Upstream:** none — decision B is independent (parallel with A and C).
- **Downstream:** decision D **excludes BS2** from the candidate-direction criteria set, consistent with
  this preserved-deferred decision. D must reflect BS2's `deferred` status.

## 6. Authorized outputs

- `configs/eval/bias_lineage.yaml` (BS2 record: add `decision_rationale`; disposition unchanged).
- `src/raptor/eval/lineage_policy.py` (strengthen the deferred-record invariant only).
- `scripts/probe_bs2_firings.py`; the persisted BS2 firing report under `data/census/`.
- `docs/reference/bs2-tsc-penetrance-mosaicism-review.md`.
- `tests/eval/test_bs2_policy.py`, `tests/eval/test_bs2_firing_probe.py`.

No other production/config/test file is edited. No test fixture is patched. BS2's disposition is not
flipped away from `deferred`.
