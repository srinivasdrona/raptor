# Slot 3 — PRD-04 preservation and inversion

## Preserve

- PRD-01 scorer evidence remains criterion-level and does not become an autonomous final classifier.
- PRD-06's Tavtigian combiner remains eval-only until a separately approved production candidate
  policy exists.
- Existing benchmark/label files remain unreachable from packet generation.
- KB append-only history and classification-version semantics are reused, not bypassed.
- No code, tests, configs, existing PRDs, strategy, program or risk documents are modified.

## Three failure modes

1. **Polished false authority:** an LLM narrative or "LP/LB" label visually becomes a clinical
   classification. Candidate direction and provisional/gate state must be unavoidable.
2. **Pattern sign-off laundering:** approving BP4+PM2 once silently classifies 1,222 variants.
   Pattern approval validates triage policy only; external reclassification remains per-variant.
3. **Unreviewable evidence dump:** reproducing BIAS TSV fields without lineage, exclusions,
   contradictions, missing evidence and reviewer actions forces the expert to redo the analysis.
   The packet must make the decision and uncertainty inspectable.
