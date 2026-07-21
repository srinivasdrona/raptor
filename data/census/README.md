# Deterministic evidence censuses

Aggregate, label-free run statistics only. Per-variant VUS identities, BIAS
outputs, and manifests remain outside the repository.

`tsc_vus_clinvar_2026-07-07_stats.json` records the first complete TSC1/TSC2
VUS deterministic evidence census. Candidate LP/LB directions are internal,
eval-only triage signals—not validated classifications.

`tsc_vus_aavc_overlap_2026-07-10.json` records the aggregate, non-authoritative
comparison with AAVC's ClinVar September-2024 classification release. AAVC
machine classes are an external prior-art comparator, never truth labels or
ACMG evidence. Reproduce the aggregate from the external release and RAPTOR
run artifacts with `scripts/audit_aavc_overlap.py`.

`tsc_bias_lineage_audit_2026-07-10.json` records the static BIAS-3.0.0 lineage
policy roll-up and aggregate incidence from the 6,618-VUS and 2,577-held-out
runs. Both runs fail closed on PS1/PM5. Dynamic firing counts never establish
lineage; detailed reports with bounded example identities remain outside the
repository.

`tsc_calibration_batch_2026-07-11.json` records the non-identifying aggregate
for the real provisional calibration batch: 1,571 candidate-universe packets,
30 selected packets covering all 20 LP + 10 LB evidence patterns, both genes,
all observed variant classes and edge flags, and zero missing populated atoms.
Full packet/first-pass artifacts remain outside the repository.

The 2026-07-12 policy reports record the arm's-length BP4/PP3 correction
materiality, the 34-firing BS2 deferral analysis, and canonical
transcript/NTHL1 reconciliation. They are engineering/policy evidence, not
variant classifications.

`tsc_masked_holdout_gate_2026-07-13.json` records the first leakage-safe
terminal gate. All 2,577 held-out identities were masked with zero survivors,
the canonical BIAS join was exact, and the gate returned **FAIL** on the
binding missense stratum. `vus_authorized` is false. PM1 was excluded from this
fixed evaluation after a zero-support audit and remains unvalidated for
production.

Rebuild it from the external terminal envelope and returned PM1 scope audits:

```text
python scripts/build_masked_holdout_gate_aggregate.py \
  --terminal-json <MASKED_EVAL_REPORT.json> \
  --terminal-report <MASKED_EVAL_REPORT.txt> \
  --return-dir <x64-return-directory> \
  --date 2026-07-13 \
  --output data/census/tsc_masked_holdout_gate_2026-07-13.json
```

`tsc_masked_holdout_gate_disabled_manual_2026-07-21.json` records the
owner-approved ADR-0012 rerun with automated PP3/BP4 disabled. The immutable
2,577-row BIAS evidence and mask artifacts were reused; 2,043 variants had
2,063 predictor calls suppressed (BP4 1,929; PP3 134), and zero PP3/BP4 calls
were scored. The binding missense gate returned **FAIL** and the v2
full-spectrum gate returned **BLOCKED_POLICY** because PM1 remains an
evaluation exclusion. `vus_authorized` is false. Although
`truncating:pathogenic` independently met its registered 0.95/0.95 thresholds,
the parity blocker prevents any research-scope authorization.

The 2026-07-13 corrected-predictor artifact remains historical comparison
evidence; it is not the current approved policy. Neither result is a clinical
classification or an expert-reviewed VUS worklist.

Rebuild the current aggregate from the external R2 terminal envelope:

```text
python scripts/build_masked_holdout_gate_aggregate.py \
  --terminal-json <MASKED_EVAL_REPORT.disabled-manual-2026-07-21-r2.json> \
  --terminal-report <MASKED_EVAL_REPORT.disabled-manual-2026-07-21-r2.txt> \
  --return-dir <x64-return-directory> \
  --date 2026-07-21 \
  --output data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json
```

`tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json` (ADR-0012) is the
packet-free, non-identifying binding census aggregate over the same
6,618-VUS TSC1/TSC2 run under the PP3/BP4-disabled-automated-emission /
manual policy: candidate LP/LB directions, pattern compression, raw and
consumed-automated criterion incidence, PP3/BP4 suppression counts, the
signed-points distribution, per-gene/per-consequence corpus and direction
breakdowns, and a superseded-historical-comparison delta against
`tsc_vus_clinvar_2026-07-07_stats.json`. It is produced by the packet-free
`raptor.census` package (`raptor.census.strata` + `raptor.census.aggregate`)
and is a DOER RUNTIME OUTPUT, never hand-authored or committed by an
implementation change. `non_authoritative_boundary` is recorded on every
emitted record: this aggregate is an internal, eval-only triage signal, not
a validated classification, an expert-reviewed VUS worklist, or a clinical
report.

Reproduce it (byte-identical, never overwriting an existing artifact) with:

```text
python -m raptor.census.cli \
  --manifest <raptor-data manifest.jsonl> \
  --bias-tsv <raptor-data BIAS output.tsv> \
  --provenance <run-pins.json> \
  --scorer-config configs/acmg/tsc.yaml \
  --eval-config configs/eval/tsc2.yaml \
  --predictor-policy configs/eval/bp4pp3_predictor_policy.json \
  --lineage-policy <bias lineage policy.json> \
  --historical-stats data/census/tsc_vus_clinvar_2026-07-07_stats.json \
  --emit-census-record data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json
```

Pass `--dry-run` or `--summary` instead of `--emit-census-record` to prove
source-of-record conservation and bound-config-hash verification with no
write. The CLI fails closed (no output) on any path other than the single
hard-pinned target above, and on any attempt to overwrite an existing
artifact, including the historical stats and the certified masked gate.

`tsc2_mave_clipe_orthogonal_2026-07-13.json` records the first orthogonal,
non-gating MAVE (multiplexed assay of variant effect) validation track for
TSC2, sourced from the public MaveDB cliPE prime-editing scoreset
`urn:mavedb:00001201-a-1` (CC0-1.0, 208 variants, transcript NM_000548.5;
PMC11185720). It reports two mutually exclusive overlaps against the current
BIAS-2015 TSC2 runs, both recomputed fresh from the raw scoreset by exact
`hgvs_c` string matching (never a cDNA->genomic projection): **66 VUS
independent functional overlap** (59 functional-BLB / 3 functional-PLP /
4 ambiguous — functional-PLP is UNDERPOWERED, n<10) and **32 ClinVar-heldout
non-independent overlap** (23 clinical-BLB/functional-BLB concordant, 5
clinical-PLP/functional-PLP concordant, 4 ambiguous-direction). The VUS
overlap is independent of RAPTOR/BIAS's own evidence (no ClinVar label
exists for a VUS); the heldout overlap is explicitly flagged non-independent
because BIAS/RAPTOR's TSC2 pipeline was built/QA'd against ClinVar-derived
evidence. All figures are `NON_GATING`: no MAVE score, correlation, or
class-power figure here is consumed by `raptor.scorer`, `BiasEvidenceSource`,
PS3/BS3, or `decide_gate`, and the aggregate contains no per-variant
identities or clinical labels. See
`docs/reference/mave-tsc2-source-register-2026-07.md` for full source
citations, licensing, and the circularity/independence rationale. IGVF
VAMP-seq, IGVF SGE, and CAGI7 TSC2 data are registered `confirm_pending`
(access not held) and are not reflected in this aggregate.

Reproduce the aggregate (byte-identical) from the external, never-committed
raw scoreset and BIAS outputs with:

```text
PYTHONPATH=src RAPTOR_MAVE_EXTERNAL_ROOT=<external/mavedb root> \
  python scripts/build_mave_orthogonal_report.py \
  --output data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json
```
