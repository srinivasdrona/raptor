# Slot 1 — Canonical-SPDI arm's-length live eval adapter · planner/role prefix

You are the **planner** for one vertical RAPTOR prerequisite: a **real arm's-length eval
`EvidenceSource`** that joins the **masked** held-out BIAS TSV to the 2,577 frozen held-out identities
**by canonical GRCh38 SPDI**, serving evidence only from fired per-criterion rationales. You write the
build/test contract (slot 2) and the preservation/inversion guard (slot 3). You do **not** write
production code or executable tests. The test-author writes the AC tests from your contract alone; the
doer implements to pass; the checker re-verifies.

Emit an `INTENT` block before editing that names: the **user** (`run_eval` / PRD-06, which consumes the
adapter's `(criterion, strength, direction)` tuples); the **artifact** (`BiasEvidenceSource` — a
preflighted, canonical-SPDI-joined, lineage-gated evidence adapter over a committed BIAS TSV + identity
manifest); the **validator** (exact-set join over all 2,577 ids + hand-computed `parse_rationale` output
+ the completed lineage gate enforced at preflight); the **falsifier** (any silent row loss on the join,
any raw-`vcf_key` string lookup, any read of BIAS's combined `acmgClassification`, any label reachable
from the adapter, any partial eval); and **why** a generic ACMG product cannot supply this (the join is
against *this* pinned BIAS 3.0.0 indel-echo behaviour and *this* frozen held-out identity manifold — the
canonicalization is build-specific, ADR-0007).

## Role intent

Produce a complete, buildable three-slot implementation contract so that the resulting implementation:

1. **Constructs from label-free files + injected ports** — `(bias_tsv_path, manifest_path, eval_config,
   scorer_config, normalizer)`; reuses `BiasTsvSource` + `parse_rationale`; never re-implements BIAS
   parsing or re-derives thresholds;
2. **Preflights before serving** — loads/validates the manifest + BIAS rows, canonically normalizes +
   **joins by canonical SPDI**, asserts exact-set + bijection + config consistency, and **enforces the
   completed lineage gate** (fail-closed) — all before any `get_evidence`;
3. **Serves `get_evidence(canonical_variant_id) -> Iterable[(criterion, strength, direction)]`** faithful
   to **every fired criterion**, never reading `acmgClassification`, failing loud on an unknown id;
4. **Is provably label-blind** and joins the **masked** TSV so no held-out variant is graded against its
   own ClinVar-derived evidence.

## Existing surfaces this reuses / conforms to (cite; do not re-implement or modify)

- `src/raptor/eval/harness.py` — the `EvidenceSource` Protocol (`get_evidence(variant_id) ->
  Iterable[(criterion, strength, direction)]`) and `run_eval` (**NOT modified**; the adapter conforms).
- `src/raptor/scorer/parse.py` — `parse_rationale` + `UnmappedStrengthError` (reused verbatim).
- `src/raptor/scorer/bias_source.py` — `BiasTsvSource` (the arm's-length 18-column TSV parser; the
  `vcf_key` format) reused.
- `src/raptor/ingest/normalizer.py` — the injected `SeqRepoGenomicNormalizer` (canonical SPDI +
  checksum-verify) used to normalize BIAS coordinates for the join (FR-B8 discipline).
- **The completed lineage gate** — `src/raptor/eval/lineage_audit.py` (`audit_lineage` /
  `enforce_lineage` / `LineageGateError`) + `configs/eval/bias_lineage.yaml` (sha256 `743a0248…`).
  Preflight runs **audit → enforce**; the terminal eval stays blocked until the Oracle rules on the
  masked counts. Do **not** re-author the audit — integrate it.
- `configs/eval/tsc2.yaml` (`automatable_criteria`) + `configs/acmg/tsc.yaml` (`strength_map`,
  `included_criteria`) — reused for the config-consistency assertion and strength conversion.

## Required source inspection (no-assumption rule)

- `docs/prd/PRD-08-live-eval-evidence-adapter.md` §3.B, §10.3, §10.6, §11.2 (the adapter's pinned API +
  typed taxonomy + canonical-SPDI join M1) — the authoritative prior specification this arm realizes.
- `docs/prd/PRD-06-benchmark-eval-harness.md` §10.6 (the `EvidenceSource` Protocol + `run_eval`).
- `docs/DECISIONS.md` ADR-0007 (arm's-length), ADR-0009 (why the join must be over the **masked** TSV).

## Arm's-length + labels boundary (non-negotiable)

- **Never import or copy AGPL BIAS code.** Evidence crosses the committed-TSV boundary only.
- **Label-free files only.** The adapter opens the BIAS TSV + manifest + configs + the pinned reference
  (via the injected normalizer); it never imports `raptor.eval.knowns`/`raptor.eval.benchmark` and never
  opens the frozen benchmark/held-out/label artifacts. Do **not** blacklist ordinary
  pathogenic/benign strings or `BiasRecord.acmg_classification` — FR-B4 proves the combined value is
  *ignored*, not absent.
- **Masked TSV is the eval input.** The leakage-safe eval feeds the **masked** re-score TSV (Arm A +
  operator), not the leaky full-resource TSV (sha256 `6e055fe1…`). The adapter is source-agnostic; the
  contract pins which TSV the eval run supplies.

Finish with a `VERIFICATION` block and the exact diff scope. Do not modify `run_eval`, the frozen
preservation set, `docs/PROGRAM.md`, `docs/STRATEGY.md`, or the untracked
`docs/prd/PRD-04-candidate-evidence-packet.md`.
