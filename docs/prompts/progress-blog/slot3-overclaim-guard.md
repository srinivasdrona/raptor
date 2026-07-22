# Slot 3 — Progress-post preservation and overclaim guard

## Preserve

Create one new blog file only. Do not edit `PROGRAM.md`, `STRATEGY.md`, PRDs, configs, data, tests, or
code. Do not expose held-out variant identities, labels, local usernames/paths, unpublished patient
data, or private credentials.

## Three failure modes

1. **Premature victory:** words such as "validated", "accurate", "works", "passed the benchmark", or
   "classified the VUS" imply a result that does not exist. State repeatedly and plainly that no
   held-out performance metric or gate verdict exists yet.
2. **Benchmark laundering:** presenting ClinVar proxy labels as expert truth, hiding class imbalance, or
   omitting PM1/PM5/PP2 uncertainty creates a hollow credibility claim. Include the adversarial ledger
   and exact limitations.
3. **Process marketing:** portraying the four-model loop or three-slot prompts as inherently reliable
   ignores the repeated misses. Describe observed failures, what became mechanically locked, and what
   remains manual; cite `STRATEGY.md`'s admission that many controls are conventions/planned.

The post may claim only that specific artifacts were built, tests/checks ran, and the label-free export
conserved 2,577 identities. It may not infer biological correctness or clinical utility from those facts.
