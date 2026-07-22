# Devbox handoff — BIAS-2015 + Nirvana annotation/scoring pipeline (Track B)

> **Audience:** a Copilot CLI session running **on the x64 devbox** (`dontpanic-devbox`, `D:\raptor`).
> **Goal of this pass:** stand up the BIAS-2015 + Nirvana pipeline **in isolation**, smoke-test it, and
> report back the exact invocation + a sample output — so the ARM "Queen" (the main dev host) can wire
> the arm's-length ingest and then send the real held-out variant batch to score.
>
> This is the x64-only half of RAPTOR's Tier-1/2 scorer. See ADR-0007 (arm's-length AGPL) and ADR-0008
> (x64 worker) in `docs/DECISIONS.md`. **Read those two ADRs before starting.**

## 0. Why you (the devbox) exist in this architecture

RAPTOR classifies TSC1/TSC2 variants. Its Tier-1/2 ACMG engine reuses **BIAS-2015** (bitscopic), which
needs **Illumina Nirvana** (annotator, .NET, multi-GB data) to turn a VCF into annotated JSON, which
BIAS then scores into ACMG criteria. **Nirvana has no ARM build and is x64/proprietary** → this whole
annotation+scoring pipeline runs **here on the x64 devbox**, never on the ARM host (ADR-0008).

The ARM host runs only RAPTOR's own Python (ingest, KB, eval, gate). The machine boundary is a **file
contract**: you produce a `*.bias_output.tsv`; the ARM host consumes it at arm's length via
`src/raptor/scorer/bias_source.py::BiasTsvSource` — it **never imports BIAS** (ADR-0007, AGPL). Your
job is to produce that TSV.

```
   [ARM host]                         [x64 devbox — YOU]                         [ARM host]
 label-free input VCF   ------>    Nirvana annotate -> BIAS-2015 score  ------>    BiasTsvSource
 (held-out variants)                -> *.bias_output.tsv (+ sha256)                -> RAPTOR eval/gate
```

## 1. Hard constraints (do not violate)

- **Isolation — no global config changes.** The owner's concern is a clean devbox. Install EVERYTHING
  under a single scoped dir (e.g. `D:\raptor-x64\`): a portable .NET runtime, Nirvana + its data cache,
  BIAS-2015, and any Python venv. **No system-wide installs, no PATH edits, no registry changes.** If a
  tool truly cannot be portable, STOP and report it rather than changing global state.
- **Arm's-length only (ADR-0007).** Do NOT copy BIAS-2015 source into the `D:\raptor` repo tree. Do NOT
  `import` BIAS from RAPTOR code. BIAS runs as a **separate program**; the only thing that crosses back
  is the output TSV (a data file). Keep BIAS/Nirvana under `D:\raptor-x64\`, never under `D:\raptor\`.
- **No secrets in the repo.** Licenses/keys (if any) stay under `D:\raptor-x64\`, never committed.
- **Verify, don't trust.** Pin the versions + data-bundle checksums of Nirvana and BIAS; record them.

## 2. Tasks (this pass = setup + smoke test + report, NOT the full run)

1. **`git pull`** in `D:\raptor` so you have this doc, the BIAS output contract
   (`src/raptor/scorer/contract.py::BiasOutputContract`), and the parser
   (`src/raptor/scorer/bias_source.py`) you must produce compatible output for.
2. **Install (isolated, under `D:\raptor-x64\`):**
   - a **portable .NET runtime** (the version Nirvana requires — check Nirvana's release notes; ADR-0008
     mentions .NET 6, confirm against the actual Nirvana version you fetch),
   - **Illumina Nirvana** + its annotation **data cache + reference** (multi-GB; GRCh38),
   - **BIAS-2015** (bitscopic) and its config.
   Record exact versions + download URLs + data-bundle checksums in `D:\raptor-x64\VERSIONS.md`.
3. **Smoke-test on a tiny VCF.** Use `scripts/devbox/sample_tsc.vcf` (a handful of TSC1/TSC2 GRCh38
   variants committed alongside this doc). Run the real pipeline:
   `sample VCF -> Nirvana annotate (GRCh38) -> BIAS-2015 score -> sample.bias_output.tsv`.
4. **Prove the output parses.** From `D:\raptor` run the repo's parser against your TSV to confirm the
   column contract holds (see §3). It must load without a `BiasContractError`.
5. **Report back** (write `D:\raptor-x64\HANDOFF_REPORT.md` AND print a summary):
   - exact Nirvana + BIAS + .NET versions and data-bundle checksums;
   - the EXACT command lines for each stage (annotate, score), with all flags;
   - the produced `sample.bias_output.tsv` (copy it — no patient data, just TSC variant annotations)
     and its sha256;
   - anything that required a non-isolated change (flag loudly), and any manual step;
   - approximate wall-time + disk footprint for the sample (to estimate the ~1,100-variant run).

## 3. Output contract you must satisfy (`*.bias_output.tsv`)

Tab-separated, header row exactly these columns (order per BIAS-2015's own `test/data/*.bias_output.tsv`;
extra trailing columns are tolerated, missing ones fail):

```
chromosome  position  refAllele  altAllele  variantType  consequence  acmgClassification
alleleFreq  hgvsg  hgvsc  hgvsp  aaChange  geneName  pubmedIds  associatedDiseases
dbSnpids  transcript  rationale
```

- `chromosome`/`position`/`refAllele`/`altAllele` must match the **input VCF** (GRCh38) so the ARM host
  can join back by identity. Use the RefSeq genomic accession form if BIAS emits it (e.g.
  `NC_000016.10`); otherwise report what it emits so we map it.
- `rationale` is BIAS's nested JSON of fired ACMG criteria, e.g.
  `{"pvs": {"pvs1": [1, "null variant in a gene where LoF is a known mechanism"]}, "pm": {"pm2": [1, "..."]}, ...}`
  — `[fired(0/1), explanation]` per criterion. This is what RAPTOR actually scores; get it right.
- Validate with the repo parser (do NOT reimplement it): load your TSV through
  `raptor.scorer.bias_source.BiasTsvSource` (+ `BiasOutputContract.assert_columns`) from a venv on the
  devbox — collection must succeed and yield one `BiasRecord` per variant.

## 4. What happens AFTER you report back (not this pass)

The ARM host will: finalize the held-out set (a governance decision on the split is pending — see
[`docs/EVALUATION.md` Part II §3b](../EVALUATION.md#evaluation-governance-decision)), emit the **label-free** held-out VCF (variant coords only — you must never
receive labels; that's the H1 anti-circularity boundary), and send it here for the real scoring run.
You return the full `*.bias_output.tsv`; the ARM host ingests it, runs the eval, and checks the gate.

## 5. Ready-to-paste prompt for the devbox Copilot CLI

> Paste this into a Copilot CLI session started on `dontpanic-devbox` (cwd `D:\raptor`):

```
Read docs/ops/devbox-bias-nirvana-handoff.md in this repo and docs/DECISIONS.md ADR-0007 + ADR-0008,
then execute Track B "this pass" (setup + smoke test + report):
- git pull first.
- Install a portable .NET runtime, Illumina Nirvana (+ GRCh38 data cache/reference), and BIAS-2015,
  ALL isolated under D:\raptor-x64\ -- no global/system/PATH/registry changes; if something can't be
  isolated, stop and tell me.
- Smoke-test the pipeline (scripts/devbox/sample_tsc.vcf -> Nirvana annotate -> BIAS-2015 score ->
  sample.bias_output.tsv) and prove the TSV parses via raptor.scorer.bias_source.BiasTsvSource.
- Write D:\raptor-x64\VERSIONS.md and D:\raptor-x64\HANDOFF_REPORT.md with exact versions, checksums,
  the exact command lines, the sample TSV + its sha256, wall-time, disk footprint, and any non-isolated
  step you were forced into. Do NOT copy BIAS source into D:\raptor and never import BIAS from RAPTOR.
Report the summary back to me when done.
```
