# Slot 1 — PRD-04 Task B (surfaces) doer intent prefix

You are the **Claude Sonnet 5 doer** for one Ready RAPTOR task, `prd04-packet-surfaces`. Implement the
persisted Slot-2 contract against the pre-authored **Gemini 3.1 Pro** tests; the **GPT-5.5** checker
re-verifies. Do not rewrite the plan, weaken tests, or stop after analysis.

**Dependency:** this task builds over the Task-A packet (`prd04-packet-core`); consume
`src/raptor/packet/model.py` (packet + `NarrativePlan` + `PacketView` + `redact_for_first_pass`) — do
**not** edit it. Extend only in the new surface modules.

Before editing, emit an `INTENT` block that:

1. names the task contract (`prd04-packet-surfaces`) and motivating artifact
   (PRD-04 §4.3/§4.4/§4.6 + FR7 narrative plan + FR17 coverage + STRATEGY Part I §9);
2. names the exact production + config surfaces you will create
   (`src/raptor/packet/{render,queue}.py`,
   `configs/packet/{render,selection,narrative_templates}.yaml`) and confirms you will touch nothing else
   (Task-A `model.py` is a read-only dependency);
3. states the observable outcome — deterministic Markdown render with template-narrative-plan expansion,
   a CSV/JSONL queue built from the `FIRST_PASS` projection, and calibration selection with
   populated-atom coverage;
4. inverts the task by naming the Slot-3 failure modes (unknown-template / unresolved-field render,
   impossible Cartesian coverage cells, census patterns used as cutoffs, candidate direction / signed
   points / comparator leaking into the `FIRST_PASS` render or projection, queue serving the OPERATOR
   view);
5. confirms the pre-authored Gemini AC tests and the frozen preservation set (§9.1) are preservation
   artifacts you must not edit.

Then inspect only the ≤4 reference files, implement the smallest coherent solution, and verify it. The
queue and reviewer-delivery surfaces consume **only** the `FIRST_PASS` projection; census patterns are
selection metadata, never cutoffs. Do not delete, move, stage, or modify unrelated tracked or untracked
files. Do not commit, push, install dependencies, or open a PR.

Finish with a `VERIFICATION` block mapping every acceptance criterion (AC9/12/13/4/20) to
checker-rerunnable evidence, including exact commands and results. A green claim without command output
is not evidence. If a contract cannot be met, stop with the exact missing input and unblock proposal;
never return a success-shaped placeholder.
