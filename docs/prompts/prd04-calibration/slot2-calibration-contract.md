# Slot 2 — Real TSC provisional calibration-batch build contract

## Output (build via the loop; planner authors only slots + manifest)

- `scripts/build_tsc_calibration_batch.py` (the only new script surface)
- `tests/packet/test_tsc_calibration_batch.py` (independent synthetic oracle + optional real integration)
- `configs/packet/calibration.yaml` **only if** a truly separate config pin is required (else reuse
  existing configs)

No packet-module edits unless a demonstrated missing reusable API blocks the script (record as a blocker;
do not silently patch a frozen module).

## Goal

Assemble a **real, deterministic, provisional TSC calibration batch** from the pinned
`clinvar_2026-07-07` VUS run that (a) reproduces the already-recorded census selection strata and
exact-strength pattern catalog, (b) conserves the source of record and fails loud on any drift, (c) emits
PRD-04-schema-conformant, provenance-complete, **direction-null / `POLICY_BLOCKED`** packets, and (d)
selects a batch (via `select_calibration_batch`) that covers all 30 observed patterns plus every observed
gene / variant class / edge flag. **Selection / evidence review only — never classification.**

## Pinned inputs (all read-only; none is a label/knowns/benchmark file)

| Role | Path | Conservation pin |
|---|---|---|
| Manifest identities | `<raptor-data>/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.manifest.jsonl` | 6,618 rows; `variant_id` = canonical GRCh38 SPDI |
| BIAS output TSV | `<raptor-data>/clinvar/vus-run/tsc-vus-2026-07-07/tsc_vus_input.bias_output.tsv` | 6,618 data rows (18-col contract); `sha256 = 0a55cab4…62e` |
| Run provenance | `<raptor-data>/clinvar/vus-run/clinvar_2026-07-07/tsc_vus_input.provenance.json` | `vcf_hash = 3fff6de7…a09`; `manifest_hash`; `source_snapshot = clinvar_2026-07-07` |
| Census source of record | `data/census/tsc_vus_clinvar_2026-07-07_stats.json` | 238 LP / 1,333 LB; 20 / 10 patterns; 1,222; 3,739 both-direction; criterion firing |
| Lineage audit | `data/census/tsc_bias_lineage_audit_2026-07-10.json` | BIAS `3.0.0` / commit `ade13f2…8da8f`; blocking PM5/PS1 |
| Scorer strength policy | `configs/acmg/tsc.yaml` | `strength_map` int→vocab; `included_criteria` |
| Eval combiner policy | `configs/eval/tsc2.yaml` | `automatable_criteria`, `tavtigian_points`, `tavtigian_cutoffs` |
| BIAS lineage policy | `configs/eval/bias_lineage.yaml` | 8 lineage classes, 4 dispositions (via `load_lineage_policy`) |
| Packet config | `configs/packet/schema.yaml` (+ candidate_direction / selection / render / narrative) | schema version; unapproved policy → null direction |

`<raptor-data>` paths are **CLI arguments**, never hardcoded; the script must not assume a fixed absolute
path (portability + no baked machine layout).

## Reused public APIs (do not reimplement)

- `raptor.scorer.bias_source.BiasTsvSource(path).records()` → `BiasRecord` (chrom/pos/ref/alt/variant_id/
  consequence/gene_name/transcript + flat `criteria` mapping).
- `raptor.scorer.config.load_config` → `ScorerConfig.strength_map`.
- `raptor.scorer.parse.parse_rationale(criteria, strength_map)` → `[CriterionCall(criterion, strength,
  direction, rationale), …]` (only fired int > 0).
- `raptor.eval.config.load_config` + **`raptor.eval.combine.implied_direction(calls, eval_config)`** →
  `ImpliedCall(implied ∈ {LP, LB, no_call}, points)`. **Imported and called only at script scope
  (outside `src/raptor/packet`)** to reproduce the census stratum. Basis token
  `eval_only_census_selection_metadata`.
- `raptor.eval.lineage_policy.load_lineage_policy`.
- `raptor.packet.config.{load_packet_config, load_selection_config, load_render_config,
  load_narrative_catalog}`.
- `raptor.packet.model.{PacketInput, PacketCriterionInput, CanonicalVariantIdentity, ScorerProvenance,
  PrimaryEvidenceRef, PrimaryGrounding, MissingEvidence, PatternRef, RunMetadata, SourceSnapshotPins,
  redact_for_first_pass}`.
- `raptor.packet.build.build_packet(packet_input, config, narrative_plan=None)` → direction-null,
  `POLICY_BLOCKED` packet under the unapproved production policy.
- `raptor.packet.queue.{select_calibration_batch, coverage_report, build_queue_index}`.
- `raptor.packet.render.render_markdown(packet, render_config, view=PacketView.FIRST_PASS)`.

## Module functions (all module-level, individually testable, deterministic)

### 1. Census-stratum reproduction (eval-only, outside the packet path)

```
@dataclass(frozen=True)
class StratumEntry:
    variant_id: str            # canonical GRCh38 SPDI (manifest join key)
    stratum: str               # candidate_LP_review | candidate_LB_review | no_deterministic_resolution | manual_review
    pattern_id: str            # canonical exact-strength signature (empty for non-LP/LB)
    pattern_signature: tuple[str, ...]   # sorted ("PVS1 Very Strong", "PM2 Supporting", …)
    signed_points: int
    basis: str                 # constant "eval_only_census_selection_metadata"

def reproduce_census_strata(
    bias_rows, scorer_config, eval_config
) -> tuple[StratumEntry, ...]:
    # For each BIAS row: parse_rationale(row.criteria, scorer_config.strength_map) -> calls;
    # keep only eval_config.automatable_criteria; implied_direction(calls, eval_config) -> ImpliedCall;
    # map implied LP/LB (points>=likely_pathogenic_min / <=likely_benign_max) to the census stratum
    # tokens; the exact-strength pattern signature = sorted "<CRITERION> <Strength Title Case>" over the
    # direction-contributing automatable criteria that produced the stratum. Manual-review (NTHL1) rows
    # are pre-routed out (see quality flags) and never enter LP/LB.
```

> **Strength-labeling determinism pin.** The census pattern `{BP4 Strong, PM2 Supporting} = −3` requires
> BIAS's fired int → `strength_map` mapping (BP4 int 3 → `strong`) and the eval `tavtigian_points`
> (`strong=4`, `supporting=1`). The doer must pin the exact `(strength_map, tavtigian_points,
> tavtigian_cutoffs, automatable_criteria)` tuple that reproduces the census counts and pattern catalog;
> if no pinned config tuple reproduces **238 LP + 1,333 LB and 20 + 10 patterns**, that is a **blocker**
> to resolve against the census oracle, not a silent re-label.

### 2. Fail-loud source-of-record conservation

```
class ConservationError(RuntimeError): ...

def assert_source_of_record_conservation(manifest, bias_rows, strata, census_stats, provenance) -> None:
    # Raise ConservationError unless ALL hold:
    #   len(manifest) == 6618; len({m.variant_id}) == 6618
    #   len(bias_rows) == 6618; len(unique raw row keys) == 6618
    #   manifest variant_id set == BIAS-row locus set (SPDI join, exact)
    #   count(stratum==candidate_LP_review) == 238
    #   count(stratum==candidate_LB_review) == 1333
    #   distinct LP pattern_ids == 20; distinct LB pattern_ids == 10; total == 30
    #   bias_output_sha256(file) == census_stats.run_integrity.bias_tsv_sha256 == provenance/audit pins
    #   worker versions (bias 3.0.0 / commit / nirvana 3.18.1) match census + audit
    # Every check names the expected vs actual value in the raised message.
```

The **BP4/PP3 aggregation defect** is **not** repaired here: BIAS aggregates correlated computational
predictors and can fire both `PP3` (pathogenic) and `BP4` (benign) on the same variant (contributing to
the 3,739 both-direction census total). It is recorded as a contradiction + edge flag and pinned as a
batch limitation. Silent correction is a falsifier.

### 3. Real scorer provenance + edge flags

```
def build_scorer_provenance(bias_row, run_pins) -> ScorerProvenance:
    # bias_row_key = deterministic BIAS row identity; chromosome/position/ref/alt from the row;
    # input_sha256 = sha256(VCF)  (provenance.vcf_hash / census.input_vcf_sha256)
    # output_sha256 = sha256(BIAS TSV)  (census.bias_tsv_sha256)
    # raw_row_sha256 = sha256(canonical raw TSV row bytes)   # per-row, real
    # bias_version "3.0.0"; bias_commit "ade13f20…8da8f"; nirvana_version "3.18.1"
    # transcript = the RAW BIAS transcript (e.g. NM_000548.4) recorded verbatim in provenance

def derive_quality_flags(bias_row, identity, calls) -> tuple[str, ...]:
    # Observed edge flags (sorted, deduped), e.g.:
    #   "nthl1_misannotation"          (30 TSC2-region inputs annotated NTHL1 -> manual_review)
    #   "transcript_version_drift"     (BIAS .4 vs MANE production .5)
    #   "bs2_no_rationale"             (BS2 fired without recorded rationale)
    #   "bp4_pp3_computational_aggregation"  (BP4 and PP3 both fired -> defect pin)
    #   "contradiction"                (both pathogenic and benign direction evidence)
```

### 4. Packet assembly (direction-null, POLICY_BLOCKED)

```
def build_packet_input(identity, bias_row, stratum_entry, packet_config, run_pins) -> PacketInput:
    # criterion_inputs = one PacketCriterionInput PER FIRED BIAS CRITERION (every fired criterion,
    #   not just the direction-contributing ones), each with exactly one real ScorerProvenance and
    #   primary_grounding = PrimaryGrounding.ABSENT + reason "no_primary_literature_or_ps3_assay"
    #   (PS3 / literature required-but-absent). primary_evidence_refs = () -> a BIAS row is never a ref.
    # identity = CanonicalVariantIdentity(canonical_spdi=manifest SPDI, gene in {TSC1,TSC2},
    #   transcript = MANE .5 production identity, consequence, variant_class in {missense,truncating,other})
    # pattern_ref = PatternRef(census_snapshot_id="clinvar_2026-07-07",
    #   pattern_id=stratum_entry.pattern_id, census_selection_stratum=stratum_entry.stratum, …)
    #   -> operator-only; stripped from FIRST_PASS.
    # missing_evidence includes a grounded "no functional/PS3 assay" next-action.
    # quality_flags = derive_quality_flags(...); external_comparators = () unless --aavc-comparator given.

def build_candidate_universe(strata, bias_rows, manifest, packet_config, run_pins)
    -> tuple[CandidateEvidencePacket, ...]:
    # Build exactly the 1,571 LP+LB packets via build_packet (candidate_direction null, POLICY_BLOCKED).
    # NTHL1 manual_review + no_deterministic_resolution variants are NOT in the candidate universe.
```

### 5. Selection + coverage assertion

```
def select_batch(universe, selection_config) -> Batch:
    return select_calibration_batch(universe, selection_config)   # PRD-04 FR17, deterministic (seed 42)

def assert_batch_coverage(batch, strata) -> None:
    # Fail loud unless batch.coverage.covered proves, per independent dimension:
    #   pattern: all 30 observed pattern_ids
    #   gene: {TSC1, TSC2} observed
    #   variant_class: every observed class
    #   edge_flag: every observed edge flag
    # and batch.coverage.missing is empty on every dimension, and no impossible/unpopulated cell selected.
```

### 6. Output writers (outside repo) + in-repo aggregate

```
def canonical_json(obj) -> str:            # sort_keys=True, separators=(",",":"), UTF-8, trailing "\n"

def write_outputs(output_dir, universe, batch, render_config, manifests) -> None:
    #  <output-dir>/packets/<packet_id>.json              (OPERATOR source of record, one per SELECTED packet)
    #  <output-dir>/first_pass/<packet_id>.md             (render_markdown view=FIRST_PASS)
    #  <output-dir>/queue/tsc_calibration_queue.csv|.jsonl (build_queue_index over the SELECTED batch; FIRST_PASS projection)
    #  <output-dir>/coverage/coverage_report.json         (populated/covered/impossible/missing)
    #  <output-dir>/batch_manifest.json                   (see build_batch_manifest)
    # All writes are byte-deterministic; packet ordering by packet_id.

def build_batch_manifest(...) -> dict:
    # source hashes (VCF/BIAS-TSV/manifest/census/audit sha256), config hashes (packet/selection/render/
    # narrative/scorer/eval/lineage sha256), code_commit, run pins (bias 3.0.0 / commit / nirvana 3.18.1),
    # conservation record (6,618 / 238 / 1,333 / 20 / 10), selected_packet_ids, coverage summary, and an
    # explicit `limitations` list (see below).

def build_census_source_of_record(...) -> dict:
    # AGGREGATE, NON-IDENTIFYING only: counts, pattern-catalog sizes, selected-batch size, source/config
    # hashes, limitations. NO per-variant SPDI, NO patient data. This is the ONLY file committed under
    # data/census, and only AFTER the real run + checker.

def main(argv=None) -> int:   # argparse CLI; any ConservationError / coverage failure -> non-zero exit
```

### Pinned `limitations` (batch + census manifest)

- `bias_bp4_pp3_aggregation_defect` — BIAS aggregates correlated computational predictors; PP3 and BP4
  can both fire on one variant. **Preserved as contradiction + edge flag; never corrected.**
- `aavc_comparator_omitted` — no pinned AAVC input; first batch omits the comparator; no network call.
- `candidate_direction_null_policy_blocked` — production policy unapproved; all packets `POLICY_BLOCKED`;
  not classifications.
- `primary_grounding_absent` — PS3/literature primary evidence absent for all packets; external
  readiness blocked (PRD-04 AC18).
- `transcript_version_drift` — BIAS emits `.4` transcripts; production MANE identity pins `.5`.
- `nthl1_misannotation` — 30 TSC2-region inputs annotated NTHL1; routed to manual_review, excluded from
  the LP/LB candidate universe.

## CLI

```
python scripts/build_tsc_calibration_batch.py \
  --manifest PATH --bias-tsv PATH --provenance PATH \
  --census-stats data/census/tsc_vus_clinvar_2026-07-07_stats.json \
  --lineage-audit data/census/tsc_bias_lineage_audit_2026-07-10.json \
  --packet-config configs/packet/schema.yaml \
  --selection-config configs/packet/selection.yaml \
  --render-config configs/packet/render.yaml \
  --narrative-catalog configs/packet/narrative_templates.yaml \
  --scorer-config configs/acmg/tsc.yaml \
  --eval-config configs/eval/tsc2.yaml \
  --output-dir PATH                        # REQUIRED; must be outside the repo; no patient data \
  [--aavc-comparator PATH]                 # optional; omitted by default (no network) \
  [--emit-census-record data/census/NAME.json]   # gated; writes ONLY the aggregate non-identifying JSON
```

`--output-dir` is **required**; the script refuses to run without it and refuses a path inside the repo
tree. No stdout leaks a per-variant SPDI beyond the operator artifacts under `--output-dir`.

## Acceptance criteria (Gemini authors as executable tests first)

- **CAL-AC1 — Conservation, fail-loud.** Exactly 6,618 manifest identities and BIAS rows; 238 LP + 1,333
  LB queue; 20 LP + 10 LB = 30 patterns; matching source hashes/versions. Dropping/adding any row, or a
  count/pattern drift, raises `ConservationError` and aborts before output.
- **CAL-AC2 — Packet conformance.** Every packet validates against the PRD-04 schema with
  `candidate_direction=null`, `null_reason=production_policy_unapproved`, `review_state=POLICY_BLOCKED`;
  carries every fired BIAS criterion; each criterion has exactly one real-format `ScorerProvenance`
  (real input/output/raw-row sha256, BIAS `3.0.0`/commit, Nirvana `3.18.1`, raw BIAS transcript) and
  `primary_grounding=absent`; canonical SPDI from the manifest; MANE `.5` identity; observed quality/edge
  flags. A BIAS row can never be constructed as a `PrimaryEvidenceRef`.
- **CAL-AC3 — Selection + coverage.** `select_calibration_batch` over the 1,571 universe yields a
  deterministic batch whose coverage proves all 30 patterns + every observed gene/class/edge flag as
  independent atoms, `missing` empty, no impossible cell selected; batch may exceed 30 only to cover
  remaining atoms.
- **CAL-AC4 — First-pass redaction.** `FIRST_PASS` Markdown + queue CSV/JSONL contain **no**
  `candidate_direction`/`null_reason`/signed points/policy id/`census_selection_stratum`/AAVC field; the
  operator packet JSON + batch manifest may carry `census_selection_stratum`.
- **CAL-AC5 — Limitations pinned.** The batch + census manifests list the BP4/PP3 aggregation defect,
  AAVC omission, null-direction/POLICY_BLOCKED, absent primary grounding, transcript drift, and NTHL1
  misannotation. No benchmark label / knowns file is opened; no submission/public worklist is written.
- **CAL-AC6 — Determinism.** Two runs over identical inputs/config produce byte-identical packet JSONs,
  Markdown, queue, coverage, and manifests (canonical serialization; packet_id ordering).
- **CAL-AC7 — Eval-only reuse boundary.** `implied_direction` is imported/called only at script scope
  (outside `src/raptor/packet`); the packet path imports no `eval.*` combiner; direction stays null; the
  reproduction records basis `eval_only_census_selection_metadata`.
- **CAL-AC8 — Output boundary.** `--output-dir` required and outside the repo; the only in-repo write is
  the aggregate non-identifying `data/census` JSON (no per-variant SPDI, no patient data), gated behind
  `--emit-census-record`.

## Test oracle (independent, portable)

`tests/packet/test_tsc_calibration_batch.py`:

- **Synthetic corpus oracle.** Hand-build ~6–12 fixture BIAS rows with KNOWN fired criteria/strengths,
  KNOWN implied strata, and KNOWN patterns; drive `reproduce_census_strata` + `assert_source_of_record_
  conservation` with **synthetic** expected counts (parameterized, NOT the real 6,618/238/1,333 — keeps
  the unit test portable with no external data). Assert fail-loud on a dropped row, a mutated count, and a
  divergent pattern set.
- **Packet assertions.** Each synthetic packet: null direction, `POLICY_BLOCKED`, every fired criterion
  present, real-format `ScorerProvenance` (per-row `raw_row_sha256`), `primary_grounding=absent`, BP4/PP3
  contradiction preserved, quality flags; BIAS row never a `PrimaryEvidenceRef`.
- **Redaction assertions.** `FIRST_PASS` render + queue rows carry no direction/stratum/comparator; the
  operator JSON may.
- **Coverage assertions.** All synthetic patterns + genes + classes + edge flags covered; `missing` empty;
  no impossible cell selected.
- **Determinism assertions.** Two builds byte-identical; input row order permutation-invariant.
- **Import-boundary assertion.** No `raptor.eval.combine` import reachable from `src/raptor/packet`;
  `implied_direction` used only by the script.
- **Optional real integration test.** Gated by `RAPTOR_TSC_CALIBRATION_REAL=1` + env paths
  (`RAPTOR_TSC_MANIFEST`, `RAPTOR_TSC_BIAS_TSV`, `RAPTOR_TSC_PROVENANCE`); **skipped by default**.
  Asserts the exact real 30-pattern / 238 / 1,333 / 6,618 conservation and first-pass redaction against
  the pinned artifacts. The real run occurs **after** the checker.

## Out of scope

Production candidate-direction policy approval; any non-null direction; PRD-06 `PASS`; per-variant
sign-off; `classification_versions` writes; the KB→`PacketInput` adapter; AAVC reconciliation; ClinVar
submission; any public/external worklist. `na_allowed: false`.
