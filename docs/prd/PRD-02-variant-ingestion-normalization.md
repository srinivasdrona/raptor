# PRD-02 — Variant Ingestion & Normalization

> **Status:** Ready (v1 increment — build contract §10) · **Owner:** @dronasrinivas · **Phase:** 0 (STRATEGY §7) · **Last updated:** 2026-07-08
>
> **Format:** standard lean PRD; acceptance criteria feed the build-loop gates (OPERATING_MODEL §4)
> and the eval mapping (EVAL_PLAN §3.2). One feature per PRD.
>
> **Links:** STRATEGY §6 (Tier 1/2 substrate) · GP-4, GP-5, GP-6, GP-9, GP-10 · RISK_REGISTER
> R-A10/R-B1/R-A9/R-A11/H7 · PRD-01 (consumer) · PRD-03 (KB schema, output target).

## 1. Context / problem

PRD-01 consumes *normalized* variants. ClinVar records arrive in heterogeneous forms
(transcript-version drift, alias HGVS, differing builds); left unnormalized, evidence silently
mismatches across ClinVar ↔ BIAS-2015 ↔ LitVar2 (**R-A10**) — the same variant appears as two
identities and its evidence splits or collides. This feature is the **data foundation** of the
measurable half: one canonical identity per variant.

**v1 ingestion scope: TSC1 + TSC2** (gene-agnostic engine, GP-6); the first **validation gate**
(PRD-06) is **TSC2-first** — TSC1 is the rarer gene with fewer knowns, so its metric gate is a
fast-follow once the methodology is proven on the better-powered TSC2 set (EVAL_PLAN §1.2).

## 2. Goal & non-goals

**Goal:** from a pinned ClinVar snapshot, ingest TSC2 variants and emit **canonical normalized variant
records** — HGVS (g./c./p.) + SPDI on a config-pinned **MANE Select transcript + genome build
(GRCh38)** — with resolvable provenance, via the PRD-03 KB schema.

**Non-goals (explicit):**
- ACMG scoring / predictor annotation (PRD-01).
- The KB storage schema itself (PRD-03 — consumed, not defined here).
- TSC1 and other genes; literature retrieval; any classification.

### 2.1 Canonical variant identity (the join key)

The primary key every downstream join uses is **`variant_id` = the normalized GRCh38 genomic SPDI**
(sequence `accession.version : position : deleted : inserted`). HGVS g./c./p. and the ClinVar
VCV/VariationID are **annotations + provenance**, never the key. Collision policy: **many source rows
→ one `variant_id`** is expected (merged, provenance retained); **one source row → multiple
`variant_id`** fails loud → manual queue (R-A10). PRD-01 FR1 joins on this `variant_id`.

## 3. Users & need

| User | Need this serves |
|---|---|
| PRD-01 scorer | Canonical input keyed on **one** variant identity, so criteria attach to the right variant. |
| EVAL harness | Benchmark labels and scores must align on the **same normalized identity** — otherwise AC1 metrics are meaningless (comparing labels and scores for different representations of the "same" variant). |

## 4. Functional requirements

- **FR1 — Ingest** from a pinned ClinVar **`variant_summary.txt.gz`** snapshot (v1 source; VCV XML is a fast-follow for richer accessions), filtered to gene **TSC2**; record snapshot date + file checksum.
- **FR2 — Normalize** each variant to a canonical **GRCh38 genomic SPDI** (→ `variant_id`, §2.1) plus HGVS g./c./p. on the config-pinned **MANE Select transcript**, using a recognized normalizer (candidates §9); left-align/shift per SPDI rules; pin normalizer + reference-data versions.
- **FR3 — Variant-class matrix:** exact SNV/MNV/small-indel → full SPDI + g./c./p.; non-coding/synonymous/splice-region → SPDI + g. (c./p. **nullable, with reason**); **imprecise SV/CNV, complex/multi-gene, or transcript-projection failures → manual queue** (never forced). Class recorded per record.
- **FR4 — Resolve alias / transcript-version drift** to the pinned transcript; anything unnormalizable → **manual queue with a structured record** (FR6), never silent-drop (R-A10).
- **FR5 — Emit records** with a **pinned-snapshot-resolvable `source_ref`** = `{VariationID/VCV, snapshot_id+date, source_file_checksum, row_locator, raw_source_value}` (GP-9) + provenance (GP-5), via the PRD-03 schema (or a minimal stub).
- **FR6 — Manual-queue schema:** each flagged variant records `{raw_input, source_ref, failure_stage, error_code, reason, attempted_coords/HGVS, tool_error, config_pins, run_id, excluded_from_scorer: true}`.
- **FR7 — Deterministic core:** deterministic record content (`variant_id`, HGVS, class, source_ref) is separated from **run metadata** (`run_id`, `generated_at`), which is excluded from the determinism hash/diff (AC2).
- **FR8 — Config-driven (GP-6):** MANE version, transcript `accession.version`, protein `accession.version`, genome assembly+accession, reference FASTA/UTA checksum, normalizer version, and ClinVar snapshot id — all in `configs/ingest/*.yaml`; nothing hardcoded.
- **FR9 — Source-contract check (R-B1):** assert the `variant_summary` column contract before parsing; **fail loudly** on drift; a malformed fixture must fail.

## 5. Non-functional requirements

- **Performance:** dominant cost is normalization (external API vs local), not raw compute. A benchmark command is provided and wall-clock **recorded**; the pass/fail target is **not yet set → non-gating** until measured (GP-9/H13 — no fabricated target).
- **Provenance (GP-5):** deterministic record + separate run metadata (FR7); the source snapshot id/date/checksum live *inside* the deterministic record.
- **Licensing:** ClinVar is **public-domain**. **GP-10:** if an external normalizer is used, only public variant coordinates are sent — never private data.
- **Reproducibility (R-A11):** a **local, version-pinned normalizer is the default** (pinned inputs → identical output); an external API is allowed **only** via a versioned, checksummed response cache with offline replay.
- **Config-driven (GP-6).**

## 6. Acceptance criteria *(→ EVAL_PLAN §3.3 mapping; become OPERATING_MODEL gates)*

- **AC1 — No silent drops:** `|input| = |normalized| + |manual-queue|`; **0** dropped; manual-queue records conform to FR6.
- **AC2 — Determinism (R-A11):** re-run on the pinned snapshot + versions → **deterministic-content-identical** (run metadata excluded, FR7).
- **AC3 — Canonical correctness (frozen fixture):** a committed canary fixture pairs **exact raw ClinVar inputs → expected `variant_id`/HGVS/SPDI**, with expected values derived **independently of the implementation** and reviewed (*not* generated by the normalizer under test); the module reproduces them exactly; transcript+build equal the pins. *(Checkable now, no oracle.)*
- **AC4 — Grounding (GP-9):** 100% of records carry a **pinned-snapshot-resolvable** `source_ref` (FR5); **0** null/unresolvable.
- **AC5 — No trace-cribbing (H1):** ingestion reads no benchmark/label/oracle file (G2 audit — manual until lint).
- **AC6 — Source-contract (R-B1):** the `variant_summary` column-contract test passes on a real-format fixture **and** a deliberately malformed fixture **fails loudly**.
- **AC7 — NFR checks:** config schema-validates with **no hardcoded pins** (GP-6, FR8); provenance fields complete (GP-5); performance benchmark **recorded** (non-gating until a target is set).

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-03 · KB schema (output target) | backlog | Yes (FR4) — or a minimal evidence/variant-record stub |
| Pinned ClinVar snapshot (TSC2) | not started | Yes (FR1) — fixtures for dev |
| MANE Select transcript set + GRCh38 reference | not started | Yes (FR2) |
| Normalization tool/library (§9) | not started | Yes (FR2) |

> **Buildable vs validated:** buildable now against fixtures + a local normalizer; **AC3 canary is
> checkable now**. Full-corpus ingest needs the ClinVar snapshot + reference data downloaded — a
> deploy-time step, not a code blocker.

## 8. Risks (see RISK_REGISTER for mitigations)

R-A10 (build/transcript mismatch — the core risk this feature exists to mitigate) · R-B1 (ClinVar
schema/API change — FR7 contract test) · R-A9 (reference-data errors) · R-A11 (reproducibility) ·
H7 (config drift) · **GP-10/R-G4** (only public coordinates leave, if an external normalizer is used).
**GP-4:** reuse an existing normalizer, not a hand-rolled HGVS parser — with its own canary validation
(AC3), not trust-transfer.

## 9. Open questions

- **Normalizer choice** (implementation detail): local `hgvs` (biocommons) + pinned **UTA** *(default, for R-A11/GP-5)* vs mutalyzer vs `bcftools norm`. An external SPDI API is used **only** via cached replay (§5).
- VCV XML as a fast-follow source for richer accessions (v1 uses `variant_summary.txt.gz`).
- **Exact pin values** (MANE Select version, transcript/protein `accession.version`, GRCh38 patch, reference/UTA checksum, normalizer version) must be filled into `configs/ingest/` **before the PRD is Ready** — they are config keys (FR8), not code. *(Resolved in §10.2, values flagged `confirm`.)*

## 10. Build contract (v1 increment) — resolves §9; feeds the loop

> Written by the planner (OPERATING_MODEL §2). The test-author writes tests to this public
> surface; the doer implements to pass them; nothing here is trace/oracle. Every pin marked
> `confirm` is a **config key** to lock before a real-corpus run (GP-9 — not fabricated, not gating
> the offline build). This section makes PRD-02 **Ready**.

### 10.1 Reference-data strategy (resolves §9 normalizer + reference)

**v1 uses a minimal, pinned, checksummed reference — NOT the full ~13 GB SeqRepo snapshot.** The engine
is **gene-agnostic** (GP-6); for the v1 gene set **{TSC1, TSC2}** the only sequences needed are the two
gene chromosomes and their MANE transcripts:

| Gene | Chromosome (genomic, for SPDI) | MANE transcript / protein (for c./p.) |
|---|---|---|
| TSC2 | GRCh38 chr16 — `NC_000016.10` | `NM_000548.5` / `NP_000539.2` |
| TSC1 | GRCh38 chr9 — `NC_000009.12` (minus strand) | `NM_000368.5` / `NP_000359.2` |

Total ~70 MB (two chromosomes + two transcripts), offline-friendly, and *more* reproducible than a
moving full-snapshot (R-A11). Full SeqRepo/fleet reference is deferred to more-genes / Tier-3.

- **`variant_id` = genomic SPDI needs only the genomic sequence — no UTA, strand-independent.** This is
  the join key (§2.1), buildable+validatable now for **both** genes (TSC1's minus strand does not affect
  genomic SPDI).
- **c./p. projection needs transcript↔genome alignment = UTA** (Postgres + pinned dump); TSC1's minus
  strand matters here. **Separate adapter, gated on the UTA setup step**; not on the genomic critical path.

### 10.2 Config = gene-list → `configs/ingest/*.yaml` (FR8; nothing hardcoded, GP-6)

Config is **gene-list-driven** (never a hardcoded single gene). Shared pins + a per-gene block:

| Key | Value | Note |
|---|---|---|
| `genes` | `[TSC1, TSC2]` | v1 ingestion set; gene-agnostic engine |
| `assembly` / `assembly_patch` | `GRCh38` / `p14` | `confirm` patch |
| `mane_release` | `1.4` | `confirm` against locked MANE release |
| `normalizer` | `{tool: <hgvs\|bcftools>, version: <pinned>}` | doer picks; `confirm` |
| `clinvar_snapshot_id` / `_date` / `_file_checksum` | *(set when snapshot pinned)* | FR1 |
| **per gene → `genome_accession`** | TSC2 `NC_000016.10` · TSC1 `NC_000009.12` | RefSeq GRCh38 |
| **per gene → `transcript_accession`** | TSC2 `NM_000548.5` · TSC1 `NM_000368.5` | `confirm` .version |
| **per gene → `protein_accession`** | TSC2 `NP_000539.2` · TSC1 `NP_000359.2` | |
| `reference_checksums` | `{NC_000016.10, NC_000009.12, NM_000548.5, NM_000368.5: <sha256>}` | R-A11 |

Config **schema-validates**; a missing/blank required pin **fails loudly** (AC7). `confirm` pins do
not block the offline build; they gate a real-corpus / c./p. run.

### 10.3 Module layout + public API (the test contract) — `src/raptor/ingest/`

- **`config.py`** — `IngestConfig` (frozen dataclass) + `load_config(path) -> IngestConfig`;
  schema-validates, raises on missing pin (AC7/FR8).
- **`model.py`** — `RawVariant` (parsed ClinVar row + source-ref fields), `VariantClass` (enum: `SNV`,
  `MNV`, `SMALL_INDEL`, `NONCODING_SPDI_ONLY`, `SPLICE_REGION`, `IMPRECISE_SV`, `COMPLEX_MULTIGENE`,
  `PROJECTION_FAILURE`), `NormalizedVariant` (`variant_id`, `hgvs_g/c/p` + null_reasons,
  `variant_class`), `ManualQueueItem` (FR6 fields), `NormalizationOutcome = NormalizedVariant | ManualQueueItem`.
- **`contract.py`** — `VariantSummaryContract.assert_columns(header)`; raises `SourceContractError`
  on drift (FR9/AC6).
- **`reader.py`** — `ClinVarVariantSummaryReader(path, gene, config)`: contract-check then yield
  `RawVariant` filtered to gene, each carrying `{VariationID, snapshot_id, snapshot_date,
  source_file_checksum, row_locator, raw_source_value}` (FR1/FR5).
- **`normalizer.py`** — `Normalizer` **Protocol port** (FR2): `normalize(raw, config) -> NormalizationOutcome`.
  Real impl `SeqRepoGenomicNormalizer` (chr16-backed: `variant_id` + `hgvs_g`; c./p. via UTA adapter
  when present, else `hgvs_c/p = None` with null_reason `"awaiting_uta_projection"`). FR3 class-routing
  lives here (`classify.py` optional).
- **`pipeline.py`** — `run_ingest(config, reader, normalizer, store) -> IngestReport`: read →
  contract → normalize → route → write-to-KB (`store.stage_source_ref` → `store.stage_variant(source_ref_ids=…)`
  **or** `store.stage_manual_queue`, then `store.publish`). **Enforces AC1 conservation:**
  `|input| = |normalized| + |queued|`, 0 dropped.
- **`report.py`** — `IngestReport`: deterministic content (counts, sorted `variant_id` list, class
  histogram, manual-queue summary) **separate** from run metadata (`run_id`, `generated_at`);
  `content_hash()` excludes run metadata (FR7/AC2).

Writes go through the **committed PRD-03 KB API** (`KBStore`): `stage_source_ref(...) -> id`,
`stage_variant(run_id, variant_id=, gene=, class_=, provenance=, source_ref_ids=, hgvs_*=, *_null_reason=)`,
`stage_manual_queue(...)`, `build_provenance(...)`, `publish(run_id)`. The store is **injected** (tests
use a real in-memory/temp `KBStore` — grounding is verified against the actual schema, not a mock).

### 10.4 Normalizer port = offline testability

The `Normalizer` is **dependency-injected**. Structural ACs (AC1/AC2/AC4/AC5/AC6/AC7) run offline with
a **deterministic fake normalizer** — a *test double for the plumbing*, never a correctness oracle
(fixed raw → fixed outcome, no reference data; also used to force edge cases like "normalizer raises →
routes to manual-queue"). **Correctness (AC3) is validated only against the real normalizer + real
reference + independent oracle — never the fake.** Real-reference markers:
- `@pytest.mark.requires_reference` — AC3 **genomic** (`variant_id` + `hgvs_g`) via the real
  `SeqRepoGenomicNormalizer`. **The ~30 MB chr16 reference is fetched during the build, so this runs
  for real in this increment** (not deferred — the reference is trivial to obtain).
- `@pytest.mark.requires_uta` — AC3 **c./p.** correctness only (genuinely needs UTA: Postgres + pinned
  dump). This is the one piece deferred to the UTA setup step.

### 10.5 AC3 independent oracle (anti-circularity — the PRD-03 lesson)

Expected `variant_id`/SPDI/`hgvs_g` in the **frozen AC3 fixture** are derived **independently of the
normalizer under test** — never by freezing our own normalizer's output (that is the confirmation-bias
trap that hid PRD-03's bugs):
- **Primary oracle:** the **NCBI Variation Services SPDI API** (`/spdi/.../canonical_representation`,
  NCBI-computed — a different implementation), queried with each fixture variant's VCF coordinates,
  and **frozen into the fixture** for offline replay (§5). *(Note: ClinVar's `variant_summary.txt.gz`
  does not currently expose a `CanonicalSPDI` column, so the SPDI API is the independent source.)*
- **Cross-check:** where available, corroborated against Mutalyzer; any value that cannot be
  independently verified is **excluded, not guessed** (GP-9).
- Fixture must include: ≥1 SNV, ≥1 **small deletion needing left-alignment** (the case that actually
  exercises the reference), ≥1 insertion/dup, ≥1 non-coding (SPDI-only, c./p. null-with-reason), ≥1
  case that **must route to manual queue** (FR3), and **≥1 variant per gene (TSC1 *and* TSC2)** so both
  chromosomes are exercised.

### 10.6 v1 increment scope (what the loop builds now)

### 10.6 v1 increment scope (what the loop builds now)

**Gene scope: ingestion/normalization covers BOTH TSC1 + TSC2** (gene-agnostic, chr16 + chr9); the
first **validation gate is TSC2-first** (PRD-06, EVAL_PLAN §1.2) — TSC1's gate is a fast-follow.

- **Built + validated offline now:** FR1, FR3, FR5–FR9; AC1, AC2, AC4, AC5, AC6, AC7.
- **Built + validated on real data in this increment:** AC3 **genomic** `variant_id` (canonical SPDI)
  — the ~70 MB pinned chr16+chr9 reference is fetched during the build and the real
  `SeqRepoGenomicNormalizer` is run against the independent **NCBI SPDI-API** oracle (§10.5). **Not
  deferred.** Integrity guards validated on real reference: an input **REF that disagrees with the
  reference genome** → manual queue (R-A10, never silently re-based); a **reference FASTA whose
  checksum ≠ the pin** → fail loud (R-A11); **symbolic/non-ACGT ALT** (`<DEL>`, `.`) → manual queue.
- **`hgvs_g` scope:** emitted (and oracle-checked) for **SNVs** now. **Indel/MNV `hgvs_g` is deferred**
  alongside c./p.: proper genomic HGVS for indels uses **3′-anchored** nomenclature (opposite to the
  left-anchored VCF/SPDI representation) and has **no independent oracle** in this increment, so it is
  left `None` rather than **guessed** (GP-9). The `variant_id` (SPDI) — the actual join key — is fully
  validated; indel `hgvs_g` is an annotation-completeness fast-follow (Mutalyzer-oracled), tracked with
  c./p.
- **Deferred to the UTA step (the one genuinely heavy dependency):** `hgvs_c/hgvs_p` projection + AC3
  c./p.. Until UTA, coding variants publish with a valid `variant_id` + class and
  **`hgvs_c/p = null` WITH reason `"awaiting_uta_projection"`** — an explicit FR3 null-with-reason,
  **not** a silent gap and **not** manual-queue (the join key is valid; only the annotation is
  deferred). PRD-01 joins on `variant_id` (§2.1), so this increment is already useful to the scorer.
