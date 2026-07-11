# Slot 3 — PRD-04 preservation and inversion (revised after rubber-duck NO-GO; r3 update)

## Preserve

- PRD-01 scorer evidence remains criterion-level and does not become an autonomous final classifier.
- PRD-06's Tavtigian combiner remains eval-only; it is **not** imported or restated as the production
  candidate-direction policy.
- Existing benchmark/label/held-out/oracle files remain **unreachable** from packet generation; the
  packet library assembles from an injected `PacketInput` and reads no label file.
- **KB append-only *discipline* is mirrored, not bypassed** — but reviewer/pattern-policy decisions are
  written to a **NEW variant-scoped append-only hash-chained decision log** (one log per canonical
  variant identity, spanning all packet versions, addressed deterministically from
  `sha256(canonical_variant_spdi)` — never a raw/unsafe identity), NOT to PRD-03
  `classification_versions`. `classification_versions` is reserved solely for a terminal, qualified,
  variant-level classification after all gates + sign-offs and is **not written by this first
  increment** (NO-GO item 1; r3-4).
- Criterion lineage is **machine-read** from `configs/eval/bias_lineage.yaml`; the packet never invents
  source lineage and **preserves both raw dispositions** (`validation_disposition`,
  `production_disposition`), deriving `packet_policy_disposition` via one exhaustive precedence in which
  **validation dominates** — `requires_heldout_mask` → masked regardless of production, unknown
  combination fails loud (NO-GO item 10; r3-1).
- No frozen scorer/eval/KB internal, existing PRD, strategy, program, decisions, or risk document is
  modified. New code lands only under `src/raptor/packet/**`, `configs/packet/**`, `tests/packet/**`,
  and later `scripts/build_tsc_calibration_batch.py`.

## Four failure modes

1. **Polished false authority.** An LLM narrative or "LP/LB" label visually becomes a clinical
   classification. Fix: template-constrained narrative plan (approved template ids + packet field paths
   only; deterministic renderer), candidate direction rendered only as a review direction (nullable
   with `null_reason`), and packet state + gate status unavoidable in every rendering. **First-pass
   reviewers are double-blinded: the `FIRST_PASS` view/projection strips BOTH the RAPTOR candidate
   direction (and signed points / policy id / census selection direction) AND the entire external
   comparator envelope; queue + reviewer delivery consume only `FIRST_PASS`; the candidate direction is
   unavoidable only in OPERATOR/RECONCILIATION rendering, and `RECONCILIATION` is gated by an
   append-only independent-decision-before-reveal event (r3-2).**
2. **Pattern sign-off laundering.** Approving BP4 Strong + PM2 Supporting silently classifies its
   1,222 members. Fix: pattern-policy approval is a distinct event that **never advances any member
   variant's state**; census patterns are selection metadata pinned to the census, never cutoffs;
   external reclassification remains per-variant. **A direction-null packet under an unapproved
   production policy is `POLICY_BLOCKED` (guard `production_policy_unapproved`): it is first-pass
   evidence-reviewable but cannot enter candidate-direction approval states, and
   `EXTERNAL_SUBMISSION_READY` requires an approved non-null production policy + non-null
   `candidate_direction` (r3-3).**
3. **Unreviewable evidence dump.** Reproducing BIAS TSV fields without lineage, exclusions,
   contradictions, missing evidence, and reviewer actions forces the expert to redo the analysis. Fix:
   machine-read lineage/disposition, visible exclusions/masked/deferred, preserved contradictions,
   grounded next-evidence action, and inspectable reviewer decisions.
4. **Provenance / decision-log laundering (new).** (a) Passing off BIAS-raw-row provenance as **primary
   evidence**, or (b) writing reviewer/pattern decisions into `classification_versions` so a review
   note masquerades as a terminal classification. Fix: **pinned** two-level provenance schemas (exactly
   one all-required `ScorerProvenance` resolving to a BIAS raw row vs zero-or-more `PrimaryEvidenceRef`
   with a resolved/unresolved predicate; a **BIAS row can never be constructed as a
   `PrimaryEvidenceRef`**; `primary_grounding` enum; `primary_required` = PS3/literature or
   config-flagged, unknown fails closed; missing primary blocks external readiness where policy
   requires) (r3-5); and a **variant-scoped** append-only hash-chained decision log (one per canonical
   variant identity across versions; deterministic path from `sha256(variant id)`; genesis `prev_hash`
   64 lowercase zeroes; `record_id` idempotency; OS exclusive lock + append/flush/fsync; replay detects
   fork/gap/hash-mismatch/cross-variant) that is separate from `classification_versions` (not written
   this increment) (r3-4). AAVC stays a reveal-only comparator, excluded from the evidence core and
   stripped from the `FIRST_PASS` view, never a truth label.
