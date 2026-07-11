# Slot 3 — Preservation & inversion guard (canonical-SPDI arm's-length live eval adapter)

## Preserve (semantics that must not change)

- **`run_eval` and the `EvidenceSource` Protocol are unchanged.** `src/raptor/eval/harness.py` and
  `tests/eval/test_ac6_ac7_ac9_harness.py` stay **byte-unchanged**; the adapter conforms to the existing
  Protocol (`get_evidence(variant_id) -> Iterable[(criterion, strength, direction)]`).
- **Scorer parsing faithfulness.** `parse_rationale` and its frozen oracle
  (`tests/scorer/test_oracle_parsing.py`, `fixtures/bias_output_slice.tsv`, `expected_evidence.json`)
  stay byte-unchanged; the adapter reuses the parser, emitting **every** fired criterion faithfully.
- **`BiasTsvSource` reuse.** The 18-column arm's-length TSV contract is reused, not re-implemented; the
  adapter never re-parses BIAS or re-derives thresholds.
- **The completed lineage gate is integrated, not re-authored.** `lineage_audit.py` /
  `bias_lineage.yaml` (sha256 `743a0248…`) are consumed; the adapter calls audit → enforce at preflight.
- **Config parity (eval = production).** `automatable_criteria == included_criteria` (both excluding
  `FORBIDDEN_CRITERIA`) is asserted, not duplicated with a second drifting filter.
- **Labels boundary (H1/R-A2).** No benchmark/held-out/label file is reachable from the adapter; the
  existing forbidden-import audits (`tests/eval/test_knowns_ac5_forbidden_import_audit.py`,
  `tests/scorer/test_ac6_no_trace_cribbing.py`) stay byte-unchanged; new coverage is append-only in a new
  module.
- **Arm's-length AGPL boundary (ADR-0007).** Evidence crosses only the committed BIAS TSV; no
  `bias_2015` import.

## Reconciliations the doer MAY make (not weakening)

- Parsing `BiasRecord.acmg_classification` (the column is contractually required) while **never reading
  it** to build evidence — presence is required, use is forbidden (FR-B4).
- Reporting `vcf_key` + the raw BIAS echo for audit/conservation while joining strictly by canonical SPDI.

## Prohibited (weakening tests/config to match an implementation)

- Do **not** join by raw `vcf_key` string / BIAS's echoed `POS/REF/ALT`; normalize to canonical SPDI
  first (indels silently mis-join otherwise — M1).
- Do **not** read `acmgClassification` to build or shortcut evidence.
- Do **not** serve on a partial/incomplete join (a subset of the 2,577) — that is a hollow-green gate; any
  exact-set breach is fatal and typed, never a silent empty list.
- Do **not** add a second included/automatable filter — eval must equal production.
- Do **not** construct/serve over the **leaky full-resource** TSV in the terminal eval; the lineage gate
  must block it, and the eval run supplies the **masked** TSV.
- Do **not** blacklist ordinary pathogenic/benign strings or `acmg_classification` to "prove"
  label-blindness — prove it structurally (no label parameter; sentinel absence).
- Do **not** modify `run_eval`, the Protocol, or any frozen oracle to make a test convenient.
- Do **not** import `raptor.eval.knowns`/`raptor.eval.benchmark` or any label/benchmark file.

## Highest-risk inversion failures

1. **Raw-string indel mis-join (M1).** Trusting BIAS's coordinate echo joins a left-shifted manifest
   indel to a right-shifted BIAS row — the wrong variant's evidence is served, and the metric is
   meaningless. **Guard:** AC-B7(a) equivalent-indel join; AC-B7(c) canonical-duplicate fatal.
2. **Partial-eval hollow green.** Silently scoring the subset that joined and dropping the unmatched
   held-out ids — a green gate over an incomplete exam. **Guard:** AC-B3 exact-set typed breach; no
   silent empty list; conservation over all 2,577.
3. **Combined-answer import.** Building evidence from `acmgClassification` imports BIAS's final call
   instead of per-criterion evidence (and re-imports whatever ClinVar circularity it encodes). **Guard:**
   AC-B2 blank/mutate invariance.
4. **Eval ≠ production drift.** A second, drifting criterion filter silently scores criteria production
   would not (R-A2). **Guard:** AC-B5 injected drifted `ScorerConfig` raises.
5. **Running on the leaky TSV.** Constructing the terminal eval over the full-resource (unmasked) TSV so
   `PS1`/`PM5` grade against their own ClinVar evidence. **Guard:** AC-B8 lineage gate raises at preflight
   on the unmasked TSV; the eval supplies the masked TSV.

No production code, tests, `docs/PROGRAM.md`, `docs/STRATEGY.md`, `src/raptor/eval/harness.py`, or the
frozen preservation set is modified by this planning task. The untracked
`docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
