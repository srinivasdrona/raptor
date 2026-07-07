# PRD-02 — Variant Ingestion & Normalization

> **Status:** Draft · **Owner:** @sdrona_microsoft · **Phase:** 0 (STRATEGY §7) · **Last updated:** 2026-07-08
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

**v1 scope: TSC2 only** (aligns PRD-01 v1); **TSC1 fast-follow.**

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
- **Exact pin values** (MANE Select version, transcript/protein `accession.version`, GRCh38 patch, reference/UTA checksum, normalizer version) must be filled into `configs/ingest/` **before the PRD is Ready** — they are config keys (FR8), not code.
