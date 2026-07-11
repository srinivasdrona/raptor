# Slot 1 — Unapproved, non-authoritative production candidate-direction policy (joins A+B+C) · planner/role prefix

You are the **planner** for the terminal vertical RAPTOR policy blocker: **pinning the production
candidate-direction policy** (PROGRAM.md item 8) that **joins decisions A, B, and C** into one coherent,
config-pinned policy — while keeping it **`unapproved`, non-authoritative, and strictly separate from the
eval combiner.** You write the build/test contract (slot 2) and the preservation/inversion guard (slot 3).
You do **not** write production code or executable tests. **This task depends on A, B, and C.**

Emit an `INTENT` block before editing that names: the **user** (the PRD-04 packet build + internal review
queue that reads the candidate direction), the **artifact** (a populated-but-`unapproved`
`candidate_direction.yaml` consistent with eval, using A's corrected strengths, B's deferred BS2, and C's
transcript/gene scope), the **validator** (dependency-readiness, eval/production criteria parity, the
corrected-strength check, the scope check, and the unapproved-null + separation-from-eval invariants), the
**falsifier** (any flip to `approved`; any resolution to a real call; any reuse of `eval.combine`/the eval
Tavtigian cutoffs as the production oracle; any inclusion of deferred BS2 or out-of-scope NTHL1; any release
of an externally usable worklist), and **why** a generic product cannot supply this (the policy is the
TSC-specific join of *this* build's defect correction, deferral, and scope — and it stays gated on the
PRD-06 held-out PASS + expert sign-off).

## What "join A+B+C, unapproved" means

The production candidate-direction policy (`configs/packet/candidate_direction.yaml`, consumed by
`src/raptor/packet/direction.py::compute_candidate_direction`) is pinned to reflect:

- **A** — the PP3/BP4 point contributions use the **corrected** aggregation strengths
  (`eval.predictor_aggregation.recompute_strength`), never BIAS's emitted buggy strength.
- **B** — **BS2 is excluded** from the candidate criteria set, consistent with its preserved `deferred`
  disposition (`decision_dependency: bs2-policy`).
- **C** — the gene/transcript scope is **TSC1/TSC2 MANE `.5` with SPDI reconciliation**; NTHL1 and any
  out-of-scope/base-mismatch record is excluded (routed to manual queue upstream).

Crucially, the policy stays **`approval_status: unapproved`**: `compute_candidate_direction` therefore
returns `direction=null`, `null_reason="production_policy_unapproved"`, and `ReviewState.POLICY_BLOCKED`
for **every** variant. Pinning the *contents* is safe and non-authoritative precisely because the approval
gate is off — no candidate call is ever emitted, no externally usable worklist is released.

## Separation from eval (non-negotiable)

- `packet.direction` **imports no `raptor.eval.combine`** and does **not** reuse the eval Tavtigian cutoffs
  as production thresholds. The candidate point map + `candidate_lp_min`/`candidate_lb_max` are a
  **separate, independently-pinned** set (PRD-04 slot-3 failure mode 6: the eval combiner must never become
  the production oracle).
- The `candidate_direction.yaml` **strict 8-key schema** is preserved (`policy_id`, `version`,
  `approval_status`, `approved_by`, `approval_ref`, `criterion_strength_points`, `candidate_lp_min`,
  `candidate_lb_max`) — no extra keys. Gene/transcript scope is enforced **upstream** by C (ingest/scorer),
  referenced here via provenance only, not by adding schema keys.

## Evidence hierarchy (highest → lowest authority)

1. **Decisions A / B / C outputs** — the corrected-strength wrapper + report (A), the BS2 deferred decision
   record (B), the transcript/SPDI scope reconciliation (C). D pins **from** these; it must not re-derive
   or contradict them.
2. **Eval parity surfaces** — `src/raptor/eval/config.py` (`VALID_CRITERIA`, `FORBIDDEN_CRITERIA`),
   `configs/eval/{tsc2,bias_lineage}.yaml` (`automatable_criteria`, dispositions). The candidate criteria
   set must be consistent with eval (`included == automatable`, the lineage-registry invariant).
3. **Packet surfaces** — `configs/packet/candidate_direction.yaml`, `src/raptor/packet/{direction,config,
   model}.py`, `src/raptor/packet/state.py` (`ReviewState.POLICY_BLOCKED`). The unapproved-null + immutable
   contract lives here.
4. **Dynamic incidence** — the census `candidate_pattern_compression` (LP: 238 across 20 patterns; LB: 1333
   with `BP4 Strong + PM2 Supporting` at 1222). **Illustrative only; it never sets the policy points or
   approves anything.**

Lower tiers never override higher ones.

## Required source inspection (no-assumption rule)

- `docs/prompts/policy-blockers/{A-bp4-pp3-aggregation,B-bs2-policy,C-transcript-nthl1}/` (the three
  contracts + their manifests — the prerequisites this task joins).
- `configs/packet/candidate_direction.yaml` (current: `unapproved`, empty points, null thresholds);
  `src/raptor/packet/direction.py` (`compute_candidate_direction`, `_UNAPPROVED_NULL_REASON`);
  `src/raptor/packet/config.py` (`load_candidate_direction_policy`, the strict 8-key schema);
  `src/raptor/packet/state.py` (`ReviewState`).
- `src/raptor/eval/config.py` (`VALID_CRITERIA`/`FORBIDDEN_CRITERIA`); `configs/eval/tsc2.yaml`
  (`automatable_criteria`); `configs/eval/bias_lineage.yaml` (dispositions).
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`candidate_pattern_compression` — illustrative).

## Empirical probes BEFORE policy (non-negotiable ordering)

1. **Dependency-readiness**: confirm A/B/C are landed and their outputs (corrected strengths, BS2 deferral,
   SPDI scope) are the exact inputs D pins. D must not be pinned before A ∧ B ∧ C.
2. **Eval/production parity**: enumerate the candidate criteria set = eval `automatable_criteria` (derived,
   post-lineage-correction), **minus** deferred BS2 (B), **minus** `FORBIDDEN_CRITERIA` and any
   not-yet-Oracle-ruled transitive `requires_heldout_mask` criteria. Derived from config, not invented.
3. **Separation-from-eval + unapproved-null**: verify (by spec/construction) that `packet.direction`
   imports no `eval.combine`, uses its own pinned points/thresholds, and — because `approval_status`
   stays `unapproved` — returns null/`POLICY_BLOCKED` for every variant.

Finish with a `VERIFICATION` block and the exact diff scope. Do not stage, commit, push, or modify
unrelated files, or the shared PROGRAM/STRATEGY/DECISIONS/RISK docs. Do not modify or delete the untracked
`docs/prd/PRD-04-candidate-evidence-packet.md` (D reads it as a reference only).
