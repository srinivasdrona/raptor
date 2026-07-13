# TSC2 orthogonal MAVE source register (2026-07)

| Field | Value |
|---|---|
| Status | Reference / orthogonal, non-gating, non-clinical evidence track (Phase 0/1) |
| Scope | TSC2, transcript NM_000548.5 |
| Primary source | MaveDB scoreset `urn:mavedb:00001201-a-1` (CC0 1.0) |
| Machine-readable aggregate | [`data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json`](../../data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json) |
| Reproducers | [`scripts/fetch_mave_scoreset.py`](../../scripts/fetch_mave_scoreset.py), [`scripts/build_mave_orthogonal_report.py`](../../scripts/build_mave_orthogonal_report.py) |
| Package | [`src/raptor/external/mave/`](../../src/raptor/external/mave/) |
| Configs | [`configs/external/mave_sources.yaml`](../../configs/external/mave_sources.yaml), [`configs/eval/mave_tsc2.yaml`](../../configs/eval/mave_tsc2.yaml) |

> **Reading rule:** every score, correlation, class-power figure, and concordance count in this
> track is `NON_GATING`. No MAVE score, functional class, or orthogonal-metric value may enter
> `raptor.scorer`, `BiasEvidenceSource`, PS3/BS3, or `decide_gate`. This document records what was
> fetched/verified, what remains `confirm_pending`/access-not-held, and why the two overlaps
> reported here have materially different independence properties.

## 1. Executive summary

This track adds a second, **orthogonal** (assay-based, not sequence/population-based) line of
evidence for TSC2 missense variants, strictly outside RAPTOR's scoring and gating path. It is used
only to sanity-check RAPTOR/BIAS-2015 directional calls against an independent functional assay,
never to authorize, weight, or gate a classification.

Two identity-anchored overlaps were built by exact `hgvs_c` string matching against the existing
BIAS-2015 TSC2 outputs (never a cDNA→genomic projection):

- **66 VUS-overlap** variants — independent of RAPTOR/BIAS's own evidence base (a VUS carries no
  ClinVar label to leak). Functional classes: 59 functional-BLB / 3 functional-PLP / 4 ambiguous.
  functional-PLP is `UNDERPOWERED` (n=3 < `min_class_n=10`) and reported descriptively only.
- **32 ClinVar-heldout overlap** variants — explicitly **not independent**, because BIAS/RAPTOR's
  TSC2 pipeline was built and QA'd against ClinVar-derived evidence; this overlap is reported for
  descriptive concordance only, never as validation. Direction/functional-class concordance:
  23 clinical-BLB/functional-BLB, 5 clinical-PLP/functional-PLP, 4 ambiguous-direction.

Three additional, larger 2026-generation TSC2 functional datasets are registered as
`confirm_pending` (access not held) and are **not** reflected in the aggregate: IGVF VAMP-seq,
IGVF Saturation Genome Editing (SGE), and the CAGI7 TSC2 protein-stability challenge. Fetching or
scoring against these is a blocked Phase 2 item (see §5).

## 2. Primary source: MaveDB `urn:mavedb:00001201-a-1`

| Field | Value |
|---|---|
| URN | `urn:mavedb:00001201-a-1` |
| Title | TSC2 functional assay using prime editing in HAP1 cells ("cliPE") |
| Gene / transcript | TSC2 / NM_000548.5 (as stated in the scoreset's `methodText`) |
| License | CC0 1.0 (public domain dedication) |
| Variant count | 208 (raw scoreset rows) |
| Publication | PMC11185720 — *Multiplexed functional interrogation of TSC2 missense variants using massively parallel, haploid genome editing* (prime-editing MAVE), Nature Genetics, 2024 |
| DOI | `10.1101/2024.06.07.597916` |
| API | `https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1` (metadata), `.../scores` (CSV download) |
| Local, never-committed path | `D:\AIProjects\raptor-data\external\mavedb\TSC2-clipe-00001201-a-1\scores.csv` |
| Pinned sha256 | `74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717` |

The pinned sha256 above is the actual, locally-computed digest of the fetched 208-row CSV (209
lines including the header) — not a placeholder. `register.verify_registered_source` fails
closed (raises `SourceVerificationError`) if the observed transcript, license, sha256, or variant
count of any locally re-fetched copy disagree with this pin.

### 2.1 Identity matching: exact `hgvs_c`, never a projection

MaveDB's registered target transcript is `NM_000548.5`. The two on-disk, already-computed
BIAS-2015 outputs used for identity matching (`tsc_vus_input.bias_output.tsv`,
`holdout_input.bias_output.tsv`) both carry transcript `NM_000548.4`. Rather than guess or
compute a cDNA→genomic projection to reconcile the transcript versions (explicitly out of scope
per this track's charter), identity matching is done by **exact bare `c.` HGVS string equality
only** (e.g. `c.1609C>T`). This is justified empirically, not assumed: across every matched row in
both partitions, the BIAS row's own `refAllele`/`altAllele` fields agree exactly with the
substitution encoded in the `hgvs_c` string and with the BIAS row's own `hgvsg` field — **zero
ref/alt disagreements** were observed. `raptor.external.mave.identity.map_cdna_to_spdi` still
raises `ProjectionUnavailableError` when no external projector is supplied, so a full cDNA→genomic
map is never silently fabricated; only the exact-string overlap used here is claimed.

### 2.2 A pre-existing off-by-one artifact in the prior overlap fixture

While cross-checking this track's fresh BIAS-derived reconstruction against the pre-existing,
already-"verified" overlap fixture (`overlap_classified.json`), the fixture's own recorded genomic
positions were found to carry a **consistent one-base-pair offset** relative to the position
independently derivable from the on-disk BIAS-2015 output for the same bare `c.` change (BIAS's
`chromosome`/`position`/`refAllele`/`altAllele` columns and its own `hgvsg` field agree with each
other and with this track's fresh reconstruction; e.g. for `c.1609C>T` BIAS reports
`chr16:2065528 C>T` and `NC_000016.10:g.2065528C>T` consistently, while the older fixture's
`variant_id` recorded `NC_000016.10:2065527:C:T`). This is exactly the kind of drift the
fail-loud, exact-match join in `identity.join_exact_overlap` is designed to surface. Per this
track's charter ("do not weaken/skip"), the fix applied was **not** to loosen the check but to
anchor the cross-check on the identity axis both sources independently agree on — the exact bare
`c.` HGVS string — rather than on either source's genomic-position encoding. No genomic
coordinate from either source is trusted blindly by the report builder.

## 3. Registered, confirm-pending 2026 sources (Phase 2, blocked)

The following are registered in `configs/external/mave_sources.yaml` with
`verification: confirm_pending` and are **not fetched, not scored, and not reflected** in the
committed aggregate. `register.verify_registered_source` raises `ConfirmationPendingError` if any
code path attempts to treat a `confirm_pending` entry as verified.

| Source | Assay | Accessions | Status |
|---|---|---|---|
| IGVF VAMP-seq (TSC2) | protein abundance (VAMP-seq) | analysis set `IGVFDS5595BTYJ`, score file `IGVFFI9747KART` | `confirm_pending`, access not held |
| IGVF Saturation Genome Editing (TSC2) | SGE functional score | analysis set `IGVFDS1782FCXW`, score file `IGVFFI3097DFGF` | `confirm_pending`, access not held |
| CAGI7 TSC2 protein-stability challenge | community DMS challenge | genomeinterpretation.org CAGI7 TSC2 challenge | `confirm_pending`, access not held, distribution terms not yet reviewed |

These three datasets are cited by PMC12871146 — a 2026 large-scale TSC2 MAVE classifier study
(bioRxiv DOI `10.64898/2026.01.16.699909`) that combines VAMP-seq and SGE assay results with
ClinVar VUS reclassification — as the basis for a substantially larger (thousands-of-variant)
TSC2 functional atlas than the 208-variant cliPE scoreset used here. RAPTOR does not currently
hold direct access to the IGVF portal accessions or the CAGI7 challenge distribution, and no
attempt was made to scrape, mirror, or reconstruct this data. Registering them now (rather than
silently ignoring them) makes the gap auditable and gives Phase 2 a concrete, pre-registered
fetch target once access is obtained.

## 4. Circularity / independence rationale

| Overlap | n | Independent? | Rationale |
|---|---:|---|---|
| VUS-overlap | 66 | **Yes** | A VUS carries no ClinVar clinical label; RAPTOR/BIAS's TSC2 pipeline was not trained, tuned, or QA'd against a label that doesn't exist for these variants. The MAVE functional score is a genuinely external signal here. |
| ClinVar-heldout overlap | 32 | **No** | These variants carry ClinVar labels that were used (directly or via adjacent variants/policy tuning) in building and QA'ing the BIAS/RAPTOR TSC2 pipeline. Any concordance here is descriptive, not validating. |

Both partitions are built via `raptor.external.mave.partition.build_partitions`, which fails loud
(`PartitionOverlapError`) if any identity appears in more than one partition, and the two
partitions are additionally asserted disjoint at the raw BIAS-universe level (VUS-candidate-run
TSV vs. full-holdout-run TSV) before any scoring occurs.

The orthogonal correlation figures in the aggregate use BIAS-2015's own prior ACMG classification
(ordinal-encoded, benign=-2 .. pathogenic=2) as a `raptor_side_proxy` — this is RAPTOR/BIAS's own
prediction, not ground truth, not MAVE-derived, and not consumed anywhere in scoring or gating; it
exists solely to compute a descriptive correlation between the assay and RAPTOR's own directional
tendency. `functional_PLP` in both partitions is `UNDERPOWERED` (n<10) and tagged `NON_GATING`
throughout the aggregate and the eval config's `min_class_n` pin.

## 5. What is committed vs. what stays external

Per the data-architecture requirement for this track:

- **Never committed**: `D:\AIProjects\raptor-data\external\mavedb\TSC2-clipe-00001201-a-1\` (raw
  MaveDB CSV, per-variant overlap/classification fixtures), and the BIAS-2015 per-variant TSVs
  used for identity matching.
- **Committed**: this document, `configs/external/mave_sources.yaml`,
  `configs/eval/mave_tsc2.yaml`, `scripts/fetch_mave_scoreset.py`,
  `scripts/build_mave_orthogonal_report.py`, `src/raptor/external/mave/`, `tests/external/`, and
  the single non-identifying aggregate
  `data/census/tsc2_mave_clipe_orthogonal_2026-07-13.json` (counts, correlations, class-power
  labels, and citations only — no variant identities, no clinical labels).

## 6. Citations

- MaveDB API: `https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1` (metadata),
  `https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1/scores` (score CSV).
- PMC11185720 — the cliPE prime-editing TSC2 MAVE (Nature Genetics, 2024); DOI
  `10.1101/2024.06.07.597916`.
- PMC12871146 — 2026 large-scale TSC2 MAVE classifier study combining VAMP-seq + SGE with ClinVar
  VUS reclassification; DOI `10.64898/2026.01.16.699909`.
- CAGI7 TSC2 protein-stability challenge — `https://genomeinterpretation.org/` (CAGI7 challenge
  set; distribution terms not yet reviewed, access not held).
- IGVF portal accessions: analysis sets `IGVFDS5595BTYJ` (VAMP-seq) / `IGVFDS1782FCXW` (SGE);
  score files `IGVFFI9747KART` (VAMP-seq) / `IGVFFI3097DFGF` (SGE).
