# Slot 3 — Preservation & inversion guard (production candidate-direction policy)

## Preserve (semantics that must not change)

- **Unapproved-null invariant.** `approval_status` stays `unapproved`; `compute_candidate_direction`
  returns `direction=None`, `null_reason="production_policy_unapproved"`, `ReviewState.POLICY_BLOCKED` for
  every variant. Pinning the policy contents never emits a candidate call (PRD-04 slot-3 failure mode 6).
- **Separation from eval.** `packet.direction` imports **no** `raptor.eval.combine` and never reuses the
  eval Tavtigian cutoffs as production thresholds. The candidate points/thresholds are an independently
  pinned set. The eval combiner never becomes the production oracle.
- **Strict 8-key schema.** `candidate_direction.yaml` keeps exactly its eight keys; no extra keys are added
  (gene/transcript scope stays enforced upstream by C).
- **Non-authoritative / gated release.** No externally usable candidate worklist is released; release
  remains gated on the PRD-06 held-out PASS + ADR-0009 correction + per-variant expert sign-off.
- **Immutability + provenance.** The packet build's immutable hash domains, first-pass double-blinding, and
  variant-scoped append-only decision log are untouched; provenance to A/B/C is recorded.
- **Consistency with A/B/C.** D pins **from** the three decisions; it does not re-derive or contradict the
  corrected strengths (A), the BS2 deferral (B), or the SPDI scope (C).
- **Probes precede the pin.** Dependency-readiness, eval/production parity, and separation/unapproved-null
  are verified **before** the policy is pinned.

## Reconciliations the doer MAY make (not weakening — pinning the joined policy)

- Populating `criterion_strength_points` over the derived `candidate_set` and pinning
  `candidate_lp_min`/`candidate_lb_max`, while keeping `approval_status: unapproved`.
- Bumping `version` ("0" → "1") to record the pinned-but-unapproved increment.
- Hardening `packet/config.py`'s validator (keys ⊆ VALID ∖ FORBIDDEN; BS2 absent; `approved` requires
  non-null `approved_by` + `approval_ref`) — a fail-closed *tightening*.

## Prohibited (approval smuggling, eval blurring, contamination)

- Do **not** set `approval_status: approved`, populate `approved_by`/`approval_ref`, or make a null
  direction resolve to a real call — approval requires expert sign-off this task does not fabricate.
- Do **not** import `raptor.eval.combine` into `packet.direction`, or reuse the eval Tavtigian cutoffs as
  the candidate thresholds — the eval combiner must never become the production oracle.
- Do **not** use BIAS's emitted (buggy) PP3/BP4 strength — use A's corrected strength.
- Do **not** include deferred **BS2** (B) or out-of-scope **NTHL1** / base-mismatch records (C) in the
  scored candidate set.
- Do **not** add a 9th schema key, or a wildcard/default in `criterion_strength_points`.
- Do **not** release an externally usable worklist, or describe the pinned policy as authoritative /
  a classification.
- Do **not** produce any clinical classification, or patch a test fixture to make the policy "resolve".

## Highest-risk inversion failures

1. **Approval smuggling.** Flipping `approval_status` to `approved` (or making null-direction resolve to a
   real LP/LB call) without expert sign-off — the entire point is that the joined policy stays unapproved
   and non-authoritative. **Guard:** AC-D5/AC-D6 — unapproved-null; `approved` requires non-null approver +
   ref.
2. **Eval-combiner-as-production-oracle.** Reusing `eval.combine`/the eval Tavtigian cutoffs as the
   production policy, blurring the eval/production boundary. **Guard:** AC-D6 — no `eval.combine` import;
   independently pinned thresholds; strict 8-key schema.
3. **Pinning buggy strengths.** Using BIAS's emitted PP3/BP4 strength instead of A's corrected values, so
   the joined policy carries the defect A exists to fix. **Guard:** AC-D3 — corrected strengths.
4. **Contamination by deferred / out-of-scope records.** Pulling deferred BS2 (B) or NTHL1/base-mismatch
   records (C) into the scored candidate set. **Guard:** AC-D2/AC-D4 — BS2 + FORBIDDEN + out-of-scope
   excluded; keys == derived `candidate_set`.
5. **Premature worklist release.** Treating the pinned-but-unapproved policy as authorizing an external VUS
   worklist. **Guard:** AC-D5 — non-authoritative; release gated on the PRD-06 PASS + sign-off.

No production code, tests, strategy, program, or risk documents are modified by this planning task. The
untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
