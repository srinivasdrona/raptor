# PRD-07 — ClinVar Knowns → Benchmark Labels Loader

> Status: **Ready** (authored just-in-time for Track A — the frozen known-variant benchmark that
> PRD-06's eval harness scores against). Planner-authored spec + §10 build contract.

## 1. Problem / why

PRD-06 (the eval harness, signed off) consumes `LabeledVariant` rows and freezes them into the
benchmark via `build_benchmark`. It does **not** source them. Today the only producers of
`LabeledVariant` are test fixtures. Before the first gated VUS run we need the **real** frozen
benchmark of KNOWN (already-classified) TSC1/TSC2 variants — the truth set the Tier-1/2 scorer is
graded against.

The known labels live in the **same** pinned ClinVar `variant_summary.txt.gz` snapshot the ingest
path (PRD-02) already reads — but PRD-02's `RawVariant` **deliberately drops every label column**
(AC5: the scorer must never see a ClinVar-provided answer). This PRD builds the **label-side**
counterpart: a loader that reads the label columns PRD-02 skips (`ClinicalSignificance`,
`ReviewStatus`, `NumberSubmitters`, protein consequence from `Name`) and emits `LabeledVariant`
rows for PRD-06 — keeping the scorer path structurally label-blind (H1).

## 2. Scope

**In:**
- A `LabeledVariant` reader over a pinned ClinVar `variant_summary.txt.gz` snapshot, gene-filtered to
  TSC1/TSC2, reusing PRD-02's `VariantSummaryContract` (column contract) and `Normalizer` (canonical
  GRCh38 SPDI `variant_id`, so labels JOIN to scored variants by identity — PRD-06 `metrics.py`).
- ClinVar `ClinicalSignificance` → label mapping (P/LP/LB/B/VUS/Conflicting).
- Protein-consequence → `variant_class` stratum (missense / truncating / other) parsed from the HGVS
  `p.` in `Name` (missense reported separately — R-A2c).
- `ReviewStatus` → `review_status` passthrough + ClinVar **star-rating → source-rank** mapping (feeds
  PRD-06's label hierarchy) and the conflicting/single-submitter exclusion inputs.
- `raptor_influenced` = `False` for every real-ClinVar row (RAPTOR has submitted nothing; the field
  exists so a future self-influenced label can be excluded — R-A2).
- A frozen, provenanced output the harness consumes; deterministic given the pinned snapshot.

**Out:**
- Downloading/pinning the real ClinVar snapshot + confirming MANE versions (Track A2 — a governance
  data-pull step; this module is built + tested offline against fixture rows, like PRD-02).
- Any scoring / ACMG logic (PRD-01), any normalization beyond reuse of PRD-02's normalizer.
- Setting Oracle thresholds (Track C — governance) or live BIAS/Nirvana scoring (Track B — x64).

## 3. Functional requirements

- **FR1 — Contract-checked label read:** assert the `variant_summary` column contract
  (`VariantSummaryContract`, reuse) before parsing; gene-filter to TSC1/TSC2 exactly as PRD-02's
  reader (`GeneSymbol` exact **or** multi-gene `subset of N genes: A:B:...` form). Fail loud on drift
  (R-B1), never silently mis-align.
- **FR2 — Identity join key:** each label row's `variant_id` is the **same canonical GRCh38 SPDI**
  PRD-02's `Normalizer` produces for the same coordinates, so a label joins to its scored variant by
  identity. A row whose coordinates cannot be normalized (imprecise SV/CNV, non-ACGT allele) is **not
  silently dropped** — it is surfaced (skipped-with-reason count), never emitted as a mis-identified
  label.
- **FR3 — Label mapping:** map `ClinicalSignificance` → `{P, LP, LB, B, VUS, Conflicting}` by the
  canonical ClinVar aggregate strings (see §10.2). Multi-value / drug-response / risk-allele / "not
  provided" strings map to a non-scoreable label (never force-fit into P/LP/LB/B). `Conflicting` is a
  first-class label (PRD-06 excludes it).
- **FR4 — Variant-class stratum:** derive `variant_class ∈ {missense, truncating, other}` from the
  HGVS `p.` in `Name` (missense = single aa substitution; truncating = nonsense/frameshift/
  stop-gain/start-loss; everything else, incl. synonymous/splice/in-frame/no-p. = other). Parsing is
  conservative: an unparseable `p.` → `other`, never guessed into `missense`.
- **FR5 — Review status → exclusion inputs + source rank:** pass `ReviewStatus` through to
  `LabeledVariant.review_status` (PRD-06's `_excluded` keys on `"conflicting"`); set
  `submitter_count` from `NumberSubmitters`; map ClinVar review level (star rating) → PRD-06 source
  rank (`reviewed by expert panel`→`clingen_vcep`; `practice guideline`→`clingen_vcep`;
  `criteria provided, multiple submitters, no conflicts`→`clinvar_2star_concordant`;
  `criteria provided, single submitter`/`conflicting`→`clinvar`), so the label hierarchy resolves
  duplicates by confidence.
- **FR6 — Never invent, never launder:** `raptor_influenced=False` for all rows; `source="clinvar"`;
  `snapshot` = the pinned `labels_snapshot` (must equal PRD-06 `config.labels_snapshot` — PRD-06
  already fails loud on mismatch). The loader reads ONLY the label + identity columns; it does not
  read or emit any scorer input.
- **FR7 — Deterministic + provenanced:** identical pinned snapshot → record-identical `LabeledVariant`
  stream (order-stable) and an identical content hash (R-A11); every emitted row carries snapshot id/
  date + source-file checksum provenance. Reuses PRD-02's `SourceChecksumMismatchError` (refuse to
  read a different file than pinned).
- **FR8 — Structural label/scorer separation (H1):** this module lives on the **eval** side and is
  never imported by `src/raptor/scorer/` or `src/raptor/ingest/`'s normalization path; a
  forbidden-import audit proves the scorer cannot reach a label.

## 4. Non-functional

- **Reproducibility (R-A11):** pure function of the pinned snapshot + config; no network at read time.
- **Provenance (GP-5/GP-9):** snapshot id/date, source-file checksum, code version on the frozen output.
- **Anti-circularity (H/R-A2/H1):** labels enter ONLY here → `build_benchmark`; the scorer path is
  untouched and provably label-blind; ClinVar-assertion-derived criteria (PP5/BP6) are already
  structurally barred from the combiner (PRD-06). PP5/BP6 circularity + label-blindness are the whole
  point — this loader must not create a back-door.

## 5. Acceptance criteria *(→ OPERATING_MODEL gates)*

- **AC1 — Label mapping correctness (independent oracle):** a frozen fixture of
  `{ClinicalSignificance string → expected label}`, expected values taken from **ClinVar's published
  aggregate-classification vocabulary** (not the implementation), reproduced exactly; includes P/LP/
  LB/B/VUS/Conflicting and at least one non-scoreable ("drug response", "not provided").
- **AC2 — Variant-class stratum:** a frozen fixture of `{Name/p. → expected class}`, hand-labelled
  missense vs truncating vs other (nonsense, frameshift, splice, synonymous, in-frame, no-p.);
  reproduced exactly; an unparseable `p.` yields `other`, never `missense`.
- **AC3 — Identity join:** a labelled row's `variant_id` equals PRD-02's normalizer output for the
  same coordinates (shared fixture) → a label joins to its scored variant; an imprecise/non-ACGT row
  is surfaced (skipped-with-reason), never emitted with a wrong id.
- **AC4 — Exclusions wired to PRD-06:** feeding the loader's output into `build_benchmark` drops
  conflicting / single-submitter / RAPTOR-influenced / non-scoreable rows and keeps the rest, with the
  label hierarchy resolving a duplicated `variant_id` to the highest-ranked source (end-to-end with
  the REAL PRD-06 `build_benchmark`, not a mock).
- **AC5 — Trace-cribbing separation (H1):** a forbidden-import/audit test proves no scorer/ingest
  normalization module imports this loader, and the loader reads no scorer input; labels reach only
  `build_benchmark`.
- **AC6 — Contract drift fails loud:** a `variant_summary` header missing a depended-on column raises
  `SourceContractError`; a pinned-checksum mismatch raises `SourceChecksumMismatchError`.
- **AC7 — Deterministic + provenanced:** identical fixture snapshot → identical `LabeledVariant`
  stream + identical content hash; provenance fields populated.

## 7. Dependencies

- **PRD-02 (built):** reuse `VariantSummaryContract`, the gene-filter, `SourceChecksumMismatchError`,
  and the `Normalizer` (canonical SPDI `variant_id`). *Open coupling:* PRD-02's `Normalizer` currently
  defers `hgvs_c/p` to UTA — but `variant_id` (genomic SPDI) is available now and is the only join key
  we need; `variant_class` comes from ClinVar's `Name` p., not from UTA.
- **PRD-06 (built):** consumes `LabeledVariant` (exact shape: `variant_id, label, review_status,
  submitter_count, source, snapshot, raptor_influenced, variant_class`) → `build_benchmark`.
- **Track A2 (data pull, separable/governance):** pin a real ClinVar `variant_summary.txt.gz`
  snapshot (id/date/sha256) + confirm MANE transcript versions. Not required to build/test this module
  (fixtures), required to produce the real benchmark.
- **Track C (governance, parallel):** Oracle thresholds — independent; the benchmark can be frozen
  before thresholds are pre-registered (gate stays `UNVERIFIED`).

## 10. Build contract (the test contract the doer must honor)

### 10.1 Independent oracle for tests
- **AC1 label map** = ClinVar's published aggregate-classification vocabulary (not self-output).
- **AC2 variant_class** = hand-computed from HGVS `p.` (not the parser's own output).
- **AC3 identity** = PRD-02 `Normalizer`'s canonical SPDI (the existing, independently-tested join key).

### 10.2 Config (GP-6)
- **Snapshot pins on `EvalConfig`** (benchmark-source provenance, co-located with `labels_snapshot`):
  add an **optional** field `clinvar_snapshot_file_checksum: str = ""` to `EvalConfig` (default `""`
  = no pin / skip the guard). `make_eval_config(**overrides)` passes it through unchanged (no conftest
  edit needed). The loader reads the checksum pin from `config` and reuses the ingest reader's
  checksum-guard semantics (a 64-hex pin that disagrees with the file's real sha256 → raise).
- **Label + variant_class vocabularies are CANONICAL BUILT-INS**, not config knobs — ClinVar's
  aggregate-classification vocabulary and the HGVS-`p.` consequence rules are fixed standards (like the
  ACMG-2015 code set in `config.VALID_CRITERIA`); they are pinned in code with the AC1/AC2 tests as the
  independent oracle. Same for the `ReviewStatus → source-rank` map (FR5). This keeps GP-6's intent
  (no *policy* hardcoded) while not pretending a fixed vocabulary is a tunable.
  - `ClinicalSignificance → label`: `Pathogenic→P`, `Likely pathogenic→LP`, `Likely benign→LB`,
    `Benign→B`, `Pathogenic/Likely pathogenic→P`, `Benign/Likely benign→B`, `Uncertain significance→VUS`,
    `Conflicting interpretations of pathogenicity→Conflicting`; anything else (`drug response`,
    `risk factor`, `not provided`, `association`, `other`, multi-condition combos) → a non-scoreable
    sentinel (excluded downstream), **never** force-fit.
  - `ReviewStatus → source rank`: as FR5 (expert panel/practice guideline→`clingen_vcep`; multiple
    submitters no conflicts→`clinvar_2star_concordant`; single submitter/conflicting→`clinvar`).

### 10.3 Module layout + public API (the test contract) — eval-side, e.g. `src/raptor/eval/knowns.py`
- `map_clinical_significance(sig: str, cfg=None) -> str` — canonical built-in map; `cfg` optional/ignored.
- `classify_variant(name: str) -> str` — variant_class ∈ {missense, truncating, other} from the p. HGVS.
- `LabeledVariantReader(path, config, normalizer, *, snapshot_id=None, snapshot_date=None)` — iterable
  yielding `raptor.eval.model.LabeledVariant`; contract-checks, reads the checksum pin from
  `config.clinvar_snapshot_file_checksum` (guard), gene-filters, normalizes to `variant_id`, maps
  label + class + review status; `LabeledVariant.snapshot = snapshot_id or config.labels_snapshot`;
  surfaces skipped-with-reason (a `.skipped` list — never a silent drop, R-A10-style).
- `load_known_labels(path, config, normalizer) -> list[LabeledVariant]` — the frozen, order-stable
  materialization (feeds `build_benchmark`); `snapshot = config.labels_snapshot`.
- The doer also adds the optional `EvalConfig.clinvar_snapshot_file_checksum: str = ""` field (§10.2).
- Reuses `raptor.ingest.contract.VariantSummaryContract`, `raptor.ingest.reader`'s checksum guard
  (`SourceChecksumMismatchError`), and an injected `raptor.ingest.normalizer.Normalizer`
  (dependency-injected, never imported into the scorer path).

### 10.4 Conformance kit (wired from the start)
`tests/eval/test_kit_conformance_knowns.py` wires `raptor.testkit.invariants`:
- **determinism** (same fixture snapshot → identical stream + content hash);
- **conservation** (every input row → exactly one of {emitted LabeledVariant, skipped-with-reason} —
  no silent drop);
- **fail-loud-propagation** (contract/checksum breach raises, not swallowed);
- **grounding** (every emitted `variant_id` is the normalizer's real output for that row's coords,
  never a fabricated id) — candidates for kit promotion if they recur.

### 10.5 Anti-circularity (the reason this is a separate module)
- Labels enter ONLY here → `build_benchmark`; **the scorer/ingest normalization path never imports
  this loader** (AC5 forbidden-import audit).
- `variant_class` for stratification comes from ClinVar's `Name` p. — descriptive, never a scorer output.
- No label ever flows to `evidence_source` (PRD-06 FR8/AC6 already enforces this downstream).

### 10.6 API specifics pinned by the test contract
- `LabeledVariant` field order/shape is PRD-06's (`variant_id, label, review_status, submitter_count,
  source, snapshot, raptor_influenced, variant_class`); tests construct/compare by keyword.
- `classify_variant("NM_000548.5(TSC2):c.1832G>A (p.Arg611Gln)") == "missense"`;
  `... "(p.Arg611Ter)"/"(p.Gln1503*)"/"...fs..." == "truncating"`; a synonymous/splice/no-p. Name →
  `"other"`.
- `map_clinical_significance("Uncertain significance", cfg) == "VUS"`;
  `"Conflicting interpretations of pathogenicity" == "Conflicting"`; `"drug response"` → non-scoreable.
- Deterministic order: input file order preserved; `load_known_labels` is a pure function of (file, config).
