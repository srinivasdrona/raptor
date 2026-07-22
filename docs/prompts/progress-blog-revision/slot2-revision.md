# Slot 2 — Adversarial blog corrections

Revise only `docs/blog/2026-07-10-before-the-first-score.md`. Preserve its title, pre-results thesis,
structure, links, numbers, and 1,400–2,200-word range. Apply these exact corrections:

1. Replace "make retrospective storytelling impossible" with calibrated wording: publishing makes
   later drift **detectable/auditable and harder**, not impossible.
2. In the benchmark paragraph, say conflicting/single-submitter/low-review rows are **excluded from
   the scored benchmark before splitting**, never "held out."
3. Replace "with no downside" for holdout 0.7: there is **no model-training penalty** because Tier 1/2
   learns no benchmark parameters, but the explicit trade-off is the smaller 1,104-variant development/
   sanity reserve. At first use of "powers," cross-reference the later caveat that the current gate
   checks point estimates rather than the rubric's Clopper-Pearson lower bound.
4. Correct leakage provenance:
   - the 8-variant TSC x64 smoke output confirmed direct-copy PP5/BP6/PS4 rationales;
   - the repository's frozen real-BIAS scorer fixture demonstrates transitive/aggregate PM1/PM5/PP2
     dependence;
   - do not imply the full TSC held-out scoring run occurred.
5. Delete the false monotonicity claim that excluding criteria can only push measured performance
   downward. State instead: removing circular criteria may move precision and recall in different
   directions; the justification is **validity of the measurement**, not a guaranteed conservative
   numeric direction.
6. Change "pinned outputs" to **recorded local export outputs**. State the hashes are recorded here and
   in the out-of-repo provenance sidecar; they are reproducible only with the pinned external ClinVar
   snapshot/reference inputs, which are intentionally not committed.
7. Change the misleading ``[commit 4965104](PRD link)`` construction to plain local commit text plus a
   separate PRD-08 link.

After editing, search for the old phrases and verify none remain. Do not add new performance,
biological, or clinical claims.
