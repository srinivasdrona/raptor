# Corrected all-VUS expert-review packet run book

**Track:** `track/review-packets-2026-07`
**Spec:** `docs/project/specs/corrected-review-packets-2026-07.yaml`

## Purpose

Assembles a corrected, evidence-review-only packet for **every** VUS in the
current-policy `clinvar_2026-07-07` TSC census run -- all four
census-selection strata (`candidate_LP_review`, `candidate_LB_review`,
`no_deterministic_resolution`, `manual_review`) -- instead of only the 164
candidate-priority (LP+LB) rows the earlier calibration batch selected.
Every packet, in every stratum, keeps `candidate_direction=null` /
`null_reason=production_policy_unapproved` /
`review_state=POLICY_BLOCKED`: this run authorizes no classification,
worklist, submission, or clinical claim. It is evidence-review scaffolding
only.

## What this run does NOT do

- It never scores PP3/BP4 (both stay `deferred`, contribute zero points,
  and are counted only in the aggregate suppression summary).
- It never emits an AAVC comparator match (`--aavc-comparator` is accepted
  but unused; every packet keeps `external_comparators=()`).
- It never writes any artifact inside the repository tree. Full
  packets/queues/first-pass views/manifest land ONLY under a brand-new,
  external run directory.
- It never overwrites an existing run directory or the frozen
  `2026-07-11` historical calibration artifact.

## Inputs

| Input | Role |
| --- | --- |
| `--manifest` | Immutable `raptor-data` manifest JSONL (canonical SPDI <-> `vcf_key`) |
| `--bias-tsv` | Immutable BIAS worker output TSV |
| `--provenance` | External run provenance (`vcf_hash`, `source_snapshot`, `manifest_hash`) |
| `--census-stats` | Committed current-policy census oracle (`data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`) |
| `--packet-config`, `--selection-config`, `--render-config`, `--narrative-catalog`, `--comparator-config` | Packet-path configs (`configs/packet/*`) |
| `--scorer-config`, `--eval-config` | `configs/acmg/tsc.yaml`, `configs/eval/tsc2.yaml` |
| `--predictor-policy` | The approved, `disabled_manual` BP4/PP3 predictor policy artifact |
| `--output-root`, `--run-name` | The external RAPTOR data root and this run's directory name |
| `--aavc-comparator` | Accepted, currently unused |
| `--dry-run` | Run every verification/conservation/assembly step; write nothing |
| `--summary` | Print the aggregate manifest (JSON) to stdout |

## Verification order (fails closed, before any write)

1. Predictor-policy **artifact** identity (canonical path + Git/LF blob
   SHA-256), then its `{schema, status, mode}` contract.
2. The four subordinate configs (scorer/eval/lineage/candidate-direction),
   RAW on-disk byte SHA-256, against the hashes recorded **inside** the
   approved policy (`raptor.census.cli._verify_bound_hashes`).
3. The five packet render/selection/narrative/comparator/schema configs,
   RAW on-disk byte SHA-256, against this track's own pins.
4. The current-policy census oracle, canonical Git/LF blob SHA-256.
5. The provenance artifact's own `vcf_hash`/`source_snapshot`
   (`raptor.census.cli._validate_provenance`), then its recorded
   `manifest_hash` (when present) against the actual `--manifest` bytes.
6. A full 40-hex `git rev-parse HEAD` on a clean working tree
   (`raptor.packet.git_provenance.resolve_corrected_provenance`) -- a
   dirty tree or an abbreviated/unresolvable commit fails closed.

Only once every check above passes does the script reproduce the
exact-join current-policy strata
(`raptor.census.strata.reproduce_census_strata`), conserve the derived
counts against the committed oracle
(`raptor.packet.corrected_universe.conserve_current_policy`), assemble the
full four-stratum universe
(`raptor.packet.corrected_universe.build_full_vus_universe`), and select
the deterministic eight-case discovery sample
(`raptor.packet.corrected_universe.select_discovery_sample`).

## Output layout

Unless `--dry-run` is set, `write_corrected_run_outputs` writes, under a
brand-new `<output-root>/<run-name>/` directory (refuses any path inside
the repository tree, and refuses an already-existing run directory):

- `packets/<packet_id>.json` -- full operator packets
- `first_pass/<packet_id>.json` (+ `.md` when a render config is supplied)
  -- the blinded `FIRST_PASS` projection
- `queues/<stratum>.json` -- one queue per census-selection stratum
- `candidate_priority_queue.json` -- the LP+LB subset
- `review_queue.csv` / `review_queue.jsonl` -- the unchanged
  `build_queue_index` ordering (`gene, canonical_spdi, packet_id`)
- `discovery_sample.json` -- the preregistered eight-case sample
- `aggregate_manifest.json` -- universe size, conservation counts,
  PP3/BP4 suppression summary, derived point distribution,
  `POLICY_BLOCKED` count, and the preregistered sample
- `summary.json` -- a short human-readable run summary

All bytes are canonical UTF-8, LF-only, exactly one terminal newline,
written via binary writes; publication is atomic (a sibling staging
directory is renamed onto the run directory only once every artifact has
been written).

## Known limitations

- PP3/BP4 remain deferred under the current `disabled_manual` predictor
  policy; this run cannot and does not re-enable them.
- The Discovery eight-case comparison starts only from the frozen,
  preregistered sample **after** an independent checker returns clean; it
  is gated by the negative masked gate (`vus_authorized=false`,
  `BLOCKED_POLICY`) and expert sign-off, and is never authorized by this
  packet run itself.
