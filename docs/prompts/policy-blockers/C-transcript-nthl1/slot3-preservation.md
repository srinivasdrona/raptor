# Slot 3 — Preservation & inversion guard (transcript/NTHL1 reconciliation)

## Preserve (semantics that must not change)

- **Reuse the canonical SPDI algebra.** `SeqRepoGenomicNormalizer` / `_spdi_normalize`
  (`bioutils.normalize` EXPAND over the pinned, checksum-guarded reference) is the sole SPDI source. This
  task **reuses** `variant_id`; it does **not** re-roll normalization, thresholds, or reference handling.
- **Fail-loud routing is preserved.** The normalizer's `REF_MISMATCH`/`REFERENCE_UNAVAILABLE`/checksum-
  mismatch fail-loud paths and `ManualQueueItem(excluded_from_scorer=True)` contract are unchanged and
  reused for the new `OUT_OF_SCOPE_GENE`/`TRANSCRIPT_BASE_MISMATCH` routings.
- **`check_out_of_scope_gene` stays always-on.** It is not gated by an `edge_cases` toggle; a gene with no
  pinned transcript/policy (NTHL1) must never be silently scored. Intent unchanged.
- **No silent coercion.** A mismatched transcript is never rewritten to the pinned accession, and an NTHL1
  record is never re-attributed to TSC2 — exactly the "never silently correct a mismatch" rule the
  normalizer already enforces for `REF_MISMATCH`.
- **Labels boundary (R-A2/H1).** No benchmark/label file is opened; the reconciliation is a function of the
  record, its genomic SPDI, and config only.
- **Config-as-policy.** The per-gene MANE base/version and the `spdi_equivalent` reconciliation flag live
  in config (schema-validated, no wildcard/default gene mapping), never hardcoded in the predicate.
- **Probes precede the policy.** The census-arithmetic check, the NTHL1 locus characterization, and the
  SPDI-version-invariance proof run **before** the reconciliation is trusted.

## Reconciliations the doer MAY make (not weakening — correcting an over-block + hardening an out-of-scope route)

- Refining `non_mane_transcript` so a pure same-base version delta (`.4` vs pinned `.5`) with a matching
  canonical SPDI is `reconciled_version_delta` and **not** dumped to manual review — this *corrects* an
  over-block, it does not weaken a guard.
- Adding the `reconcile_transcript_identity` helper + config + probe + tests.
- Recording the version delta as provenance on reconciled records.

## Prohibited (over-blocking, silent coercion, or scoring out-of-scope)

- Do **not** route the whole TSC1/TSC2 corpus to manual review on a `.4≠.5` version bump (the blanket
  over-block).
- Do **not** silently rewrite BIAS `.4` to `.5`, or NTHL1 to TSC2, or coerce any mismatched transcript to
  the pinned accession — reconcile **only** on proven SPDI identity + base-accession match; else fail loud.
- Do **not** score, or emit any direction/classification for, the 30 NTHL1 records (or any manual-queue
  row).
- Do **not** re-attribute the 30 NTHL1 records into the TSC2 scored set / census.
- Do **not** re-implement SPDI normalization, reference lookup, or checksum handling — reuse the normalizer.
- Do **not** introduce a wildcard/default gene→transcript mapping or a silent fallback accession.
- Do **not** reconcile a genuine base-accession mismatch (a different transcript, not a version bump) as if
  it were a version delta.
- Do **not** patch a test fixture to make a mismatch "pass".

## Highest-risk inversion failures

1. **Version-bump manual-review dump (active committed baseline).** The committed config already enables
   `non_mane_transcript: true` with TSC2-only `.5` pins, so the committed pipeline **today** routes the
   whole TSC2 `.4` corpus to `EDGE_CASE_ROUTED` and every TSC1 `.4` row to `OUT_OF_SCOPE_GENE` — a live
   full-corpus misroute on a cosmetic version delta, not a hypothetical. **Guard:** AC-C3/AC-C4 (SPDI-keyed
   `reconciled_version_delta`, not routed) **and AC-C7** — a real-config / real-row / real-pipeline
   regression that first pins the baseline misroute, then proves the correction, with the 30 NTHL1 rows
   staying manual.
2. **Silent transcript/gene coercion.** Auto-rewriting `.4→.5` or NTHL1→TSC2 without SPDI proof — the
   `REF_MISMATCH`-style silent-correction failure this pipeline exists to prevent. **Guard:** AC-C5 —
   reconcile only on proven identity + base match; else fail loud.
3. **NTHL1 mis-attribution / contamination.** Folding the 30 NTHL1 records into TSC2 scoring, contaminating
   the census and candidate directions with out-of-scope calls. **Guard:** AC-C2 — always-on
   `out_of_scope_gene` → manual queue, `excluded_from_scorer=True`.
4. **Clinical classification of the 30.** Emitting a direction/call for the NTHL1 (or any manual-queue)
   record — the task is routing, not classifying. **Guard:** AC-C2/AC-C6 — no direction emitted for
   manual-queue rows.
5. **Re-rolled SPDI drift.** Hand-writing a second, subtly-different normalization to compare transcripts,
   diverging from the pinned `bioutils` SPDI. **Guard:** AC-C5 — reuse `variant_id`; no new SPDI algebra.

No production code, tests, strategy, program, or risk documents are modified by this planning task. The
untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
