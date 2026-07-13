# Masked held-out BIAS rerun: x64 operator handoff

**Status:** source provenance, source mask, and PS1/PM5 baseline reproduction
complete. PM1 is excluded from this evaluation after a zero-support audit;
masked-resource regeneration and held-out re-score require
`dontpanic-devbox` (x64).

**Authority boundary:** this run is evaluation-only. It must not approve a
production scoring policy, classify a patient variant, reveal held-out labels
before scoring, or submit anything to ClinVar/ClinGen.

## 1. Pinned execution state

| Component | Pin |
|---|---|
| RAPTOR repository | `srinivasdrona/raptor` |
| Minimum RAPTOR commit containing the streaming masker | `c0bae294cc36058f58c8ebd466059c4b76c9ae8f` |
| BIAS | `3.0.0`, commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f` |
| Nirvana | `3.18.1`, runtime banner `3.18.1-0-g05f88047` |
| Existing x64 root | `D:\raptor-x64` |
| Existing RAPTOR checkout | `D:\raptor\repo` |
| New isolated run root | `D:\raptor-x64\masked-heldout-2026-07-12` |
| Local handoff bundle | `D:\AIProjects\raptor-data\handoffs\masked-heldout-2026-07-12` |

Do not modify `D:\raptor-x64\bias-hg38-data`, the installed Nirvana
supplementary bundle, or prior full/VUS outputs. Copy inputs and resources into
the new run root before writing anything.

## 2. Proven source snapshot

BIAS `CHANGELOG.md:41-43` says the `2026.03.01` resource bundle was regenerated
with **ClinVar February 2026**, but the current hg38 files were regenerated and
uploaded on March 10 after the original release's preprocessing failure
(BIAS issue 43). BIAS preprocessing uses NCBI's rolling, unversioned
`clinvar.vcf.gz` URL.

The official March 9 GRCh38 archive semantically reproduces both published
gene-level ClinVar resources at pinned BIAS commit `ade13f2`:

- NCBI archive:
  `https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/archive_2.0/2026/clinvar_20260309.vcf.gz`
- Official MD5: `308d66b5fe172104298081c2fd555d8e`
- SHA-256:
  `e775b80f79ac4946a3a6666201a5b0cd44d789c848e355321dfd4b001804cef8`
- PP2: 879 reproduced rows = 879 published rows; semantic multiset exact.
- BP1: 114 reproduced rows = 114 published rows; semantic multiset exact.

Byte hashes differ because the BIAS generator builds sets and sorts only by
gene, leaving duplicate same-gene row order process-dependent. Canonically
comparing the complete tab-separated row multiset is therefore the
reproducibility gate; raw file hash equality is not a valid gate for these two
generated files. Evidence is pinned in
`evidence\grch38-20260309-pp2-bp1-comparison.json`.

## 3. Completed label-free source mask

The local masker reads only `variant_id` from the frozen manifest. It preserves
non-TSC VCF records byte-for-byte and canonicalizes only chromosome 9/16
records using the pinned GRCh38 FASTAs.

| Check | Result |
|---|---:|
| Source VCF records | 4,397,693 |
| Held-out manifest identities | 2,577 |
| Source rows removed | 2,577 |
| Distinct held-out identities removed | 2,577 |
| Held-out identities absent from source | 0 |
| Masked VCF records | 4,395,116 |
| Independent re-mask removals | 0 |

Key bundle hashes:

| File | SHA-256 |
|---|---|
| `inputs\holdout_input.manifest.jsonl` | `9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4` |
| `inputs\holdout_input.vcf` | `4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d` |
| `source\clinvar_20260309.vcf.gz` | `e775b80f79ac4946a3a6666201a5b0cd44d789c848e355321dfd4b001804cef8` |
| `masked\clinvar_20260309.masked.vcf.gz` | `f1e25cd2c12b6d19a7e727ae1472ab086e5578e2e51819b466fbf333e1230b28` |
| `masked\clinvar_20260309.mask-ledger.json` | `0f55e5cff0903c94baad896c23b7675526dfcd78513580f41c88b45f5c310fd0` |
| `masked\clinvar_20260309.remask-audit.json` | `b58ee687cb554659efe5434434e383536198c5b99b09c1f0793368b4fea03fec` |
| `references\NC_000009.12.fasta` | `650011382f44e91b90c85271833737af2afdb6f9e92ef56f1f8f58f2389e3351` |
| `references\NC_000016.10.fasta` | `22dc1bb93de407e0653791c36e4097fbaf64c9efa2510c83b7777f607a61e4d0` |

No held-out labels are in this bundle.

## 4. Setup and preflight

1. Copy the complete handoff bundle to
   `D:\raptor-x64\masked-heldout-2026-07-12\handoff-input`.
2. Verify every file against `CHECKSUMS.sha256`; stop on any mismatch.
3. Update or copy the RAPTOR checkout so it contains commit
   `c0bae294cc36058f58c8ebd466059c4b76c9ae8f`. Do not assume that `git pull`
   is sufficient until that commit exists on the selected remote.
4. Verify the existing BIAS, Nirvana, required-paths, and baseline resource
   hashes against:
   - `D:\raptor-x64\VERSIONS.md`
   - `D:\raptor-x64\CHECKSUMS\bias-hg38-data.sha256.txt`
   - `D:\raptor-x64\CHECKSUMS\nirvana-grch38-full.sha256.txt`
   - `D:\raptor-x64\CHECKSUMS\nirvana-grch38-updates.sha256.txt`
5. Create separate, writeable `unmasked-reproduction`, `masked-resources`,
   `score`, and `reports` directories below the new run root.

## 5. Mandatory baseline-reproduction gate

Use BIAS's own preprocessing functions at pinned commit `ade13f2`; do not
reimplement its aggregation rules in RAPTOR.

### 5.1 Confirm the proven March 9 source

Use the supplied `source\clinvar_20260309.vcf.gz`. Regenerate **unmasked** PP2
and BP1 and compare their complete row multisets with the published files in
`D:\raptor-x64\bias-hg38-data`.

Both comparisons must be semantically exact:

- PP2: 879 rows, no reproduced-only or published-only rows.
- BP1: 114 rows, no reproduced-only or published-only rows.

Do not require raw byte hashes for PP2/BP1: duplicate same-gene output order is
nondeterministic in the pinned BIAS generator. Stop with
`BLOCKED_SNAPSHOT_PROVENANCE` only if either canonical row multiset differs.

### 5.2 Reproduce PS1/PM5

Run BIAS's pinned ClinVar filter, annotate the resulting clean unmasked VCF
with the installed pinned Nirvana data, and run BIAS's
`generate_pathogenic_aa_list.py`. The generated semantic row multiset must
equal the published `hg38_PS1_PM5_clinvar_pathogenic_aa_nirvana.tsv`. Record
both byte hashes; byte inequality is allowed only when the report proves the
same complete semantic multiset and attributes the difference to ordering or
line endings.

### 5.3 Scope PM1 without a moving UniProt download

Do not fetch today's UCSC `uniProt.bb`. Reconstruct a frozen domain BED from
the published PM1 resource:

- group all published rows by `(chromosome, domain_full_name,
  annotation_source)`;
- encode each group's published intervals as one BED multi-block record;
- use only this published domain universe;
- run BIAS's pinned `generate_domain_lists.py` against the unmasked source.

The genome-wide reproduced PM1 resource differs from the published resource,
but the published resource has zero intervals containing any of the 2,577
held-out positions. The frozen lineage audit also records zero PM1 firings in
both the VUS and held-out runs
(`data/census/tsc_bias_lineage_audit_2026-07-10.json:77`).

Independently run the PM1 reachability audit against both published and
reproduced resources. Both must report zero reachable rows. If either has a
reachable row, stop. If both are zero, record PM1 as
`SKIPPED_ZERO_SUPPORT_BASELINE_MISMATCH`; this is an evaluation-only
exclusion, not production PM1 validation.

Do not substitute a current ClinVar snapshot, current UniProt file,
approximate aggregate, or hand-edited resource.

## 6. Regenerate the masked comparator resources

After section 5 passes:

1. Use the supplied March 9 masked VCF and ledger. If they are unavailable,
   recreate them with:

   ```powershell
   Set-Location D:\raptor\repo
   $env:PYTHONPATH='D:\raptor\repo\src'
   python scripts\mask_clinvar_vcf_for_holdout.py `
     --source-vcf D:\raptor-x64\masked-heldout-2026-07-12\handoff-input\source\clinvar_20260309.vcf.gz `
     --output-vcf D:\raptor-x64\masked-heldout-2026-07-12\masked-resources\clinvar_20260309.masked.vcf.gz `
     --holdout-manifest D:\raptor-x64\masked-heldout-2026-07-12\handoff-input\inputs\holdout_input.manifest.jsonl `
     --reference-root D:\raptor-x64\masked-heldout-2026-07-12\handoff-input\references `
     --ledger D:\raptor-x64\masked-heldout-2026-07-12\reports\source-mask-ledger.json
   ```

2. Regenerate from the masked source, using the exact section 5 toolchain:
   - `hg38_PS1_PM5_clinvar_pathogenic_aa_nirvana.tsv`;
   - `hg38_PP2_missense_pathogenic_genes.tsv`;
   - `hg38_BP1_truncating_genes.tsv`.
3. Use an isolated byte-identical copy of the published PM1 file to satisfy
   the loader contract, and pass an evaluation skip-list containing `PM1` to
   BIAS. Confirm all 2,577 PM1 rationale entries remain zero/empty.
4. Keep PS4, PP5, and BP6 forbidden/unscored. Do not claim that the installed
   Nirvana supplementary ClinVar database was masked.
5. Create a new required-paths JSON pointing to the three masked files above
   (PS1 and PM5 share one file). Every other allowed input must point to an
   isolated copy whose hash equals the baseline resource.
6. Run an independent survivor audit. No canonical held-out identity may
   remain in the direct PS1/PM5 comparator. Record all aggregate before/after
   diffs for TSC1 and TSC2.

Never overwrite the full resource bundle.

## 7. Blind held-out re-score

Use only the label-free input VCF:

```powershell
D:\raptor-x64\dotnet-runtime-6\dotnet.exe `
  D:\raptor-x64\Nirvana-v3.18.1\Nirvana.dll `
  -c D:\raptor-x64\nirvana-data\GRCh38\Cache\GRCh38\Both `
  --sd D:\raptor-x64\nirvana-data\GRCh38\SupplementaryAnnotation\GRCh38 `
  -r D:\raptor-x64\nirvana-data\GRCh38\References\Homo_sapiens.GRCh38.Nirvana.dat `
  -i D:\raptor-x64\masked-heldout-2026-07-12\handoff-input\inputs\holdout_input.vcf `
  -o D:\raptor-x64\masked-heldout-2026-07-12\score\holdout_input_nirvana

Set-Location D:\raptor-x64\BIAS-2015
python bias_2015.py `
  D:\raptor-x64\masked-heldout-2026-07-12\score\holdout_input_nirvana.json.gz `
  D:\raptor-x64\masked-heldout-2026-07-12\masked-resources\hg38_nirvana_required_paths.masked.json `
  D:\raptor-x64\masked-heldout-2026-07-12\score\holdout_input.masked.bias_output.tsv `
  --skip_list D:\raptor-x64\masked-heldout-2026-07-12\masked-resources\evaluation_skip_list.txt
```

The output must contain exactly 2,577 data rows and no duplicate
`chromosome:position:refAllele:altAllele` keys. Do not join labels, calculate
accuracy, apply the BP4/PP3 wrapper, or run the final release gate on the
devbox.

## 8. Return package

Return only the following under one `return` directory:

- the three regenerated comparator resources;
- masked required-paths JSON;
- masked BIAS TSV;
- PM1 published/reproduced reachability audits and evaluation skip-list;
- source-mask and independent survivor-audit ledgers;
- baseline reproduction report and machine-readable comparisons;
- exact commands, timings, versions, and SHA-256 manifest;
- stderr/stdout logs;
- a terminal status:
  - `SCORED_MASKED`;
  - `BLOCKED_SNAPSHOT_PROVENANCE`;
  - `BLOCKED_BASELINE_REPRODUCTION`;
  - `BLOCKED_MASK_CONSERVATION`;
  - `BLOCKED_TOOLCHAIN`.

Do not return labels or a PASS/FAIL accuracy claim. RAPTOR will apply the
canonical adapter, lineage audit, approved evaluation-only BP4/PP3 policy,
frozen labels, and exact confidence-bound gate only after this package passes
local review.

## 9. Stop conditions

Stop immediately if:

- a handoff, reference, BIAS, Nirvana, or baseline-resource hash mismatches;
- the exact February source cannot be proven by baseline reproduction;
- any full resource or prior output is modified;
- any held-out identity survives a masked direct comparator;
- either PM1 scope audit finds a held-out-reachable interval;
- the BIAS TSV does not contain exactly 2,577 unique records;
- a held-out label is opened before blind scoring completes;
- a step would require a current/live substitute for a pinned source.
