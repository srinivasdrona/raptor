# Slot 2 — PRD-04 Task C: review workflow (state machine + decision log + comparator)

## Contract

- **Task:** `prd04-packet-workflow`
- **Goal:** Fail-closed state machine (exact transition table + gate enum + reviewer role/count/
  distinctness; `production_policy_unapproved` → `POLICY_BLOCKED`; T3/T9 require a non-null direction) +
  ONE variant-scoped append-only hash-chained decision log (deterministic path from canonical variant
  hash, genesis prev_hash, `record_id` idempotency, lock+fsync, replay-verified) + three-view first-pass
  double-blinding + AAVC reveal-only comparator (decision-before-reveal, append-only reconciliation),
  over the Task-A/B packet.
- **Motivating artifact:** `docs/prd/PRD-04-candidate-evidence-packet.md`
  (r3, source commit `9adbd7b`; read especially §4.4 FR14.1, §4.5 FR15/FR15.1 state machine, §4.7/§4.9
  decision log FR25, §4.11 comparator FR27, §10.3 module layout, §11.3 task spec).
- **Sequencing:** third of three sequenced doer tasks (A → B → C).
- **Depends on:** `prd04-packet-core` (Task A) and `prd04-packet-surfaces` (Task B) — consumes the Task-A
  packet + `DecisionLogRecord` + `ExternalComparator` shapes + `decision_record_hash`; do not edit Task-A/B
  output.

## Context surface

Create only:

- `src/raptor/packet/state.py`      — `PacketStateMachine` + transition table + `can_promote(gate, reviewers)`
- `src/raptor/packet/decisions.py`  — ONE variant-scoped append-only hash-chained decision log
  (path=`sha256(variant id)`; genesis/idempotency/lock+fsync/replay; **no `classification_versions` write**)
- `src/raptor/packet/comparator.py` — reveal-only AAVC envelope; decision-before-reveal
- `configs/packet/comparator.yaml`  — pinned AAVC DOI/checksum/commit + match-method vocabulary

Do not create the core (Task A) or surfaces (Task B) modules. Do not edit any frozen file (§9.1),
including Task-A `src/raptor/packet/model.py` and `hashing.py`.

## Reference files (four maximum — PRD §11.3)

1. `src/raptor/packet/model.py`   — Task-A packet + `ExternalComparator` shapes
2. `src/raptor/packet/hashing.py` — Task-A `decision_record_hash` (chain)
3. `docs/prd/PRD-06-benchmark-eval-harness.md` — gate status semantics `PASS/FAIL/UNDERPOWERED/UNVERIFIED` (AC10/AC15)
4. `docs/reference/aavc-prior-art-audit-2026-07.md` — AAVC reveal-only controls (AC17)

## Public API (copied verbatim from PRD §10.3 — implement exactly; you may add, never weaken)

- **`state.py`** — `PacketStateMachine` with the §4.5 states + transition table (FR15.1) +
  `can_promote(packet, gate_status, reviewers)`; fail-closed guards (FR15/AC10/AC15).
  `production_policy_unapproved`/null direction → `POLICY_BLOCKED`; T3/T7/T8/T9 require a non-null
  direction. Gate enum `PASS|FAIL|UNDERPOWERED|UNVERIFIED`. Pattern approval marks pattern-policy
  validated **only** (FR18/AC16).
- **`decisions.py`** — `decision_log_path(variant_identity) -> Path` (= `sha256(canonical SPDI)`, FR25) +
  `append_decision(log_path, record, *, record_id) -> DecisionLogRecord` + `replay(log_path)`: the
  **one-per-variant append-only hash-chained decision log** (FR25) — genesis `prev_hash`=64 zeroes,
  `record_id` idempotency (same id+payload no-op; same id+different payload → `DecisionLogConflictError`),
  OS exclusive lock + append/flush/fsync, replay verifying one linear chain + variant/version identity.
  Handles `reviewer_decision`, `independent_decision`, `pattern_policy_approval`, `supersession`,
  `comparator_reveal`, `reconciliation`. **Writes no `classification_versions` row** (FR23/AC11/AC23).
- **`comparator.py`** — `attach_comparator(packet, aavc_record)` + `reveal_allowed(packet, log) -> bool` +
  `reveal(log, packet)`: the reveal-only AAVC envelope (FR27); reviewer independent-decision-with-confidence
  before reveal enforced via the decision log; the comparator is stripped from `FIRST_PASS` (FR14.1).

## Exact Task-C schemas and signatures

Task C owns these frozen models in `decisions.py` (Task-A `model.py` remains frozen):

- `DecisionEventType`: `reviewer_decision | independent_decision | pattern_policy_approval |
  supersession | comparator_reveal | reconciliation`.
- `ActorRole`: `operator | qualified_molecular_geneticist | vcep_curator | system`.
- `DecisionDraft(variant_id: str, packet_id: str, evidence_core_hash: str,
  event_type: DecisionEventType, actor_id: str, actor_role: ActorRole, timestamp: str,
  decision: str, rationale: str, confidence: float | None,
  supersedes_packet_id: str | None, supersedes_envelope_hash: str | None)`.
  `variant_id` is canonical SPDI; confidence, when present, is in `[0,1]`.
- `DecisionLogRecord(record_id: str, variant_id: str, packet_id: str,
  evidence_core_hash: str, event_type: DecisionEventType, actor_id: str,
  actor_role: ActorRole, timestamp: str, decision: str, rationale: str,
  confidence: float | None, supersedes_packet_id: str | None,
  supersedes_envelope_hash: str | None, prev_hash: str, record_hash: str)`.
- `DecisionHistory(variant_id: str, records: tuple[DecisionLogRecord, ...])`.
- typed failures: `DecisionLogError`, `DecisionLogConflictError`, `DecisionLogTamperError`,
  `ComparatorRevealError`, `StateTransitionError`, `ComparatorConfigError`.

Exact decision APIs:

- `decision_log_path(root: str | Path, variant_identity: str) -> Path` returns
  `<root>/<sha256(variant_identity)>.jsonl`; canonical SPDI syntax is validated.
- `append_decision(log_path: str | Path, draft: DecisionDraft, *, record_id: str) ->
  DecisionLogRecord`. `record_id` is canonical UUID text. Canonical record payload for hashing contains
  every record field except `prev_hash`/`record_hash`, including `record_id`. Same id+identical payload
  returns the existing record without writing; same id+different payload raises
  `DecisionLogConflictError`.
- `replay(log_path: str | Path) -> DecisionHistory`. Empty/missing log is an empty history with variant
  identity inferred only when the first append occurs; replay of a non-empty file verifies filename
  addressing, one variant, JSON schema, UUIDs, genesis zero hash, linear `prev_hash`, every
  `record_hash`, and packet/evidence/supersession hash formats.
- Locking is cross-platform: `fcntl.flock(LOCK_EX)` on POSIX and `msvcrt.locking` on Windows over a
  dedicated sibling lock file. Append, flush and `os.fsync` occur while held; lock release is in
  `finally`.

Task C owns these frozen state models in `state.py`:

- `ReviewerSignoff(reviewer_id: str, role: ActorRole, decision: str, packet_id: str)`.
- `TransitionContext(actor_id: str, actor_role: ActorRole, gate_status: GateStatus,
  mask_ruling_complete: bool, primary_grounding_complete: bool,
  production_policy_approved: bool, reviewers: tuple[ReviewerSignoff, ...],
  successor_packet_id: str | None, successor_envelope_hash: str | None)`.
- `PacketStateMachine.can_transition(packet, target: ReviewState, context) -> bool`.
- `PacketStateMachine.transition(packet, target, context) -> CandidateEvidencePacket`; unauthorized
  transitions raise `StateTransitionError`. A successful transition returns a **new frozen packet
  version**: predecessor fields bind the old packet, review/gate state change, envelope hash/packet id
  recomputed. It never mutates the source packet.
- `can_promote(packet, gate_status, reviewers) -> bool` is a convenience check for T9 only and cannot
  bypass the full transition guard.
- Pattern approval is only a `DecisionEventType.PATTERN_POLICY_APPROVAL`; state APIs accept no pattern id
  and perform no member transitions.

Comparator config/API:

- `ComparatorConfig(config_version: str, source_name: str, source_snapshot: str, source_doi: str,
  source_archive_sha256: str, source_commit: str, match_methods: tuple[str, ...])`;
  `load_comparator_config(path: str | Path) -> ComparatorConfig` is strict/path-only.
- `attach_comparator(packet, comparator: ExternalComparator) -> CandidateEvidencePacket` returns a new
  immutable envelope with unchanged evidence core, comparator appended once by `comparator_id`, and
  recomputed envelope hash/packet id; conflicting duplicate id fails.
- `reveal_allowed(packet, history: DecisionHistory) -> bool` requires an `independent_decision` record
  for the same `packet_id`/`evidence_core_hash` by QMG/VCEP with non-null confidence and no prior
  comparator reveal.
- `reveal(log_path, packet, *, actor_id, actor_role, timestamp, record_id) ->
  DecisionLogRecord` replays, checks `reveal_allowed`, appends `comparator_reveal`, and returns the
  record. It reveals only comparators already bound to the full packet; it never changes criteria,
  direction or grounding.

## State machine (PRD §4.5 FR15/FR15.1 — implement exactly)

States: `DRAFT_PROVISIONAL`, `POLICY_BLOCKED`, `READY_FOR_EXPERT_REVIEW`, `EXPERT_CHANGES_REQUESTED`,
`EXPERT_APPROVED_INTERNAL`, `SECOND_REVIEW_APPROVED`, `EXTERNAL_SUBMISSION_READY`, `SUPERSEDED`. Every
transition is mechanically decidable with its exact guard and reviewer role/count/distinctness.
`production_policy_unapproved` (null direction) is a `POLICY_BLOCKED` guard (T2); a direction-null packet
is first-pass evidence-reviewable but cannot enter candidate-direction approval states — T3/T7/T8/T9
require a non-null `candidate_direction` under an approved production policy. Gate enum
`PASS|FAIL|UNDERPOWERED|UNVERIFIED`. `EXTERNAL_SUBMISSION_READY` (T9) requires an approved non-null
production policy + non-null `candidate_direction` + gate `PASS` + ADR-0009 mask ruling + **two distinct**
QMG sign-offs + `primary_grounding=present` for every `primary_required` criterion; it is unreachable
**by construction** this increment. Pattern-policy approval is its own event and **never** advances any
member variant's state.

## Decision log identity (PRD §4.9 FR25 / AC23 — implement exactly)

**Exactly one** log per canonical variant identity spanning **all packet versions**, addressed
deterministically at `<root>/<sha256(canonical_variant_spdi)>.jsonl` (**never** a raw/unsafe identity).
Each record binds `packet_id`/`evidence_core_hash`/`variant_id` (+ supersession links), actor/role/
timestamp, payload, `prev_hash`, `record_hash = sha256(prev_hash + canonical(record))`. Genesis
`prev_hash = 64 lowercase zeroes`. Idempotency: same `record_id` + payload is a no-op returning the
existing record; same `record_id` + different payload **fails loud** (`DecisionLogConflictError`).
Single-writer v1 takes an **OS exclusive file lock** and does **append → flush → fsync while held**.
`replay` verifies **one linear chain** (no fork/gap/hash-mismatch/reorder/insert) + variant/version
identity; any tamper or cross-variant record fails loud. **No `classification_versions` row** is written.

## AAVC reveal-only + decision-before-reveal (PRD §4.11 FR27 / AC17)

The AAVC envelope is excluded from `evidence_core_hash` and stripped from the `FIRST_PASS` view
(`redact_for_first_pass`). A reviewer **independent decision + confidence** is recorded **before** any
`comparator_reveal` (`reveal_allowed` is false until it exists); reveal and `reconciliation` are separate
append-only decision-log records. AAVC **never** enters criteria, the combiner, or grounding.

## Acceptance criteria (PRD §11.3 / §6 — the AC subset this task must satisfy; verbatim)

- **AC10** exact transition table + gate enum + reviewer role/count/distinctness;
  `production_policy_unapproved` → `POLICY_BLOCKED`; T3/T9 require non-null direction *(mechanical)*
- **AC11** variant-scoped decision-log conservation; NO `classification_versions` write *(mechanical)*
- **AC14** supersession immutability (no prior-hash mutation) *(mechanical)*
- **AC15** no external-ready without approved policy + non-null direction + gate PASS + two distinct
  reviewers + mask ruling + primary grounding *(mechanical)*
- **AC16** pattern approval advances 0 member variants *(mechanical)*
- **AC17** AAVC reveal-only (excluded from core + stripped from `FIRST_PASS`; decision-before-reveal;
  reconciliation append-only) *(mechanical)*
- **AC18** primary grounding gates external readiness *(mechanical)*
- **AC20** first-pass double-blinding enforced in delivery (`reveal_allowed` decision-before-reveal for
  `RECONCILIATION`) *(mechanical)*
- **AC23** variant-scoped decision-log identity: one log/variant across versions; genesis `prev_hash` 64
  zeroes; `record_id` idempotency; lock+fsync; replay detects fork/gap/tamper/cross-variant *(mechanical)*

Independent oracles: PRD-06 gate-status semantics (AC10/AC15); the AAVC audit controls (AC17) — never the
implementation's own output. `na_allowed: false`.

## Out of scope

Packet model/build (Task A); render/queue/calibration (Task B); the LLM narrative call; the KB adapter;
ClinVar submission; any real external release.

## Verification

Run the pre-authored Gemini tests for Task C and the full suite; show the frozen preservation set
(including Task-A `model.py`/`hashing.py`) is byte-unchanged, and prove no `classification_versions`
write. The GPT checker re-verifies AC10/11/14/15/16/17/18/20/23 against the commands in your
`VERIFICATION` block.
