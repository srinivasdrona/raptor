# Slot 2 — PRD-04 candidate evidence packet (revised after rubber-duck NO-GO; r3 update)

## Output

Create only:

- `docs/prd/PRD-04-candidate-evidence-packet.md`

## Goal

Specify a versioned, expert-reviewable **candidate evidence packet** and queue index for every TSC
VUS. RAPTOR presents a grounded **review direction**, never a classification:

- `candidate_LP_review`
- `candidate_LB_review`
- `no_deterministic_resolution`
- `manual_review`
- **or `null`** (see Direction, below) when no production candidate-direction policy is approved yet.

Provisional packets are generated before validation; externally usable worklists require benchmark
PASS, corrected policy, and qualified expert sign-off. A packet is an **evidence-review** artifact,
not a classification.

## Sources

- `docs/STRATEGY.md` GP-1/3/5/6/8/9/11/13, §9 (two sign-off levels)
- `docs/PROGRAM.md` census/priorities/PRD-04 sequencing (items 6/8/9), AAVC boundary
- `docs/DECISIONS.md` ADR-0009 (ClinVar lineage) / ADR-0010 (vertical reset)
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (pattern/topology facts + provenance)
- `configs/eval/bias_lineage.yaml` + `src/raptor/eval/lineage_policy.py` (machine-readable lineage)
- `data/census/tsc_bias_lineage_audit_2026-07-10.json` (static lineage gate outcome)
- `docs/reference/aavc-prior-art-audit-2026-07.md` (external comparator controls)
- `docs/prd/PRD-01-tier12-acmg-scorer.md`, `src/raptor/scorer/model.py`, `report.py`
- `docs/prd/PRD-03-kb-schema-provenance-ledger.md`, `src/raptor/kb/store.py` (persistence semantics)
- `docs/prd/PRD-06-benchmark-eval-harness.md`, `docs/prd/PRD-08-live-eval-evidence-adapter.md`

## Assembly model (NO-GO fix — items 2, 6, 10 buildable now)

The packet library assembles a packet from an **injected `PacketInput`** (evidence records +
provenance + comparator + census-selection metadata). It **must not** require the 6,618 VUS to already
exist in the PRD-03 KB, **must not** read a benchmark/held-out/label/oracle file, and **must not**
import the eval combiner. A KB adapter that materializes `PacketInput` from the PRD-03 KB is a
**separate, future** surface, out of this increment. This makes real provisional/calibration packets
buildable now (STRATEGY GP-1; PROGRAM item 9).

## Required packet model

Pin a machine-readable schema (`configs/packet/schema.yaml` + JSON Schema) with at least:

- `packet_schema_version`, `packet_id`, and the **four named hashes** (see Hash domains);
- run/config/code/model/prompt/source snapshot pins (**run metadata**, excluded from the evidence
  core hash);
- canonical GRCh38 SPDI identity, gene ∈ {TSC1, TSC2}, MANE transcript, consequence, variant class;
- per-criterion entry: raw fired criterion + rationale, **machine-read lineage** (both raw dispositions
  preserved — see Lineage), derived `packet_policy_disposition`, criterion strength + direction;
- **two-level provenance** (see Provenance);
- `candidate_direction` (nullable) + `null_reason`, policy id/version, signed point calculation
  (see Direction);
- contradictions (both-direction firing preserved), quality/manual flags;
- excluded evidence + machine exclusion reason; missing-evidence categories + grounded next-evidence
  action;
- a **structured narrative plan** (template ids + packet field bindings only — see Narrative), with
  `model` + `prompt_hash`; a separate reviewer-notes block (freeform, excluded from generated
  narrative, never fact-safe-claimed);
- `external_comparators` **reveal-only** envelope (see AAVC), excluded from evidence core + **stripped
  from the `FIRST_PASS` view along with the candidate direction/signed points**;
- `review_state` + per-criterion reviewer decisions (append-only, variant-scoped log — see Decision
  log);
- calibration selection metadata (`census_selection_stratum`, `pattern_id`) — selection only, never a
  cutoff;
- revision/supersession linkage.

### Provenance — two levels, pinned schemas (NO-GO fix, item 2; r3-5)

Every scored criterion carries **exactly one mandatory `ScorerProvenance`** (all fields required, strict
formats: `bias_row_key`, `chromosome`, `position`, `ref`, `alt`, `scorer_run_id`, `input_sha256`,
`output_sha256`, `raw_row_sha256`, `bias_version`, `bias_commit`, `nirvana_version`, `transcript`) plus
**zero or more `PrimaryEvidenceRef`s** (`ref_id`, `source_type` enum, `source_id`/`accession`,
`locator`/`span`, `source_snapshot`/`version`, `source_sha256` nullable only with an explicit
`source_sha256_null_reason`, `supports_criterion`, `resolution_status` ∈ {resolved, unresolved},
`unresolved_reason`). `ScorerProvenance` resolves to a **BIAS raw row** and is **never** a
`PrimaryEvidenceRef` (distinct types; a BIAS row can never be constructed as primary). A ref is
`resolved` only with `source_id` + `locator`/`span` + `source_snapshot`/`version` + (checksum **or**
checksum-null-reason). Each `CriterionEntry` has exactly one `scorer_provenance` + zero-or-more primary
refs + `primary_grounding ∈ {present, absent, not_required}` + reason. `primary_required` = any
included/deferred functional/literature (PS3 / `literature_unvalidated`) claim + every criterion
config-flagged `primary_required: true`; **unknown fails closed**. Missing primary grounding blocks
external readiness where policy requires (a `primary_required` criterion), never the provisional packet.
Scorer-row provenance being present is not primary grounding.

### Lineage — machine-read + exhaustive disposition precedence (NO-GO fix, item 10; r3-1)

Each criterion entry consumes the **exact** `lineage_class`, `validation_disposition`,
`production_disposition`, and `decision_dependency` from `configs/eval/bias_lineage.yaml` via
`load_lineage_policy` — the packet **never invents** source lineage in code, and **preserves both raw
disposition fields verbatim**. Because `validation_disposition` and `production_disposition` legitimately
differ (PS1/PM5/PM1/PP2/BP1 are `requires_heldout_mask` at validation but `allowed` in production), the
packet derives one `packet_policy_disposition` via **exactly one exhaustive precedence function**
`resolve_packet_policy_disposition(validation, production)` — for this pre-validation packet the
**validation disposition dominates** (first match wins):

1. `validation == forbidden` → **excluded** (`direct_copy_forbidden`: PP5/BP6/PS4);
2. `validation == requires_heldout_mask` → **masked** — **regardless of** production (PS1/PM5/PM1/PP2/BP1);
3. `validation == deferred` **or** `production == deferred` → **deferred** with `decision_dependency`
   (PS3, BS2);
4. `validation == allowed` **and** `production == allowed` → **included**;
5. any other combination (incl. `production == forbidden` under a non-forbidden validation disposition, or
   any unknown pairing) → **fail loud** (never silently `included`).

Tests lock the precedence to the loader's output, not a hardcoded map.

### Direction — nullable, not the eval combiner (NO-GO fix, item 6; r3-3)

`candidate_direction` may be `null`. When no production candidate-direction policy is Oracle-approved,
the packet sets `candidate_direction = null`, `null_reason = production_policy_unapproved`, and is routed
to `POLICY_BLOCKED` for candidate-direction progression. A direction-null packet may be evidence-complete
and **eligible for first-pass evidence review** (the direction-blinded view) but **cannot** enter any
candidate-direction approval or external state. The census pattern facts (20 LP + 10 LB patterns;
238/1,333; 1,222) are **selection metadata pinned to the census analysis only** — they **never** define
candidate cutoffs or criteria inclusion. The eval Tavtigian combiner is **not** imported/restated as
production policy. A calibration packet may carry `census_selection_stratum` + `pattern_id` while
remaining `candidate_direction = null` / `POLICY_BLOCKED` — a valid evidence-review packet, not a
classification.

### Narrative — template-constrained plan (NO-GO fix, item 3)

Replace freeform narrative. The model may **only** select and order **approved template ids** and bind
**packet field paths** — a `NarrativePlan = [ {template_id, field_bindings{path: packet_field_path}} ]`.
A **deterministic renderer** expands templates against the bound packet fields; the model authors no
arbitrary factual text or citations. Any freeform note is **reviewer-authored**, lives in a separate
`reviewer_notes` block, is excluded from the generated narrative, and is never mechanically claimed
fact-safe. The narrative-plan check is mechanically decidable: every `template_id ∈ catalog` and every
bound path resolves to an existing packet field.

### Hash domains — four exact names (NO-GO fix, item 4)

Define four canonical hash domains with exact names and canonical serialization:

1. `evidence_core_hash` — sha256 over the **immutable deterministic evidence core** (canonical
   identity, sorted criterion trail + lineage + disposition + strengths/directions + two-level
   provenance refs, direction/null_reason + signed points, exclusions/contradictions/missing-evidence).
   Excludes narrative, comparators, run metadata, review state, decisions.
2. `narrative_plan_hash` — sha256 over the canonical structured narrative plan (template ids +
   bindings), plus `model` + `prompt_hash`.
3. `packet_envelope_hash` — sha256 over the full envelope: `evidence_core_hash` + `narrative_plan_hash`
   + the **enumerated** run-metadata pins the envelope binds (schema version, config/policy versions,
   source snapshot id). It **excludes** `run_id`, `generated_at`, and other non-reproducible run fields
   (these are recorded but not hashed).
4. decision-log record hash chain — a **separate** append-only chain (`record_hash` over
   `prev_hash + canonical(record)`); see Decision log.

State changes and reviewer decisions **must not mutate a prior packet hash** — they produce either a
new content-addressed packet version or an appended decision-log record.

## Persistence (NO-GO fix, item 1 — do not misuse `classification_versions`; r3-4)

Reviewer decisions and pattern-policy decisions are written to a **NEW variant-scoped append-only
hash-chained decision log**: **exactly one log per canonical variant identity**, spanning **all packet
versions**, addressed **deterministically from the canonical variant hash**
(`<root>/<sha256(canonical_variant_spdi)>.jsonl`, never a raw/unsafe identity). Each record carries a
`record_id` (caller-provided UUID or exact deterministic key), `event_type`, the bound
`packet_id`/`evidence_core_hash`/`variant_id` (+ supersession links), actor/role/timestamp, payload,
`prev_hash`, `record_hash = sha256(prev_hash + canonical(record))`. **Genesis `prev_hash` = 64 lowercase
zeroes.** Idempotency: same `record_id` + payload is a no-op returning the existing record; same
`record_id` + different payload **fails loud**. Single-writer v1 takes an **OS advisory/exclusive file
lock** and does **append → flush → fsync while held**. `replay` verifies **one linear `prev_hash` chain**
(no fork/gap/hash mismatch) and packet/variant identity; any tamper or cross-variant record fails loud.
PRD-03 `classification_versions` is **reserved solely** for a terminal, qualified, variant-level
classification after all gates + sign-offs and is **NOT written by this first increment** (note: PRD-03's
ledger `EventType` vocabulary is frozen and has no packet-decision event, so the decision log is
packet-owned by construction). The PRD must state: first increment writes **no** `classification_versions`
row. Tests prove append/replay/tamper/idempotency and variant/version spanning.

## External comparator — AAVC reveal-only + first-pass double-blinding (NO-GO fix, item 9; r3-2)

AAVC is a **reveal-only external comparator envelope**: pinned DOI/checksum/commit + match method +
machine class/criteria/flags, stored under `external_comparators`, **excluded from the evidence core
hash**. Per the authoritative AAVC audit §4, first-pass reviewers are **blinded to BOTH the RAPTOR
candidate direction AND the external comparator direction**. A mechanically separate `FirstPassPacketView`
(`redact_for_first_pass(packet)`) strips the **entire `external_comparators` envelope AND**
`candidate_direction`/`null_reason`/signed points/policy id/census direction labels, while **retaining**
per-criterion strength/direction and the evidence trail. Three views exist —
`PacketView ∈ {FIRST_PASS, OPERATOR, RECONCILIATION}`; `render_markdown(..., view=FIRST_PASS)` and the
queue/reviewer-delivery surface consume **only** the redacted `FIRST_PASS` projection; the full JSON
source of record is a restricted operator artifact, never a first-pass reviewer input. The reviewer
records an **independent decision + confidence before reveal**; a `reveal_allowed(packet, log)` state
function enforces **decision-before-reveal** and the `RECONCILIATION` view/reveal is refused until that
append-only independent-decision-with-confidence record exists. AAVC **never** enters criteria, the
combiner, or grounding.

## Output surfaces (first increment only)

- JSON packet source of record;
- deterministic Markdown rendering (`render_markdown(..., view)` over `FIRST_PASS`/`OPERATOR`/
  `RECONCILIATION`; deterministic template expansion; non-authoritative markers + state + gate status
  unavoidable in operator/reconciliation views; **the `FIRST_PASS` view strips both the candidate
  direction and the comparator**);
- CSV/JSONL queue index (built from the `FIRST_PASS` projection for reviewer delivery);
- reviewer decision records (accept/reject/adjust/request-evidence/retain-VUS) in the variant-scoped
  append-only decision log;
- batch/pattern metadata + calibration selection.

No frontend, API server, authentication, Prefect flow, clinical-report template, ClinVar-submission
automation, or patient communication.

## State machine (NO-GO fix, item 5; r3-3)

Specify a fail-closed state machine with an **exact transition table**: for each transition name the
`from`/`to` state, trigger, mechanical guard, and — where a reviewer is required — the reviewer
**role, count, and distinctness**. States: `DRAFT_PROVISIONAL`, `POLICY_BLOCKED`,
`READY_FOR_EXPERT_REVIEW`, `EXPERT_CHANGES_REQUESTED`, `EXPERT_APPROVED_INTERNAL`,
`SECOND_REVIEW_APPROVED`, `EXTERNAL_SUBMISSION_READY`, `SUPERSEDED`. Every transition is mechanically
decidable. **`production_policy_unapproved` (null direction) is a `POLICY_BLOCKED` guard (T2); a
direction-null packet is first-pass evidence-reviewable but cannot enter candidate-direction approval
states — T3/T7/T8/T9 require a non-null `candidate_direction` under an approved production policy.** The
**full gate enum** is `PASS | FAIL | UNDERPOWERED | UNVERIFIED`; `EXTERNAL_SUBMISSION_READY` (T9) requires
an **approved non-null production policy + non-null `candidate_direction`** plus gate `PASS` +
ADR-0009 mask ruling + two distinct QMG sign-offs + primary grounding for every `primary_required`
criterion. Pattern-policy approval is its own event and **never advances any member variant's state**.
The first increment **cannot** reach `EXTERNAL_SUBMISSION_READY` (production policy unapproved so
direction is null, gate not PASS, and expert sign-off absent) — the state is unreachable **by
construction**, not by omission.

## Review scaling & calibration coverage (NO-GO fix, item 7)

Encode the measured census pattern facts (238 candidate-LP, 20 patterns, 6 cover 90%; 1,333
candidate-LB, 10 patterns, BP4 Strong + PM2 Supporting = 1,222) as **selection metadata pinned to the
census snapshot** — never as cutoffs. Define **deterministic set coverage over populated observed
atoms only**: all **30 observed patterns**, each **observed gene**, each **observed variant class**,
each **observed edge flag** — as independent per-dimension observed sets, **never** a cross-product of
empty cells. The coverage report distinguishes **populated**, **covered**, and **impossible /
unpopulated** cells. Pattern-level decision is distinct from variant-level sign-off; 100% individual
review before any external LP claim; LB stratified sampling validates policy but per-variant sign-off
precedes any external reclassification; disagreement drives a global-policy rerun, not fixture patches;
dual-review + inter-reviewer-agreement fields support `SECOND_REVIEW_APPROVED`.

## Acceptance criteria

Assertion-specific ACs must cover: schema completeness + unknown-field fail-loud; deterministic
serialization of **all four hashes**; no label/oracle leakage + no eval-combiner import + no direct KB
read (injected `PacketInput`); candidate direction never rendered as classification and nullable with
`null_reason`; **pinned two-level provenance schemas** (exactly one `ScorerProvenance`, all-required
strict formats; `PrimaryEvidenceRef` resolved/unresolved predicate; BIAS row **never** a
`PrimaryEvidenceRef`; `primary_grounding` enum; `primary_required` PS3/literature-or-config-flagged,
unknown fails closed; missing primary blocks external readiness where required); machine-read lineage
with **exhaustive disposition precedence** (both raw dispositions preserved; validation dominates —
`requires_heldout_mask` → masked regardless of production; direct-copy excluded; PS3/BS2 deferred;
unknown combination fails loud); exact signed-point arithmetic + policy version;
exclusion/deferred/masked visibility; contradiction preservation; **template-narrative-plan** validity
(only approved templates + resolvable field paths; reviewer notes excluded); **first-pass
double-blinding** (`FIRST_PASS` view/projection strips candidate direction + signed points + policy id
+ whole comparator envelope; queue/reviewer delivery consume only `FIRST_PASS`; `RECONCILIATION` gated
by decision-before-reveal); exact state-transition table + reviewer role/count/distinctness + full gate
enum (`production_policy_unapproved` → `POLICY_BLOCKED`; T3/T9 require non-null direction under an
approved policy); **variant-scoped append-only hash-chained decision log** (one per canonical variant
identity across versions; deterministic path from `sha256(variant id)`; genesis `prev_hash` 64 zeroes;
`record_id` idempotency; OS lock + append/flush/fsync; replay detects fork/gap/tamper/cross-variant; no
`classification_versions` write); calibration selection determinism + **populated-atom coverage**
(populated/covered/impossible); renderer/queue consistency; supersession immutability (no hash
mutation); **AAVC reveal-only** (excluded from core hash + stripped from `FIRST_PASS`; independent
decision-before-reveal; reconciliation append-only); no external-ready state without an approved policy
+ non-null direction + PASS + required reviewers + primary grounding.

Include a Definition-of-Ready Task Spec and preservation set. Keep the explicit **'NO-GO findings
closed'** table mapping all 10 r2 corrections to sections/ACs, **and add a second r3 closure table for
the five further findings** (disposition precedence, first-pass double-blinding, state guards,
decision-log identity, exact provenance schemas). Gemini authors tests before Sonnet implementation; GPT
checks. Decompose implementation into **two or three sequenced doer tasks**, each with **≤4 reference
files**.

## Initial prototype

Authorize real provisional/calibration packets before policy/gate completion, assembled from injected
`PacketInput`/evidence records (fixtures or safe internal census records). For calibration, direction
may be `null`/`POLICY_BLOCKED` and selection uses the census pattern stratum only. Do not authorize
public release; do not imply that 1,571 variants are reclassified.
