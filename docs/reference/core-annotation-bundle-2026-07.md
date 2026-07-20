# Core annotation bundle — pinned historical evidence (2026-07)

## What this is

This document is the human-readable companion to the canonical machine
manifest `configs/eval/core_annotation_bundle.yaml`
(schema `raptor-core-annotation-bundle-manifest-v1`,
status `pinned_historical_evidence`). It implements the planner contract in
`docs/project/specs/core-annotation-bundle.yaml` (rev 5).

It records the EXACT deployed Nirvana 3.18.1 / BIAS 3.0.0 annotation bundle
and its 28-source header set as pinned, immutable historical evidence for the
masked held-out rerun. **It does not download, refresh, re-annotate, or
decide activation of anything.** Pinning is not the same as re-verifying the
bundle today, and pinning is not a green light to reuse or reannotate.

## Readiness at a glance

| Axis | Value |
| --- | --- |
| Reuse readiness | `BLOCKED_POLICY_IMPLEMENTATION` |
| Reannotation readiness | `X64_WORKER_UNVERIFIED_UNTIL_OPERATOR_MAKES_AVAILABLE` |
| Licensing readiness | `PENDING_PERMITTED_USE_REVIEW` |

These three values are pinned in `configs/eval/core_annotation_bundle.yaml`
under `readiness` and must be read together with the boundaries below — none
of them assert that reuse, reannotation, or raw-score use is currently
permitted.

## Deployed runtime identity

- Annotator: Nirvana 3.18.1 (`3.18.1-0-g05f88047`), data version `91.27.66`,
  schema version `6`, genome assembly GRCh38.
- BIAS: version `3.0.0`, commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`.
- .NET runtime: `6.0.36`.
- Exactly 28 deployed data sources are pinned in `data_sources`, verified
  from the deployed Nirvana JSON header (`sample_tsc_nirvana.json.gz`,
  present on ARM). The manifest performs a full equality check — no source
  may be missing, added, or version-mismatched, so a later "latest release"
  cannot silently slip into this rerun.

## Historical evidence is pinned

The masked BIAS held-out run occurred and its outputs are immutable
evidence that is currently present on ARM. This historical evidence is
pinned — 14 files under `arm_inventory.present_hashed`, each recomputed and
hash-verified on ARM (`arm_inventory.data_root: D:\AIProjects\raptor-data`).
No x64-only path appears anywhere in `arm_inventory`; x64-only files and
directories live only in `x64_handoff_requirements.items`.

The `historical_run_attestation` section pins the full attestation chain:
input VCF, provenance, provenance manifest, return manifest, scoring report,
BIAS TSV, and held-out Nirvana JSON hashes. Policy-only reuse relies on this
immutable ARM evidence — **not** on the 58.7-GB x64 bundle still existing
today. That split is deliberate: historical attestation is independent of
current x64 reannotation readiness.

## Reuse is blocked pending the PP3/BP4 suppression contract

Reuse is blocked: `reuse_readiness` is `BLOCKED_POLICY_IMPLEMENTATION`, never
`GO_REUSE`. The existing runner has no implemented PP3/BP4 disabled/manual
suppression path — it hard-forbids `{PP5, BP6, PS4}` at config-load and
combine time, and the masked run only added a PM1 batch-scope skip. Reuse of
the immutable disabled/manual TSV cannot be declared safe until the
downstream `resolve-pp3-bp4-activation` task implements and tests an explicit
PP3/BP4 suppression contract (`PP3_BP4_SUPPRESSION_CONTRACT_REQUIRED`). Until
then, `reuse_vs_reannotate.reuse_path.current_route` stays
`BLOCKED_POLICY_IMPLEMENTATION`.

## Current x64 reannotation readiness is unverified

`current_x64_reannotation_readiness` is
`X64_WORKER_UNVERIFIED_UNTIL_OPERATOR_MAKES_AVAILABLE` / status `UNVERIFIED`,
required only for the `X64_REANNOTATE` route. The 58.7-GB deployed data
bundle is absent from ARM by design; the operator makes the x64 worker
available on demand. Six x64 handoff requirements are pinned by id in
`x64_handoff_requirements.items` (`heldout_nirvana_json`,
`nirvana_data_root`, `bias_data_root`, `nirvana_full_manifest`,
`nirvana_updates_manifest`, `bias_data_manifest`), each with a nullable
expected hash/byte-count (never fabricated) and an explicit verification
rule. Reannotation proof requires a returned `x64_bundle_verification.json`
worker artifact; RAPTOR must not download or rebuild the 58.7-GB bundle on
ARM64.

## Licensing: raw-predictor-score permissions are pending permitted-use review

Licensing is fail-closed. `historical_execution_observed` is true — a masked
BIAS run already happened and its outputs are immutable historical
artifacts — but that fact is not permission to use raw predictor scores
going forward. Local execution status, and the REVEL and AlphaMissense
per-source statuses, are all `pending_permitted_use_review`; raw public
redistribution and raw cloud egress are `false` everywhere in the manifest.
No field in this contract asserts that raw REVEL or AlphaMissense scores are
currently permitted, and REVEL/AlphaMissense raw scores must not enter any
cloud egress (including model prompts) while that review is pending. The
AlphaMissense licence version is `confirm_pending`.

## Structured extraction contract

- REVEL: `positions[].variants[].revel.score` (float). REVEL is read only
  from this structured Nirvana JSON path — never parsed from BIAS free-form
  narrative output.
- AlphaMissense: `positions[].variants[].AlphaMissense.AM_score` (float).
- Scalars: phyloP `positions[].variants[].phylopScore`, Gerp
  `positions[].variants[].gerpScore`.
- REVEL is pinned at version `20200205`; it must not be relabeled as a
  v1.3/2021 build without a resolved provenance record. Whether Pejaver
  REVEL intervals apply to this exact build is an open, downstream question
  — not assumed here.

## Deferred upgrades (explicitly out of scope for this rerun)

`dbNSFP 5.x`, `MANE 1.5`, `gnomAD 4.1.1`, `dbSNP 157`, `RepeatMasker`, and
broad 16-predictor coverage are future source-modernization work and must
not enter this rerun.

## Operator / x64 routing summary

| Route | When it applies | Current status |
| --- | --- | --- |
| `POLICY_ONLY_REUSE` | Upstream inputs unchanged and the PP3/BP4 suppression contract is implemented and tested | Not selected — suppression contract absent |
| `X64_REANNOTATE` | Any upstream input changes, or PP3/BP4 activation needs a structured input the held-out JSON lacks | Not selected — requires operator to make the x64 worker available and pass the six handoff requirements |
| `BLOCKED_DATA_until_x64_verifies` | Upstream inputs are unknown or unverifiable | Fallback if evidence cannot be confirmed |

This document and the manifest it mirrors record pinned historical evidence
only. They do not select reuse or reannotation, do not clear cloud egress
for raw predictor scores, and do not make the PP3/BP4 activation or owner
decision.
