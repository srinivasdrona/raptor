# Slot 1 — PRD-04 Task C (review workflow) doer intent prefix

You are the **Claude Sonnet 5 doer** for one Ready RAPTOR task, `prd04-packet-workflow`. Implement the
persisted Slot-2 contract against the pre-authored **Gemini 3.1 Pro** tests; the **GPT-5.5** checker
re-verifies. Do not rewrite the plan, weaken tests, or stop after analysis.

**Dependency:** this task builds over the Task-A/B packet (`prd04-packet-core` → `prd04-packet-surfaces`);
consume `src/raptor/packet/model.py` (packet + `DecisionLogRecord` + `ExternalComparator` shapes) and
`src/raptor/packet/hashing.py` (`decision_record_hash` chain) — do **not** edit them. Extend only in the
new workflow modules.

Before editing, emit an `INTENT` block that:

1. names the task contract (`prd04-packet-workflow`) and motivating artifact
   (PRD-04 §4.4 FR14.1 + §4.5 FR15.1 + §4.7/§4.9 decision log + §4.11 comparator + STRATEGY §9);
2. names the exact production + config surfaces you will create
   (`src/raptor/packet/{state,decisions,comparator}.py`, `configs/packet/comparator.yaml`) and confirms
   you will touch nothing else (Task-A `model.py`/`hashing.py` are read-only dependencies);
3. states the observable outcome — a fail-closed state machine, one variant-scoped append-only
   hash-chained decision log (deterministic path, genesis prev_hash, record_id idempotency, lock+fsync,
   replay-verified), and a reveal-only AAVC comparator with decision-before-reveal;
4. inverts the task by naming the Slot-3 failure modes (decision written to `classification_versions`,
   pattern approval advancing members, in-place history edit, raw/unsafe or forking/cross-variant log
   identity, silent duplicate-`record_id` acceptance, `EXTERNAL_SUBMISSION_READY` without
   policy+direction+PASS+two reviewers, AAVC entering criteria/combiner or reveal-before-decision);
5. confirms the pre-authored Gemini AC tests and the frozen preservation set (§9.1) are preservation
   artifacts you must not edit.

Then inspect only the ≤4 reference files, implement the smallest coherent solution, and verify it.
Decisions are written **only** to the one variant-scoped append-only hash-chained decision log, **never**
`classification_versions`; the packet path writes no `classification_versions` row this increment. Do not
delete, move, stage, or modify unrelated tracked or untracked files. Do not commit, push, install
dependencies, or open a PR.

Finish with a `VERIFICATION` block mapping every acceptance criterion (AC10/11/14/15/16/17/18/20/23) to
checker-rerunnable evidence, including exact commands and results. A green claim without command output
is not evidence. If a contract cannot be met, stop with the exact missing input and unblock proposal;
never return a success-shaped placeholder.
