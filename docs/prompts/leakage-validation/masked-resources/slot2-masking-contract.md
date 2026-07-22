# Slot 2 — Masking contract: public API, config, outputs, acceptance criteria

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the slot-1
> surfaces only**, before the doer. The doer implements to pass (may add, not weaken). Every leakage fact
> is derived from the pinned BIAS source (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`) and ADR-0009;
> dynamic firing counts are annotations, never the oracle for mask membership.

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 Mask set (fixed by static lineage, not incidence)
- **Transitive comparator resources (5):** `PS1, PM5, PM1, PP2, BP1` — rebuilt from the masked ClinVar
  source. Fired counts on the full-resource held-out run (`PS1 116, PM5 13, PM1 0, PP2 0, BP1 0`) are
  **annotation only**; all five are masked regardless.
- **Direct-copy fallback inputs (3):** `PS4` (submitter counts), `PP5`/`BP6` (own-variant ClinVar
  significance). Masking removes each **held-out variant's own** ClinVar record so the fallback cannot
  echo the held-out variant's own assertion (held-out incidence `PS4 288, PP5 353, BP6 2174`).

### 0.2 Held-out identity set (the conservation oracle)
2,577 canonical GRCh38 SPDI ids = 707 `NC_000009.12` + 1,870 `NC_000016.10`; shapes 2,416 SNV / 4 MNV /
135 delins / 3 ins / 19 del (PRD-08 §12, planner-verified). This set is the exact-set the masked ClinVar
source must **not** contain and every regenerated resource must **not** reference.

### 0.3 Single upstream (the reason one mask covers all eight)
Every resource in §0.1 rebuilds from the ClinVar source (VCF + Nirvana JSON + `variant_summary` /
`submission_summary`). Mask the upstream, re-run the generators → every downstream resource is masked
(slot-1 leakage table). This is a **data-level** mask; no generator logic is reimplemented.

---

## 1. Public API (the test contract) — `src/raptor/eval/mask_clinvar.py` (NEW, eval-side)

> Smallest coherent surface: one library module + one thin CLI. The scorer never imports it. Runs on the
> eval/data-prep side (may physically see truth) but its **outputs** are the label-free boundary the
> operator's x64 rebuild consumes.

- **`MaskConfig` + `load_mask_config(path, ingest_config)`** — frozen, schema-validated view of
  `configs/eval/mask.yaml` (§2). Rejects a blank/duplicate ClinVar input pin, an unknown resource key,
  or an `assembly` other than `ingest_config.assembly`. Tests may construct `MaskConfig` directly.
- **`load_holdout_identities(heldout_jsonl, normalizer) -> frozenset[str]`** — reads **only**
  `row["variant_id"]`, normalizes each through the injected `normalizer` to canonical GRCh38 SPDI, and
  returns the frozen identity set. Any other field access is forbidden (proven by AC-M6). A duplicate or
  un-normalizable id is **fatal** (`HoldoutIdentityError`), never dropped.
- **`mask_clinvar_source(clinvar_records, holdout_ids, normalizer, config) -> MaskResult`** — the core.
  For each ClinVar input stream (VCF/Nirvana-JSON records keyed by coordinate; `variant_summary` /
  `submission_summary` rows keyed by `VariationID`) it:
  - normalizes each ClinVar record to canonical SPDI (VCF/Nirvana) or resolves its VariationID→SPDI via
    the provided ClinVar identity map (summary tables), and **drops exactly** the records whose canonical
    identity ∈ `holdout_ids`;
  - emits the **masked stream** + a per-stream `MaskLedger` (`{input_total, matched_removed,
    remaining, removed_ids}`);
  - is **fail-loud** on ambiguity: a ClinVar record that fails to normalize raises
    `MaskReferenceError` (never silently kept or dropped); a held-out id that matches **zero** ClinVar
    records is recorded (expected — the held-out variant may be absent from the ClinVar source) but a
    held-out id matching **multiple non-equivalent** ClinVar coordinates is fatal
    (`MaskAmbiguityError`).
- **`MaskResult`** = `{masked_streams: dict[str, MaskedStream], ledger: dict[str, MaskLedger],
  conservation: ConservationReport, content_hash()}`. `write(out_dir)` emits, per input, the masked file
  under a **separate masked namespace** (`{out_dir}/masked/...`), a `mask.manifest.jsonl` (per-removed-id
  rows: exactly `{variant_id, clinvar_variation_id, input_stream}`), and a `mask.provenance.json`
  sidecar (source hashes, benchmark snapshot, code version, counts, per-stream hashes).
- **`audit_mask_conservation(masked_resources, holdout_ids, normalizer, config) -> ConservationReport`**
  — the **independent** post-rebuild audit (run after the operator returns the rebuilt masked resources).
  Re-derives every variant-level identity referenced by each of the five comparator resources and the
  three fallback tables, and asserts **none** ∈ `holdout_ids`. For aggregate resources (`PM1/PP2/BP1`) it
  recomputes each domain/gene aggregate from the masked ClinVar and asserts the resource's stored
  aggregate **equals** the recomputed value (proving no held-out member contributed). Returns
  `{clean: bool, transitive_survivors: dict[criterion, list[id]], aggregate_mismatches: [...],
  content_hash()}`. `clean` is `False` (never raises inside the audit) so the report is total; the CLI
  enforces.
- **Typed taxonomy (small hierarchy):** `HoldoutIdentityError`, `MaskReferenceError`,
  `MaskAmbiguityError`, `MaskConfigError`.

### 1.1 CLI — `scripts/mask_clinvar_source.py`
`--heldout <jsonl> --clinvar-vcf <path> --clinvar-nirvana-json <path> --variant-summary <path>
--submission-summary <path> --out-dir <dir> --benchmark-snapshot <id>
[--mask-config configs/eval/mask.yaml] [--ingest-config configs/ingest/tsc.yaml]`. Reads only
`row["variant_id"]` from the held-out JSONL; takes the snapshot id from the CLI arg (never a labelled
row); writes the masked namespace + manifest + provenance; prints per-stream conservation counts + hashes;
exits non-zero if any stream's `matched_removed` count is inconsistent with the ledger (fail-loud).

A **second** CLI mode `--audit <masked_resource_dir>` runs `audit_mask_conservation` on the operator's
rebuilt resources and exits non-zero iff `not report.clean`, persisting + printing the report either way.

---

## 2. Config → `configs/eval/mask.yaml` (NEW; GP-6, nothing hardcoded)

| Key | Value | Note |
|---|---|---|
| `assembly` | `GRCh38` | must equal `ingest.assembly` |
| `mask_criteria` | `[PS1, PM5, PM1, PP2, BP1]` | the five `requires_heldout_mask`; validated ⊆ `bias_lineage.yaml::requires_heldout_mask` |
| `direct_copy_fallbacks` | `[PS4, PP5, BP6]` | own-variant ClinVar records to mask |
| `clinvar_inputs` | ordered list of `{stream: clinvar_vcf|clinvar_nirvana_json|variant_summary|submission_summary, resources: [...]}` | which resource each input feeds (slot-1 table) |
| `full_resource_paths` | list of the full VUS comparator resource paths | asserted **byte-unchanged** post-run (invariant 5) |
| `masked_namespace` | `masked/` | separate output root |
| `bias_version` | `"3.0.0"` | pin; a version bump re-derives the input contract |

Reuses `configs/ingest/tsc.yaml::reference_checksums` (via the injected normalizer) and
`configs/eval/bias_lineage.yaml` (mask-set consistency). No new threshold, no policy value.

---

## 3. Acceptance criteria (→ STRATEGY Part II §4 gates)

- **AC-M1 (mechanical) — Exact-set mask conservation.** After `mask_clinvar_source` on a synthetic
  ClinVar stream containing a known subset of held-out ids, every masked stream's canonical-SPDI id set
  ∩ `holdout_ids` == ∅, and every held-out id present in the input appears in `mask.manifest.jsonl`
  exactly once. **Independent oracle:** the test computes the expected removed set by canonical-SPDI
  membership itself, never from the tool's ledger.
- **AC-M2 (mechanical) — No silent row loss (conservation identity).** For each stream,
  `remaining == input_total − matched_removed`, and `remaining` equals the input **minus exactly** the
  held-out members (set difference recomputed independently); a non-held-out record is **never** removed;
  a removed record is **always** held-out. Over/under-removal is a test failure.
- **AC-M3 (mechanical) — Transitive absence in rebuilt resources.** On a synthetic rebuilt comparator
  fixture (aggregates recomputable by hand) `audit_mask_conservation` returns `clean=True` when the
  masked resource excludes all held-out members, and `clean=False` with the exact survivor id in
  `transitive_survivors[criterion]` when a held-out variant is injected into a domain/gene aggregate —
  even when that variant **never fires** (PM1/PP2/BP1 zero-incidence case).
- **AC-M4 (mechanical) — Aggregate recomputation oracle.** For a hand-computed domain with a known
  pathogenic/benign membership, the audit's recomputed `PM1` domain rate (and `PP2`/`BP1` gene
  proportions) equals the hand-computed value on the masked set and **differs** from the unmasked value;
  a stored aggregate that still reflects a held-out contributor is flagged in `aggregate_mismatches`.
- **AC-M5 (mechanical) — Direct-copy own-variant mask.** A held-out variant's own ClinVar `VariationID`
  is absent from the masked `variant_summary`/`submission_summary` (PS4) and from the masked ClinVar
  annotation stream (PP5/BP6); a **non**-held-out variant at the same residue/gene is **retained** (only
  the held-out variant's own record is removed, not its neighbours — PS1/PM5 evidence for others stays).
- **AC-M6 (evidence-form) — Label-free identity access.** A synthetic held-out row carrying **sentinel**
  values in `label`/`source`/`review_status`/`variant_class` yields masked outputs, a manifest, and a
  provenance sidecar in which none of those sentinel **values** appears in any per-row field; the manifest
  per-row field-set is exactly `{variant_id, clinvar_variation_id, input_stream}`. Constructor/API
  inspection proves the tool has no benchmark/label-source parameter (only ClinVar inputs + held-out ids
  + normalizer + config).
- **AC-M7 (evidence-form) — Full VUS resources untouched.** The `full_resource_paths` are **byte-identical**
  (hash-equal) before and after a run; masked outputs are written **only** under `masked_namespace`; the
  tool refuses (raises `MaskConfigError`) if an output path resolves inside a full-resource path.
- **AC-M8 (mechanical) — Determinism + provenance.** Two runs on identical ids + inputs produce
  byte-identical masked streams, manifest, and hashes; `mask.provenance.json` carries the BIAS source
  commit, `bias_lineage.yaml` hash, benchmark snapshot, code version, and per-stream content hashes;
  `content_hash()` excludes run metadata.
- **AC-M9 (mechanical) — Fail-loud, no AGPL import.** An un-normalizable ClinVar record raises
  `MaskReferenceError`; a held-out id matching multiple non-equivalent ClinVar coordinates raises
  `MaskAmbiguityError`; a static import audit (NEW module) proves `mask_clinvar.py` never imports
  `bias_2015`/BIAS preprocessing and never opens the frozen benchmark/held-out **labels** (only
  `row["variant_id"]`).

---

## 4. Independent oracles (never the implementation's own output)

- **Canonical-SPDI set membership** recomputed in-test from the fixture (AC-M1/M2/M5).
- **Hand-computed domain/gene aggregates** for PM1/PP2/BP1 (AC-M3/M4) — the audit must reproduce them.
- **The pinned BIAS generator input contracts** (which column/field keys a variant) — slot-1 citations,
  read by the tester to build fixtures, never imported by production.
- **Full-resource byte hashes** (AC-M7) as the untouched-VUS oracle.

## 5. Deferred (operator / arm's-length; not this code)

Running BIAS's own `generate_*.py` on the masked ClinVar (x64 devbox, ADR-0007/0008) to produce the
masked comparator resources, and the masked held-out re-score. This code delivers the **masked inputs +
the conservation audit**; the operator's rebuilt resources are fed back into
`audit_mask_conservation --audit` before the masked TSV is trusted by Arm B. The masked re-score TSV
replaces the leaky full-resource TSV (sha256 `6e055fe1a4f7d18e428c62739e3b60fa55362f72aa6322429d2f4ff93076dd9c`).
