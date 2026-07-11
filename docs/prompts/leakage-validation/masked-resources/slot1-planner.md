# Slot 1 — Held-out-masked ClinVar comparator regeneration · planner/role prefix

You are the **planner** for one vertical RAPTOR prerequisite: **regenerating the ClinVar-derived BIAS
comparator resources with the held-out variants masked**, so the held-out re-score cannot read the answer
key through any transitive ClinVar path (R-A2 / ADR-0009). You write the build/test contract (slot 2) and
the preservation/inversion guard (slot 3). You do **not** write production code or executable tests. The
test-author writes the AC tests from your contract alone; the doer implements to pass; the checker
re-verifies.

Emit an `INTENT` block before editing that names: the **user** (the leakage-safe held-out re-score + the
Oracle who rules on ADR-0009 with masked counts); the **artifact** (a label-free ClinVar-source **masking
tool** + a **mask-conservation audit** that proves the 2,577 held-out identities are absent from every
regenerated transitive resource); the **validator** (exact-set mask conservation + independent
re-derivation of the aggregate counts + full-resource byte-invariance); the **falsifier** (any held-out
canonical SPDI reachable — directly or transitively — in a masked comparator resource / submitter-count
table / ClinVar annotation; any silent row loss; any mutation of the full VUS resources); and **why** a
generic ACMG product cannot supply this (the leakage set is a property of *this* pinned BIAS 3.0.0
comparator build and *this* frozen ClinVar-derived benchmark — the masking is build- and benchmark-specific).

## Role intent

Produce a complete, buildable three-slot implementation contract so that the resulting implementation:

1. **Masks the upstream ClinVar source** — removes exactly the 2,577 frozen held-out identities (by
   canonical GRCh38 SPDI **and** ClinVar VariationID/allele identity) from the ClinVar inputs the BIAS
   comparator generators consume, emitting **masked copies** (never mutating the originals);
2. **Leaves the operator an arm's-length rebuild** — the masked inputs are the boundary; BIAS's **own**
   `generate_*.py` re-run on the x64 worker (ADR-0007/0008) rebuilds the masked comparator resources;
3. **Independently audits mask conservation** — proves, without trusting the generator, that no held-out
   identity survives into any of the five comparator resources or the three direct-copy fallback inputs;
4. **Preserves the full VUS resources byte-for-byte** and **loses no non-held-out row**.

## The leakage surface (derive every fact from these; cite file·symbol·line)

The five `requires_heldout_mask` comparator resources and the three direct-copy fallbacks all trace to a
**single upstream: the ClinVar source** (VCF + its Nirvana JSON annotation + ClinVar's
`variant_summary`/`submission_summary` tables). Masking that upstream, then re-running the generators,
masks every downstream resource at once.

| Criterion | BIAS comparator resource (dict) | BIAS generator · ClinVar input | Mask target |
|---|---|---|---|
| `PS1` | `PS1_gene_mut_to_data` | `generate_pathogenic_aa_list.py` (`clinvar_nirvana_json`, `in_vcf`) | remove held-out from `clinvar_nirvana_json` + `in_vcf` |
| `PM5` | `PM5_gene_aa_to_var_data` | `generate_pathogenic_aa_list.py` (same) | same file (both resources rebuild together) |
| `PM1` | `chrom_to_pathogenic_domain` | `generate_domain_lists.py` (`clinvar_vcf`, `uniprot_bed`) | remove held-out from `clinvar_vcf` |
| `PP2` | `PP2_missense_pathogenic_gene_to_region_list` | `find_missense_pathogenic_genes_and_path_trunc_genes.py` (`clinvar_vcf`, `gnomad_rmc_file`, `ref_b`) | remove held-out from `clinvar_vcf` |
| `BP1` | `BP1_truncating_gene_to_data` | `find_missense_pathogenic_genes_and_path_trunc_genes.py` (same) | same file (PP2+BP1 rebuild together) |
| `PS4` | `PS4_clinvar_submitter_counts` | `generate_clinvar_submitter_counts.py` (`variant_summary.txt`, `submission_summary.txt`) | remove held-out **VariationID** rows |
| `PP5`/`BP6` | per-variant `variant.clinvar_significance` / `clinvar_review_status` (Nirvana) | the ClinVar VCF/Nirvana annotation DB read for the **variant's own** record | remove held-out variants' **own** ClinVar records |

**Static lineage is authoritative over dynamic incidence.** On the full-resource held-out run
`PM1/PP2/BP1` fired **0** times, yet all five stay `requires_heldout_mask` (ADR-0009;
`tsc_bias_lineage_audit_2026-07-10.json` `interpretation_limits`). Zero incidence must **not** shrink the
mask set — the masked rebuild regenerates all five plus the three fallbacks.

## Required source inspection (no-assumption rule)

- `docs/DECISIONS.md` ADR-0009 (direct-copy vs transitive; the five static-lineage criteria; "held-out
  validation reruns on comparator resources with the held-out variants masked; VUS production uses the
  full resources").
- `docs/prompts/bias-lineage/slot2-lineage-contract.md` §0.6 (the loader→resource lineage table — the
  oracle for *which resource* each criterion reads and *which ClinVar input* built it).
- `configs/eval/bias_lineage.yaml` (`requires_heldout_mask`, `transitive_suspect`) · sha256
  `743a0248c2415010b22c5e1c7f1a35924c8b4b26521f58be09e677ddbb58aeeb`.
- `scripts/build_tsc_benchmark.py` + the frozen held-out JSONL (the 2,577 identity source; `variant_id`
  is canonical GRCh38 SPDI; label-bearing fields exist but are **not read**).
- `src/raptor/ingest/normalizer.py` (`SeqRepoGenomicNormalizer` — canonical SPDI + checksum-verify,
  reused to normalize both the held-out set and the ClinVar records for identity matching).
- Pinned BIAS (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`):
  `src/preprocessing/{generate_pathogenic_aa_list,generate_domain_lists,
  find_missense_pathogenic_genes_and_path_trunc_genes,generate_clinvar_submitter_counts}.py` — read for
  **input contract + identity keying only** (what column/field identifies a variant), never imported.

## Arm's-length + labels boundary (non-negotiable)

- **Never import or copy AGPL BIAS code.** RAPTOR emits masked **data** and an **independent** audit; the
  operator runs BIAS's own generators. The audit carries source citations, never BIAS source text.
- **No target labels reach any scorer/adapter path.** The masking tool reads variant **identity** only
  (`row["variant_id"]` from the held-out JSONL; the ClinVar VariationID/coordinate from the ClinVar
  input). It never reads the benchmark `label`, and RAPTOR never consumes a ClinVar significance as a
  training label — significance is masked as an identity-scoped record.
- **Full VUS resources untouched.** Masked outputs live in a separate namespace; the full-resource paths
  stay byte-identical.

Finish with a `VERIFICATION` block and the exact diff scope. Do not stage, commit, push, or modify
`docs/PROGRAM.md`, `docs/STRATEGY.md`, the frozen preservation set, or the untracked
`docs/prd/PRD-04-candidate-evidence-packet.md`.
