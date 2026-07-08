"""PRD-01 — Tier-1/2 deterministic ACMG scorer.

Wraps BIAS-2015 (ADR-0007: arm's-length, never imported -- consumed only
across a TSV data boundary) to turn its per-variant criterion calls into
grounded, deterministic KB `evidence` rows (or a `manual_queue` routing for
FR8 edge cases). RAPTOR does not re-derive ACMG thresholds; BIAS owns them.
Writes go through the committed PRD-03 `KBStore` API (`pipeline.run_scorer`).
"""
