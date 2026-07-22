# PRD-08 — Live-Eval Evidence Adapter (held-out export · arm's-length BIAS source · ClinVar-derivation audit)

> **Status:** Ready (v1 increment — planner spec + build contract §10; Gemini writes the AC contract next,
> from this spec only, before the Sonnet doer). **Ready caveat:** the §11 `prompt_manifest` placeholders
> are NOT yet filled — they still require the STRATEGY Part II §3.1 preflight fill (real slot{1,2}
> ids+hashes, concrete slot-3). · **Owner:** @dronasrinivas · **Phase:** 1 (STRATEGY Part I §7) · **Updated:**
> 2026-07-10
>
> **Links:** STRATEGY Part I §5 GP-1/2/6/8/9, §7, §9 · STRATEGY Part II §3.1, §4 G1–G7 · PRD-06 FR3/FR8, AC5/AC6,
> §10.6 · PRD-07 (label side / frozen benchmark) · PRD-02 (`ingest.normalizer` canonical GRCh38 SPDI) ·
> ADR-0007 (BIAS arm's-length), ADR-0008 (x64 worker), ADR-0009 (ClinVar-derived: direct-copy banned,
> transitive deferred to audit) · RISK_REGISTER R-A2/R-A2c/R-A10/R-A11/H1 · configs/{eval/tsc2,acmg/tsc,
> ingest/tsc}.yaml · `eval/config.py` (`FORBIDDEN_CRITERIA`, `VALID_CRITERIA` — imported by
> `eval/combine.py::implied_direction`) · `eval/harness.py` (`run_eval`, `EvidenceSource`) ·
> `scorer/bias_source.py` (`BiasTsvSource`) · `scorer/parse.py` (`parse_rationale`, `UnmappedStrengthError`)
> · `scorer/config.py` (`ScorerConfig`: `strength_map`, `included_criteria`) · `ingest/normalizer.py`
> (`SeqRepoGenomicNormalizer`, `ReferenceChecksumMismatchError`) · scripts/build_tsc_benchmark.py (freeze)
> · scripts/devbox/make_sample_vcf.py (smoke tool superseded).

---

## 1. Context / problem

PRD-06 built the eval harness (`run_eval`); PRD-07 froze the real known-variant benchmark. The first
**real** held-out measurement — the gate authorizing the ~6,700 VUS run (STRATEGY Part I §7) — needs a bridge
that does not exist:

1. **VCF vs canonical SPDI, neither may see a label.** BIAS-2015 + Nirvana run at arm's length on an x64
   worker (ADR-0007/0008) and consume a **VCF**; the frozen held-out benchmark
   (`scripts/build_tsc_benchmark.py`) is keyed by **canonical GRCh38 SPDI** and carries labels. The only
   exporter, `make_sample_vcf.py`, emits **8 SNVs** and leaks `CLASS=<variant_class>` into VCF `INFO` — a
   devbox smoke tool, not a real-exam exporter.
2. **No eval-side source reads real BIAS output.** `run_eval` expects an injected
   `EvidenceSource.get_evidence(variant_id) -> Iterable[(criterion, strength, direction)]`; only a test
   fake exists. A real arm's-length adapter over a committed BIAS TSV, joined to the benchmark by
   **canonical SPDI** through a label-free identity manifest, is missing.
3. **ADR-0009 deferred a mechanized audit.** Direct-copy ClinVar criteria (PP5/BP6/PS4) are already banned
   (`eval.config.FORBIDDEN_CRITERIA`). But real BIAS v3.0.0 output + the scorer fixture
   (tests/scorer/fixtures/bias_output_slice.tsv) show **transitive/aggregate** ClinVar rationales in
   **PM5** (same-residue), **PM1** (domain rate), likely **PP2** (gene proportions) — **currently scored**
   (in `automatable_criteria`, not `FORBIDDEN_CRITERIA`). Grading them against ClinVar-derived labels reads
   the answer key (R-A2). ADR-0009 deferred the ruling until real firing counts exist; the gate cannot
   honestly run until an audit produces those counts and **blocks the terminal eval closed** until the
   Oracle rules.

This slice builds all three — a **label-free held-out export**, a **real arm's-length eval evidence
adapter**, and a **mechanized ClinVar-derivation audit + blocker** — the last construction step before a
real gate run.

## 2. Scope

**In:** (A) label-free, deterministic, all-shape SPDI→VCF 4.2 export of **all 2,577** held-out ids + a
bijective identity manifest; (B) a new eval-side `EvidenceSource` over a committed BIAS TSV + manifest +
policy pins + an injected canonical normalizer; (C) a mechanized ClinVar-derivation audit + terminal-eval
blocker + standalone CLI/report; (D) the test/loop contract (§5/§9/§10/§11).

**Out (prevents scope spiral):** running BIAS/Nirvana (built + validated **offline against fixtures**);
changing any threshold value (`oracle_thresholds`/`min_count_per_class`/`tavtigian_*` — consumed, never
fitted); the CI/lower-bound gate; **deciding** PM5/PM1/PP2 legitimacy (Oracle-deferred — this slice only
produces counts and blocks); VUS scoring, PRD-04 worklist, Prefect, the PRD-02 loader fix; any new ACMG
class/tier or threshold re-derivation (BIAS owns thresholds).

## 3. Functional requirements

### A — Label-free held-out export boundary
- **FR-A1 — Field-level input access.** Input = the frozen held-out JSONL (out-of-repo, label-bearing:
  `label`, `source`, `snapshot`, `variant_class`, `variant_id`). Export code accesses **only
  `row["variant_id"]`**; no other field is read. It may run on the eval/data-prep side (may physically see
  truth), but its **outputs** are the label-free boundary the x64 scorer consumes.
- **FR-A2 — All-shape SPDI→VCF 4.2 (all 2,577, not SNV-only).** Canonical SPDI `variant_id =
  {accession}:{pos0}:{deleted}:{inserted}`, `pos0` = **0-based** interbase start (as
  `SeqRepoGenomicNormalizer` produces). Per shape: **both non-empty (SNV/MNV/delins)** →
  `POS=pos0+1, REF=deleted, ALT=inserted` after verifying `deleted == reference[pos0:pos0+len(deleted)]`;
  **pure insertion (deleted empty)** → anchor `= reference[pos0-1]`, `POS=pos0, REF=anchor,
  ALT=anchor+inserted`; **pure deletion (inserted empty)** → verify `deleted`, anchor `= reference[pos0-1]`,
  `POS=pos0, REF=anchor+deleted, ALT=anchor`; **contig-start (`pos0==0`) pure indel** → **fail loud** (typed
  error): no left anchor exists, never guess or silently switch to a right-anchor rule (out of scope unless
  separately oracle-proven). A fetched anchor must be **exactly one uppercase A/C/G/T base**; an empty,
  multi-base, lowercase, or ambiguous anchor raises `ExportReferenceMismatchError` before REF/ALT
  construction — never emit an invalid VCF allele.
- **FR-A3 — Reference pinned, verified, never hardcoded.** Bases read from the pinned checksummed GRCh38
  FASTA(s) (`configs/ingest/tsc.yaml::reference_checksums` for `NC_000009.12`/`NC_000016.10`), reusing
  `ingest.normalizer`'s FASTA access + checksum-verify (`ReferenceChecksumMismatchError`). A
  deleted-vs-reference disagreement is a **fail-loud** `REF_MISMATCH`-class error (never a silent
  correction — R-A10).
- **FR-A4 — Structural no-truth boundary (NOT a lexical/byte ban).** Defined by field-set + value
  provenance, never by banning bytes/substrings: (i) every VCF **data-row** `INFO` is exactly `.` — no
  `CLASS=`, no `variant_class` key (excludes make_sample_vcf's leak structurally); (ii) each manifest
  **per-variant row** field-set is **exactly** `{variant_id, vcf_key, accession, contig}` (minimal,
  explicitly pinned; no other keys); (iii) export copies **only** `row["variant_id"]`'s value into any
  per-row output — no label/source/review_status/snapshot/variant_class **value** flows into a per-row field
  or VCF `INFO`. **File-level provenance is allowed**: the VCF `##`-header and a separate
  `.provenance.json` sidecar may carry `source`, reference checksums, benchmark snapshot id, code
  version, counts, and content hashes. The manifest JSONL contains data rows only (no overloaded
  metadata/header row). Legitimate
  VCF/provenance text (the word "source", criterion directions, the snapshot id) is permitted — the boundary
  is per-row value provenance, not a substring blacklist.
- **FR-A5 — Deterministic, sorted, hashed.** VCF + JSONL manifest (+ optional TSV mirror) byte-identical
  across runs on identical ids + pinned reference (R-A11). VCF data rows use the **total sort key
  `(contig, POS, REF, ALT)`**, contig order a **pinned config order** (accession/sequence order,
  `NC_000009.12` before `NC_000016.10`), never accidental lexical string order. Both outputs carry a content
  hash; provenance at file/header level (FR-A4).
- **FR-A6 — Bijective manifest, conservation-checked.** Each row maps `variant_id ↔ vcf_key`,
  `vcf_key="{contig}:{POS}:{REF}:{ALT}"` using the **same contig naming the VCF uses** (config-driven
  `accession→contig`, e.g. `NC_000009.12→chr9`/`NC_000016.10→chr16`, validated against
  `configs/ingest/tsc.yaml`). `vcf_key` is kept for **audit/conservation and raw reporting** — not by itself
  the semantic join key (see FR-B8/M1). Every requested identity yields exactly one VCF data row + one
  manifest row; any collision or non-bijection is **fatal**. Conservation count (2,577) + both hashes are
  reported.
- **FR-A7 — Additive, scorer-blind.** A separate export tool (library + thin CLI) leaving the PRD-07 freeze
  unchanged; the scorer/KB path never imports it; `make_sample_vcf.py` stays devbox-smoke-only.

### B — Real arm's-length eval `EvidenceSource`
- **FR-B1 — Constructed from label-free files + injected policy/normalizer.** `BiasEvidenceSource` is built
  from `(bias_tsv_path, manifest_path, eval_config, scorer_config, normalizer)`, where `scorer_config` is a
  `ScorerConfig` (giving `strength_map` + `included_criteria`) and `normalizer` is an injected canonical
  normalizer/reference port (`SeqRepoGenomicNormalizer` or a DI fake — FR-B8). It **reuses** `BiasTsvSource`
  + `parse_rationale`; never re-implements BIAS parsing or re-derives thresholds. Tests can inject a
  deliberately drifted `ScorerConfig` **without editing any config file**.
- **FR-B2 — Preflight before serving.** At construction the adapter loads/validates the manifest + BIAS
  rows, canonically normalizes + joins (FR-B8), and runs the ClinVar-derivation audit (FR-C) **before** any
  `get_evidence`. A preflight failure raises at construction (fail-fast, G5); nothing served.
- **FR-B3 — `get_evidence(canonical_variant_id) -> iterable[(criterion, strength, direction)]`.** Resolves a
  canonical SPDI id → joined BIAS record → fired calls via `parse_rationale`, faithful to **every fired
  criterion**. `combine.implied_direction` (PRD-06 FR3) consumes those calls; the adapter does not duplicate
  it. A requested id absent from the joined set **fails loud** (never a silent empty list).
- **FR-B4 — Never use BIAS's combined classification.** `BiasRecord` **contains + parses**
  `acmg_classification` because `BiasOutputContract` requires the column; the adapter simply **never reads
  it** to build evidence — evidence comes **only** from the fired per-criterion `rationale`. Output is
  invariant to the `acmgClassification` value.
- **FR-B5 — Exact-set contract (typed taxonomy, not one class per condition).** Preflight rejects (no
  partial eval) via a **small typed hierarchy** (§10.3): malformed manifest → `MalformedManifestError`; any
  non-bijection → `ManifestBijectionError(kind=...)`; an exact-set breach → `ExactSetMismatchError` with
  **structured sets keyed by kind** (`duplicate_bias_row`, `duplicate_canonical_bias_row`, `unknown_bias_row`,
  `missing_holdout_row`); config drift → `ConfigConsistencyError`. **Coordinate representation differences
  are not a standalone error** — after canonical normalization (FR-B8) a semantic mismatch surfaces as
  `unknown_bias_row` + `missing_holdout_row`.
- **FR-B6 — Config consistency (eval = production).** Single source of truth + explicit assertion: preflight
  asserts `set(eval_config.automatable_criteria) == set(scorer_config.included_criteria)` and both exclude
  `FORBIDDEN_CRITERIA`; drift raises `ConfigConsistencyError`. Strength conversion reuses
  `scorer_config.strength_map`; an unmapped fired strength fails loud (`parse.UnmappedStrengthError`), never
  coerced. No duplicated filter is introduced.
- **FR-B7 — Label-free files only.** Opens only the BIAS TSV + manifest + configs + the pinned reference
  (via the injected normalizer); never imports `raptor.eval.knowns`/`raptor.eval.benchmark` and never opens
  the frozen benchmark/held-out/label artifacts. Enforced by the static import/path audit (AC-D1) plus
  constructor/API inspection (AC-B6). Do **not** apply a generic value blacklist to `BiasRecord`:
  BIAS's required `acmgClassification` field and criterion directions legitimately contain
  pathogenic/benign vocabulary; FR-B4 proves the combined value is ignored rather than absent.
- **FR-B8 — Canonical-SPDI join (do NOT trust BIAS's coordinate echo).** BIAS is **not** assumed to echo the
  exact input VCF `POS/REF/ALT` (fine for SNVs, unreliable for indel anchoring). At preflight the adapter
  reverse-maps each BIAS `chromosome` (`chr9`/`chr16`) to its pinned RefSeq accession via the export
  config/manifest, normalizes every BIAS `(position, refAllele, altAllele)` through the **injected canonical
  normalizer** (same PRD-02/07 discipline + pinned checksummed FASTA) to the **canonical GRCh38 SPDI**, and
  **joins by canonical SPDI** — never a raw `vcf_key` string lookup. This normalization is label-free. A BIAS
  record whose reference disagrees / fails to normalize **fails loud**; **two raw BIAS rows collapsing to one
  canonical SPDI is fatal** (`duplicate_canonical_bias_row`). `vcf_key` + the raw echo may still be reported
  for audit.

### C — Mechanized ClinVar-derivation audit (ADR-0009 follow-up)

> **Canonical predicates (stated once; referenced as CP-1..CP-3).** `VALID_CRITERIA`/`FORBIDDEN_CRITERIA`
> are defined in `src/raptor/eval/config.py` and imported by `combine.py`.
> ```
> CP-1  would_be_scored(c)      = c in eval.automatable_criteria AND c in VALID_CRITERIA
>                                                                  AND c not in FORBIDDEN_CRITERIA
> CP-2  clinvar_derived(c, rat) = marker_match(rat) OR c in transitive_suspect
> CP-3  blocked = ∃ fired c : ( would_be_scored(c) AND clinvar_derived(c, rat) AND c not in oracle_allowed )
>                          OR ( c not in VALID_CRITERIA AND marker_match(rat) )
> ```
> `oracle_allowed` gates **only** the CP-3 BLOCK disposition — it is **never** in the combiner's scored set
> (CP-1); `combine.implied_direction` does not read it. An **unknown criterion (`c not in VALID_CRITERIA`)
> with a marker blocks** (CP-3 second clause); an unknown criterion **without** a marker is unscored/recorded
> per the parser/config policy (`implied_direction` skips non-`VALID_CRITERIA` codes) — no scoring invented.

- **FR-C1 — Audit every fired rationale, case-insensitive.** For **every** fired criterion (not a
  hand-selected list) scan the rationale (case-insensitive) for resolvable ClinVar-derived markers using a
  **schema-validated, version-pinned** marker vocabulary (BIAS v3.0.0). The whole rationale is preserved
  verbatim.
- **FR-C2 — Deterministic aggregate report.** Per-criterion `{criterion, total_fired_count,
  clinvar_derived_fired_count, would_be_scored (CP-1), disposition, detection_source ∈ {marker_detected,
  transitive_suspect_only}, bounded deterministic example variant_ids}`. `detection_source` distinguishes
  **marker-detected** from **fail-closed transitive-suspect-only** (a criterion caught solely by CP-2's
  `transitive_suspect` net, no marker hit, is not counted as marker evidence) so counts stay honest.
  Identical inputs → identical report + content hash.
- **FR-C3 — Direct-copy: reported, never scored.** PP5/BP6/PS4 (`FORBIDDEN_CRITERIA`) may appear in raw
  rationale; reported with counts + examples but never scored and never block by themselves (already
  `would_be_scored=False`, CP-1).
- **FR-C4 — Fail-closed on any scored ClinVar-derived criterion.** When CP-3 holds the terminal eval **fails
  closed** — a **typed exception/result carrying the complete audit report + counts**. Evidence is never
  silently stripped and the run must not continue; the point is the counts for the Oracle. This blocks
  PM5/PM1/PP2 today.
- **FR-C5 — No wildcard/default-allow; unknown-with-marker fails.** `oracle_allowed` starts **empty**; no
  default-allow, no wildcard/regex allow. A future ADR/config decision may **name** a transitive criterion
  banned (→ `FORBIDDEN_CRITERIA`) or allowed (→ `oracle_allowed`); only named criteria change disposition.
  Per CP-3, an unknown criterion carrying a marker is **blocked**, never ignored.
- **FR-C6 — Version-pinned vocabulary + declared limits.** Schema-validated config, **pinned to BIAS
  v3.0.0**, documented limits: BIAS v3.0.0 exposes **no structured source field**, so detection is heuristic
  English-sentence matching; a version bump requires re-deriving the vocabulary. To keep the block
  fail-closed despite that fragility the config also declares the ADR-0009 `transitive_suspect` set —
  the **full static-lineage set `PS1, PM5, PM1, PP2, BP1`** (ADR-0009; `bias-lineage` slot 2 §0.6),
  **not** the earlier `PM5/PM1/PP2`. *Discrepancy resolved:* PS1 and BP1 are ClinVar-comparator-derived
  and currently scored, and **BP1's rationale carries no ClinVar marker** (`benign_classifiers.get_bp1`;
  `truncating_gene_to_data` ← `find_missense_pathogenic_genes_and_path_trunc_genes.py`, a ClinVar VCF),
  so only the transitive net blocks it — omitting PS1/BP1 would leak two scored ClinVar-derived criteria.
  Those criteria block even if a phrasing evades the markers (CP-2). Whole rationale is
  preserved for the Oracle.
- **FR-C7 — Standalone CLI/report.** A standalone command runs the audit on the **full BIAS TSV before
  labels/eval**, exits non-zero iff `report.blocked`, and **persists + prints the complete deterministic
  report** regardless of exit code.

### D — Test / loop contract
- **FR-D1 — Test-authorship separation.** The planner writes the AC + public-API contract; the Gemini
  test-author writes executable tests from this spec only, before the Sonnet doer. The doer may add but not
  weaken tests (G1).
- **FR-D2 — Preservation with a split boundary.** The **frozen** set (§9.1) stays byte-unchanged; new
  import/path + no-label-leak coverage lives in **new test modules** (§9.2) — a frozen file is never edited
  to add assertions.
- **FR-D3 — Property-based invariants where they fit.** Prefer Hypothesis (already a dev-dep) for
  conservation/bijection + structural no-truth invariants; **no** new dependency.

## 4. Non-functional requirements
- **Config-driven (GP-6):** contig map, marker vocabulary + `transitive_suspect` + (empty) `oracle_allowed`,
  BIAS-version pin — all schema-validated; nothing policy-bearing hardcoded; thresholds consumed, never set.
- **Reproducibility (R-A11):** export, join, and audit report are pure functions of pinned inputs; content
  hashes exclude run metadata (as `EvalReport.content_hash`).
- **Provenance (GP-5/9):** every artifact carries reference checksums / snapshot id / code version / config
  pins; every quantitative claim resolves to a source (G7).
- **Eval integrity (R-A2/H1):** structural no-truth boundary; new-module forbidden-import/path audits;
  fail-closed CP-3 blocker.
- **Least complexity (GP-7):** reuse `BiasTsvSource`/`parse_rationale`/`implied_direction`/the ingest
  normalizer; smallest coherent new surface (§10.3).

## 5. Acceptance criteria *(→ STRATEGY Part II §4 gates; Gemini authors these as executable tests)*

> Types: **mechanical** (checker re-runs a test) · **evidence-form** (checker inspects an artifact) ·
> **domain-truth** (not CLEAN without Oracle sign-off — G4/H11). The real 2,577 figure is a **real-run** CLI
> assertion, never a committed label-bearing fixture; offline tests use synthetic label-free fixtures +
> property invariants.

**Export (A)**
- **AC-A1 (mechanical) — All shapes convert, hand-computed.** On a synthetic label-free fixture covering
  every shape (SNV, MNV, both-non-empty delins, pure insertion, pure deletion), each VCF row equals the
  **hand-computed** `(POS, REF, ALT)` per FR-A2; anchors read from the (stub/pinned) reference, not
  fabricated.
- **AC-A2 (mechanical) — Missing/invalid anchor fails loud.** A pure indel at `pos0==0` raises
  `ContigStartAnchorError` (no guessed anchor/right-anchor fallback); an injected reference returning an
  empty, multi-base, lowercase, or non-ACGT left anchor raises `ExportReferenceMismatchError` before
  REF/ALT construction.
- **AC-A3 (mechanical) — Reference mismatch fails loud (R-A10).** A row whose `deleted` disagrees with the
  pinned reference raises a `REF_MISMATCH`-class error; no silent correction, no emitted row.
- **AC-A4 (evidence-form) — Structural no-truth boundary.** Given a synthetic input row carrying **sentinel
  truth values** in `label`/`source`/`review_status`/`variant_class`, assert none of those sentinel
  **values** appears in any manifest per-row field value or any VCF data-row `INFO`; assert every data-row
  `INFO=='.'`; assert the manifest per-row field-set is **exactly** `{variant_id, vcf_key, accession,
  contig}`. Whole-value/field structural check, **not** a substring/byte scan — file/header provenance
  (`##source`, snapshot id, criterion words) is allowed.
- **AC-A5 (mechanical) — Determinism (R-A11).** Two runs on identical ids + pinned reference produce
  byte-identical VCF + manifest and identical hashes; rows ordered by the pinned total sort key
  `(contig, POS, REF, ALT)` with `NC_000009.12` before `NC_000016.10`.
- **AC-A6 (mechanical, property-based) — Conservation + bijection.** Over generated SPDI id sets (all
  shapes), `|VCF data rows| == |manifest rows| == |input ids|` and `variant_id ↔ vcf_key` is bijective; an
  injected duplicate/collision is **fatal**. (The real-run CLI asserts the count equals **2,577**.)
- **AC-A7 (evidence-form) — Manifest identity/provenance only.** Per-row fields exactly `{variant_id,
  vcf_key, accession, contig}`; file-level provenance (reference checksums, code version, snapshot id,
  counts, hashes) lives in the VCF `##` header and separate `.provenance.json` sidecar; the JSONL
  manifest has no metadata/header row and no per-label field.

**Adapter (B)**
- **AC-B1 (mechanical) — Evidence via `parse_rationale`, hand-computed.** `get_evidence(canonical_id)`
  returns the fired `(criterion, strength, direction)` calls from `parse_rationale` on the
  canonically-joined BIAS record, matching a hand-computed expected set on a synthetic TSV + manifest fixture.
- **AC-B2 (mechanical) — Ignores `acmgClassification` value.** Mutating or **blanking** the
  `acmgClassification` column **value** (the required column stays present, so `BiasOutputContract` still
  holds) leaves `get_evidence` output byte-identical.
- **AC-B3 (mechanical) — Exact-set contract; typed error + structured kind; no partial eval.** Each failure
  raises the **correct typed error with structured detail**, not eight bespoke classes: malformed manifest →
  `MalformedManifestError`; non-bijection → `ManifestBijectionError` with `kind`; {`duplicate_bias_row`,
  `duplicate_canonical_bias_row`, `unknown_bias_row`, `missing_holdout_row`} each surface as an
  `ExactSetMismatchError` whose structured breakdown names that **kind** (a semantic coordinate mismatch →
  `unknown_bias_row` + `missing_holdout_row`, not a bespoke error); config drift → `ConfigConsistencyError`.
  Nothing served on preflight failure.
- **AC-B4 (mechanical) — Strength map reuse; unmapped fails.** Conversion uses `scorer_config.strength_map`;
  an unmapped fired strength raises `UnmappedStrengthError`; no hardcoded strength.
- **AC-B5 (mechanical) — Config consistency (eval = production).** Preflight asserts
  `set(eval_config.automatable_criteria) == set(scorer_config.included_criteria)` and both exclude
  `FORBIDDEN_CRITERIA`; an **injected deliberately-drifted `ScorerConfig`** (built in-test, no file edited)
  raises `ConfigConsistencyError`. No duplicated filter in the tree.
- **AC-B6 (evidence-form) — Label-free inputs by construction.** Constructor/API inspection proves the
  adapter accepts only BIAS TSV, identity manifest, configs, and canonical normalizer/reference; it has
  no benchmark/label-source parameter. A synthetic, unique benchmark-truth sentinel placed only in the
  export-side label-bearing input is absent from the manifest, BIAS fixture, adapter state, and emitted
  evidence. The test must **not** blacklist ordinary `P`/`B`/pathogenic/benign strings or
  `BiasRecord.acmg_classification`; FR-B4 separately proves the latter is ignored. Static path/import
  proof is AC-D1.
- **AC-B7 (mechanical) — Canonical-SPDI join (M1).** (a) Two **semantically equivalent but differently
  represented** indels (e.g. left- vs right-shifted echo of one insertion) **join to the same manifest
  identity** after canonical normalization; (b) a BIAS record whose reference disagrees / fails to normalize
  **fails loud** (via the normalizer's `REF_MISMATCH`/normalization failure); (c) **two raw BIAS rows
  collapsing to one canonical SPDI** fail as `ExactSetMismatchError(duplicate_canonical_bias_row)`. Join is
  by canonical SPDI, never raw `vcf_key` lookup.

**Audit (C)**
- **AC-C1 (mechanical) — Forbidden reported, not scored.** PP5/BP6/PS4 in raw rationale are reported with
  counts + examples, are `would_be_scored=False` (CP-1), and do not by themselves block.
- **AC-C2 (domain-truth) — Scored ClinVar-derived blocks with counts.** A ClinVar-derived criterion that
  would be scored (PM5/PM1/PP2 under current policy) fails the audit/adapter/terminal-eval closed (CP-3) with
  a **typed exception carrying the complete deterministic report + counts**; PM5/PM1/PP2 legitimacy is
  **UNVERIFIED / pending-Oracle** (no CLEAN terminal eval until the ruling — G4/H11).
- **AC-C3 (mechanical) — No ClinVar mention permits evidence.** A rationale with no ClinVar marker (PVS1
  LoF/LOEUF, PM2 gnomAD-absence, PP3 REVEL/AlphaMissense, BS1 gnomAD-AF) does not block; reported clean.
- **AC-C4 (mechanical) — Case-insensitive; rationale preserved.** `ClinVar`/`clinvar`/`CLINVAR`/`cLiNvAr`
  all match; the whole rationale is preserved verbatim.
- **AC-C5 (mechanical) — False-positive guard + unknown-with-marker fails.** A benign substring collision is
  not misclassified; an unknown/unrecognized criterion carrying a ClinVar marker is **blocked** (CP-3), never
  ignored.
- **AC-C6 (mechanical) — Deterministic all-criteria report.** Covers **every** fired criterion with the
  FR-C2 fields (incl. `detection_source`); identical inputs → identical report + content hash.
- **AC-C7 (mechanical) — CLI nonzero + report persistence.** On a full BIAS TSV with scored ClinVar-derived
  evidence the CLI exits **non-zero** and still **persists + prints** the complete report; on a clean TSV it
  exits zero with the same shape.
- **AC-C8 (mechanical) — No wildcard/default-allow.** `oracle_allowed` is empty and a config wildcard/regex
  allow is rejected by schema validation; a single named allow/ban changes only that criterion's disposition
  (CP-3), never the combiner's scored set (CP-1).

**Cross / pipeline (D)**
- **AC-D1 (evidence-form) — Label-blind static audit (NEW modules).** A **new** forbidden-path/import test
  module proves the **scorer package** and the new `live_source.py` + `clinvar_audit.py` never import
  `raptor.eval.knowns`/`raptor.eval.benchmark` and never open the frozen benchmark/held-out/labels.
  `export.py` + the export CLI are **explicitly OUT of this static scope** — they legitimately run on the
  eval/data-prep side and read only `row["variant_id"]`; the export's key-access + output boundary is proven
  separately by AC-A4/AC-A7.
- **AC-D2 (mechanical) — Pipeline reaches `run_eval` only when clean.** A clean synthetic
  label-free-held-out → export → adapter → `run_eval` produces an `EvalReport`; a fixture with scored
  ClinVar-derived evidence blocks **before** `run_eval` (typed exception).
- **AC-D3 (evidence-form; preservation, G1) — Frozen set unchanged.** The §9.1 **frozen** set remains
  **byte-unchanged** and passing. New coverage lives in §9.2 new modules, never by editing a frozen file.

## 6. Risks (see RISK_REGISTER)
- **R-A2 / H1 (circular validation / trace-cribbing) — existential.** Mitigation: structural no-truth
  boundary (FR-A4); new-module forbidden-import/path audits (AC-D1); fail-closed CP-3 blocker.
- **R-A2c (distribution shift — missense).** PM5 is prime missense signal; blocking it until the Oracle
  rules is deliberate — the gate is missense-stratified, so a wrong PM5 disposition moves the gated number.
- **R-A10 (build/transcript mismatch).** Export verifies every deleted sequence + fails loud on
  mismatch/contig-start; the adapter fails loud on a BIAS record that fails canonical normalization (FR-B8).
- **R-A11 (non-reproducibility).** Deterministic sorted VCF/manifest + content hashes; pinned reference +
  checksum verify; deterministic audit report.

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-06 harness (`run_eval`, `EvidenceSource`, `implied_direction`) + `eval.config` (`FORBIDDEN`/`VALID`) | **built** | Yes — adapter plugs in; audit reuses `combine`/`config` |
| PRD-07 freeze (`scripts/build_tsc_benchmark.py` → frozen held-out) | **built** | Yes (FR-A1) — the export's input |
| Scorer ports (`BiasTsvSource`, `parse_rationale`, `ScorerConfig`) | **built** | Yes (FR-B) — reused, ADR-0007 |
| Canonical normalizer (`SeqRepoGenomicNormalizer`, `configs/ingest/tsc.yaml::reference_checksums`) | **built** | Yes (FR-A2/A3, FR-B8) — pinned FASTA + checksum verify + canonical join |
| ADR-0009 disposition (direct-copy banned; transitive deferred) | **Accepted** | Yes (FR-C) — the audit is its follow-up |
| Pinned GRCh38 FASTA present locally (`RAPTOR_SEQREPO_ROOT`) | data-pull | Yes for a **real** run — not for offline fixture tests (DI) |
| Real BIAS v3.0.0 output TSV (x64 worker, ADR-0008) | deferred | Yes for a **real** gate run — not for the offline build |
| Oracle ruling on PM5/PM1/PP2 (ADR-0009 follow-up) | not started | Yes for a **CLEAN terminal eval** — the audit blocks until it lands |

> **Buildable vs validated (GP-1).** All three deliverables are built + validated offline now against
> synthetic label-free fixtures + property invariants. A **real** run additionally needs the local FASTA,
> the real BIAS output, and the Oracle ruling. Ship the bridge; the measurement is gated on data + Oracle.

## 8. Resolved design decisions
- **Contig naming:** dedicated, ordered, schema-validated `configs/eval/export.yaml` (§10.2); no
  hardcoded accession/contig map.
- **Marker vocabulary:** dedicated `configs/eval/clinvar_markers.yaml`, because it is tied to the BIAS
  annotator version and must re-pin on a BIAS bump (FR-C6).
- **Manifest format:** JSONL only, with exactly four per-row fields; no TSV mirror and no metadata row.
  File-level metadata lives in `{prefix}.provenance.json`.

## 9. Preservation set *(H3 / G1)*

### 9.1 Frozen — byte-unchanged (the checker fails any diff that touches these)
- **PRD-01 scorer parsing oracle:** `tests/scorer/test_oracle_parsing.py`,
  `tests/scorer/fixtures/bias_output_slice.tsv`, `tests/scorer/fixtures/expected_evidence.json` —
  `parse_rationale` still emits the same fired calls (incl. PP5/BP6/PS4/PM5/PM1/PP2 faithfully).
- **PP5/BP6/PS4 structural ban:** `eval.config.FORBIDDEN_CRITERIA` + its ban tests
  (`tests/eval/test_eval_fixes*.py`), plus `configs/eval/tsc2.yaml` / `configs/acmg/tsc.yaml` exclusions.
- **PRD-06 harness label-blindness:**
  `tests/eval/test_ac6_ac7_ac9_harness.py::test_ac6_labels_never_reach_evidence_source` + `run_eval`'s
  signature/behavior (`src/raptor/eval/harness.py`) — unchanged (the adapter conforms to the existing
  `EvidenceSource` Protocol; `run_eval` is not modified).
- **Existing forbidden-import audits:** `tests/eval/test_knowns_ac5_forbidden_import_audit.py`,
  `tests/scorer/test_ac6_no_trace_cribbing.py` — **byte-unchanged** (not edited to add assertions).

### 9.2 New coverage — append-only, in NEW test modules (never edit a frozen file)
- A **new** import/path audit module extending the label-blind proof to `live_source.py` +
  `clinvar_audit.py` (AC-D1), e.g. `tests/eval/test_live_adapter_forbidden_import_audit.py`.
- New conformance-kit modules (§10.4) for export / adapter / audit.
- No new module reads the frozen benchmark/held-out/label files on the scorer or adapter path.

## 10. Build contract (v1 increment) — resolves §8; feeds the loop

> Planner-authored. Gemini writes the AC tests to this surface from the spec only; the Sonnet doer
> implements to pass them (may add, not weaken); GPT re-verifies; the conformance kit
> (`raptor.testkit.invariants`) is wired from the start.

### 10.1 Scope of this increment
- **Built + validated offline now:** FR-A*/B*/C*/D* against synthetic label-free fixtures + property
  invariants; AC-A1..A7, AC-B1..B7, AC-C1..C8, AC-D1..D3. Gene scope TSC1/TSC2.
- **Deferred (real run, not code):** real FASTA, real BIAS output, Oracle ruling. Until the ruling the audit
  **blocks** the terminal eval — by design (ADR-0009), not omission.
- **Independent oracles:** hand-computed VCF `(POS,REF,ALT)` per shape + the VCF 4.2 left-anchor convention
  (AC-A1/A2); the scorer parsing fixture (AC-B1); ClinVar's own BIAS v3.0.0 phrasings (AC-C*) — never the
  implementation's own output.

### 10.2 Config (GP-6; nothing policy-bearing hardcoded)
- **Contig map** — dedicated `configs/eval/export.yaml`, schema-validated with
  `assembly: GRCh38` and an ordered `contigs` list of
  `{accession: NC_000009.12, vcf_contig: chr9}` then
  `{accession: NC_000016.10, vcf_contig: chr16}`. List order is the deterministic VCF sort order;
  accessions are validated against `configs/ingest/tsc.yaml`. The pins are recorded in the
  provenance sidecar.
- **ClinVar marker vocabulary** — `configs/eval/clinvar_markers.yaml` (proposed), **schema-validated,
  version-pinned**: `bias_version: "3.0.0"`; a `markers:` list (case-insensitive tokens/**bounded** phrases
  tied to BIAS v3.0.0 — e.g. `clinvar`, `vcv`, `clinvar pathogenic rate`, `clinvar benign rate`,
  `independent clinvar submitters` — **no regex wildcard / catch-all**); a `transitive_suspect:` list
  (`[PS1, PM5, PM1, PP2, BP1]` — the full ADR-0009 static-lineage set, fail-closed, FR-C6; includes BP1,
  which has no ClinVar marker); an `oracle_allowed:` list (**empty**, FR-C5). Reuses
  `configs/acmg/tsc.yaml::strength_map` + `configs/eval/tsc2.yaml::automatable_criteria` for CP-1.
- **Reference** — reuse `configs/ingest/tsc.yaml::reference_checksums` + the ingest normalizer; no new pin.
- **Thresholds** — untouched (consumed, never set — GP-3).

### 10.3 Module layout + public API (the test contract) — eval-side
> Smallest coherent surface: a library module per deliverable + a thin CLI each; all eval-side (the scorer
> never imports them). A **separate export tool** (not a branch of the PRD-07 freeze) keeps the freeze
> unchanged and makes the label-free boundary one auditable module.

- **`src/raptor/eval/export.py`** — SPDI→VCF 4.2 + identity manifest.
  - `ExportConfig` + `load_export_config(path, ingest_config)` — frozen/schema-validated view of
    `configs/eval/export.yaml`; rejects blank/duplicate accession or VCF-contig pins and any assembly
    other than `ingest_config.assembly`, and requires its accession set to equal the ingest config's
    configured genomic accessions. Tests may construct `ExportConfig` directly.
  - `spdi_to_vcf(variant_id, reference) -> (contig, pos, ref, alt)` — per FR-A2; verifies
    deleted-vs-reference; raises `ExportReferenceMismatchError`/`ContigStartAnchorError` (fail-loud).
    `reference` is an injected FASTA-access port (DI: offline uses a tiny synthetic FASTA; real uses the
    checksummed `ingest.normalizer` reference).
  - `export_holdout(variant_ids, reference, config, *, provenance=None) -> ExportResult` —
    deterministic VCF sorted by `(contig, POS, REF, ALT)` (pinned contig order) + manifest rows +
    provenance/hashes; enforces conservation + bijection (fatal on collision, FR-A6).
    `provenance` is an explicit file-level mapping only; it is never copied into manifest data rows.
  - `ExportResult` = `{vcf_text, manifest_rows, conservation_count, vcf_hash, manifest_hash, provenance}`;
    `write(out_dir, prefix="holdout_input")` emits exactly
    `{prefix}.vcf`, `{prefix}.manifest.jsonl`, and `{prefix}.provenance.json`.
    Manifest per-row fields = exactly `{variant_id, vcf_key, accession, contig}` (FR-A4/A7); provenance
    never masquerades as a manifest data row.
- **`scripts/export_holdout_vcf.py`** — CLI:
  `--heldout <jsonl> --out-dir <dir> [--prefix holdout_input]
  --benchmark-snapshot <id>
  [--export-config configs/eval/export.yaml] [--ingest-config configs/ingest/tsc.yaml]
  [--reference-root <path>]`. It reads the frozen held-out JSONL (accessing only
  `row["variant_id"]`), takes the benchmark snapshot explicitly from the CLI argument (never from a
  label-bearing row), loads the checksum-verified reference, and supplies file-level provenance
  `{benchmark_snapshot, reference_checksums, code_version}` to `export_holdout`. It writes the three
  pinned output files and prints the conservation count (2,577) + hashes. Supersedes
  `make_sample_vcf.py`.
- **`src/raptor/eval/live_source.py`** — the arm's-length adapter.
  - `BiasEvidenceSource(bias_tsv_path, manifest_path, eval_config, scorer_config, normalizer)` — preflights
    at construction (manifest+BIAS load, canonical-SPDI normalization + join via `normalizer` (FR-B8),
    bijection/exact-set validation, config-consistency assertion, ClinVar-derivation audit); reuses
    `BiasTsvSource` + `parse_rationale`. `scorer_config` supplies `strength_map` + `included_criteria`.
  - `.get_evidence(variant_id) -> Iterable[(str, str, str)]` — the exact `EvidenceSource` Protocol `run_eval`
    expects; canonical SPDI → joined BIAS record → calls; never reads `acmg_classification` (FR-B4); fails
    loud on an unknown id.
  - **Typed taxonomy (small hierarchy):** `MalformedManifestError`; `ManifestBijectionError(kind)`;
    `ExactSetMismatchError(sets_by_kind)` with kinds ∈ {`duplicate_bias_row`, `duplicate_canonical_bias_row`,
    `unknown_bias_row`, `missing_holdout_row`}; `ConfigConsistencyError`.
- **`src/raptor/eval/clinvar_audit.py`** — the mechanized audit.
  - `audit_clinvar_derivation(records, eval_config, markers_config) -> ClinVarAuditReport` — over every fired
    criterion; deterministic; per-criterion `{total_fired, clinvar_derived_fired, would_be_scored (CP-1),
    disposition ∈ {forbidden, pending_oracle, oracle_allowed, clean}, detection_source ∈ {marker_detected,
    transitive_suspect_only}, examples}`, plus `blocked: bool` (CP-3), `blocking_criteria`, `content_hash()`,
    `render()`.
  - `ClinVarDerivedEvidenceError(report)` — the typed exception the adapter preflight raises when
    `report.blocked` (carries the full report/counts, FR-C4).
  - `scripts/clinvar_derivation_audit.py` — standalone CLI: audits a full BIAS TSV, persists+prints the
    report, exits non-zero iff `report.blocked` (FR-C7).

Evidence flows to `run_eval` only as `variant_id`-keyed `(criterion, strength, direction)` tuples (PRD-06
§10.6); labels never reach any of these modules (H1).

### 10.4 Conformance kit (wired from the start — new modules, §9.2)
- `tests/eval/test_kit_conformance_export.py` — determinism, conservation, fail-loud-propagation
  (ref-mismatch/contig-start/collision raise), no-truth-leak (no sentinel truth value in any per-row field /
  INFO).
- `tests/eval/test_kit_conformance_live_source.py` — determinism, fail-loud-propagation
  (exact-set/bijection/normalization breach raises at preflight), label-free-input/API boundary
  (unique truth sentinel; no generic pathogenic/benign value blacklist).
- `tests/eval/test_kit_conformance_clinvar_audit.py` — determinism (content_hash stable),
  fail-loud-propagation (scored ClinVar-derived → raises).

### 10.5 Anti-circularity (this slice IS the eval-integrity boundary)
- Structural no-truth boundary (AC-A4/A7); scorer + adapter provably label-blind (AC-B6/AC-D1, new-module
  audits) with the export CLI out of that static scope (proven by its own key-access/output ACs).
- `run_eval` unchanged — the adapter conforms to the existing Protocol; the audit blocks **before**
  `run_eval` (adapter preflight), so no harness change weakens PRD-06's separation.
- Fail-closed audit (AC-C2, CP-3) — a scored ClinVar-derived criterion cannot be silently stripped; the gate
  stays UNVERIFIED until the Oracle rules. Independent oracles only (§10.1).

### 10.6 API specifics pinned by the test contract (the doer must honor these)
- `spdi_to_vcf` treats SPDI position as **0-based**; both-non-empty → `POS=pos0+1`; pure indels → left anchor
  at `pos0-1`, `POS=pos0`; `pos0==0` pure indel → raise; deleted-vs-reference mismatch or an anchor other
  than exactly one uppercase A/C/G/T base → `ExportReferenceMismatchError`.
- `spdi_to_vcf(variant_id, reference)` returns the SPDI **accession** as tuple element 1; only
  `export_holdout(..., config)` maps that accession to the configured VCF contig name. This preserves
  the minimal conversion API without a hidden global contig map.
- The manifest `vcf_key` format is exactly `"{contig}:{POS}:{REF}:{ALT}"`, kept for audit/conservation + raw
  reporting; the adapter's **semantic join is by canonical GRCh38 SPDI** after normalizing BIAS coordinates
  through the injected normalizer (FR-B8) — **not** a raw `vcf_key` string lookup.
- `get_evidence` returns `(criterion.upper(), strength, direction)` from `parse_rationale`, never reads
  `acmg_classification`, and raises on an unknown requested id — never a silent empty list.
- **CP-1 is the sole would-be-scored predicate** (no `oracle_allowed` term); `oracle_allowed` enters only the
  CP-3 BLOCK disposition. The audit and `combine.implied_direction` must never diverge on the scored set.
- `audit_clinvar_derivation` is deterministic (criteria sorted; examples bounded + sorted); `content_hash()`
  excludes run metadata. CLI exit is `0` iff `not report.blocked`, persisting+printing in both cases.

---

## 11. Definition-of-Ready Task Specs (STRATEGY Part II §3.1)

> **Decomposition (STRATEGY Part II §7 — one hypothesis per task, ≤4 reference files).** Fired as **three
> sequenced doer tasks in dependency order A → C → B** (export → audit → integrating adapter), sharing
> this PRD, each with its own ≤4 reference files, preservation directive (slot 3), and inverted failure
> modes. The section labels remain A/B/C by product surface; they are not execution order.

### 11.1 Task Spec — export (A)
```yaml
task_id: live-eval-holdout-export
goal: Emit a deterministic label-free GRCh38 VCF 4.2 + bijective identity manifest for all 2,577 held-out SPDI ids.
motivating_reference: ADR-0009 (follow-up bridge) + PRD-08 §3.A + STRATEGY Part I §7
context_surface:
  - src/raptor/eval/export.py                 # NEW: spdi_to_vcf, export_holdout, ExportResult
  - scripts/export_holdout_vcf.py             # NEW: CLI (reads held-out row["variant_id"] only)
  - configs/eval/export.yaml                  # NEW (or constant): accession->contig pin
  - scripts/devbox/make_sample_vcf.py         # superseded (smoke-only; do not reuse the CLASS-leaking path)
reference_files:                              # <=4
  - scripts/build_tsc_benchmark.py            # held-out JSONL shape + real-normalizer/reference wiring
  - src/raptor/ingest/normalizer.py           # reference read + checksum verify + REF_MISMATCH pattern
  - configs/ingest/tsc.yaml                   # reference_checksums + genome accessions
  - src/raptor/scorer/bias_source.py          # the vcf_key format the manifest must match
acceptance_criteria:
  - {text: "AC-A1 all-shape conversion hand-computed", type: mechanical}
  - {text: "AC-A2 contig-start and short/malformed anchor fail loud", type: mechanical}
  - {text: "AC-A3 reference mismatch fails loud (R-A10)", type: mechanical}
  - {text: "AC-A4 structural no-truth boundary; INFO=='.'; manifest field-set pinned", type: evidence-form}
  - {text: "AC-A5 determinism + total sort key (contig,POS,REF,ALT)", type: mechanical}
  - {text: "AC-A6 conservation + bijection (property-based); real-run count 2,577", type: mechanical}
  - {text: "AC-A7 manifest identity/provenance only", type: evidence-form}
preservation_set:                             # §9.1 frozen — byte-unchanged
  - scripts/build_tsc_benchmark.py
  - tests/scorer/test_ac6_no_trace_cribbing.py
invert_failure_modes:
  - "SNV-only export (repeats make_sample_vcf's gap) -> the 22 anchored + non-SNV held-out silently dropped."
  - "A truth VALUE (variant_class/label/source) flows into VCF INFO or a manifest per-row field -> H1 breach."
  - "Pure-indel anchor guessed at contig start / deleted seq not verified -> wrong-variant VCF (R-A10)."
out_of_scope: running BIAS/Nirvana; the adapter; the audit; threshold changes.
na_allowed: false
prompt_manifest:
  manifest: "docs/prompts/prd08-task-a/manifest.json"
  slot1_id+hash: "slot1-prefix.md@991a73b8bc11cc60702ef0b057b7bf7df031da96554ba889e816d8da91248074"
  slot2_id+hash: "slot2-export-task.md@9c7e60c80bfb55ddcabbf175c0c2c9195592a42913c23cc66cd79903517f83ee"
  slot3_id+hash: "slot3-preservation.md@af71373a0fc515d8a864290ccc81a3d7b5a7f1cde02d96a068ea4f655e58ac95"
  intent_block_present: true
```

### 11.2 Task Spec — adapter (B)
```yaml
task_id: live-eval-bias-evidence-source
goal: An arm's-length eval EvidenceSource over a BIAS TSV + identity manifest, joined by canonical SPDI, computing evidence only from fired rationales.
motivating_reference: PRD-08 §3.B + PRD-06 FR3/FR8/§10.6 + PRD-02 (canonical SPDI) + ADR-0007
context_surface:
  - src/raptor/eval/live_source.py            # NEW: BiasEvidenceSource (+ preflight, canonical join, typed errors)
  - src/raptor/eval/harness.py                # the EvidenceSource Protocol it satisfies (NOT modified)
reference_files:                              # <=4
  - src/raptor/scorer/parse.py                # parse_rationale + UnmappedStrengthError (reused)
  - src/raptor/scorer/bias_source.py          # BiasTsvSource (reused arm's-length parser)
  - src/raptor/ingest/normalizer.py           # injected canonical SeqRepoGenomicNormalizer (FR-B8 join)
  - src/raptor/eval/clinvar_audit.py          # Task C output integrated during adapter preflight
acceptance_criteria:
  - {text: "AC-B1 evidence via parse_rationale, hand-computed", type: mechanical}
  - {text: "AC-B2 ignores acmgClassification value (column kept)", type: mechanical}
  - {text: "AC-B3 exact-set contract; typed error + structured kind; no partial eval", type: mechanical}
  - {text: "AC-B4 strength_map reuse; unmapped fails", type: mechanical}
  - {text: "AC-B5 config consistency eval==production via injected drifted ScorerConfig", type: mechanical}
  - {text: "AC-B6 label-free constructor/API + unique truth-sentinel absence; no generic value blacklist", type: evidence-form}
  - {text: "AC-B7 canonical-SPDI join: equivalent indels join; ref-fail loud; canonical duplicate fatal", type: mechanical}
preservation_set:                             # §9.1 frozen — byte-unchanged
  - src/raptor/eval/harness.py
  - tests/eval/test_ac6_ac7_ac9_harness.py
  - tests/scorer/test_oracle_parsing.py
  - tests/eval/test_knowns_ac5_forbidden_import_audit.py
invert_failure_modes:
  - "Adapter reads acmgClassification -> imports BIAS's combined answer instead of per-criterion evidence."
  - "Raw vcf_key string join trusts BIAS's indel echo -> indels silently mis-join (M1); use canonical SPDI."
  - "Partial eval on an incomplete BIAS/manifest join -> silently scores a subset, hollow-green gate."
  - "A second, drifting included/automatable filter -> eval != production (R-A2)."
out_of_scope: the export; the audit's block policy internals; threshold changes; modifying run_eval.
na_allowed: false
prompt_manifest:                              # placeholders — MUST be filled at Ready preflight
  slot1_id+hash: "<prefix/intent-block: TBD at Ready preflight>"
  slot2_id+hash: "<eval-adapter task template: TBD at Ready preflight>"
  slot3: "Do NOT modify run_eval; conform to the existing EvidenceSource Protocol; reuse BiasTsvSource/parse_rationale; join by canonical SPDI via injected normalizer; assert eval==production criterion set."
  intent_block_present: true
```

### 11.3 Task Spec — ClinVar-derivation audit + blocker (C)
```yaml
task_id: clinvar-derivation-audit
goal: Mechanize the full-output ClinVar-derivation audit; fail-closed on any scored ClinVar-derived criterion; standalone CLI + deterministic report for the Oracle.
motivating_reference: ADR-0009 (transitive deferred to audit) + PRD-08 §3.C
context_surface:
  - src/raptor/eval/clinvar_audit.py          # NEW: audit_clinvar_derivation, ClinVarAuditReport, ClinVarDerivedEvidenceError
  - scripts/clinvar_derivation_audit.py       # NEW: standalone CLI (nonzero on block; always persists report)
  - configs/eval/clinvar_markers.yaml         # NEW: schema-validated, version-pinned markers + transitive_suspect + empty oracle_allowed
reference_files:                              # <=4
  - src/raptor/eval/config.py                 # FORBIDDEN_CRITERIA, VALID_CRITERIA, automatable set (CP-1)
  - src/raptor/eval/combine.py                # would-be-scored policy (must not diverge; no oracle_allowed term)
  - tests/scorer/fixtures/bias_output_slice.tsv  # real PM5/PM1/PP2/PP5/BP6/PS4 rationales (oracle)
  - docs/DECISIONS.md                          # ADR-0009 disposition
acceptance_criteria:
  - {text: "AC-C1 forbidden reported, not scored", type: mechanical}
  - {text: "AC-C2 scored ClinVar-derived blocks with counts; PM5/PM1/PP2 UNVERIFIED", type: domain-truth}
  - {text: "AC-C3 no ClinVar mention permits evidence", type: mechanical}
  - {text: "AC-C4 case-insensitive; rationale preserved", type: mechanical}
  - {text: "AC-C5 false-positive guard + unknown-with-marker blocks", type: mechanical}
  - {text: "AC-C6 deterministic all-criteria report + detection_source + content hash", type: mechanical}
  - {text: "AC-C7 standalone CLI nonzero + report persistence", type: mechanical}
  - {text: "AC-C8 no wildcard/default-allow", type: mechanical}
preservation_set:                             # §9.1 frozen — byte-unchanged
  - eval.config.FORBIDDEN_CRITERIA + its ban tests (tests/eval/test_eval_fixes*.py)
  - tests/scorer/fixtures/expected_evidence.json
invert_failure_modes:
  - "A scored ClinVar-derived criterion is silently stripped and eval continues -> no counts for the Oracle, hollow gate."
  - "oracle_allowed leaks into the would-be-scored predicate (CP-1) -> combiner and audit diverge."
  - "A permissive wildcard/default-allow lets an unaudited ClinVar-derived criterion through (R-A2)."
  - "Fragile English matching misses PP2's proportion phrasing -> the transitive_suspect net must still block it."
out_of_scope: deciding PM5/PM1/PP2 legitimacy (Oracle); the export; the adapter's join internals; threshold changes.
na_allowed: false
prompt_manifest:                              # placeholders — MUST be filled at Ready preflight
  slot1_id+hash: "<prefix/intent-block: TBD at Ready preflight>"
  slot2_id+hash: "<clinvar-audit task template: TBD at Ready preflight>"
  slot3: "Never silently strip a scored ClinVar-derived criterion; fail closed with the full report; no wildcard allow; keep CP-1 (would-be-scored) identical to combine.implied_direction and free of oracle_allowed."
  intent_block_present: true
```

> **Ready preflight (STRATEGY Part II §3.1).** Before each doer runs, the operator/checker verifies the spec
> is complete **and** the `prompt_manifest` is persisted with real `slot{1,2}` ids+hashes + a concrete slot-3
> directive. The placeholders above are **not yet filled** — a spec with an unexplained missing slot is
> **not Ready** (H10).

---

## 12. Self-audit (planner) — empirical allele profile + no-truth boundary

**Allele profile (verified locally against the frozen held-out; planning facts, not fixtures):** 2,577
held-out ids = 707 `NC_000009.12` + 1,870 `NC_000016.10`; shapes = 2,416 SNV + 4 MNV + 135 both-non-empty
delins + 3 pure insertion + 19 pure deletion; 0 malformed, 0 non-ACGT.

- **Coverage:** FR-A2 maps exactly onto the profile — **2,555 both-non-empty** rows (2,416 SNV + 4 MNV + 135
  delins) take the `POS=pos0+1` path; the **22 anchored** rows (3 insertions + 19 deletions) take the
  left-anchor path; `2,555 + 22 = 2,577` (AC-A6). SNV-only export would silently drop the non-SNV rows —
  inverted as a §11.1 failure mode and blocked by AC-A6.
- **Contig-start risk:** the 22 anchored rows are the only ones needing a left anchor; AC-A2 forces fail-loud
  at `pos0==0` rather than a guess.
- **Empirical output-conversion probe (independent of BIAS echo):** the SPDI→VCF math was probed against the
  pinned reference — **all 2,577 convert, 0 reference mismatches, 0 collisions, 0 contig-start cases**. FR-B8's
  canonical-SPDI join deliberately does **not** rely on BIAS echoing these coordinates; it re-normalizes BIAS
  output independently, so an indel-representation drift on the BIAS side cannot silently mis-join.

**No-truth boundary check:** the export input is label-bearing, but FR-A1 accesses only `row["variant_id"]`;
AC-A4's structural check (sentinel truth values, whole-value/field) proves no
label/source/review_status/snapshot/variant_class **value** reaches a VCF data-row `INFO` or a manifest
per-row field, and the field-set is exactly `{variant_id, vcf_key, accession, contig}` — closing the
make_sample_vcf `CLASS=` leak without a brittle byte/substring ban. The adapter + scorer are label-blind by
construction (AC-B6/AC-D1, new-module audits); `run_eval` is unchanged, so PRD-06's
`test_ac6_labels_never_reach_evidence_source` still holds. The audit fails **closed** (AC-C2, CP-3): a scored
ClinVar-derived criterion blocks the terminal eval with the full counts, so no hollow-green gate runs before
the Oracle rules PM5/PM1/PP2 (labelled **UNVERIFIED**, no new ACMG class).

**Design decisions (flagged for the operator/Oracle):** (1) **separate export tool** (not a branch of the
PRD-07 freeze) — keeps the freeze unchanged, one auditable module. (2) **Canonical-SPDI join, not raw
`vcf_key` echo** (FR-B8/M1) — BIAS is re-normalized through the injected `SeqRepoGenomicNormalizer` and joined
by canonical GRCh38 SPDI; `vcf_key` kept for audit/conservation only. (3) **Config consistency by explicit
assertion** (`eval.automatable_criteria == scorer_config.included_criteria`), injectable via a drifted
`ScorerConfig` (FR-B6). (4) **Fail-closed belt-and-suspenders** — markers (counts for the Oracle) **plus** an
ADR-0009 `transitive_suspect` declaration, `detection_source` keeping the two honest; schema-validated,
version-pinned, no wildcard (FR-C6). (5) **Audit blocks at adapter preflight, before `run_eval`** — no harness
change. (6) **Small typed error taxonomy** — structured detail over a per-condition class explosion; a
semantic coordinate mismatch surfaces as unknown+missing (B5). (7) **CP-1..CP-3 stated once** —
`would_be_scored` excludes `oracle_allowed`; unknown-with-marker blocks; audit and combiner cannot diverge (B3).
