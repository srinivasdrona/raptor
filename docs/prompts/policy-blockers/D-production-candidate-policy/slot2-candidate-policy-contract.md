# Slot 2 — Production candidate-direction policy contract: probes, config, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the source
> surfaces in slot 1 only**, before the doer. The doer implements to pass (may add, not weaken). D **joins
> A+B+C**; it pins **from** their outputs and must not contradict them. Census incidence is illustrative
> only — it never sets the points or approves anything. **Depends on A ∧ B ∧ C.**

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 The policy stays unapproved ⇒ null for every variant
`configs/packet/candidate_direction.yaml` today: `approval_status: unapproved`, empty
`criterion_strength_points`, null thresholds. `compute_candidate_direction` (`packet/direction.py`) returns
`direction=None`, `null_reason="production_policy_unapproved"` whenever `approval_status != "approved"`;
the packet build maps that to `ReviewState.POLICY_BLOCKED`. **This task pins the policy contents but keeps
`approval_status: unapproved`** — so no candidate call is ever emitted. Pinning is safe *because* the gate
is off.

### 0.2 The join inputs (from A, B, C)
- **A** → PP3/BP4 point contributions use `eval.predictor_aggregation.recompute_strength`'s **corrected**
  strength, never BIAS's emitted strength.
- **B** → **BS2 excluded** from `criterion_strength_points`, consistent with its `deferred` disposition.
- **C** → gene/transcript scope = TSC1/TSC2 MANE `.5` with SPDI reconciliation; NTHL1 and any
  base-mismatch/out-of-scope record excluded upstream (never reaches this policy).

### 0.3 Separation from eval
`packet.direction` imports **no** `raptor.eval.combine` and does **not** reuse the eval Tavtigian cutoffs.
The candidate points + `candidate_lp_min`/`candidate_lb_max` are an **independently-pinned** set (PRD-04
slot-3 fm6). The strict **8-key** `candidate_direction.yaml` schema is preserved.

---

## 1. Empirical probes (run BEFORE pinning the policy)

### 1.1 Probe 1 — dependency-readiness
Confirm A/B/C are landed and their outputs are D's inputs: A's `predictor_aggregation` corrected strengths
exist; B's BS2 record is `deferred` with a rationale; C's transcript reconciliation + NTHL1 exclusion are
in place. A test asserts the three prerequisite manifests/surfaces are present; D's pinned values reference
them.

### 1.2 Probe 2 — eval/production criteria parity
Enumerate the candidate criteria set **from config**:
`candidate_set = automatable_criteria (eval, post-lineage-correction) − {BS2 (deferred, B)} − FORBIDDEN_CRITERIA
− {unruled transitive requires_heldout_mask}`. Emit the derived set + the excluded set with reasons; assert
`criterion_strength_points` keys == `candidate_set` (no BS2, no forbidden, no out-of-scope). Derived, never
a magic list.

### 1.3 Probe 3 — separation-from-eval + unapproved-null
Verify (static import check + behavior) that `packet.direction` imports no `eval.combine`, uses its own
pinned thresholds, and returns null/`POLICY_BLOCKED` for every variant while `approval_status: unapproved`.

---

## 2. Config — `configs/packet/candidate_direction.yaml` (populated, strict 8-key, stays unapproved)

```yaml
policy_id: "tsc-candidate-direction-v1"
version: "1"                        # bumped from "0"; still unapproved
approval_status: "unapproved"       # UNCHANGED — no approval invented
approved_by: null
approval_ref: null
criterion_strength_points:          # over candidate_set (Probe 2); PP3/BP4 from A's corrected strengths;
  # ...pinned point map, BS2 ABSENT, FORBIDDEN absent, unruled-transitive absent...
candidate_lp_min: null              # requires future Oracle approval; no cutoff invented
candidate_lb_max: null              # requires future Oracle approval; no cutoff invented
```

- No 9th key (schema rejects). Gene/transcript scope is enforced upstream by C — referenced in a
  provenance note/commit message, not by adding schema keys.
- `criterion_strength_points` keys are exactly the Probe-2 `candidate_set`; PP3/BP4 strength→point rows
  reflect A's corrected aggregation (a variant's PP3/BP4 strength is the corrected one before it is scored).
- `candidate_lp_min`/`candidate_lb_max` remain **null** while unapproved. A future approved policy must
  derive and pin them independently from the eval Tavtigian cutoffs; this task does not invent them.
- Loader invariant refinement: `unapproved` may carry a populated `criterion_strength_points` map for
  review, but requires null cutoffs/approver fields and still returns null direction. `approved` requires
  non-empty points, integer cutoffs, and non-null approver/reference.

The doer MAY add a validator (in `packet/config.py`) asserting: keys ⊆ `VALID_CRITERIA` ∖ `FORBIDDEN_CRITERIA`;
BS2 ∉ keys; `approval_status ∈ {unapproved, approved}` with `approved` requiring non-null `approved_by` +
`approval_ref` (so approval can never be a silent empty flip).

---

## 3. Acceptance criteria (AC-D1…AC-D7)

- **AC-D1** (dependency-readiness): D's contract names A/B/C as prerequisites; the pinned points/scope
  reflect their outputs; the prerequisite surfaces are present (Probe 1).
- **AC-D2** (criteria parity): `criterion_strength_points` keys == the derived `candidate_set` (eval
  `automatable_criteria` − BS2 − FORBIDDEN − unruled transitive); enumerated from config, not invented;
  the excluded set + reasons are recorded (Probe 2).
- **AC-D3** (corrected strengths): PP3/BP4 point contributions use A's **corrected** aggregation strength,
  not BIAS's emitted buggy strength.
- **AC-D4** (scope): the policy applies only to TSC1/TSC2 MANE `.5` records reconciled via SPDI (C); NTHL1
  and base-mismatch/out-of-scope records are excluded upstream and never scored here.
- **AC-D5** (unapproved-null / non-authoritative): `approval_status` stays `unapproved`;
  `compute_candidate_direction` returns `null` / `production_policy_unapproved` / `POLICY_BLOCKED` for every
  variant; no externally usable candidate worklist is released.
- **AC-D6** (separation-from-eval + strict schema): `packet.direction` imports no `eval.combine`; candidate
  points/thresholds are a separate pinned set (not the eval Tavtigian cutoffs); the strict 8-key schema is
  preserved (no extra keys); `approved` requires non-null `approved_by` + `approval_ref`.
- **AC-D7** (no classification / no fixture patch / provenance): **no clinical classification** is produced;
  no test fixture is patched; provenance links to A/B/C are recorded.

---

## 4. DoR task specs (sequence — after A ∧ B ∧ C)

1. `candidate-parity-probe` — Probe 2 derivation of `candidate_set` + tests (RED first).
2. `candidate-policy-pin` — populate `candidate_direction.yaml` (stays unapproved) + `packet/config.py`
   validator (keys, BS2 absent, approval-requires-approver).
3. `candidate-separation-guard` — the import + unapproved-null tests (Probe 1/3), provenance to A/B/C.

## 5. Dependencies

- **Upstream (hard):** decision A (corrected strengths), decision B (BS2 deferred), decision C (transcript/
  SPDI scope). **D must not be pinned before all three land.**
- **Downstream:** the PRD-04 packet build reads this policy; external worklist release remains gated on the
  PRD-06 held-out gate PASS + the ADR-0009 policy correction + per-variant expert sign-off (out of scope
  here).

## 6. Authorized outputs

- `configs/packet/candidate_direction.yaml` (populated, stays `unapproved`).
- `src/raptor/packet/config.py` (validator hardening only — keys/BS2/approval-requires-approver).
- `tests/packet/test_candidate_direction_policy.py`, `tests/packet/test_candidate_separation_from_eval.py`.

No other production/config/test file is edited. `approval_status` is not flipped to `approved`.
`packet.direction` never imports `eval.combine`. No test fixture is patched.
