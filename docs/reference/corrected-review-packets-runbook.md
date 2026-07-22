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

## Running this script

`scripts/build_corrected_review_packets.py` is a standalone entrypoint.
Both of the following are supported, from **any** current working
directory, with **no** manual `PYTHONPATH`:

```
python D:\path\to\raptor\scripts\build_corrected_review_packets.py --manifest ... --bias-tsv ... --provenance ... --census-stats ... --output-root ... --run-name ...
```

The module form is also supported, but -- like any `python -m pkg.mod`
invocation -- Python must already be able to locate the `scripts` package
**before** running any of this module's code, so the repository root must
already be on `sys.path`/`PYTHONPATH` (in practice: run it with the
repository root as the current working directory, or with the repository
root already on `PYTHONPATH`):

```
cd D:\path\to\raptor
python -m scripts.build_corrected_review_packets --manifest ... --bias-tsv ... --provenance ... --census-stats ... --output-root ... --run-name ...
```

Every `--*-config`/`--predictor-policy` flag's built-in default (e.g.
`configs/packet/schema.yaml`) and the two fixed, non-overridable
`lineage_policy`/`packet_candidate_direction` paths are resolved against
this script's own fixed on-disk location (`Path(__file__).resolve()`),
**never** the caller's current working directory -- a `--dry-run` invoked
from an unrelated directory, relying entirely on these built-in defaults,
still resolves the correct in-repo config files. Passing any of those
flags explicitly overrides the default and is then resolved normally (as
given, or relative to the caller's own cwd), exactly like any other CLI
path (`--manifest`, `--bias-tsv`, `--provenance`, `--census-stats`,
`--output-root`, which have no built-in default and are always resolved
this way).

## Inputs

| Input | Role |
| --- | --- |
| `--manifest` | Immutable `raptor-data` manifest JSONL (canonical SPDI <-> `vcf_key`) |
| `--bias-tsv` | Immutable BIAS worker output TSV |
| `--provenance` | External run provenance (`vcf_hash`, `source_snapshot`, `manifest_hash`) -- its own raw on-disk bytes are also pinned by SHA-256 (`immutable_external_inputs.provenance.sha256`) and verified BEFORE this file's JSON is parsed; content hash is authority, so the file may be supplied from any path |
| `--census-stats` | Committed current-policy census oracle (`data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`) |
| `--packet-config`, `--selection-config`, `--render-config`, `--narrative-catalog`, `--comparator-config` | Packet-path configs (`configs/packet/*`); repo-root-anchored defaults when omitted |
| `--scorer-config`, `--eval-config` | `configs/acmg/tsc.yaml`, `configs/eval/tsc2.yaml`; repo-root-anchored defaults when omitted |
| `--predictor-policy` | The approved, `disabled_manual` BP4/PP3 predictor policy artifact; repo-root-anchored default when omitted |
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
4. The current-policy census oracle, canonical Git/LF blob SHA-256 (its
   JSON is loaded once and becomes the oracle step 5 cross-checks below).
5. The provenance artifact's own raw on-disk byte SHA-256
   (`immutable_external_inputs.provenance.sha256`,
   `raw_path_bytes_external`) -- verified BEFORE its JSON is ever parsed --
   then its `vcf_hash`/`source_snapshot`
   (`raptor.census.cli._validate_provenance`), then its recorded
   `manifest_hash` (when present) against the actual `--manifest` bytes,
   then the raw `--manifest`/`--bias-tsv` bytes and the provenance
   artifact's `vcf_hash`/`source_snapshot` against the verified census
   oracle's **own** recorded `source_hashes.manifest`/
   `source_hashes.bias_tsv`/`source_hashes.input_vcf`/`snapshot` (never a
   hardcoded pin -- the census oracle is the single source of truth this
   input bundle must agree with).
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
the repository tree; refuses a `run_name` that is empty, absolute,
drive-qualified, rooted, contains a path separator, or is `.`/`..`/any
other traversal shape -- `run_name` is a single safe directory-name
component; refuses an already-existing run directory or one that resolves
outside the external root):

- `packets/<packet_id>.json` -- full operator packets, each carrying a
  top-level `census_selection_stratum` field
- `first_pass/<packet_id>.json` (+ `.md` when a render config is supplied)
  -- the blinded `FIRST_PASS` projection (neither `census_selection_stratum`
  nor `pattern_ref` is present)
- `queues/<stratum>.csv` / `queues/<stratum>.jsonl` -- one queue per
  census-selection stratum, requires `--render-config`
- `candidate_priority_queue.csv` / `candidate_priority_queue.jsonl` -- the
  LP+LB subset, requires `--render-config`
- `review_queue.csv` / `review_queue.jsonl` -- the unchanged
  `build_queue_index` ordering (`gene, canonical_spdi, packet_id`)

  All four queue artifacts above are DERIVED from `build_queue_index`'s own
  rows by filtering alone (never resorted, never rebuilt from a bare
  packet-id list), so every row carries only `build_queue_index`'s
  FIRST_PASS-safe fields (`packet_id`, `evidence_core_hash`,
  `canonical_spdi`, `gene`, `review_state`, `gate_status`, `quality_flags`,
  `contradiction` -- no direction, selection, or comparator field).
- `discovery_sample.json` -- the preregistered eight-case sample as a
  **hash-only** commitment: `{packet_id, packet_hash, evidence_core_hash}`
  per case, no raw SPDI/identity, no `census_selection_stratum`, no
  direction
- `aggregate_manifest.json` -- universe size, conservation counts,
  PP3/BP4 suppression summary, derived point distribution,
  `POLICY_BLOCKED` count, and the preregistered sample (same hash-only
  schema as `discovery_sample.json`); any packet-id list here is sorted
  lexically and is manifest ordering, not queue ordering
- `summary.json` -- a short human-readable run summary (counts only, no
  per-variant identity)

All bytes are canonical UTF-8, LF-only, exactly one terminal newline,
written via binary writes; publication is atomic (a sibling staging
directory -- asserted to resolve to a direct child of the external root,
same as the final run directory -- is renamed onto the run directory only
once every artifact, including the rename itself, has succeeded; any
failure removes the staging directory).

## Known limitations

- PP3/BP4 remain deferred under the current `disabled_manual` predictor
  policy; this run cannot and does not re-enable them.
- The Discovery eight-case comparison starts only from the frozen,
  preregistered sample **after** an independent checker returns clean; it
  is gated by the negative masked gate (`vus_authorized=false`,
  `BLOCKED_POLICY`) and expert sign-off, and is never authorized by this
  packet run itself.
