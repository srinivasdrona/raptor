# Leakage-safe validation — multi-task three-slot contract (planner overview)

> **Planner:** OPUS PLANNER (`claude-opus-4.8`). **Branch:** `track/leakage-validation-2026-07`.
> **Worktree:** `D:\AIProjects\raptor-worktrees\leakage-validation`. **Planning only** — no production
> code, no executable tests, no commit is authored by this task. This file + the three arm folders are
> the entire deliverable.

This contract closes the **terminal-join** gap on the path to the first authorized VUS run
(PROGRAM.md *Path to first VUS run*, row J): the raw label-free held-out VCF is already emitted and
scored on the x64 worker against the **full** comparator resources (2,577 parsed records), and both the
static-lineage gate and the full-output ClinVar-derivation audit are **complete** (ADR-0009;
`data/census/tsc_bias_lineage_audit_2026-07-10.json`). What remains is to make the held-out score
**leakage-safe** and the gate **rubric-faithful**, then run it. That work is decomposed into three
arms, each a self-contained tester/doer/checker three-slot contract:

| Arm | Folder | Hypothesis (one per task) |
|---|---|---|
| **A** | [`masked-resources/`](masked-resources/) | The five ClinVar-comparator resources (`PS1 PM5 PM1 PP2 BP1`) **and** the direct-copy ClinVar fallback inputs (`PS4 PP5 BP6`) can be regenerated with the 2,577 held-out identities **masked out of the upstream ClinVar source**, arm's-length, leaving the **full VUS comparator resources byte-untouched**. |
| **B** | [`canonical-adapter/`](canonical-adapter/) | A new arm's-length eval `EvidenceSource` joins the **masked** BIAS TSV to the 2,577 held-out identities **by canonical GRCh38 SPDI** (never a raw VCF-coordinate string), serving evidence only from fired per-criterion rationales, with the completed lineage gate enforced at preflight. |
| **C** | [`gate-fidelity/`](gate-fidelity/) | The PRD-06 gate can be made to compute the **95% Clopper-Pearson lower confidence bound** per stratum per direction (not the point estimate) and hard-gate a **per-stratum** `oracle_thresholds` map; the **final masked rerun + authoritative report** then runs on that gate. |

## Buildable now vs waits-for-policy (the load-bearing separation)

Each arm is split so its **mechanical infrastructure builds and is validated offline now** against
synthetic label-free fixtures with independent oracles, while its **data/policy-dependent final run** is
explicitly deferred. Conflating the two is the R-E1 (validated-vs-buildable) failure this contract exists
to prevent.

| Layer | What | Status / gate |
|---|---|---|
| **Build now (RAPTOR, offline)** | A: ClinVar-source masking tool + mask-conservation audit. B: `BiasEvidenceSource` canonical-SPDI adapter. C: Clopper-Pearson lower-bound (corrected anchors `n≥36/72/368`) + nested per-stratum gate code + `min_count_per_class: 36` + the `bp4pp3-predictor-policy` fail-closed loader and `BLOCKED_POLICY` wiring. | No blocker. Validated on synthetic fixtures (incl. approved/unapproved/malformed policy artifacts) + property invariants + independent oracles (`scipy.stats.beta.ppf`). |
| **Operator / arm's-length (x64 devbox, not code)** | Re-run BIAS's **own** `generate_*.py` on the masked ClinVar to rebuild the masked comparator resources (ADR-0007/0008); re-score the held-out VCF on the masked resources → **masked BIAS TSV**. | Gated on **A** delivering masked inputs + conservation proof. Produces the masked TSV **B** consumes. |
| **Final gate run (waits policy-track)** | C's terminal step `scripts/run_masked_holdout_eval.py` (requires `--predictor-policy PATH`): masked TSV → **B** adapter → `run_eval` → missense-stratified Clopper-Pearson lower-bound metrics → **gate decision + authoritative report + VUS authorization**. | **BLOCKED until (i) an approved `bp4pp3-predictor-policy` artifact is supplied by the policy track and (ii) the ADR-0009 masked resources exist.** A missing/unapproved/malformed artifact is fail-closed `BLOCKED_POLICY` (no metrics, `vus_authorized=false`); until both land the gate is honestly `BLOCKED_POLICY`/`UNVERIFIED`, never `PASS`. |

### The BP4/PP3 policy track (why the *final* gate waits, distinct from A's masking)

Arm A mechanically removes the **direct and transitive ClinVar-comparator** leakage of
`PS1/PM5/PM1/PP2/BP1` (comparator resources) and `PS4/PP5/BP6` (own-variant ClinVar copy). That closes
the *label-copy* circularity ADR-0009 named. It does **not** resolve a **separate, still-open policy
question**: **`BP4` and `PP3` fire from computational predictors / splice models** (ABSplice, phyloP,
REVEL/AlphaMissense-class scores — `bias-lineage` slot 2 §0.6, lineage class
`label_independent_reference_or_predictor`) that are themselves **trained on ClinVar-labelled data**.
Whether that constitutes admissible independent evidence or a subtler predictor-mediated circularity when
graded against a ClinVar-derived benchmark is an **Oracle policy decision** (`decision_dependency:
bp4pp3-predictor-policy`), not a mechanical mask. **This is an algorithm-correctness axis, not a data-
lineage relabel:** `BP4`/`PP3` keep their `allowed` data-lineage disposition in
`configs/eval/bias_lineage.yaml` (their inputs are label-independent); the predictor-circularity question
is enforced *only* at the final gate. `BP4` is also the **dominant** benign-direction line
(fired 1,929× on the held-out set; PROGRAM.md §Priorities notes BP4-Strong + PM2-Supporting cover 92% of
one census stratum), so its disposition materially moves the benign-direction metrics the gate reads.

**Concrete prerequisite interface (built now, ruling deferred).** The final runner requires a
`--predictor-policy PATH` argument — a `bp4pp3-predictor-policy`-schema artifact **supplied by the policy
track (Track C)** with fields `{schema, status, predictor_source_hash, correction_hash,
decision_reference}`, loaded fail-closed via `src/raptor/eval/predictor_policy.py`. Only `status ==
approved` on a well-formed artifact unblocks; missing/unapproved/malformed → `BLOCKED_POLICY`, no metrics.
The **loader + gate wiring build and are tested now** against synthetic approved/unapproved/malformed
artifacts (Arm C, AC-G8/G9); only the *real* approved artifact + masked TSV are deferred. This contract
does **not** make the ruling and encodes no default-allow or default-ban for `BP4`/`PP3`.

## Cross-arm invariants (every arm's slot 3 restates the ones it can violate)

1. **Mask conservation — held-out identities absent from every transitive resource.** No canonical
   GRCh38 SPDI in the frozen 2,577 held-out set may appear — directly *or transitively* (as a
   same-residue / same-domain / same-gene aggregate contributor, or as an own-variant ClinVar copy) — in
   any masked comparator resource, submitter-count table, or ClinVar annotation the masked re-score reads.
   Verified by an independent re-derivation, not by trusting the generator.
2. **No labels crossing the scorer (H1 / R-A2).** Masking, the adapter, and the gate read variant
   **identity** and BIAS **output** only; no `label`/`source`/`review_status`/`variant_class`/benchmark
   file is reachable from any scorer- or adapter-path module. The held-out JSONL is read for
   `row["variant_id"]` only (FR-A1). ClinVar *significance is masked as an identity-scoped record, never
   read as a training label by RAPTOR.
3. **No AGPL import/copy (ADR-0007).** RAPTOR never imports or copies `bias_2015` / BIAS preprocessing
   code. Comparator regeneration runs BIAS's **own** `generate_*.py` **arm's-length across the file
   boundary** on the x64 worker; RAPTOR contributes only masked **inputs** and an **independent**
   conservation audit that carries source citations (file·symbol·line), never BIAS source text.
4. **No silent row loss.** Every masking step is a bijection-checked, conservation-counted operation:
   masked ClinVar = full ClinVar **minus exactly** the held-out members present, and nothing else; the
   adapter join is exact-set over all 2,577 identities; the gate counts every called/abstained variant.
   Any collision, over-removal, under-removal, or unmatched row is **fatal**, never dropped.
5. **Full VUS resources untouched.** Masked resources are written to a **separate** namespace; the full
   comparator resources (and the production/VUS scoring path that points at them) are **byte-identical**
   before and after. Proven by a frozen-hash check on the full-resource paths.
6. **Determinism + provenance (R-A11 / GP-9).** Every RAPTOR output (masked inputs, masking manifest,
   adapter evidence, gate report) is a pure function of pinned inputs and carries a content hash + the
   source-hash pins below; run metadata is excluded from the hash.

## Source-hash registry (pinned; every arm cites the subset it depends on)

| Pin | Value | Role |
|---|---|---|
| Arm's-length BIAS source | commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f` · v`3.0.0` | can-fire lineage, generator citations, marker vocab pin |
| RAPTOR repo HEAD (planning base) | `e52e855` | branch `track/leakage-validation-2026-07` |
| Lineage policy | `configs/eval/bias_lineage.yaml` · sha256 `743a0248c2415010b22c5e1c7f1a35924c8b4b26521f58be09e677ddbb58aeeb` | can-fire set, `requires_heldout_mask = [PS1,PM5,PM1,PP2,BP1]`, `transitive_suspect` |
| Completed lineage/audit record | `data/census/tsc_bias_lineage_audit_2026-07-10.json` · sha256 `cef6b2dc749c9d0a1f3b227c5002a7fdc7704a331c1c64bbae0b67bc2331604e` | audit provenance; held-out firing counts |
| Held-out **full-resource** BIAS output (the leaky one A/B/C must NOT use for the final gate) | sha256 `6e055fe1a4f7d18e428c62739e3b60fa55362f72aa6322429d2f4ff93076dd9c` · 2,577 rows | the unmasked TSV the masked rerun replaces |
| VUS full-resource BIAS output | sha256 `0a55cab470d3de93f06cd87ba30957fd1674c0ae2098ec86350f5aaac1a1162e` · 6,618 rows | full VUS path that must stay untouched (Arm A invariant 5) |
| Benchmark snapshot | `clinvar_2026-07-07` · holdout `0.7` → **2,577 held-out** / 1,104 dev reserve / 3,681 scoreable | frozen identity set masked + joined + gated |
| Held-out allele profile (planner-verified; PRD-08 §12) | 2,577 = 707 `NC_000009.12` + 1,870 `NC_000016.10`; 2,416 SNV + 4 MNV + 135 delins + 3 ins + 19 del | conservation oracle for A/B |
| Held-out ClinVar direct-copy incidence (masked re-score must zero these on held-out ids) | `PS4 288`, `PP5 353`, `BP6 2174` (full-resource run) | Arm A own-variant mask target |
| Requires-heldout-mask firing (full-resource held-out) | `PS1 116`, `PM5 13`, `PM1 0`, `PP2 0`, `BP1 0` | zero incidence does **not** revise static lineage — all five masked |

## Sequencing & dependency graph

```
A (masking tool + conservation audit)  ──►  operator: BIAS generators on masked ClinVar  ──►  masked BIAS TSV
                                                                                                    │
C-code (Clopper-Pearson + per-stratum gate)  ── builds in parallel, no dep ──┐                      │
                                                                             ▼                      ▼
B (canonical-SPDI adapter over masked TSV) ─────────────────────────────► C-final: masked TSV → B → run_eval → gate report
                                                                             ▲
       waits: ADR-0009 masked resources (A+operator) ∧ Track C approved bp4pp3-predictor-policy artifact (--predictor-policy)
```

- **Build order (offline, no cross-dependency):** A-code, B-code, C-code may be authored in parallel;
  each has its own tester → doer → checker loop.
- **Runtime order (deferred):** A-code → operator masked rebuild → masked re-score → B (masked TSV) →
  C-final report. C-final's runner additionally **requires** an approved `bp4pp3-predictor-policy`
  artifact (else fail-closed `BLOCKED_POLICY`).

## Dependencies & blockers (rollup)

- **Ready to build now (no blocker):** A-code, B-code, C-code — all offline against synthetic fixtures
  (C includes the `bp4pp3-predictor-policy` loader + `BLOCKED_POLICY` wiring, tested against synthetic
  approved/unapproved/malformed artifacts).
- **Blocks the masked re-score:** Arm A masked inputs + conservation proof; operator x64 devbox time
  (arm's-length BIAS generator rerun — ADR-0007/0008).
- **Blocks the final gate `PASS` / authoritative report (C-final):** (i) ADR-0009 masked comparator
  resources existing (A + operator); (ii) a **Track-C-supplied approved `bp4pp3-predictor-policy`
  artifact** at `--predictor-policy` (the Oracle predictor-circularity ruling; missing/unapproved/
  malformed → `BLOCKED_POLICY`); (iii) the completed ADR-0009 Oracle ruling on the masked
  `PS1/PM5/PM1/PP2/BP1` firing counts. None of these is decided by this planning task.
- **Do not edit:** `docs/PROGRAM.md`, `docs/STRATEGY.md` (shared program/strategy — read-only here);
  the BP4/PP3 lineage records in `configs/eval/bias_lineage.yaml` (not relabeled — the block is a
  separate final-gate axis); the §frozen preservation sets each arm names; the untracked
  `docs/prd/PRD-04-candidate-evidence-packet.md`. The narrow `docs/EVAL_RUBRIC.md` §2 power-table
  correction (`n≥36/72/368`, `min_count 36`) is authorized for integration (Arm C).

## Manifests

Three tester/doer/checker manifests, each with **≤4 reference files**:
[`masked-resources/manifest.json`](masked-resources/manifest.json) ·
[`canonical-adapter/manifest.json`](canonical-adapter/manifest.json) ·
[`gate-fidelity/manifest.json`](gate-fidelity/manifest.json). Each manifest pins its slot sha256s at the
Ready preflight (OPERATING_MODEL §3.1); the values are filled in this deliverable.

## NO-GO closure note (rubber-duck review, 2026-07-12)

This revision closes the four rubber-duck NO-GO findings **without** implementing code, editing shared
`PROGRAM.md`/`STRATEGY.md`, or relabeling BP4/PP3 lineage. All changes are confined to Arm C
(`gate-fidelity/`) planning artifacts + this README; Arms A and B are byte-unchanged (three-arm parallel
build + final join preserved).

1. **BP4/PP3 predictor-circularity is a policy axis, not a lineage relabel.** `bias_lineage.yaml` is
   **not** touched — BP4/PP3 keep `allowed` data lineage (their inputs are label-independent). Instead a
   concrete final-gate prerequisite is added: `scripts/run_masked_holdout_eval.py --predictor-policy PATH`
   consumes a Track-C-supplied `bp4pp3-predictor-policy`-schema artifact (`{schema, status,
   predictor_source_hash, correction_hash, decision_reference}`) via a fail-closed
   `src/raptor/eval/predictor_policy.py` loader. Missing/unapproved/malformed → `BLOCKED_POLICY`, no
   metrics, `vus_authorized=false`. Loader + wiring **build/test now** against synthetic
   approved/unapproved/malformed artifacts; the real run waits Track C (Arm C slot 2 AC-G8/G9).
2. **Nested-schema migration is fully authorized + specified.** Arm C authorized outputs now include
   `src/raptor/eval/config.py` (breaking `EvalConfig.oracle_thresholds` flat → nested per-stratum
   migration; the `float(v)`-per-key builder is replaced so **no `float(dict)` failure** exists) and
   `pyproject.toml` (declare `scipy>=1.10` regardless — verified importable 1.18.0). Backward
   incompatibility, migration, and every affected test surface (`conftest.py`, `test_ac5_gate.py`,
   `test_eval_fixes*.py`, `tsc2.yaml`, new gate/policy tests) are enumerated in slot 2 §2. A narrow
   `docs/EVAL_RUBRIC.md` §2 correction is authorized for integration (not shared PROGRAM).
3. **Clopper-Pearson exact anchors corrected from `scipy.stats.beta.ppf`.** Zero-error 95%-CI lower
   bound: **0.90 needs n≥36** (`LB(35,35)=0.8999676<0.90`), **0.95 needs n≥72**, **0.99 needs n≥368**
   (`LB(367,367)=0.9899989<0.99`). `min_count_per_class` floor corrected **35 → 36** with an explicit
   **non-performance-tuning** rationale (a mathematical power-floor fix, blind to held-out outcomes; 51
   held-out missense-pathogenic still clears 36). Slots, manifest, and test anchors updated; no invented
   tolerance retains the wrong values.
4. **Three-arm parallel build + final join preserved; hashes/manifests/README recalculated.** Only Arm C
   slots + this README changed; the `gate-fidelity/manifest.json` slot sha256s are recomputed below and
   the A/B manifest hashes re-verified unchanged.
