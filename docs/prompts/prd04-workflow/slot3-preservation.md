# Slot 3 — PRD-04 Task C (review workflow) preservation and inversion

## Preserve — frozen, byte-unchanged (§9.1; the checker fails any diff that touches these)

- `src/raptor/scorer/**` — the scorer stays criterion-level and never becomes an autonomous final
  classifier.
- `src/raptor/eval/**` (esp. `combine.py`, `harness.py`) — the AAVC comparator and the state machine
  import **no** eval combiner; AAVC never enters criteria/combiner/grounding.
- **`src/raptor/kb/store.py`** — the KB append-only *discipline* is mirrored, not bypassed; this
  increment writes **no** `classification_versions` row and reads no KB table directly. Reviewer/pattern
  decisions go to the packet-owned decision log (FR25).
- `docs/reference/aavc-prior-art-audit-2026-07.md` + the AAVC overlap aggregate — read-only reveal-only
  inputs; AAVC never enters criteria/combiner/grounding (FR27).
- **`src/raptor/packet/model.py`** and **`src/raptor/packet/hashing.py`** — Task-A output: do **not**
  edit; consume the packet, `DecisionLogRecord`, `ExternalComparator`, and `decision_record_hash` and
  extend only in the new workflow modules.
- No code, tests, configs, existing PRDs, strategy, program, decisions, or risk documents are modified
  beyond the authorized Task-C outputs.

New coverage is **append-only in NEW modules** (§9.2): `src/raptor/packet/{state,decisions,comparator}.py`,
`configs/packet/comparator.yaml`, and the Task-C `tests/packet/**`.

## Task-specific failure modes to invert (PRD §11.3 `invert_failure_modes` — verbatim)

1. **Decision-log laundering (item 1).** A reviewer/pattern decision is written to
   `classification_versions`. Fix: decisions go **only** to the one variant-scoped append-only
   hash-chained decision log; `classification_versions` is reserved for a terminal, qualified,
   variant-level classification after all gates and is **not written** this increment (AC11/AC23).
2. **Pattern sign-off laundering (Slot-3 failure mode 2).** Approving `BP4 Strong + PM2 Supporting`
   advances its 1,222 members. Fix: `pattern_policy_approval` marks the pattern's triage policy validated
   only and executes **no** state transition on any member — 0 of 1,222 advance (AC16).
3. **Audit bypass.** A decision edits history in place instead of appending a hash-chained record. Fix:
   supersession is immutable — a new version is a new content-addressed packet linked via a decision-log
   supersession record; editing a superseded packet or mutating a prior packet hash fails (AC14).
4. **Decision-log identity breach (r3-4).** The log is addressed from a raw/unsafe variant identity,
   forks/gaps, or replays to a different variant identity. Fix: exactly one log per canonical variant
   identity at `sha256(canonical_variant_spdi)`; genesis `prev_hash` 64 zeroes; `replay` detects and
   fails on fork/gap/`record_hash` mismatch/reorder/insert/cross-variant (AC23).
5. **Idempotency breach (r3-4).** A duplicate `record_id` with a divergent payload is silently accepted.
   Fix: same `record_id` + payload is a no-op returning the existing record; same `record_id` + a
   different payload **fails loud** (`DecisionLogConflictError`) (AC23).
6. **H4/H13 hollow green (r3-3).** `EXTERNAL_SUBMISSION_READY` is reachable without an approved policy +
   non-null direction + gate `PASS` + two distinct reviewers. Fix: T9 requires an approved non-null
   production policy + non-null `candidate_direction` + gate `PASS` + ADR-0009 mask ruling + two distinct
   QMG sign-offs + `primary_grounding=present` for every `primary_required` criterion; unreachable by
   construction this increment (AC10/AC15/AC18).
7. **False-authority reveal breach (item 9 / r3-2).** AAVC enters criteria/combiner, or the
   `RECONCILIATION` view/reveal is served before the independent decision-with-confidence. Fix: AAVC is
   reveal-only, excluded from the evidence core and stripped from `FIRST_PASS`; `reveal_allowed` enforces
   decision-before-reveal; reveal + reconciliation are separate append-only records; AAVC never enters
   criteria/combiner/grounding (AC17/AC20).

If any implementation shortcut weakens one of these assertions, **stop** rather than editing a frozen
file (including Task-A `model.py`/`hashing.py`) or a pre-authored test.
