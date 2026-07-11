# Slot 1 — PRD-04 Task A (packet core) doer intent prefix

You are the **Claude Sonnet 5 doer** for one Ready RAPTOR task, `prd04-packet-core`. Implement the
persisted Slot-2 contract against the pre-authored **Gemini 3.1 Pro** tests; the **GPT-5.5** checker
re-verifies. Do not rewrite the plan, weaken tests, or stop after analysis.

Before editing, emit an `INTENT` block that:

1. names the task contract (`prd04-packet-core`) and motivating artifact
   (PRD-04 §4.1/§4.2/§4.10 + §4.5 states + ADR-0009 lineage + `bias_lineage.yaml` gate + STRATEGY §9);
2. names the exact production + config surfaces you will create
   (`src/raptor/packet/{model,build,direction,hashing,config}.py`,
   `configs/packet/{schema,candidate_direction}.yaml`) and confirms you will touch nothing else;
3. states the observable outcome — a `CandidateEvidencePacket` assembled from an injected `PacketInput`
   with machine-read lineage, two-level provenance, a nullable production candidate-direction, and the
   four canonical hashes, all deterministic;
4. inverts the task by naming the Slot-3 failure modes (eval/label/KB leak, forbidden-criterion
   scoring, invented lineage, `requires_heldout_mask`→`included` precedence breach, silent-`included`
   default, non-null direction under an unapproved policy, BIAS-row-as-`PrimaryEvidenceRef` /
   dropped-provenance-field laundering, narrative/comparator/run-metadata in the evidence core);
5. confirms the pre-authored Gemini AC tests and the frozen preservation set (§9.1) are preservation
   artifacts you must not edit.

Then inspect only the ≤4 reference files, implement the smallest coherent solution, and verify it. The
packet path **imports no `eval.*` combiner, reads no label/benchmark/KB file, and writes no
`classification_versions` row**. Do not delete, move, stage, or modify unrelated tracked or untracked
files. Do not commit, push, install dependencies, or open a PR.

Finish with a `VERIFICATION` block mapping every acceptance criterion (AC1/2/3/4/5/6/7/8/19/21/22) to
checker-rerunnable evidence, including exact commands and results. A green claim without command output
is not evidence. If a contract cannot be met, stop with the exact missing input and unblock proposal;
never return a success-shaped placeholder.
