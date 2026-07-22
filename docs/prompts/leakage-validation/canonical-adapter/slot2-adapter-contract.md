# Slot 2 — Adapter contract: public API, config, outputs, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the slot-1
> surfaces only**, before the doer. The doer implements to pass (may add, not weaken). This arm realizes
> PRD-08 §3.B / §10.3 / §11.2 with the leakage-safe framing: the eval run joins the **masked** BIAS TSV.

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 Join identity
The semantic join key is **canonical GRCh38 SPDI** (`{accession}:{pos0}:{deleted}:{inserted}`, `pos0`
0-based interbase). BIAS's echoed `POS/REF/ALT` is **not** trusted (fine for SNVs, unreliable for indel
anchoring) — every BIAS `(chromosome, position, refAllele, altAllele)` is reverse-mapped to its RefSeq
accession and re-normalized through the injected normalizer to canonical SPDI before joining. The
`vcf_key = "{contig}:{POS}:{REF}:{ALT}"` is kept for **audit/conservation** only, never the semantic
lookup.

### 0.2 Exact set
All **2,577** held-out identities join to exactly one BIAS record each (bijection). The allele profile
(707 `NC_000009.12` + 1,870 `NC_000016.10`; 2,416 SNV / 4 MNV / 135 delins / 3 ins / 19 del) is the
conservation oracle: 135 delins + 3 ins + 19 del are the shapes where a raw-string join would silently
mis-join.

### 0.3 Evidence source
Evidence = the fired per-criterion `rationale` calls from `parse_rationale` **only**. BIAS's combined
`acmgClassification` is parsed (the column is contractually required) but **never read** to build
evidence.

---

## 1. Public API (the test contract) — `src/raptor/eval/live_source.py` (NEW, eval-side)

- **`CanonicalBiasNormalizer` Protocol** —
  `normalize(chromosome: str, position: int, ref: str, alt: str, accession: str) -> str`.
  It returns canonical GRCh38 SPDI or raises; tests inject a deterministic fake. A future runtime wrapper
  adapts `SeqRepoGenomicNormalizer`/pinned reference to this protocol. The adapter never mocks or calls
  `SeqRepoGenomicNormalizer.normalize` with a fabricated signature.
- **`BiasEvidenceSource(bias_tsv_path, manifest_path, eval_config, scorer_config, normalizer)`** —
  preflights at construction, then satisfies the `EvidenceSource` Protocol `run_eval` expects. Preflight
  (in order):
  1. load + validate the identity manifest (per-row field-set exactly `{variant_id, vcf_key, accession,
     contig}`) → `MalformedManifestError` on shape breach;
  2. load BIAS rows via `BiasTsvSource` (reused; 18-column contract);
  3. reverse-map each BIAS `chromosome`→accession and normalize `(position, refAllele, altAllele)`
     through `normalizer` to canonical SPDI (FR-B8); a reference disagreement / normalization failure
     **fails loud**;
  4. **join by canonical SPDI**; validate exact-set + bijection over all manifest ids;
  5. assert config consistency (`set(eval_config.automatable_criteria) ==
     set(scorer_config.included_criteria)`, both excluding `FORBIDDEN_CRITERIA`);
  6. run the **completed lineage gate** `audit_lineage(...)` → `enforce_lineage(report)` (fail-closed;
     `LineageGateError` carries the report). Nothing is served on any preflight failure (fail-fast, G5).
- **`.get_evidence(variant_id) -> Iterable[(str, str, str)]`** — canonical SPDI id → joined BIAS record →
  `parse_rationale` fired calls as `(criterion.upper(), strength, direction)`. Never reads
  `acmg_classification` (FR-B4). Strength via `scorer_config.strength_map`; an unmapped fired strength
  raises `parse.UnmappedStrengthError`. An id absent from the joined set **fails loud**
  (`UnknownVariantError`), never a silent empty list.
- **Typed taxonomy (small hierarchy, PRD-08 §10.3):** `MalformedManifestError`;
  `ManifestBijectionError(kind)`; `ExactSetMismatchError(sets_by_kind)` with kinds ∈ {`duplicate_bias_row`,
  `duplicate_canonical_bias_row`, `unknown_bias_row`, `missing_holdout_row`}; `ConfigConsistencyError`;
  `UnknownVariantError`. A semantic coordinate mismatch surfaces as `unknown_bias_row` +
  `missing_holdout_row`, **not** a bespoke coordinate error.

No new CLI: the adapter is consumed by `run_eval`. Construction is the entry point.

---

## 2. Config (GP-6; nothing new hardcoded)

Reuses existing pins only: `configs/eval/tsc2.yaml` (`automatable_criteria`), `configs/acmg/tsc.yaml`
(`strength_map`, `included_criteria`), `configs/eval/export.yaml` (accession↔contig for the reverse
map), `configs/eval/bias_lineage.yaml` (the lineage gate, sha256 `743a0248…`), and
`configs/ingest/tsc.yaml::reference_checksums` (via the injected normalizer). No new config file; no
threshold touched.

---

## 3. Acceptance criteria (→ STRATEGY Part II §4 gates; = PRD-08 AC-B1..B7 in leakage-safe framing)

- **AC-B1 (mechanical) — Evidence via `parse_rationale`, hand-computed.** `get_evidence(canonical_id)`
  returns the fired `(criterion, strength, direction)` set matching a **hand-computed** expected set on a
  synthetic TSV + manifest fixture.
- **AC-B2 (mechanical) — Ignores `acmgClassification` value.** Mutating or blanking the
  `acmgClassification` column value (column present, contract holds) leaves `get_evidence` output
  byte-identical.
- **AC-B3 (mechanical) — Exact-set contract; typed error + structured kind; no partial eval.** Each of
  `duplicate_bias_row`, `duplicate_canonical_bias_row`, `unknown_bias_row`, `missing_holdout_row` surfaces
  as `ExactSetMismatchError` naming that **kind**; a semantic coordinate mismatch surfaces as
  `unknown_bias_row` + `missing_holdout_row`; malformed manifest → `MalformedManifestError`; config drift
  → `ConfigConsistencyError`. Nothing served on failure. **No silent row loss.**
- **AC-B4 (mechanical) — Strength map reuse; unmapped fails.** Conversion uses
  `scorer_config.strength_map`; an unmapped fired strength raises `UnmappedStrengthError`; no hardcoded
  strength.
- **AC-B5 (mechanical) — Config consistency (eval = production).** Preflight asserts
  `automatable_criteria == included_criteria` (both excluding `FORBIDDEN_CRITERIA`); an **injected
  deliberately-drifted `ScorerConfig`** (built in-test, no file edited) raises `ConfigConsistencyError`.
- **AC-B6 (evidence-form) — Label-free by construction.** Constructor/API inspection proves only
  `(bias_tsv, manifest, eval_config, scorer_config, normalizer)` inputs — no benchmark/label-source
  parameter; a unique benchmark-truth **sentinel** placed only in the export-side label-bearing input is
  absent from the manifest, BIAS fixture, adapter state, and emitted evidence. No generic
  pathogenic/benign value blacklist (FR-B4 separately proves `acmgClassification` is ignored).
- **AC-B7 (mechanical) — Canonical-SPDI join (M1).** (a) Two semantically equivalent but differently
  represented indels join to the same manifest identity; (b) a BIAS record whose reference disagrees /
  fails to normalize fails loud; (c) two raw BIAS rows collapsing to one canonical SPDI fail as
  `ExactSetMismatchError(duplicate_canonical_bias_row)`. Join is by canonical SPDI, never raw `vcf_key`.
- **AC-B8 (domain-truth) — Lineage gate enforced at preflight.** Constructing over the **leaky
  full-resource** held-out TSV (with scored `PS1`/`PM5` firing) raises `LineageGateError` at preflight
  carrying the report; constructing over a synthetic **masked/clean** TSV constructs successfully and
  serves. The terminal eval cannot run on an unmasked TSV.
- **AC-B9 (evidence-form) — Label-blind static audit (NEW module).** A new forbidden-path/import test
  proves `live_source.py` never imports `raptor.eval.knowns`/`raptor.eval.benchmark` and never opens the
  frozen benchmark/held-out/labels.

---

## 4. Independent oracles (never the implementation's own output)

- **Hand-computed `parse_rationale` fired-call sets** on the synthetic TSV (AC-B1) — reuses the frozen
  scorer parsing oracle discipline, not the adapter's echo.
- **The 2,577 allele-profile conservation counts** (AC-B7) as the join-completeness oracle.
- **The completed lineage gate** (`audit_lineage`) as the independent block oracle (AC-B8) — integrated,
  not re-derived.
- **A unique truth sentinel** absent from adapter state (AC-B6) as the label-blindness oracle.

## 5. Deferred (not this code)

The masked BIAS TSV itself (Arm A + operator rebuild + masked re-score). The adapter is built + validated
offline on synthetic label-free fixtures now; the real masked TSV is supplied at the C-final run, which
additionally waits on the Oracle BP4/PP3 policy ruling. `run_eval` is unchanged; the adapter conforms to
its existing Protocol.
