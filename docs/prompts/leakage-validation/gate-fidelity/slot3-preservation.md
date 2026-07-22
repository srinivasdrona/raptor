# Slot 3 — Preservation & inversion guard (Clopper-Pearson lower-bound / per-stratum gate fidelity)

## Preserve (semantics that must not change)

- **Pre-registered threshold VALUES are unchanged.** Missense precision 0.90 / recall 0.85, truncating
  0.95, `split.holdout_fraction: 0.7` (`configs/eval/tsc2.yaml`, committed blind — GP-3). The
  per-stratum schema migration is **value-preserving**; changing any *policy* number post-hoc breaks
  pre-registration (R-A2). **The sole sanctioned exception:** `min_count_per_class` 35 → **36** — a
  mathematical Clopper-Pearson power-floor **correction** (`scipy.stats.beta.ppf(0.025,35,1)=0.8999676 <
  0.90`; n=36→0.9026 ≥ 0.90), blind to held-out outcomes, **not** a performance tune. The 51 held-out
  missense-pathogenic still clears 36, so the gate stays powered.
- **Config schema migration is intentional, not additive.** `EvalConfig.oracle_thresholds` becomes the
  nested per-stratum map (flat form removed); the `float(v)`-per-key builder is replaced so no
  `float(dict)` path exists. Empty `{}` still → `UNVERIFIED`. Every flat-schema construction in the
  affected tests is migrated in the same change (slot 2 §2.3).
- **Gate honesty (PRD-06 FR6/AC5).** Empty gating-stratum threshold → `UNVERIFIED`; below min-count →
  `UNDERPOWERED`; neither ever `PASS`; `vus_authorized == (status == PASS)`. No invented target.
- **`run_eval` + harness label-blindness unchanged.** `src/raptor/eval/harness.py` and
  `tests/eval/test_ac6_ac7_ac9_harness.py::test_ac6_labels_never_reach_evidence_source` stay
  byte-unchanged; labels reach only the harness/benchmark, never a scorer/adapter path (FR8).
- **Additive dataclasses.** `Metrics`/`GateDecision`/`EvalReport` gain fields; existing fields, the point
  estimate, counts, `abstain`, `gating`, and `content_hash()` semantics are preserved; frozen dataclasses
  stay frozen.
- **Independent oracles only.** Clopper-Pearson via `scipy.stats.beta.ppf` + the **corrected**
  EVAL_RUBRIC §2 table (`n≥36 / 72 / 368`) + hand-computed confusion matrices + the synthetic
  `bp4pp3-predictor-policy` approved/unapproved/malformed fixtures — never the implementation's own output.

## Reconciliations the doer MAY make (not weakening)

- Replacing the **point-estimate comparison at the gate boundary** with the **lower-bound comparison**
  (this is the tracked fidelity fix, EVAL_RUBRIC §6 / PROGRAM §Active Decisions) while keeping the point
  estimate reported.
- Migrating the flat `oracle_thresholds {precision, recall}` to the per-stratum map **at equal values**
  (a breaking `config.py` schema change, not additive), and hard-gating truncating-pathogenic at 0.95
  where powered (§5) while keeping truncating-benign (n=1) report-only.
- Correcting `min_count_per_class` 35 → 36 and the EVAL_RUBRIC §2 anchors (`n≥36 / 72 / 368`) from
  `scipy.stats.beta.ppf` — a **mathematical correction**, not a threshold tune. Declaring `scipy` in
  `pyproject.toml` even though it is already importable locally.
- Requiring an approved `bp4pp3-predictor-policy` artifact at the terminal runner and emitting
  `BLOCKED_POLICY` (no metrics) when it is missing/unapproved/malformed — **without** relabeling BP4/PP3
  lineage in `bias_lineage.yaml` and **without** any default-allow/ban.

## Prohibited (weakening tests/config to match an implementation)

- Do **not** gate on the point estimate `k/n`; gate on the Clopper-Pearson **lower bound**.
- Do **not** change, lower, or "tune" a pre-registered *policy* threshold value, or fit a threshold from
  the held-out result (R-A2 / GP-3). Empty stays `UNVERIFIED`. (The `min_count` 35→36 correction is the
  sole sanctioned exception — a math fix, blind to outcomes.)
- Do **not** retain the wrong `n≥35` / `n≥367` anchors, or invent a tolerance/rounding to keep them —
  the boundary is exactly `LB(35,35) < 0.90 ≤ LB(36,36)` and `LB(367,367) < 0.99 ≤ LB(368,368)`.
- Do **not** relabel BP4/PP3 lineage in `bias_lineage.yaml` to force the block; their data lineage stays
  `allowed`. The block lives at the final gate via the `bp4pp3-predictor-policy` artifact, a separate
  policy axis.
- Do **not** default-allow a missing/silent predictor-policy artifact, or let `decide_gate` (the offline
  gate) emit a `PASS` that bypasses the terminal `--predictor-policy` requirement.
- Do **not** emit `PASS` for an `UNDERPOWERED` (below-min-count) stratum, or hard-gate the
  truncating-benign n=1 stratum.
- Do **not** approximate Clopper-Pearson with a normal/Wald interval or a self-rolled beta that the same
  code also tests — the oracle is `scipy.stats.beta.ppf` + the corrected rubric table.
- Do **not** let the **final masked rerun** emit `PASS`/`BLOCKED_POLICY`-bypass on the leaky
  full-resource TSV (sha256 `6e055fe1…`) or before an **approved** `bp4pp3-predictor-policy` artifact is
  supplied.
- Do **not** modify `run_eval`, the harness label-blindness test, or any frozen oracle.

## Highest-risk inversion failures

1. **Point-estimate green.** Gating on `k/n` so a tiny stratum with a lucky perfect point estimate passes
   though its lower bound is far below 0.90 — a statistically indefensible `PASS` (EVAL_RUBRIC §2).
   **Guard:** AC-G2 point-clears-but-LB-fails → not `PASS`.
2. **Threshold drift / fitting.** Lowering missense to 0.85 or reading the held-out result to set the bar
   — breaks pre-registration. **Guard:** AC-G5 schema rejects any deviation from the pinned value;
   AC-G4 empty → `UNVERIFIED`.
3. **Underpowered pass.** Emitting `PASS` on a stratum below n=**36** (the corrected floor), or
   hard-gating truncating-benign (n=1). **Guard:** AC-G3/G4 — `UNDERPOWERED`, report-only benign.
4. **Premature terminal PASS.** Running the final masked rerun on the unmasked TSV, or without an
   approved `bp4pp3-predictor-policy` artifact, and emitting `PASS`/VUS authorization. **Guard:** AC-G8/G9
   — masked-TSV requirement (Arm B lineage gate) **and** the required `--predictor-policy` approved
   artifact; missing/unapproved/malformed → fail-closed `BLOCKED_POLICY`, no metrics, until both land.
5. **Wald approximation.** Substituting a normal-approximation interval that over-covers at small n and
   silently loosens the gate. **Guard:** AC-G1 exact-Beta oracle + corrected boundary anchors.
6. **Retaining a wrong anchor / default-allow policy.** Keeping `n≥35`/`n≥367`, inventing a tolerance to
   pass the old floor, or treating a missing predictor-policy as allow. **Guard:** AC-G1 exact boundary;
   AC-G9 fail-closed loader (no default-allow).

No production code, tests, *policy* threshold values, `docs/PROGRAM.md`, `docs/STRATEGY.md`, `run_eval`,
the BP4/PP3 `bias_lineage.yaml` lineage records, or the frozen preservation set is modified by this
planning task. The narrow `docs/EVAL_RUBRIC.md` §2 power-table correction is authorized for integration.
The untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
