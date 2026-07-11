# PRD-04 — Candidate Evidence Packet & Queue Index (per-variant candidate *direction* + full, reviewable evidence trail)

> **Status:** Ready (v1.2 increment — **revised twice after rubber-duck NO-GO; r2 closed 10 findings (§0a),
> r3 closed 5 further findings (§0b)**; build contract §10; **provisional packets only**, external worklist
> release gated on PRD-06 gate `PASS`
> + ADR-0009 policy correction + qualified expert sign-off) · **Owner:** @dronasrinivas ·
> **Phase:** 1/2 (STRATEGY §7; PROGRAM *Priorities* item 9) · **Last updated:** 2026-07-11
>
> **Format:** standard lean PRD (Context · Goals/Non-goals · Users · Functional · Non-functional ·
> Acceptance · Dependencies · Risks · Open questions) + build contract (§10) + Definition-of-Ready Task
> Specs (§11). One feature per PRD; acceptance criteria are the source for the build-loop gates
> (OPERATING_MODEL §4) and are authored as executable tests by the test-author (Gemini) **before** the
> Sonnet doer implements; the GPT checker re-verifies.
>
> **Links:** STRATEGY §6 (three vertical lines), §9 (scope + two sign-off levels) · **GP-1** (validation
> ceiling), **GP-3** (oracle-first), **GP-5** (provenance), **GP-6** (config-as-truth), **GP-8**
> (adversarial honesty), **GP-9** (grounded execution), **GP-11** (enabler-not-decision-maker), **GP-13**
> (vertical scope) · PROGRAM (census · *Priorities* item 9 · PRD backlog PRD-04) · DECISIONS **ADR-0009**
> (ClinVar-derived criterion lineage), **ADR-0010** (vertical TSC/mTOR reset) · PRD-01 (criterion-level
> evidence produced) · PRD-03 (KB the evidence + history are read from) · PRD-06 (the held-out gate that
> authorizes any external worklist) · PRD-08 (the terminal-join adapter/audit feeding that gate) ·
> RISK_REGISTER R-A2/R-A2c/R-A3/R-A11/R-E4, H1/H4/H5/H12/H13 · Census source of record
> `data/census/tsc_vus_clinvar_2026-07-07_stats.json`.

---

## 0. Intent (GP-13 gate — named five)

| Element | This feature |
|---|---|
| **(a) TSC/mTOR user** | The TSC VCEP curator / qualified molecular geneticist (GP-3 oracle) triaging the ~6,618 TSC1/TSC2 VUS that today carry **0 expert-panel reviews**. |
| **(b) Artifact** | A versioned, expert-reviewable **candidate evidence packet** (JSON source of record + deterministic Markdown rendering) and a **queue index** presenting a grounded, non-authoritative point of view per variant. |
| **(c) Expert validator** | Mechanical checks (schema/hash/state) validate *form*; a **qualified molecular geneticist / VCEP** validates any externally meaningful disposition (STRATEGY §9 two-sign-off rule — operator approves internal records only). |
| **(d) Falsifier** | An expert **cannot** reconstruct the decision + uncertainty from the packet alone; OR a candidate direction renders as a classification (or is emitted as non-null under an unapproved policy); OR a pattern-policy sign-off silently reclassifies or advances its members' state; OR any of the four named packet hashes (§4.2) is non-deterministic, or a state/reviewer action mutates a prior packet hash; OR a benchmark/label file is reachable from packet generation (the packet reads an injected `PacketInput`, not the KB/labels); OR **BIAS-row provenance is labeled as primary evidence**; OR a **reviewer/pattern decision is written to `classification_versions`** instead of the packet-owned append-only decision log; OR the AAVC comparator enters criteria/combiner/grounding or is visible in the first-pass reviewer view; OR the **`FIRST_PASS` view exposes the candidate direction, signed points, policy id, or ANY comparator/direction label** (first-pass reviewers must be blinded to **both** the RAPTOR candidate direction and the external comparator direction — §4.4 FR14.1); OR the **`packet_policy_disposition` contradicts the bias-lineage precedence** (a `validation_disposition = requires_heldout_mask` criterion rendered anything but `masked`, or an unmapped disposition combination silently defaulting to `included` instead of failing loud — §4.1 FR4.1); OR the **variant decision log forks/gaps/replays to a different variant identity, is addressed from a raw unsafe identity, or a duplicate `record_id` with a divergent payload is silently accepted** (§4.9 FR25); OR **`ScorerProvenance`/`PrimaryEvidenceRef` drops a required field or a BIAS row is emitted as a `PrimaryEvidenceRef`** (§4.1 FR4.2); OR a model-authored narrative introduces text/citations outside the approved template ids + packet field paths. |
| **(e) Why a generic product cannot supply it** | Generic ACMG / variant-interpretation / literature-agent / NGS products emit a *call*, not a TSC-calibrated, **criterion-lineage-aware** (ADR-0009), **leakage-safe**, **gate-blocked** (PRD-06), per-criterion **expert-reviewable** packet bound to the measured TSC census patterns and the two-sign-off boundary. This is TSC-vertical evidence *assembly + auditability*, not generic classification methodology (GP-4/GP-13). |

> This section IS the persisted INTENT block (`manifest.intent_block_present = true`). It names the five
> GP-13 elements and points at existing surfaces (§10.3) rather than redesigning them.

---

## 0a. NO-GO findings closed (rubber-duck revision, 2026-07-11)

The earlier draft received a rubber-duck **NO-GO**. This revision closes all ten findings. Several were
**prompt/spec bugs** (the persisted slot 2/3 under-specified the contract), corrected in
`docs/prompts/prd04-packet/slot2-packet-contract.md` + `slot3-preservation.md` and here.

| # | NO-GO finding | Root cause | Correction (sections / ACs) |
|---|---|---|---|
| 1 | `classification_versions` misused for reviewer/pattern decisions | **Spec bug**: slot 2/3 said "reuse classification-version semantics" without defining packet review persistence | New **packet-owned append-only hash-chained decision log** (`decision_log.jsonl`); `classification_versions` reserved for a terminal, qualified, variant-level classification after all gates — **not written this increment**. §4.2 (hash 4), §4.7 FR23, §4.9 FR25, AC11 |
| 2 | Primary-source grounding was prompt-silent; KB `source_refs` resolve to BIAS raw rows, not primary spans | **Spec gap** | **Two provenance levels**: mandatory scorer-row/run provenance (a BIAS row, **never** primary) + optional `primary_evidence_refs`; missing primary is explicit and **blocks external readiness where policy requires**. FR4.2, AC5, AC18 |
| 3 | Freeform "LLM adds no facts" was mechanically undecidable | **Spec gap** | **Template-constrained narrative plan** (approved template ids + packet field paths only; deterministic renderer). Freeform notes → reviewer-authored `reviewer_notes`, excluded from generated narrative, never fact-safe-claimed. FR7, AC9 |
| 4 | Hashes ambiguous | **Spec gap** | **Four exact hash domains**: `evidence_core_hash`, `narrative_plan_hash`, `packet_envelope_hash`, decision-log `record_hash` chain. State/reviewer actions never mutate a prior packet hash. §4.2 FR8, AC2, AC19 |
| 5 | State transitions / reviewer counts underspecified | **Spec gap** | **Exact transition table** with guards, reviewer role/count/distinctness, and full gate enum `PASS\|FAIL\|UNDERPOWERED\|UNVERIFIED`; every transition mechanically decidable; pattern approval never advances a member variant. §4.5 FR15, AC10 |
| 6 | Eval-derived counts becoming a production oracle | **Spec gap** | Pattern catalog/counts are **selection metadata pinned to the census**, never cutoffs; `candidate_direction` **nullable** with `null_reason=production_policy_unapproved` in `DRAFT_PROVISIONAL`/`POLICY_BLOCKED`; eval combiner not imported/restated. FR5, FR16, AC4 |
| 7 | Calibration coverage over impossible Cartesian cells | **Spec gap** | Deterministic set coverage over **populated observed atoms only** (30 patterns, observed genes, classes, edge flags — per-dimension, not cross-product); coverage report distinguishes populated / covered / impossible-unpopulated. FR17, AC12 |
| 8 | Tense / status / gate enum underspecified | **Spec gap** | Status set to **Ready only after this correction**; full gate enum used throughout; first increment **cannot** reach `EXTERNAL_SUBMISSION_READY` (policy/gate/sign-off absent). Header, §4.5, §10.1 |
| 9 | New AAVC control not incorporated | **New control** | `external_comparators` **reveal-only** envelope, excluded from evidence core + first-pass view; reviewer records independent decision/confidence **before reveal**; reconciliation is a separate append-only event; AAVC never enters criteria/combiner. FR27, AC17 |
| 10 | Lineage now machine-readable | **New surface** | Criterion entries consume exact `lineage_class` + validation/production dispositions from `configs/eval/bias_lineage.yaml`; direct-copy excluded, comparator-dependent `requires_heldout_mask`, PS3/BS2 deferred; packet never invents lineage. FR4.1, AC7 |

**Implementation scope resolution (items 2 + 3 completable now).** The packet library assembles from an
**injected `PacketInput`** (evidence records + provenance + comparator + census-selection metadata); it
does **not** require the 6,618 VUS to exist in the PRD-03 KB, reads **no** benchmark/label file, and
imports **no** eval combiner. A KB adapter that materializes `PacketInput` from the PRD-03 KB is a
**separate, future** surface (§10.6). Real provisional/calibration packets are buildable now; for
calibration, `candidate_direction` may be `null`/`POLICY_BLOCKED` and selection uses the census pattern
stratum only — a valid evidence-review packet, not a classification.

---

## 0b. NO-GO findings closed (second rubber-duck revision → r3, 2026-07-11)

A **fresh** rubber-duck pass on the r2 artifacts returned a further **NO-GO** with five findings (two
BLOCKER, three MAJOR). This r3 revision closes all five mechanically; the r2 §0a corrections stand.

| # | r3 finding | Severity | Root cause | Correction (sections / ACs) |
|---|---|---|---|---|
| r3-1 | Disposition precedence undefined: `bias_lineage.yaml` carries **two** dispositions and PS1/PM5/PM1/PP2/BP1 are `validation=requires_heldout_mask` but `production=allowed` — the r2 map was single-valued and could resolve them to `included`. | **BLOCKER** | Spec gap | **One exhaustive precedence function/table** `resolve_packet_policy_disposition(validation, production)`; for this pre-validation packet the **validation disposition dominates** — `requires_heldout_mask` → `masked` regardless of production; both raw fields preserved; unknown combination **fails loud** (never `included`). §4.1 **FR4.1**, **AC7**, **AC22** |
| r3-2 | First-pass blinding incomplete: r2 hid only the AAVC comparator, but the AAVC audit §4 requires first-pass reviewers blinded to **both** the RAPTOR candidate direction **and** the comparator direction. | **BLOCKER** | Under-spec vs authoritative control | Mechanically separate **`FirstPassPacketView`** / `redact_for_first_pass(packet)` strips the whole `external_comparators` envelope **and** `candidate_direction`/signed points/policy id/census direction labels (retains criterion strength/direction); three-view enum `PacketView ∈ {FIRST_PASS, OPERATOR, RECONCILIATION}`; `render_markdown(..., view=FIRST_PASS)` + queue/reviewer delivery consume **only** the redacted view; `RECONCILIATION` gated on a decision-before-reveal state function. §4.4 **FR14/FR14.1**, **AC4**, **AC17**, **AC20** |
| r3-3 | State guards: `production_policy_unapproved` was not a `POLICY_BLOCKED` guard; T9 did not require a non-null candidate direction / approved production policy. | **MAJOR** | Spec gap | `production_policy_unapproved` added to `POLICY_BLOCKED` (T2); direction-null packets are first-pass **evidence**-reviewable but **cannot** enter candidate-direction approval states (T3/T7/T8/T9 require non-null direction under an approved policy); T9 additionally requires approved non-null production policy + non-null `candidate_direction`; T9 unreachable this increment. §4.5 **FR15/FR15.1**, **AC10**, **AC15** |
| r3-4 | Decision-log identity under-pinned: no variant scoping, genesis `prev_hash`, `record_id`/idempotency, locking/fsync, replay/tamper semantics, or safe path addressing. | **MAJOR** | Spec gap | **One variant-scoped log per canonical variant identity** spanning all packet versions; records bind `packet_id`/`evidence_core_hash` + supersession links; genesis `prev_hash = 64 lowercase zeroes`; `record_id` idempotency (same id+payload no-op, same id+diff payload fails); OS exclusive lock + append/flush/fsync; replay verifies one linear chain (no fork/gap/mismatch) + variant/version identity; path deterministic from `sha256(canonical variant identity)`, never raw. §4.9 **FR25**, **AC23** |
| r3-5 | Provenance schemas were prose, not pinned dataclasses/fields/predicates. | **MAJOR** | Spec gap | Concrete **`ScorerProvenance`** (all required, strict formats) + **`PrimaryEvidenceRef`** (resolution predicate; `source_sha256` nullable only with `null_reason`) pinned; `CriterionEntry` = exactly one `scorer_provenance` + zero-or-more primary refs + `primary_grounding ∈ {present, absent, not_required}`; BIAS row is **never** a `PrimaryEvidenceRef`; `primary_required` = any included/deferred functional/literature (PS3) claim + every config-flagged criterion, unknown **fails closed**. §4.1 **FR4.2**, **AC5**, **AC18**, **AC21** |

**r3 verdict claim.** With r3-1…r3-5 mechanically closed on top of the r2 closures (§0a), the packet
contract is **GO for build** as a provisional/internal evidence-assembly artifact: the disposition
precedence is exhaustive and fail-loud, first-pass review is double-blinded by construction, the state
machine keeps every candidate-direction/external state unreachable while the production policy is
unapproved, the decision log is a tamper-evident variant-scoped chain, and provenance is strictly
typed. Externally usable release remains gated (PRD-06 `PASS` + ADR-0009 ruling + per-variant sign-off).

---

## 1. Context / problem

PRD-01 emits **criterion-level** ACMG evidence into the PRD-03 KB; the deterministic TSC1/TSC2 evidence
census is complete (`data/census/tsc_vus_clinvar_2026-07-07_stats.json`: **6,618** VUS scored on pinned
Nirvana 3.18.1 + BIAS-2015 v3.0.0). That evidence is currently a KB substrate — there is **no
expert-facing artifact** that turns it into a reviewable point of view. The census records internal,
eval-only, non-authoritative **candidate directions** — **238** `candidate_LP_review`, **1,333**
`candidate_LB_review`, **5,017** `no_deterministic_resolution`, **30** `manual_review` — but these
"directions" are **not classifications** (PROGRAM census section; ADR-0010), and a raw BIAS/BIAS-TSV
dump forces the expert to redo the analysis (Slot-3 failure mode 3).

This feature specifies the **candidate evidence packet**: the output contract that presents, per variant,
a grounded **point of view** plus the *full, inspectable* evidence trail — fired criteria, lineage,
exclusions, contradictions, missing evidence, and a next-evidence action — in a form a qualified expert
can accept/reject/adjust, and a **queue index** that scales that review across ~6,618 variants using the
measured census patterns. It is the **Product Line 1** artifact (STRATEGY §6): *expert-reviewable candidate
evidence packets (eval-only, non-authoritative until validated)*.

**Buildable now vs authoritative-later (GP-1/PROGRAM item 9).** The output *contract* is active and
unblocked: **provisional** representative (and even all-VUS) packets may be generated now, before policy
completion and before the gate, for **internal** review. But the packet is **not** a reclassification: no
**externally usable** worklist may be released until (i) the PRD-06 held-out gate returns **PASS**
(missense-stratified, both directions), (ii) the ADR-0009 criterion-lineage policy correction lands, and
(iii) a qualified molecular geneticist signs off per variant. **This PRD authorizes the packet, not the
release.**

---

## 2. Goal & non-goals

**Goal.** Specify a **versioned, machine-readable, expert-reviewable candidate evidence packet** and a
**queue index** for every TSC VUS, such that RAPTOR presents a grounded point of view — one of
`candidate_LP_review`, `candidate_LB_review`, `no_deterministic_resolution`, `manual_review` — that is
**never** a final classification, is fully provenanced and grounded (GP-5/GP-9), separates deterministic
content from non-deterministic narrative, and drives a fail-closed review workflow whose external outputs
are gated on validation + expert sign-off.

**Non-goals (explicit).**
- **Any final classification / VUS→LP/LB decision.** The four values are *review directions*, human/oracle-gated (STRATEGY §9; GP-11).
- **Computing ACMG criteria** (PRD-01) or **the benchmark/gate** (PRD-06/PRD-08) — *consumed*, not built here.
- **Importing the eval-only Tavtigian combiner** into packet generation (Slot 3 preservation — see §9).
- **No web application, API server, authentication system, Prefect flow, clinical-report template,
  ClinVar-submission automation, or patient communication** (Slot 2 output surfaces; STRATEGY §9; ADR-0010 freeze of generic orchestration/PRD-05).
- **No claim that 1,571 variants (238 + 1,333) are reclassified**, and no "% VUS resolved" headline (PROGRAM census).
- Tier-3 literature evidence, cross-linkage, the gap-map (later PRDs / GP-2/GP-7).

> **Validation ceiling (GP-1).** The packet is validated *as an evidence-assembly + rendering artifact*
> (deterministic, grounded, reconstructable) — **not** as a classifier. Its candidate directions are
> non-authoritative until PRD-06 `PASS` + ADR-0009 correction + expert sign-off. The word "classification"
> is reserved for a signed `classification_versions` row (PRD-03), never for a packet direction — and this
> **first increment writes no `classification_versions` row at all** (reviewer/pattern decisions go to the
> packet-owned decision log, §4.7/§4.9). A packet is an **evidence-review** artifact, not a classification.

---

## 3. Users & need

| User | Need this feature serves |
|---|---|
| **VCEP curator / molecular geneticist (GP-3 oracle)** | A per-variant packet that makes the decision *and its uncertainty* inspectable — accept/reject/adjust without redoing the analysis; a queue that ranks by expert-value-per-hour (R-E4). |
| **Operator** | Generate **provisional/internal** packets + queue for census QA and calibration-batch selection; approve *internal* records only (STRATEGY §9). |
| **PRD-06 gate / program** | A stable output contract whose external release is mechanically blocked on `PASS` (no hollow-green worklist — H4/H13). |
| **Auditor** | Full provenance + append-only revision/supersession history (via PRD-03 ledger) to reconstruct any packet version (GP-5/GP-9). |

---

## 4. Functional requirements

### 4.1 Packet model (schema-pinned, GP-6)

- **FR1 — Versioned, content-addressed packet schema.** A machine-readable packet schema pinned in
  `configs/packet/*.yaml` (+ a JSON Schema), carrying at minimum: `packet_schema_version`, `packet_id`
  (content-addressed from `packet_envelope_hash`), and the **four named hashes** (§4.2). Unknown/unexpected
  fields **fail loud** at load (no silent drop — H5).
- **FR2 — Canonical variant identity.** Canonical **GRCh38 SPDI** (the PRD-02 identity, matching PRD-08's
  join key), `gene ∈ {TSC1, TSC2}`, MANE `transcript`, `consequence`, `variant_class ∈ {missense,
  truncating, other}`. A **missing/ambiguous canonical identity blocks promotion** (§4.5) and routes to
  `manual_review` (never silently packaged — R-A3).
- **FR3 — Run/config/code/model/prompt/source snapshot pins (GP-5).** Every packet records the
  originating `run_id`, code version, scorer/policy config versions, LLM `model` + `prompt_hash` (narrative
  only), and the **source snapshot** (census/KB snapshot id + date, e.g. `clinvar_2026-07-07`). These pins
  are **run metadata**: the reproducible subset (schema/config/policy versions, source snapshot id) is
  bound into `packet_envelope_hash`; `run_id`/`generated_at` and other non-reproducible fields are excluded
  from all packet hashes (§4.2).
- **FR4 — Criterion evidence trail (assembled from an injected `PacketInput`, reused not re-derived).**
  Per variant, the packet carries, for each fired criterion:
  - **raw fired criterion + rationale** exactly as the scorer/BIAS produced it (the `CriterionCall`
    rationale shape from `scorer/model.py`, carried on the injected `PacketInput` — §4.10);
  - **FR4.1 — machine-read criterion lineage (ADR-0009 / bias-lineage gate, item 10).** The packet
    **consumes** the exact `lineage_class`, `validation_disposition`, `production_disposition`, and
    `decision_dependency` for each criterion from `configs/eval/bias_lineage.yaml` via
    `raptor.eval.lineage_policy.load_lineage_policy` — it **never invents** source lineage in packet
    code. The eight lineage classes and four dispositions are the policy's own fail-closed enums.
    A criterion whose code is a BIAS-internal stub (`structurally_forbidden`) that nonetheless appears
    fired is a contract error and routes to `manual_review`. Each record carries **two** dispositions —
    `validation_disposition` and `production_disposition` — which legitimately differ (ADR-0009:
    PS1/PM5/PM1/PP2/BP1 are `requires_heldout_mask` at validation but `allowed` in production). The
    packet **preserves both raw disposition fields verbatim** on the `CriterionEntry` and derives one
    `packet_policy_disposition` through **exactly one exhaustive precedence function**
    `resolve_packet_policy_disposition(validation_disposition, production_disposition)`. For this
    **pre-validation** packet the **validation disposition dominates**: a criterion is `masked`
    whenever `validation_disposition == requires_heldout_mask`, **regardless of** its production
    disposition. Precedence is evaluated top-to-bottom, **first match wins**, over the full
    four-value × four-value disposition enum:

    | # | Condition (over the two raw dispositions) | `packet_policy_disposition` | Reason token | Current criteria |
    |---|---|---|---|---|
    | 1 | `validation_disposition == forbidden` | **excluded** | `direct_copy_forbidden` | PP5, BP6, PS4 |
    | 2 | `validation_disposition == requires_heldout_mask` | **masked** | `requires_heldout_mask` | PS1, PM5, PM1, PP2, BP1 |
    | 3 | `validation_disposition == deferred` **or** `production_disposition == deferred` | **deferred** (carries `decision_dependency`) | `deferred:<decision_dependency>` | PS3 (`assay-validity-review`), BS2 (`bs2-policy`) |
    | 4 | `validation_disposition == allowed` **and** `production_disposition == allowed` | **included** | — | PVS1, PM2, PM4, PP3, BA1, BS1, BP3, BP4, BP7 |
    | 5 | any other combination (e.g. `production_disposition == forbidden` under a non-forbidden validation disposition, or any unknown/unmapped enum pairing) | **fail loud** (`LineageDispositionError`) | `unknown_disposition_combination` | (none today) |

    The table is **exhaustive** over the enum cross-product; rule 5 is the fail-closed catch-all, so an
    unmapped combination **never** silently defaults to `included`. Masked (rule 2) is a **hard block on
    external readiness** until the ADR-0009 mask/ruling lands, independent of production being `allowed`.
    The packet **never invents** source lineage; the two raw dispositions come only from
    `configs/eval/bias_lineage.yaml` via `load_lineage_policy`, and tests lock the precedence to that
    loader's output, not a hardcoded map (AC7/AC22).
  - **packet policy disposition** (`packet_policy_disposition`) ∈ `included` | `excluded` | `masked` |
    `deferred` | `unverified` | `manual` (derived per the FR4.1 precedence table for lineage-driven
    cases; `unverified` for a criterion whose scorer-row provenance does not resolve — FR4.2);
  - **FR4.2 — two-level provenance with pinned schemas (item 2; r3-5).** Every scored criterion holds
    **exactly one mandatory `ScorerProvenance`** and **zero or more `PrimaryEvidenceRef`s**. The
    scorer-row provenance resolves to a **BIAS raw row and is NEVER a `PrimaryEvidenceRef`** — they are
    **distinct types**; a BIAS row can never be constructed as primary evidence. The concrete,
    strictly-typed schemas (fail loud on a missing/blank/malformed field) are:

    **`ScorerProvenance`** — all fields **required**, strict formats:
    - `bias_row_key` (str, non-blank) — the BIAS/scorer row identity;
    - `chromosome` (str, e.g. `chr16`), `position` (int ≥ 1), `ref` (str, `^[ACGTN]+$`),
      `alt` (str, `^[ACGTN]+$`) — the scored locus;
    - `scorer_run_id` (str, non-blank);
    - `input_sha256`, `output_sha256`, `raw_row_sha256` — each a **64-char lowercase hex** sha256;
    - `bias_version` (str, must equal the pinned `3.0.0`), `bias_commit` (str, 40-char lowercase hex,
      the pinned commit);
    - `nirvana_version` (str, non-blank, e.g. `3.18.1`);
    - `transcript` (str, MANE transcript with explicit version, non-blank).

    A criterion whose `ScorerProvenance` does not resolve (any required field missing/malformed, or the
    row does not exist) is `unverified`, non-authoritative, and **blocks promotion** (§4.5).

    **`PrimaryEvidenceRef`** — a reference to *primary* evidence (literature span, functional-assay
    record, ClinGen guidance); **never** a BIAS row:
    - `ref_id` (str, non-blank, unique within the criterion);
    - `source_type` ∈ `{literature, functional_assay, clingen_guidance, database_record}` (enum; fail
      loud on unknown);
    - `source_id` / `accession` (str; non-blank when `resolved`) — e.g. PMID, DOI, accession;
    - `locator` / `span` (str) — span/coordinates/figure/table locator within the source;
    - `source_snapshot` / `version` (str; non-blank when `resolved`);
    - `source_sha256` (64-char lowercase hex **or** `null`) — **nullable only** with an explicit
      non-blank `source_sha256_null_reason` naming why the source lacks downloadable bytes;
    - `supports_criterion` (str, an ACMG code — the criterion this ref grounds);
    - `resolution_status` ∈ `{resolved, unresolved}` (enum); `unresolved_reason` (str, non-blank when
      `unresolved`).

    A `PrimaryEvidenceRef` is **`resolved`** only when it carries `source_id` **and** `locator`/`span`
    **and** `source_snapshot`/`version` **and** (`source_sha256` **or** a non-blank
    `source_sha256_null_reason`); otherwise it is `unresolved` with a reason. Fail loud on a `resolved`
    ref missing any required field.

    **`CriterionEntry` grounding.** Each `CriterionEntry` holds **exactly one** `scorer_provenance` and
    a (possibly empty) `primary_evidence_refs` list, plus `primary_grounding ∈ {present, absent,
    not_required}` (enum) and a `primary_grounding_reason` (str). `present` requires ≥ 1 `resolved`
    `PrimaryEvidenceRef`; `absent` is the explicit no-primary state (with reason); `not_required` is
    used only where policy does not require primary grounding.

    **Which claims require primary grounding for external readiness.** A criterion is `primary_required`
    when **either** (a) it is an included-or-deferred **functional/literature** claim — concretely
    **PS3** (`literature_unvalidated` lineage / functional-assay), extended to any criterion whose
    `lineage_class == literature_unvalidated` — **or** (b) it is explicitly flagged `primary_required:
    true` by packet config (`configs/packet/candidate_direction.yaml` / `schema.yaml`). For a
    `primary_required` criterion, `primary_grounding` must be `present` before the packet may reach
    `EXTERNAL_SUBMISSION_READY`; `absent`/`not_required` **blocks external readiness** (AC18). A
    criterion whose `primary_required` status cannot be determined (unknown flag / unknown lineage)
    **fails closed** — treated as `primary_required`, blocking external readiness until resolved.
    **Missing primary grounding never blocks the provisional/internal packet** — it is surfaced, never
    hidden. Scorer-row provenance being present is **not** primary grounding.
  - **strength** ∈ `{stand_alone, very_strong, strong, moderate, supporting}` and **direction** ∈
    `{pathogenic, benign}` (PRD-01 vocabulary; PVS/PS/PM/PP→pathogenic, BA/BS/BP→benign).
- **FR5 — Candidate direction (nullable) + signed point calculation (config-pinned production policy).**
  The packet's `candidate_direction ∈ {candidate_LP_review, candidate_LB_review,
  no_deterministic_resolution, manual_review, null}`. It is computed by a **production
  candidate-direction policy** (`configs/packet/candidate_direction.yaml`: policy id + version, criteria
  set, point values, cutoffs), recording the **signed point calculation** (per-criterion signed
  contributions + sum). This policy is **separate from and does not import** the PRD-06 eval-only
  combiner (§9). **When no production policy is Oracle-approved** (`confirm` empty), the packet sets
  `candidate_direction = null`, `null_reason = production_policy_unapproved`, and is routed to
  `POLICY_BLOCKED` for candidate-direction progression (§4.5) — it is a **valid evidence-review
  packet, not a classification**, and while direction-null it **remains eligible for first-pass
  *evidence* review** (the direction-blinded `FIRST_PASS` view, §4.4 FR14.1) but **cannot** enter any
  candidate-direction approval or external state (§4.5 FR15.1, T3/T7/T8/T9).
  `null_reason ∈ {production_policy_unapproved, missing_canonical_identity,
  unresolved_lineage, unverified_source}`. The direction (or its null state) is rendered **only** as a
  review direction, never as a classification (§4.4/AC4). The eval-derived census patterns (FR16) are
  **selection metadata only** and **never** define the direction's cutoffs or criteria set.
- **FR6 — Exclusions, contradictions, quality/manual flags, missing evidence.**
  - **excluded evidence + exclusion reason** (e.g. `direct_copy_forbidden` per ADR-0009, `strength_out_of_vocab`, `masked_for_holdout`) — visible, never silently dropped (H5);
  - **contradictions** — both-direction firing preserved (the census records **3,739** variants with
    both pathogenic and benign direction evidence) with a `contradiction` flag, never resolved away;
  - **quality / manual flags** (e.g. NTHL1-misannotation, transcript `.4`-vs-`.5` drift, BS2 no-rationale — the census `known_policy_gaps`);
  - **missing-evidence categories + a grounded next-evidence action** — what evidence class is absent
    (e.g. no functional/PS3 assay) and the concrete next step that would resolve it (grounded, GP-9).
- **FR7 — Structured, template-constrained narrative plan (non-authoritative; item 3).** In place of a
  freeform LLM narrative, the packet carries a **`NarrativePlan`**: an **ordered list** of
  `{template_id, field_bindings}` where each `template_id` is drawn from an **approved template catalog**
  (`configs/packet/narrative_templates.yaml`) and each binding value is a **packet field path** (not
  arbitrary text). The model may only **select and order approved templates and bind packet field
  paths**; it authors **no** free factual text or citations. A **deterministic renderer** expands the
  templates against the bound fields (a given plan + packet → byte-identical narrative). The plan carries
  `model` + `prompt_hash` and is **mechanically decidable**: every `template_id ∈ catalog` and every
  bound path resolves to an existing packet field, else it **fails loud** (AC9). Any freeform note is
  **reviewer-authored**, lives in a separate `reviewer_notes` block, is **excluded** from the generated
  narrative, and is **never** mechanically claimed fact-safe. The narrative is an aid to the reviewer,
  never a source of evidence.

### 4.2 Determinism, hash domains & separation (R-A11; item 4)

- **FR8 — Four named hash domains, separating deterministic content from narrative, comparators, and run
  metadata.** The packet defines exactly four canonical hashes with fixed names and canonical
  serialization (mirroring `scorer/report.py::content_hash` + `kb/store.py` canonicalization). A
  **state change or reviewer decision never mutates a prior packet hash** — it yields a new
  content-addressed packet version (§4.7) or an appended decision-log record (§4.9).

  | # | Hash | Canonical domain (what it covers) | Explicitly excludes |
  |---|---|---|---|
  | 1 | `evidence_core_hash` | The **immutable deterministic evidence core**: canonical identity; sorted criterion trail (criterion, strength, direction, rationale, lineage_class + disposition + decision_dependency, **scorer-row provenance ref** + primary_evidence_ref ids); `candidate_direction`/`null_reason` + signed points under the pinned policy id/version; exclusions, contradictions, missing-evidence + next-action. | narrative, comparators, review state, decisions, `run_id`, `generated_at` |
  | 2 | `narrative_plan_hash` | The **structured narrative plan**: canonical ordered `{template_id, field_bindings}` list + `model` + `prompt_hash`. | rendered prose (derived), reviewer_notes |
  | 3 | `packet_envelope_hash` | The **envelope**: `evidence_core_hash` + `narrative_plan_hash` + the **enumerated** reproducible run-metadata pins (schema version, config/policy versions, source snapshot id). | `run_id`, `generated_at`, wall-clock, and other non-reproducible run fields (recorded, not hashed) |
  | 4 | decision-log `record_hash` chain | A **separate** append-only chain over the decision log (§4.9): each record's `record_hash = sha256(prev_hash + canonical(record))`. | (independent of packet hashes; never folded into 1–3) |

  `packet_id` is content-addressed from `packet_envelope_hash`. Same injected `PacketInput` + pinned
  policy → identical hashes 1–3 (R-A11).

### 4.3 Output surfaces (first increment only — Slot 2)

- **FR9 — JSON packet source of record.** The canonical, schema-validated per-variant packet.
- **FR10 — Deterministic Markdown packet rendering.** A pure function of the JSON packet (a given packet
  JSON always renders byte-identical Markdown); it visibly separates the **non-authoritative** direction +
  narrative from the deterministic evidence trail (§4.4), and states the packet state + gate status.
- **FR11 — CSV/JSONL queue index.** One row per variant: `variant_id`, gene, class, `candidate_direction`,
  `pattern_id` (§4.6), signed points, packet state, and flags (contradiction/manual/unverified). Renderer
  and queue index are **consistent** (same direction/state/flags per variant — AC13).
- **FR12 — Reviewer decision records (variant-scoped append-only log).** A per-variant / per-criterion
  decision record: `accept` | `reject` | `adjust` | `request-evidence` | `retain-VUS`, with reviewer
  identity/role/date/rationale. Decisions are appended to the **variant-scoped append-only hash-chained
  decision log** (§4.9 FR25), **never** to PRD-03 `classification_versions`; history is conserved (AC11).
- **FR13 — Batch / pattern metadata.** The calibration-batch selection (§4.6) and per-pattern metadata
  (signature, member count, coverage) as a machine-readable artifact.

> **No** frontend, API server, authentication, Prefect flow, clinical-report template, ClinVar-submission
> automation, or patient communication (§2 non-goals).

### 4.4 No false authority (Slot-3 failure mode 1)

- **FR14 — Candidate direction never rendered as a classification.** Every **operator/reconciliation**
  rendering of a candidate direction — **including the `null` state** (`null_reason` shown) — is
  unavoidably marked *candidate / review-direction / non-authoritative*, with the packet **state**
  (§4.5) and **gate status** (`PASS` | `FAIL` | `UNDERPOWERED` | `UNVERIFIED`) shown adjacent. The
  narrative and the "LP/LB" tokens **cannot** appear as a standalone clinical label (mechanically
  checked — AC4). The candidate direction is present **only** in the `OPERATOR` and `RECONCILIATION`
  renderings and is **absent by design from the `FIRST_PASS` view** (FR14.1) — reconciling the
  first-pass blinding requirement: a first-pass reviewer never sees a direction to misread, so FR14's
  "never a classification" marking applies to the operator/reconciliation surfaces where the direction
  actually exists.

- **FR14.1 — Three packet views + first-pass double-blinding (r3-2; AAVC audit §4).** The authoritative
  AAVC audit requires first-pass reviewers **blinded to BOTH the RAPTOR candidate direction AND the
  external comparator direction**. The packet defines a **mechanically separate** `FirstPassPacketView`
  produced by a pure projection `redact_for_first_pass(packet) -> FirstPassPacketView` that **strips**:
  - the **entire `external_comparators` envelope** (AAVC DOI/checksum/commit/class/criteria/flags);
  - `candidate_direction`, `null_reason`, the **signed-point calculation** (`signed_points` +
    `per_criterion_points`), and the candidate-direction **policy id/version**;
  - any **census-selection direction label** (`census_selection_stratum`/`pattern_id` direction hints);

  and **retains** the evidence criteria and each criterion's **strength** and **direction**
  (`pathogenic`/`benign`) plus lineage/disposition/exclusions/contradictions/missing-evidence — a
  first-pass evidence reviewer necessarily sees each *criterion's* direction (that IS the evidence),
  but **never** the packet-level candidate direction or the comparator.

  Three views are named by an enum `PacketView ∈ {FIRST_PASS, OPERATOR, RECONCILIATION}`:
  - **`FIRST_PASS`** — the `FirstPassPacketView` projection above; the **only** view a first-pass
    reviewer and the queue / reviewer-delivery surface may consume;
  - **`OPERATOR`** — the full packet; a **restricted operator artifact**, **never** a first-pass
    reviewer input;
  - **`RECONCILIATION`** — the full view **including** the candidate direction and the revealed
    comparator, **available only after** an append-only **independent-decision event carrying the
    reviewer's decision and confidence** exists in the variant decision log (§4.9). A state function
    `reveal_allowed(packet, decision_log) -> bool` enforces **decision-before-reveal**: it returns
    `True` only once that independent-decision-with-confidence record is appended; before that, the
    `RECONCILIATION` view and any comparator reveal are **refused (fail loud)**.

  `render_markdown(packet, config, *, view: PacketView) -> str` renders **only** the requested view.
  The full JSON packet **source of record** is a restricted operator artifact and is **never** delivered
  as first-pass reviewer input — first-pass reviewers and the queue index consume **only** the redacted
  `FIRST_PASS` projection. The JSON `FirstPassPacketView` and the `FIRST_PASS` Markdown render are each
  mechanically checked to contain **no** `candidate_direction`, `null_reason`, signed points, policy
  id, or `external_comparators` key/value (AC4/AC17/AC20).

### 4.5 Packet state machine (fail-closed)

- **FR15 — Fail-closed state machine.** Each packet has a `review_state` drawn **only** from mechanically
  testable states with authorized transitions:

  | State | Meaning | Promotion guard (fail-closed) |
  |---|---|---|
  | `DRAFT_PROVISIONAL` | Provisional packet built pre-gate / pre-policy-approval. | Default entry; **internal only**. |
  | `POLICY_BLOCKED` | Blocked from **candidate-direction progression**: unresolved criterion lineage (`requires_heldout_mask`/`deferred`) / unverified scorer-row source / missing canonical identity / **`production_policy_unapproved` (`candidate_direction` is null)**. | Cannot advance to any candidate-direction approval or external state until the blocker clears. **A packet blocked only by `production_policy_unapproved` that is otherwise evidence-complete remains eligible for first-pass *evidence* review (direction-blinded `FIRST_PASS` delivery, FR14.1).** |
  | `READY_FOR_EXPERT_REVIEW` | Deterministic content complete, grounded, identity present, **and a non-null `candidate_direction` under an approved production policy** — the entry to the candidate-direction review/approval chain. | Requires: scorer-row provenance resolves for every scored criterion, canonical identity, **approved production policy → non-null `candidate_direction`**, no `forbidden`/`unverified` and no un-adjudicated `requires_heldout_mask`/`deferred` in scored set. (First-pass *evidence* review needs **not** this state — it is a blinded delivery available from `DRAFT_PROVISIONAL`/`POLICY_BLOCKED`.) |
  | `EXPERT_CHANGES_REQUESTED` | Reviewer returned `reject`/`adjust`/`request-evidence`. | Re-enters review; captured as a decision-log record (§4.9). |
  | `EXPERT_APPROVED_INTERNAL` | One qualified reviewer signed off (internal). | Operator/internal scope only (STRATEGY §9). |
  | `SECOND_REVIEW_APPROVED` | Dual review complete; inter-reviewer agreement recorded. | Requires two distinct qualified reviewers. |
  | `EXTERNAL_SUBMISSION_READY` | Cleared for external worklist. | **Requires PRD-06 gate `PASS` (missense-stratified, both directions) + ADR-0009 policy correction + per-variant qualified sign-off.** |
  | `SUPERSEDED` | Replaced by a newer packet version. | Immutable; supersession recorded (§4.7). |

  **FR15.1 — Exact transition table (item 5; every transition mechanically decidable).** `T` names each
  authorized transition; every guard is a boolean test over the packet + gate status + decision log.
  Reviewer **role** = qualified molecular geneticist (QMG) unless noted; **operator** approves internal
  records only (STRATEGY §9). Distinctness is enforced by reviewer identity.

  | T | From → To | Trigger | Mechanical guard | Reviewer role / count / distinctness |
  |---|---|---|---|---|
  | T1 | (init) → `DRAFT_PROVISIONAL` | packet built | evidence core assembled; default entry | none |
  | T2 | `DRAFT_PROVISIONAL` → `POLICY_BLOCKED` | blocker detected | any of: `null_reason ∈ {production_policy_unapproved, missing_canonical_identity, unresolved_lineage, unverified_source}`; a scored criterion with `requires_heldout_mask` un-adjudicated; a `deferred` criterion scored | none (mechanical) |
  | T3 | `DRAFT_PROVISIONAL` → `READY_FOR_EXPERT_REVIEW` | promotion request | **approved production policy → `candidate_direction` non-null**; canonical identity present; every scored criterion resolves scorer-row provenance; **no** `forbidden`/`unverified` in scored set; no un-adjudicated `requires_heldout_mask`/`deferred` scored | operator (1) |
  | T4 | `POLICY_BLOCKED` → `READY_FOR_EXPERT_REVIEW` | blocker cleared | the T2 predicate is now false (**incl. production policy approved → `candidate_direction` non-null**) and the T3 guard holds | operator (1) |
  | T5 | `READY_FOR_EXPERT_REVIEW` → `EXPERT_CHANGES_REQUESTED` | reviewer `reject`/`adjust`/`request-evidence` | decision-log record appended (§4.9) | QMG × 1 |
  | T6 | `EXPERT_CHANGES_REQUESTED` → `READY_FOR_EXPERT_REVIEW` | rebuild/re-submit | a **new packet version** (new hashes) supersedes prior (§4.7); T3 guard holds | operator (1) |
  | T7 | `READY_FOR_EXPERT_REVIEW` → `EXPERT_APPROVED_INTERNAL` | reviewer `accept` | signed decision-log record; internal scope only | QMG × 1 |
  | T8 | `EXPERT_APPROVED_INTERNAL` → `SECOND_REVIEW_APPROVED` | second `accept` | second signed record by a reviewer **distinct** from T7; inter-reviewer agreement recorded | QMG × 2, distinct identities |
  | T9 | `SECOND_REVIEW_APPROVED` → `EXTERNAL_SUBMISSION_READY` | external release request | **an approved (non-empty `confirm`) production candidate-direction policy AND `candidate_direction` non-null** **AND** **gate = `PASS`** (missense-stratified, both directions) **AND** ADR-0009 mask/ruling landed for every scored `requires_heldout_mask` criterion **AND** `primary_grounding = present` for every `primary_required` criterion (FR4.2) **AND** a per-variant qualified sign-off exists | QMG × 2 distinct (from T7/T8) + gate `PASS` |
  | T10 | any non-terminal → `SUPERSEDED` | new version created | successor packet id linked; predecessor becomes immutable (§4.7) | operator (1) |

  **Gate enum (full).** `gate_status ∈ {PASS, FAIL, UNDERPOWERED, UNVERIFIED}`. Only `PASS` satisfies T9;
  `FAIL`, `UNDERPOWERED`, and `UNVERIFIED` each block T9 (fail-closed). **Pattern-policy approval (§4.6
  FR18) is a distinct decision-log event and executes NONE of T1–T10 on any member variant** — it never
  advances a member variant's state.

  **Blocked promotion (mechanical):** a gate **`FAIL`/`UNDERPOWERED`/`UNVERIFIED`**, a scored criterion
  with `forbidden` lineage disposition or an un-adjudicated `requires_heldout_mask`/`deferred`
  disposition, a **missing canonical identity**, or an **unverified scorer-row source** each **blocks**
  promotion toward `EXTERNAL_SUBMISSION_READY`. No state is named that a test cannot decide (AC10).

  **Direction-null evidence-review semantics (r3-3).** A packet with `candidate_direction = null`
  (`null_reason = production_policy_unapproved`) may be **evidence-complete** and is **eligible for
  first-pass evidence review** via the direction-blinded `FIRST_PASS` view (FR14.1) — that review
  inspects the evidence trail, not a direction, so delivering it is a blinded read, not a state
  transition. It **cannot** enter `READY_FOR_EXPERT_REVIEW` or any later candidate-direction approval /
  external state: T3/T7/T8/T9 each require a **non-null `candidate_direction` under an approved
  production policy**. `production_policy_unapproved` is a `POLICY_BLOCKED` guard (T2).

  **First increment reachability (item 8; r3-3).** Because this increment has **no approved production
  policy**, `candidate_direction` is `null` for every packet, so each packet is at most `POLICY_BLOCKED`
  for direction progression (still first-pass evidence-reviewable), and `READY_FOR_EXPERT_REVIEW`,
  `SECOND_REVIEW_APPROVED`, and `EXTERNAL_SUBMISSION_READY` are **unreachable by construction** — the
  production policy is unapproved, the PRD-06 gate is not `PASS`, and no qualified sign-off exists.

### 4.6 Review scaling (measured census patterns — Slot 2)

Encode the measured pattern facts from the census source of record
(`candidate_pattern_compression`, `evidence_topology`):

- **FR16 — Pattern facts encoded as selection metadata (NOT cutoffs; item 6).** `candidate_LP_review`:
  **238** variants, **20** exact strength patterns, **6** cover 90%, largest pattern `{PM2 Supporting,
  PVS1 Very Strong}` = 9 points, **115** variants. `candidate_LB_review`: **1,333** variants, **10**
  patterns, largest `{BP4 Strong, PM2 Supporting}` = −3 points, **1,222** variants (≈92%). **30 observed
  patterns total.** These are **reproducible internal analysis pinned to the census snapshot, not
  validated truth and not policy** — they are **selection metadata only**: a packet may carry
  `census_selection_stratum` + `pattern_id`, but the census patterns **never** define `candidate_direction`
  cutoffs or the criteria set (FR5). The packet cites the census snapshot id (`clinvar_2026-07-07`) as
  provenance.
- **FR17 — Deterministic calibration-batch selection over populated observed atoms (item 7).** A selector
  that achieves **set coverage over the populated observed atoms of each dimension independently** — all
  **30 observed patterns**, each **observed gene** (TSC1, TSC2), each **observed variant class**
  (missense, truncating, other), and each **observed edge flag** (contradiction, manual, unverified) — and
  **never** a cross-product of empty cells. The selector is deterministic under a pinned selection policy +
  census snapshot (AC12). The **coverage report distinguishes** `populated` (an atom observed in the
  corpus), `covered` (a populated atom included in the batch), and `impossible/unpopulated` (a
  dimension-combination that has no observed member) cells. It selects the calibration batch; it does
  **not** decide direction.
- **FR18 — Pattern-level decision distinct from variant-level sign-off (Slot-3 failure mode 2).** Approving
  a pattern (e.g. `BP4 Strong + PM2 Supporting`) validates the **triage policy** for that pattern **only**;
  it **never** signs off its 1,222 member variants. External reclassification remains **per-variant**
  (AC16; §4.5 `EXTERNAL_SUBMISSION_READY` requires per-variant sign-off).
- **FR19 — 100% individual review before any external LP claim.** Every `candidate_LP_review` variant
  requires individual expert sign-off before any external LP claim (no pattern shortcut for the pathogenic
  direction).
- **FR20 — LB stratified sampling for policy validation.** `candidate_LB_review` uses stratified sampling
  to validate the triage **policy**, but **per-variant sign-off** is still required before any external
  reclassification.
- **FR21 — Disagreement capture → global-policy rerun.** Reviewer disagreements are captured and drive a
  **global candidate-policy rerun**, not a fixture-specific patch (no per-variant band-aids that mask a
  policy defect — GP-6/GP-8).
- **FR22 — Dual-review calibration + inter-reviewer agreement.** Calibration batches carry dual-review and
  inter-reviewer-agreement fields (for `SECOND_REVIEW_APPROVED`).

### 4.7 History & supersession (mirror PRD-03 discipline; do NOT write `classification_versions`)

- **FR23 — Append-only revision/supersession, packet-owned (item 1).** Revision/supersession **mirrors**
  the PRD-03 append-only *discipline* but is **packet-owned**: a superseded packet is **immutable**; a new
  version is a **new content-addressed packet** (new `packet_envelope_hash`, §4.2) linked to its
  predecessor via a supersession record in the decision log (§4.9). **This increment writes NO
  `classification_versions` row.** PRD-03 `classification_versions` is **reserved solely** for a terminal,
  qualified, variant-level classification after **all** gates + sign-offs (a later increment, only from an
  `EXTERNAL_SUBMISSION_READY` packet); reviewer/pattern decisions and final internal dispositions are
  **never** written there (AC14/AC11). A state/reviewer action never mutates a prior packet hash (§4.2).

### 4.8 No label/oracle leakage + no direct KB/eval coupling (H1)

- **FR24 — Benchmark/label files unreachable; assembled from an injected `PacketInput`.** The packet build
  path consumes an **injected `PacketInput`** (§4.10) + config; it reads **no** benchmark/held-out/label/
  oracle file and imports **no** `eval.*` combiner. Enforced structurally + a forbidden-path/import audit
  (AC3). The optional KB→`PacketInput` adapter (§10.6) is the only KB-reading surface and is out of this
  increment.

### 4.9 Variant-scoped append-only hash-chained decision log (item 1; r3-4)

- **FR25 — Variant-scoped decision log identity.** There is **exactly one decision log per canonical
  variant identity**, spanning **all packet versions** of that variant. Its storage path/address is
  **deterministic from the canonical variant hash** —
  `decision_log_path = <root>/<sha256(canonical_variant_spdi)>.jsonl` — **never** from a raw/unsafe
  identity string (no path traversal, no collision on unnormalized SPDI text). All reviewer decisions,
  independent decisions, pattern-policy approvals, supersession, comparator-reveal, and reconciliation
  events for **every version** of that variant append to this **one** log.

  Each record carries:
  - `record_id` — a **caller-provided UUID** (or an exact deterministic key);
  - `event_type ∈ {reviewer_decision, independent_decision, pattern_policy_approval, supersession,
    comparator_reveal, reconciliation}`;
  - **bound identity** — `packet_id` + `evidence_core_hash` + `variant_id`, plus
    `supersedes_packet_id` / `superseded_by_packet_id` links for a `supersession` record;
  - actor identity + role, timestamp, the decision/rationale payload (an `independent_decision`
    additionally carries the reviewer **confidence**, which `reveal_allowed` gates on — FR14.1);
  - `prev_hash`, and `record_hash = sha256(prev_hash + canonical(record))` (§4.2 hash 4).

  - **Genesis.** The first record's `prev_hash` is **64 lowercase zero characters** (`"0" * 64`).
  - **Idempotency.** Appending a record whose `record_id` **and** canonical payload match an existing
    record is a **no-op** that returns the existing record (**no second append**); appending the
    **same `record_id` with a different payload fails loud** (`DecisionLogConflictError`).
  - **Single-writer durability (v1).** A writer takes an **OS advisory/exclusive file lock** on the log
    and performs **append → flush → fsync while the lock is held**, then releases; concurrency beyond
    single-writer is not a v1 concern (§5, ARCHITECTURE §4).
  - **Replay / verification.** `replay(log)` verifies **one linear `prev_hash` chain** — **no fork, no
    gap, no `record_hash` mismatch** — and that **every record binds the same `variant_id` / canonical
    variant identity** and a known `packet_id`/`evidence_core_hash`; any tamper (edited payload,
    reordered / inserted record, or a cross-variant record) **fails loud**. Replay reconstructs full
    history across **all packet versions** of the variant.

  The log is **append-only** (no in-place edit) and **separate from** PRD-03 `classification_versions`
  (FR23). A `pattern_policy_approval` record validates a pattern's triage policy and executes **no**
  state transition on any member variant (FR18/AC16). Tests prove append / replay / tamper /
  idempotency and variant-and-version spanning (AC11/AC23).

### 4.10 Injected `PacketInput` (buildable now — items 2/6 resolution)

- **FR26 — `PacketInput` assembly contract.** `build_packet` consumes an injected `PacketInput`: the
  variant's canonical identity, its scorer `CriterionCall`s (data shape from `scorer/model.py`), the
  **scorer-row/run provenance** (FR4.2), optional `primary_evidence_refs`, the machine-read lineage
  records (FR4.1), optional `census_selection_stratum`/`pattern_id`, and an optional AAVC comparator
  record (§4.11). It does **not** require the 6,618 VUS to exist in the PRD-03 KB and reads no KB table
  directly. Fixtures or safe internal census records supply `PacketInput` for the offline build.

### 4.11 External comparator — AAVC reveal-only envelope (item 9)

- **FR27 — AAVC reveal-only comparator.** The packet carries an optional `external_comparators` envelope
  (AAVC): pinned **DOI + archive checksum + repository commit**, SPDI **match method** (exact / common-trim
  / full-SPDI), AAVC machine class, criteria, and flags (per `docs/reference/aavc-prior-art-audit-2026-07.md`
  §4). The envelope is **excluded from `evidence_core_hash`** (§4.2) and **stripped from the
  direction-blinded `FIRST_PASS` view** by `redact_for_first_pass` (FR14.1), alongside the RAPTOR
  candidate direction — first-pass reviewers are blinded to **both** machine directions. The reviewer
  records an **independent decision + confidence BEFORE reveal** (an `independent_decision` decision-log
  record); the **reveal** and any **reconciliation** are **separate append-only decision-log events**
  (§4.9), and the `RECONCILIATION` view / comparator reveal is refused until `reveal_allowed` is true
  (FR14.1). AAVC **never** enters criteria, the candidate-direction policy/combiner, or grounding — it
  is a disagreement baseline, never a truth label or ACMG evidence (AC17).

---

## 4a. Field → validation owner + provenance rule (GP-1/GP-5/GP-9)

> Every field, state, and claim has an explicit validation owner and provenance rule (Slot 1).

| Field group | Validation owner | Provenance rule |
|---|---|---|
| Canonical identity (FR2) | PRD-02 normalizer + KB schema (mechanical) | canonical GRCh38 SPDI; missing/ambiguous → `manual_review` + `POLICY_BLOCKED`. |
| Criterion trail + strength/direction (FR4) | PRD-01 scorer shapes (data-only, via `PacketInput`) | scorer-row provenance (mandatory) resolves; else `unverified`. |
| Two-level provenance (FR4.2) | Mechanical (`ScorerProvenance` all-required, strict formats) + policy (`primary_required` for external use) | exactly one `ScorerProvenance` (a BIAS row, **never** a `PrimaryEvidenceRef`) + zero-or-more `PrimaryEvidenceRef`s with a `resolved`/`unresolved` predicate; `source_sha256` nullable only with `null_reason`; `primary_grounding ∈ {present, absent, not_required}`; `primary_required` (PS3/literature or config-flagged; unknown fails closed) blocks external readiness (AC18/AC21). |
| Criterion lineage (FR4.1) | `configs/eval/bias_lineage.yaml` via `load_lineage_policy` (machine-read) | both raw `validation_disposition` + `production_disposition` preserved; one exhaustive precedence `resolve_packet_policy_disposition` — **validation dominates**: `forbidden`→excluded, `requires_heldout_mask`→**masked (regardless of production)**, either-`deferred`→deferred, both-`allowed`→included, else **fail loud**. Packet never invents lineage (AC7/AC22). |
| Candidate direction + signed points (FR5) | Production candidate-direction **policy** (config, GP-6) + Oracle approval | policy id + version + per-criterion signed contributions; **unapproved → `candidate_direction=null`, `null_reason=production_policy_unapproved`, `POLICY_BLOCKED`** (first-pass evidence-reviewable, no direction approval). |
| Narrative plan (FR7) | Deterministic template renderer (mechanical) + reviewer | approved `template_id` + resolvable packet field paths only; `model` + `prompt_hash`; reviewer freeform in separate `reviewer_notes`, never fact-safe-claimed. |
| Review state (FR15) | State-machine guards (mechanical) + reviewers | fail-closed transition table (§4.5 FR15.1); `production_policy_unapproved` is a `POLICY_BLOCKED` guard; T3/T7/T8/T9 require non-null direction; gate enum `PASS\|FAIL\|UNDERPOWERED\|UNVERIFIED`. |
| Packet views / first-pass blinding (FR14/FR14.1) | `redact_for_first_pass` projection (mechanical) + reveal-state function | `PacketView ∈ {FIRST_PASS, OPERATOR, RECONCILIATION}`; `FIRST_PASS` strips candidate direction + signed points + policy id + whole comparator envelope; queue/reviewer delivery consume only `FIRST_PASS`; `RECONCILIATION` gated by `reveal_allowed` (decision-before-reveal) (AC20). |
| Reviewer/pattern decisions (FR12/FR25) | Operator (internal) / QMG (external) — STRATEGY §9 | **one variant-scoped append-only hash-chained decision log** (path = `sha256(canonical variant identity)`), genesis `prev_hash`=64 zeroes, `record_id` idempotency, lock+fsync, replay-verified; **no `classification_versions` write this increment** (AC11/AC23). |
| External comparator (FR27) | Reveal-only; reviewer independent-then-reconcile | AAVC DOI/checksum/commit + match method; excluded from `evidence_core_hash` + **stripped from `FIRST_PASS`** (both machine directions blinded); never enters criteria/combiner. |
| Pattern/calibration metadata (FR16/FR17) | Deterministic selector + census snapshot | census snapshot id (`clinvar_2026-07-07`) + pinned selection policy; **selection metadata only, never cutoffs**; coverage over populated atoms. |
| External release (`EXTERNAL_SUBMISSION_READY`) | PRD-06 gate + QMG / VCEP | gate `PASS` (missense-stratified, both directions) + ADR-0009 correction + per-variant sign-off. |

---

## 5. Non-functional requirements

- **Determinism / reproducibility (R-A11):** JSON packet, all four named hashes (§4.2), Markdown render,
  and queue index are record-identical on re-run of pinned inputs + policy; run metadata excluded.
- **Grounding (GP-9):** every scored criterion carries resolvable scorer-row provenance (0 null in the
  scored set; unresolvable → `unverified`, surfaced not hidden); primary-evidence grounding is optional
  and, when absent, explicit (`primary_grounding: absent`) — missing primary blocks external readiness
  where policy requires (FR4.2).
- **Provenance completeness (GP-5):** every packet carries the run/config/code/model/prompt/source pins (FR3).
- **Config-driven (GP-6):** packet schema, candidate-direction policy, selection policy, render options,
  state-machine guards all in versioned, schema-validated config; nothing policy-bearing hardcoded.
- **Single-writer (ARCHITECTURE §4):** the Queen writes via the PRD-03 KB; the variant-scoped decision log
  (FR25) uses an OS exclusive file lock + append/flush/fsync while held; concurrency beyond single-writer
  is not a v1 concern.
- **Enabler-not-decision-maker (GP-11):** no packet output is a diagnosis/treatment/patient-facing artifact.

---

## 6. Acceptance criteria *(→ OPERATING_MODEL §4 gates; test-author writes these as executable tests first)*

- **AC1 — Schema completeness + unknown-field handling.** A packet validates against the pinned schema;
  every §4.1 field group is present or explicitly null-with-reason; an **unknown/extra field fails loud**.
- **AC2 — Deterministic serialization + four hashes.** Same injected `PacketInput` + policy → byte-identical
  JSON, Markdown, queue index, and all four hashes (`evidence_core_hash`, `narrative_plan_hash`,
  `packet_envelope_hash`, decision-log `record_hash` chain); `run_id`/`generated_at`/narrative prose
  excluded from `evidence_core_hash`; comparators excluded from `evidence_core_hash` (R-A11; §4.2).
- **AC3 — No leakage / no coupling (H1).** The packet build path reads no benchmark/held-out/label/oracle
  file, imports no `eval.*` combiner, and reads no KB table directly (assembles from `PacketInput`) —
  proven structurally + a forbidden-path/import audit.
- **AC4 — Candidate direction never a classification; nullable; blinded first-pass.** No rendering emits an
  `LP`/`LB` token as a standalone classification; in the **`OPERATOR`/`RECONCILIATION`** views the direction
  (including the **`null` + `null_reason`** state) always carries the *candidate/non-authoritative* marker +
  packet state + gate status; an unapproved policy yields `candidate_direction=null,
  null_reason=production_policy_unapproved`; the **`FIRST_PASS` view carries no candidate direction at all**
  (Slot-3 failure mode 1; items 6, r3-2).
- **AC5 — Two-level provenance resolution (item 2; r3-5).** Every scored criterion resolves **exactly one
  mandatory `ScorerProvenance`** (a BIAS row, **never** a `PrimaryEvidenceRef`); an unresolvable
  `ScorerProvenance` (any required field missing/malformed) is `unverified` and blocks promotion;
  `primary_evidence_refs` is optional and, when absent, explicit (`primary_grounding: absent`); test proves
  scorer-row-required, primary-optional, and that a BIAS row can never be constructed as a
  `PrimaryEvidenceRef`.
- **AC6 — Exact point arithmetic + policy version.** The signed point calculation equals the hand-computed
  sum under the pinned candidate-direction policy; the packet records the policy id + version. (When the
  policy is unapproved, direction is `null` and no cutoff is applied.)
- **AC7 — Machine-read lineage disposition + precedence (item 10; r3-1).** Each criterion's `lineage_class`
  + **both** raw dispositions (`validation_disposition`, `production_disposition`) come from
  `configs/eval/bias_lineage.yaml` (not invented) and are **preserved verbatim**; `packet_policy_disposition`
  is derived by the single exhaustive `resolve_packet_policy_disposition` precedence (FR4.1): `forbidden`
  (PP5/BP6/PS4) → **excluded** with `direct_copy_forbidden`, `requires_heldout_mask` (PS1/PM5/PM1/PP2/BP1)
  → **masked regardless of `production_disposition == allowed`**, either-`deferred` (PS3/BS2) → **deferred**
  with its `decision_dependency`, both-`allowed` → **included**; **none silently dropped** (H5); test proves
  the packet matches the policy loader, not a hardcoded map.
- **AC8 — Contradiction preservation.** A variant with both-direction evidence (census: 3,739) keeps both
  with a `contradiction` flag; the packet never resolves it away.
- **AC9 — Template-narrative-plan validity (item 3).** A narrative plan referencing a `template_id` not in
  the catalog, or binding a field path that does not resolve to a packet field, **fails loud**; the
  deterministic renderer expands a valid plan to byte-identical prose; reviewer freeform lives only in
  `reviewer_notes`, is excluded from the generated narrative, and is never marked fact-safe.
- **AC10 — State-transition table + gate enum (item 5; r3-3).** Only transitions in §4.5 FR15.1 succeed, each
  with its exact guard and reviewer role/count/distinctness; **`production_policy_unapproved` routes to
  `POLICY_BLOCKED` (T2) and blocks T3/T7/T8/T9** (a null-direction packet cannot enter any candidate-direction
  approval state, though it stays first-pass evidence-reviewable); a gate `FAIL`/`UNDERPOWERED`/`UNVERIFIED`,
  un-adjudicated masked/deferred/forbidden lineage, missing canonical identity, unverified scorer-row source,
  or a null `candidate_direction` **blocks** `EXTERNAL_SUBMISSION_READY`; `SECOND_REVIEW_APPROVED`→external
  requires **two distinct** QMG sign-offs; every named state is test-decidable.
- **AC11 — Variant-scoped decision-log conservation (item 1; r3-4).** Reviewer/pattern decisions are appended to
  the **one variant-scoped** hash-chained decision log (`record_hash = sha256(prev_hash + canonical(record))`),
  **never** to `classification_versions` (test proves no `classification_versions` write); replaying the log
  reconstructs history across all packet versions of the variant; nothing is edited in place.
- **AC12 — Calibration selection determinism + populated-atom coverage (item 7).** The selector
  deterministically covers every **populated observed atom** of each dimension independently (30 patterns,
  observed genes, classes, edge flags) — **not** a Cartesian product; the coverage report distinguishes
  `populated`/`covered`/`impossible-unpopulated`; re-run identical.
- **AC13 — Renderer / queue consistency.** For every variant, the Markdown render and the queue-index row
  agree on direction, state, and flags.
- **AC14 — Supersession immutability.** A superseded packet is immutable; a new version is a new
  content-addressed packet (`packet_envelope_hash`) linked to its predecessor via a decision-log
  supersession record; editing a superseded packet or mutating a prior packet hash fails.
- **AC15 — No external-ready state without PASS + policy + direction + reviewers (r3-3).**
  `EXTERNAL_SUBMISSION_READY` is unreachable unless an **approved production policy + non-null
  `candidate_direction`**, the PRD-06 gate `PASS` (missense-stratified, both directions), **two distinct**
  qualified reviewer sign-offs, the ADR-0009 mask/ruling, and `primary_grounding=present` for every
  `primary_required` criterion all exist; a gate `FAIL`/`UNDERPOWERED`/`UNVERIFIED`, a null direction, or
  any missing precondition fails promotion (H4/H13). This increment cannot reach the state (item 8).
- **AC16 — Pattern approval ≠ variant sign-off (Slot-3 failure mode 2).** Approving a pattern marks only the
  pattern's triage policy validated (a `pattern_policy_approval` decision-log record); it produces **zero**
  `EXTERNAL_SUBMISSION_READY` member variants and executes **no** state transition on any member; each
  member still requires its own sign-off; test proves approving `BP4 Strong + PM2 Supporting` reclassifies
  and advances **0** of its 1,222 members.
- **AC17 — AAVC reveal-only comparator (item 9; r3-2).** The AAVC envelope is **excluded from
  `evidence_core_hash`** and **stripped from the `FIRST_PASS` view** by `redact_for_first_pass`; a reviewer
  **independent decision + confidence** is recorded **before** any `comparator_reveal` (`reveal_allowed`
  is false until it exists); reveal and `reconciliation` are separate append-only decision-log records; a
  test proves AAVC never feeds a criterion, the candidate-direction policy, or grounding.
- **AC18 — Primary grounding gates external readiness (item 2; r3-5).** A `primary_required` criterion
  (any included/deferred functional/literature — PS3 — claim, or a config-flagged criterion; unknown
  **fails closed**) carrying `primary_grounding ∈ {absent, not_required}` **cannot** reach
  `EXTERNAL_SUBMISSION_READY`; scorer-row provenance alone never satisfies a primary-grounding requirement;
  test proves the block and that BIAS-row provenance is never a `PrimaryEvidenceRef`.
- **AC19 — Four hash domains distinct + stable (item 4).** The four hashes are computed over exactly their
  §4.2 domains; changing the narrative plan changes only `narrative_plan_hash` (+ envelope), never
  `evidence_core_hash`; changing a run-metadata pin outside the enumerated set changes no packet hash;
  appending a decision changes only the decision-log chain, never packets 1–3.
- **AC20 — First-pass double-blinding projection (r3-2).** `redact_for_first_pass(packet)` and the
  `render_markdown(..., view=FIRST_PASS)` output contain **no** `candidate_direction`, `null_reason`,
  `signed_points`/`per_criterion_points`, candidate-direction policy id/version, census-selection direction
  label, or `external_comparators` key/value — while **retaining** per-criterion strength/direction and the
  evidence trail; the queue index and reviewer-delivery surface consume **only** the `FIRST_PASS` projection,
  and the full JSON/`OPERATOR` view is never delivered as a first-pass reviewer input; a `RECONCILIATION`
  view or comparator reveal is **refused (fail loud)** until an append-only independent-decision-with-confidence
  record exists (`reveal_allowed` false), proving decision-before-reveal.
- **AC21 — Exact provenance schemas (r3-5).** `ScorerProvenance` fails loud when any required field
  (`bias_row_key`, `chromosome`, `position`, `ref`, `alt`, `scorer_run_id`, `input_sha256`, `output_sha256`,
  `raw_row_sha256`, `bias_version`, `bias_commit`, `nirvana_version`, `transcript`) is missing/malformed;
  a `PrimaryEvidenceRef` is `resolved` **only** with `source_id` + `locator`/`span` + `source_snapshot`/`version`
  + (`source_sha256` **or** a non-blank `source_sha256_null_reason`), else `unresolved` with reason; a BIAS
  row can never be constructed as a `PrimaryEvidenceRef`; `primary_grounding ∈ {present, absent, not_required}`;
  a criterion whose `primary_required` status is unknown is treated as `primary_required` (fails closed).
- **AC22 — Disposition precedence exhaustiveness (r3-1).** `resolve_packet_policy_disposition` implements the
  FR4.1 precedence over the full disposition enum cross-product: `validation=forbidden`→excluded,
  `validation=requires_heldout_mask`→**masked even when `production=allowed`**, either-`deferred`→deferred,
  both-`allowed`→included, any other combination **fails loud** (never silently `included`); both raw
  disposition fields are preserved on the `CriterionEntry`; test drives every current criterion
  (PS1/PM5/PM1/PP2/BP1 → masked; PP5/BP6/PS4 → excluded; PS3/BS2 → deferred; the nine allowed → included)
  plus a synthetic unknown pairing that must raise.
- **AC23 — Variant-scoped decision-log identity (r3-4).** There is exactly **one** log per canonical variant
  identity spanning all packet versions, addressed at `sha256(canonical_variant_spdi)` (never a raw
  identity); the genesis `prev_hash` is 64 lowercase zeroes; appending the same `record_id` + payload is a
  no-op returning the existing record, while the same `record_id` + a different payload **fails loud**; the
  writer holds an OS exclusive lock and append→flush→fsync; `replay` detects and fails on a fork, gap,
  `record_hash` mismatch, reordered/inserted record, or a cross-variant record, and reconstructs full history;
  records bind `packet_id`/`evidence_core_hash` and supersession links.

---

## 7. Dependencies

| Dependency | Status | Blocking? |
|---|---|---|
| PRD-01 · scorer criterion-level evidence | **built** (`1d2444e`) | Yes (FR4) — `CriterionCall` shapes consumed via injected `PacketInput` (not read from KB this increment) |
| PRD-03 · KB schema + ledger (history, source_refs, classification_versions) | **built** (`b627073`) | Reference only — `classification_versions` **not written** this increment; KB→`PacketInput` adapter is future (§10.6) |
| Census source of record `tsc_vus_clinvar_2026-07-07_stats.json` | **present** | Yes (FR16/FR17) — selection-metadata facts + provenance |
| **BIAS lineage gate** `configs/eval/bias_lineage.yaml` + `eval/lineage_policy.py` | **built** (static gate complete, `data/census/tsc_bias_lineage_audit_2026-07-10.json`) | Yes (FR4.1) — machine-read lineage classes + dispositions |
| **AAVC external comparator** (`docs/reference/aavc-prior-art-audit-2026-07.md`) | **audited/pinned** | Optional (FR27) — reveal-only comparator envelope; never criteria/combiner |
| **Production candidate-direction policy** (config; separate from PRD-06 combiner) | **not started** (PROGRAM item 8) | Yes (FR5) for a non-null direction — provisional packets proceed as `null`/`POLICY_BLOCKED` (first-pass evidence-reviewable) |
| PRD-06 · held-out gate `PASS` | **built; not yet PASS** (masked rerun + audit pending) | Yes for `EXTERNAL_SUBMISSION_READY` only (AC15) — **not** for provisional packets |
| PRD-08 · comparator-dependent lineage adjudication (ADR-0009) | **static gate landed; Oracle ruling on `requires_heldout_mask` pending** | Yes for masking/adjudicating PS1/PM5/PM1/PP2/BP1 before external release |
| Qualified molecular geneticist / VCEP (GP-3 oracle) | **not recruited** | Yes for any external disposition (STRATEGY §9) |

> **Buildable vs authoritative (GP-1).** The packet, render, queue, decisions, and state machine are
> **built + validated offline now** against fixtures / safe internal census records (provisional packets).
> An **externally usable worklist** additionally requires the production policy (FR5), a PRD-06 `PASS`
> (AC15), the ADR-0009 correction, and per-variant expert sign-off. Ship the contract; gate the release.

---

## 8. Risks (see RISK_REGISTER)

- **H1** (trace-cribbing) → FR24/AC3: label/benchmark files unreachable; assembled from injected `PacketInput`; no `eval.*` import.
- **H4** (unbacked green) / **H13** (fabricated target) → AC15/AC18: no `EXTERNAL_SUBMISSION_READY` without gate `PASS` + two distinct reviewers + primary grounding where required.
- **H5** (silent placeholder) → AC1/AC7: unknown-field fail-loud; excluded/masked/deferred visibility.
- **R-A2** (circular validation) → FR4.1 machine-read lineage precedence; `validation=forbidden` excluded, `validation=requires_heldout_mask` **masked regardless of production**, `deferred` deferred, unknown combination fails loud (AC7/AC22 — r3-1).
- **R-A3** (edge-case mis-application) → FR2: missing identity / NTHL1 / transcript drift route to `manual_review`.
- **R-A11** (non-reproducibility) → FR8/AC2/AC19: four hash domains separate deterministic core from narrative/comparator/run metadata.
- **R-E4** (expert-oracle bottleneck) → FR16–FR22: pattern-aware scaling (selection metadata), populated-atom coverage.
- **H12** (sycophancy) → FR21: disagreements drive a global-policy rerun, not fixture patches; "the config said so" is not a justification (GP-8).
- **Provenance/decision laundering (item 1/2; r3-4/r3-5)** → AC5/AC11/AC18/AC21/AC23: pinned `ScorerProvenance`/`PrimaryEvidenceRef`, BIAS row never a `PrimaryEvidenceRef`; decisions to a variant-scoped tamper-evident log, never `classification_versions`.
- **AAVC false authority + first-pass leakage (item 9; r3-2)** → FR14.1/FR27/AC17/AC20: reveal-only comparator, excluded from core; `FIRST_PASS` strips both machine directions; decision-before-reveal.
- **State-guard bypass (r3-3)** → FR15.1/AC10/AC15: `production_policy_unapproved` → `POLICY_BLOCKED`; T3/T9 require a non-null direction under an approved policy; external state unreachable this increment.
- **Slot-3 failure modes:** (1) polished false authority → FR14/FR14.1/AC4/AC20; (2) pattern sign-off laundering →
  FR18/AC16; (3) unreviewable evidence dump → FR4/FR6; (4) provenance/decision-log laundering → AC5/AC11/AC18/AC21/AC23.

---

## 9. Preservation set *(H3 / G1 — Slot 3)*

### 9.1 Frozen — byte-unchanged (the checker fails any diff that touches these)
- **PRD-01 scorer stays criterion-level, not an autonomous final classifier:** `src/raptor/scorer/**`,
  `tests/scorer/**` (esp. the parsing oracle + `test_ac6_no_trace_cribbing.py`) — the packet **consumes**
  `CriterionCall`/`EvidenceRecord` **shapes** via an injected `PacketInput`; it does not modify or re-tier
  the scorer.
- **PRD-06 Tavtigian combiner stays eval-only:** `src/raptor/eval/**` (esp. `combine.py`, `harness.py`) +
  its tests — **not** imported by packet generation; a *production* candidate-direction policy is a
  **separate** config-pinned surface (FR5).
- **BIAS lineage gate is read-only, not modified:** `configs/eval/bias_lineage.yaml`,
  `src/raptor/eval/lineage_policy.py`/`lineage_registry.py`/`lineage_audit.py` — the packet **consumes**
  `load_lineage_policy` output (FR4.1); it never edits the policy or invents lineage.
- **Benchmark/label files remain unreachable from packet generation:** the frozen held-out / labels
  artifacts and their loaders (PRD-06/PRD-07) — no packet module reads them; the packet reads an injected
  `PacketInput` (FR24/AC3).
- **KB append-only *discipline* mirrored, not bypassed — and `classification_versions` NOT written:**
  `src/raptor/kb/store.py` public API + its tests remain frozen; this increment writes **no**
  `classification_versions` row and does not read KB tables directly (the KB→`PacketInput` adapter is a
  future surface, §10.6). Reviewer/pattern decisions go to the packet-owned decision log (FR25).
- **AAVC stays a reveal-only comparator:** `docs/reference/aavc-prior-art-audit-2026-07.md` + the AAVC
  overlap aggregate are read-only inputs; AAVC never enters criteria/combiner/grounding (FR27).
- **No code, tests, configs, existing PRDs, strategy, program, decisions, or risk documents are modified**
  by this PRD authoring task (Slot 3; §12 diff scope). Implementation lands later via the loop against §11.

### 9.2 New coverage — append-only, in NEW modules (never edit a frozen file)
- New `src/raptor/packet/**` modules + new `tests/packet/**` modules + new `configs/packet/**` (§10.3).
- A **new** forbidden-path/import audit proving the packet path reads no benchmark/label/oracle file and
  imports no `eval.*` combiner (AC3).
- New conformance-kit wiring for the packet modules (§10.4).
- A later `scripts/build_tsc_calibration_batch.py` (§10.5) — the only script surface.

---

## 10. Build contract (v1 increment) — feeds the loop

> Planner-authored (OPERATING_MODEL §2). The test-author (Gemini) writes AC tests to this public surface
> **from the spec only**; the Sonnet doer implements to pass them (may add, not weaken); the GPT checker
> re-verifies; the conformance kit (`raptor.testkit.invariants`) is wired from the start. Config `confirm`
> pins (the production candidate-direction policy) do **not** block the offline provisional build.

### 10.1 Scope of this increment
- **Built + validated offline now:** FR1–FR27 against **fixtures / safe internal census records** assembled
  into an injected `PacketInput` (§4.10); AC1–AC23. Provisional/calibration packets only
  (`DRAFT_PROVISIONAL`/`POLICY_BLOCKED` + first-pass evidence review, with `candidate_direction`
  legitimately `null`; `READY_FOR_EXPERT_REVIEW` and later states unreachable while the production policy
  is unapproved). Gene scope TSC1/TSC2. Surfaces: packet core/schema/config, deterministic
  JSON/Markdown/queue, three-view rendering (`FIRST_PASS`/`OPERATOR`/`RECONCILIATION`) with the
  first-pass redaction projection, template narrative plan, variant-scoped append-only decision log, state
  machine, external-comparator reveal envelope, calibration selector.
- **Deferred (not code / not this increment):** production candidate-direction policy approval (FR5), the
  real PRD-06 `PASS`, the ADR-0009 Oracle ruling on `requires_heldout_mask`, per-variant expert sign-off,
  writing any `classification_versions` row, and the KB→`PacketInput` adapter (§10.6) — all required before
  any `EXTERNAL_SUBMISSION_READY` packet or external worklist (AC15/AC18). Until then the external state is
  **unreachable by construction**, not by omission.
- **Independent oracles for tests:** hand-computed signed point sums (AC6); hand-built expected
  JSON/Markdown/queue fixtures (AC2/AC13); the census stats file's recorded counts (AC12/AC16); the
  `bias_lineage.yaml` policy loader output as the lineage oracle (AC7) — never the implementation's own
  output.

### 10.2 Config (GP-6; nothing policy-bearing hardcoded)
- **`configs/packet/schema.yaml`** (+ JSON Schema) — packet field set, required/nullable, `packet_schema_version`.
- **`configs/packet/candidate_direction.yaml`** — production candidate-direction **policy**: `policy_id` +
  `version`, criteria set, point values, cutoffs. **`confirm`** (Oracle-pinned; empty/unapproved →
  `candidate_direction=null, null_reason=production_policy_unapproved`, packets are `POLICY_BLOCKED`
  via T2 guard `production_policy_unapproved`).
  **Separate from `configs/eval/tsc2.yaml`** (eval combiner) — no import (§9).
- **`configs/packet/selection.yaml`** — calibration selection policy (observed-atom coverage dims + pinned
  seed) + census snapshot id.
- **`configs/packet/render.yaml`** — deterministic render options + non-authoritative markers (FR14) + the
  first-pass comparator-hiding rule (FR27).
- **`configs/packet/narrative_templates.yaml`** — the approved narrative template catalog (`template_id` →
  template body with named field slots) for FR7.
- Consumes `configs/eval/bias_lineage.yaml` (via `load_lineage_policy`) for FR4.1 lineage; reuses
  `configs/acmg/tsc.yaml` (`strength_map`) for FR4 strengths.

### 10.3 Module layout + public API (the test contract) — `src/raptor/packet/`
> Smallest coherent surface: a library module per deliverable. The packet path **imports no `eval.*`
> combiner and reads no KB table / label file**; it assembles from an injected `PacketInput`. Only
> `scorer/model.py` record **shapes** and `eval/lineage_policy.load_lineage_policy` (data, not combiner
> logic) are consumed.

- **`config.py`** — `PacketConfig`/`CandidateDirectionPolicy`/`SelectionConfig`/`NarrativeCatalog` (frozen)
  + `load_*`; schema-validate, raise on missing/blank required pin (GP-6).
- **`model.py`** — `CandidateEvidencePacket` (§4.1 schema, frozen dataclass), `PacketInput` (§4.10),
  `CriterionEntry` (`criterion, strength, direction, rationale, lineage_class, validation_disposition,
  production_disposition, decision_dependency, packet_policy_disposition, scorer_provenance` (exactly one),
  `primary_evidence_refs` (zero+), `primary_grounding ∈ {present, absent, not_required}`,
  `primary_grounding_reason`, `primary_required: bool`), `ScorerProvenance` + `PrimaryEvidenceRef` (FR4.2
  pinned schemas), `CandidateDirection` (`direction|None, null_reason, policy_id, policy_version,
  signed_points, per_criterion_points`), `NarrativePlan` (`entries: [{template_id, field_bindings}]`,
  `model, prompt_hash`), `ExternalComparator` (AAVC envelope), `PacketView` enum
  (`FIRST_PASS|OPERATOR|RECONCILIATION`), `FirstPassPacketView`, `ReviewState`, `ReviewerDecision`,
  `DecisionLogRecord`, `PatternRef`. Exposes `resolve_packet_policy_disposition(validation, production)`
  (FR4.1 precedence) + `redact_for_first_pass(packet) -> FirstPassPacketView` (FR14.1).
- **`build.py`** — `build_packet(packet_input: PacketInput, config, *, narrative_plan=None) ->
  CandidateEvidencePacket`: applies the candidate-direction policy (FR5; `null` when unapproved), maps
  machine-read lineage → `packet_policy_disposition` via `resolve_packet_policy_disposition` (FR4.1,
  preserving both raw dispositions), assembles two-level provenance (FR4.2),
  exclusions/contradictions/missing-evidence (FR6). **Reads no KB/benchmark/label file** (FR24); the AAVC
  comparator is attached but excluded from the evidence core and from the first-pass view.
- **`direction.py`** — `compute_candidate_direction(entries, policy) -> CandidateDirection`: signed sum
  under the **production** policy; returns `null`/`null_reason` when unapproved; `no_deterministic_resolution`/
  `manual_review` are first-class. Does **not** import `eval/combine.py`.
- **`hashing.py`** — `evidence_core_hash(packet)`, `narrative_plan_hash(plan)`, `packet_envelope_hash(packet)`,
  `decision_record_hash(prev_hash, record)` — the four canonical domains (§4.2/FR8), mirroring
  `scorer/report.py` + `kb/store.py` canonicalization. Genesis `prev_hash = "0"*64` (FR25).
- **`render.py`** — `render_markdown(packet, config, *, view: PacketView) -> str`: deterministic template
  expansion of the narrative plan (FR7); non-authoritative markers + state + gate status unavoidable in
  `OPERATOR`/`RECONCILIATION`; the `FIRST_PASS` render consumes `redact_for_first_pass` and carries no
  candidate direction / signed points / comparator (FR10/FR14/FR14.1/FR27/AC20).
- **`queue.py`** — `build_queue_index(packets, config) -> QueueIndex` (CSV + JSONL, built from the
  `FIRST_PASS` projection for reviewer delivery) + `select_calibration_batch(packets, selection_config) ->
  Batch` + `coverage_report(...)` distinguishing populated/covered/impossible atoms (FR11/FR13/FR17),
  deterministic.
- **`state.py`** — `PacketStateMachine` with the §4.5 states + transition table (FR15.1) +
  `can_promote(packet, gate_status, reviewers)`; fail-closed guards (FR15/AC10/AC15).
  `production_policy_unapproved`/null direction → `POLICY_BLOCKED`; T3/T7/T8/T9 require a non-null
  direction. Gate enum `PASS|FAIL|UNDERPOWERED|UNVERIFIED`. Pattern approval marks pattern-policy
  validated **only** (FR18/AC16).
- **`decisions.py`** — `decision_log_path(variant_identity) -> Path` (= `sha256(canonical SPDI)`, FR25) +
  `append_decision(log_path, record, *, record_id) -> DecisionLogRecord` + `replay(log_path)`: the
  **one-per-variant append-only hash-chained decision log** (FR25) — genesis `prev_hash`=64 zeroes,
  `record_id` idempotency (same id+payload no-op; same id+different payload → `DecisionLogConflictError`),
  OS exclusive lock + append/flush/fsync, replay verifying one linear chain + variant/version identity.
  Handles `reviewer_decision`, `independent_decision`, `pattern_policy_approval`, `supersession`,
  `comparator_reveal`, `reconciliation`. **Writes no `classification_versions` row** (FR23/AC11/AC23).
- **`comparator.py`** — `attach_comparator(packet, aavc_record)` + `reveal_allowed(packet, log) -> bool` +
  `reveal(log, packet)`: the reveal-only AAVC envelope (FR27); reviewer independent-decision-with-confidence
  before reveal enforced via the decision log; the comparator is stripped from `FIRST_PASS` (FR14.1).

> The doer **must honor**: `PacketInput` is injected (fixtures/temp store in tests); the packet path imports
> **no** `eval.*` combiner, reads **no** label/benchmark/oracle file, reads **no** KB table directly, and
> writes **no** `classification_versions` row; candidate direction is a review direction (nullable), never a
> classification.

### 10.4 Conformance kit (wired from the start — new modules)
`tests/packet/test_kit_conformance_packet.py` wires `raptor.testkit.invariants`:
- **determinism** (all four hashes + render + queue stable across runs);
- **fail-loud-propagation** (unknown field / bad template id / unresolved field path raises — AC1/AC9);
- **no-state-change-on-failure** for any decision-log append;
- packet-specific: **no-label/eval-leak** (build imports no `eval.*` and touches no label/KB file — AC3),
  **direction-not-classification** (no standalone LP/LB token; nullable — AC4), **first-pass-double-blinding**
  (`FIRST_PASS` strips candidate direction + comparator — AC20), **no-classification-versions-write**
  (AC11) — candidates for kit promotion if they recur.

### 10.5 Implementation decomposition (three sequenced doer tasks; ≤4 reference files each)
The v1 increment exceeds four reference files, so it is fired as **three sequenced doer tasks A → B → C**
(core → surfaces → workflow), sharing this PRD, each with ≤4 reference files, preservation directive
(slot 3), and inverted failure modes. A later, separate script `scripts/build_tsc_calibration_batch.py`
assembles a real calibration batch from injected census `PacketInput`s (direction `null`/`POLICY_BLOCKED`;
census stratum selection only) — it is not a doer task in this increment. See §11.

### 10.6 KB→`PacketInput` adapter (future, out of this increment)
A separate `src/raptor/packet/kb_adapter.py` will materialize `PacketInput` from the PRD-03 KB
(`effective_evidence_at` + `source_refs`) when the 6,618 VUS are loaded. It is the **only** KB-reading
surface and is **deferred**: the packet library must not depend on it and must build fully from injected
`PacketInput` now.

### 10.7 Anti-authority / anti-circularity (this artifact IS the false-authority boundary)
- **Direction is a review direction (nullable), not a classification** (FR14/AC4); **first-pass reviewers are blinded to both machine directions** (FR14.1/AC20).
- **Pattern approval ≠ variant sign-off** (FR18/AC16) — approving `BP4 Strong + PM2 Supporting` advances **0** of 1,222 members.
- **Evidence is fully inspectable** (FR4/FR6) — machine-read lineage + exclusions + contradictions + missing evidence + reviewer actions; disposition precedence is exhaustive + fail-loud (FR4.1/AC22).
- **BIAS row is never a `PrimaryEvidenceRef`; decisions never touch `classification_versions`** (FR4.2/FR23/AC5/AC11/AC18/AC21/AC23).
- **AAVC is a reveal-only comparator** (FR27/AC17) — excluded from core + stripped from `FIRST_PASS`; decision-before-reveal; never criteria/combiner.
- **Eval stays eval; production policy is separate** (FR5/§9) — no `eval.combine` import; no label/KB read (FR24/AC3); `production_policy_unapproved` → `POLICY_BLOCKED`, external state unreachable (FR15.1/AC10/AC15).

---

## 11. Definition-of-Ready Task Spec (OPERATING_MODEL §3.1)

> **Decomposition (OPERATING_MODEL §7 — one hypothesis per task, ≤4 reference files).** The v1 increment
> exceeds four reference files, so it is fired as **three sequenced doer tasks in dependency order
> A → B → C** (packet core → surfaces → review workflow/comparator), sharing this PRD, each with its own
> ≤4 reference files, preservation directive (slot 3), and inverted failure modes. A later, separate
> `scripts/build_tsc_calibration_batch.py` assembles a real calibration batch from injected census
> `PacketInput`s (direction `null`/`POLICY_BLOCKED`; census stratum selection only).

### 11.1 Task Spec — packet core (A)
```yaml
task_id: prd04-packet-core
goal: Build the candidate-evidence-packet model + machine-read lineage/two-level provenance + nullable production candidate-direction policy + the four canonical hashes, assembled from an injected PacketInput (no eval-combiner import; no label/benchmark/KB read; no classification_versions write).
motivating_reference: PRD-04 §4.1/§4.2/§4.10 + §4.5 states + ADR-0009 lineage + bias_lineage gate + STRATEGY §9
context_surface:
  - src/raptor/packet/model.py         # NEW: CandidateEvidencePacket, PacketInput, CriterionEntry, CandidateDirection(nullable)
  - src/raptor/packet/build.py         # NEW: build_packet(PacketInput, config, *, narrative_plan=None)
  - src/raptor/packet/direction.py     # NEW: production candidate-direction policy (nullable; NOT eval.combine)
  - src/raptor/packet/hashing.py       # NEW: evidence_core/narrative_plan/packet_envelope/decision_record hashes
  - src/raptor/packet/config.py        # NEW: PacketConfig/CandidateDirectionPolicy (frozen, schema-validated)
  - configs/packet/schema.yaml         # NEW
  - configs/packet/candidate_direction.yaml  # NEW (confirm empty -> candidate_direction=null, POLICY_BLOCKED)
reference_files:                       # <=4
  - src/raptor/scorer/model.py         # CriterionCall/EvidenceRecord shapes (data-only reuse)
  - src/raptor/eval/lineage_policy.py  # load_lineage_policy -> lineage_class + dispositions (FR4.1)
  - src/raptor/scorer/report.py        # content_hash pattern to mirror (FR8)
  - data/census/tsc_vus_clinvar_2026-07-07_stats.json  # selection-metadata/topology facts + provenance
acceptance_criteria:
  - {text: "AC1 schema completeness + unknown-field fail-loud", type: mechanical}
  - {text: "AC2 deterministic JSON + four hashes (core excludes narrative/comparator/run-metadata)", type: mechanical}
  - {text: "AC3 no label/oracle/KB read + no eval.* import (forbidden-path/import audit)", type: mechanical}
  - {text: "AC4 candidate_direction nullable; null_reason=production_policy_unapproved", type: mechanical}
  - {text: "AC5 two-level provenance: exactly one ScorerProvenance (never a PrimaryEvidenceRef); primary optional/explicit-absent", type: mechanical}
  - {text: "AC6 exact signed-point arithmetic + policy version", type: mechanical}
  - {text: "AC7 machine-read lineage disposition + precedence (validation dominates; requires_heldout_mask->masked regardless of production)", type: mechanical}
  - {text: "AC8 contradiction preservation", type: mechanical}
  - {text: "AC19 four hash domains distinct + stable", type: mechanical}
  - {text: "AC21 exact provenance schemas (ScorerProvenance all-required strict; PrimaryEvidenceRef resolved/unresolved predicate; BIAS row never a PrimaryEvidenceRef)", type: mechanical}
  - {text: "AC22 disposition precedence exhaustive + fail-loud on unknown combination (r3-1)", type: mechanical}
preservation_set:                      # §9.1 frozen — byte-unchanged
  - src/raptor/scorer/**
  - src/raptor/eval/**
  - src/raptor/kb/store.py
  - configs/eval/bias_lineage.yaml
  - tests/scorer/test_ac6_no_trace_cribbing.py
invert_failure_modes:
  - "Packet build imports eval.combine or reads a label/benchmark/KB file -> eval/production leak + H1 breach."
  - "A forbidden (PP5/BP6/PS4) criterion is scored not excluded -> R-A2 circularity (ADR-0009)."
  - "Packet invents its own lineage instead of reading bias_lineage.yaml -> lineage drift (item 10)."
  - "A requires_heldout_mask criterion (PS1/PM5/PM1/PP2/BP1) resolves to included because production=allowed -> disposition-precedence breach (r3-1)."
  - "An unmapped disposition combination silently defaults to included instead of failing loud -> R-A2 circularity (r3-1)."
  - "candidate_direction emitted non-null under an unapproved policy -> eval combiner becomes production oracle (item 6)."
  - "A BIAS row is constructed as a PrimaryEvidenceRef, or a ScorerProvenance drops a required field -> provenance laundering (item 2/r3-5)."
  - "evidence_core_hash includes the narrative/comparator/run_id -> non-deterministic core (R-A11)."
out_of_scope: rendering; queue; state machine; decision log; comparator reveal; the LLM narrative call; the KB adapter; any external release.
na_allowed: false
prompt_manifest:                       # placeholders — MUST be filled at Ready preflight (OPERATING_MODEL §3.1)
  slot1_id+hash: "docs/prompts/prd04-core/slot1-intent.md @ sha256:16e5b3e0a9be010f513b262926d455cecf9a6f9a120b351a43364dd5a6d0a08f"
  slot2_id+hash: "docs/prompts/prd04-core/slot2-core-contract.md @ sha256:e1afbca41fc901381c23ad1bbd73fff5fb6d75f3f0622db161a43889dfbfcb41"
  slot3: "Assemble from injected PacketInput; import no eval.combine; read no label/benchmark/KB file; write no classification_versions row; consume lineage from bias_lineage.yaml (never invent); derive packet_policy_disposition via the exhaustive precedence (validation dominates; requires_heldout_mask->masked; unknown combination fails loud); a BIAS row is never a PrimaryEvidenceRef; candidate_direction is nullable and never a classification."
    slot3_id+hash: "docs/prompts/prd04-core/slot3-preservation.md @ sha256:953e3168029ef95051ecff012f83a5280da1e7a4f23a082243aad06f8c71fdfc"
    intent_block_present: true
```

### 11.2 Task Spec — surfaces: render + queue + calibration (B)
```yaml
task_id: prd04-packet-surfaces
goal: Deterministic Markdown render with template-narrative-plan expansion + CSV/JSONL queue index + calibration-batch selection with populated-atom coverage, over the Task-A packet.
motivating_reference: PRD-04 §4.3/§4.4/§4.6 + FR7 narrative plan + FR17 coverage + STRATEGY §9
context_surface:
  - src/raptor/packet/render.py        # NEW: deterministic Markdown; template expansion; markers unavoidable; PacketView views; FIRST_PASS strips direction + comparator
  - src/raptor/packet/queue.py         # NEW: CSV/JSONL queue (from FIRST_PASS projection) + select_calibration_batch + coverage_report
  - configs/packet/render.yaml         # NEW
  - configs/packet/selection.yaml      # NEW
  - configs/packet/narrative_templates.yaml  # NEW: approved template catalog (FR7)
reference_files:                       # <=4
  - src/raptor/packet/model.py         # Task-A packet + NarrativePlan + PacketView + redact_for_first_pass (dependency)
  - src/raptor/scorer/report.py        # deterministic render/canonicalization pattern
  - data/census/tsc_vus_clinvar_2026-07-07_stats.json  # 30 observed patterns; 238/1,333; 1,222 (coverage oracle)
  - docs/reference/aavc-prior-art-audit-2026-07.md  # first-pass double-blinding rule (both machine directions)
acceptance_criteria:
  - {text: "AC9 template-narrative-plan validity (approved templates + resolvable field paths; reviewer notes excluded)", type: mechanical}
  - {text: "AC12 calibration selection determinism + populated-atom coverage (populated/covered/impossible)", type: mechanical}
  - {text: "AC13 renderer/queue consistency", type: mechanical}
  - {text: "AC4 direction (incl. null) never rendered as classification; absent from FIRST_PASS", type: mechanical}
  - {text: "AC20 first-pass double-blinding: FIRST_PASS render/projection strips candidate direction + signed points + policy id + comparator; queue/reviewer delivery consume only FIRST_PASS", type: mechanical}
preservation_set:                      # §9.1 frozen — byte-unchanged
  - src/raptor/scorer/**
  - src/raptor/eval/**
  - src/raptor/kb/store.py
  - src/raptor/packet/model.py         # Task-A output (do not edit; extend in new modules)
invert_failure_modes:
  - "A narrative plan with an unknown template_id or unresolved field path renders anyway -> freeform-fact leak (item 3)."
  - "Calibration coverage enumerates a Cartesian product of empty cells -> impossible-cell coverage (item 7)."
  - "Census patterns used as direction cutoffs -> eval counts become a production oracle (item 6)."
  - "The candidate direction, signed points, or the AAVC comparator appear in the FIRST_PASS render/projection -> first-pass double-blinding breach (r3-2)."
  - "The queue/reviewer-delivery surface serves the full/OPERATOR view instead of the FIRST_PASS projection -> reviewer sees a machine direction (r3-2)."
out_of_scope: packet model/build (Task A); state machine + decision log + comparator reveal (Task C); the LLM narrative call; any external release.
na_allowed: false
prompt_manifest:
  slot1_id+hash: "docs/prompts/prd04-surfaces/slot1-intent.md @ sha256:89272ea035fd494834742810a04513152c021a7f589758d37b4a98c7801c9e45"
  slot2_id+hash: "docs/prompts/prd04-surfaces/slot2-surfaces-contract.md @ sha256:16db6df5ea591edab9b209900f814f92eeb1091360ec56dd9f94b481fe39a5d9"
  slot3: "Template-constrained narrative only (approved ids + packet field paths); coverage over populated observed atoms only; census patterns are selection metadata, never cutoffs; the FIRST_PASS view/projection strips BOTH the RAPTOR candidate direction (and signed points/policy id) AND the AAVC comparator; queue + reviewer delivery consume only the FIRST_PASS projection."
    slot3_id+hash: "docs/prompts/prd04-surfaces/slot3-preservation.md @ sha256:7e5156db3a8a85678a1fa2b3521b5c4295e0d67d31f85e748926b06381b81acc"
    intent_block_present: true
```

### 11.3 Task Spec — review workflow: state machine + decision log + comparator (C)
```yaml
task_id: prd04-packet-workflow
goal: Fail-closed state machine (exact transition table + gate enum + reviewer role/count/distinctness; production_policy_unapproved->POLICY_BLOCKED; T3/T9 require a non-null direction) + ONE variant-scoped append-only hash-chained decision log (deterministic path from canonical variant hash, genesis prev_hash, record_id idempotency, lock+fsync, replay-verified) + three-view first-pass double-blinding + AAVC reveal-only comparator (decision-before-reveal, append-only reconciliation), over the Task-A/B packet.
motivating_reference: PRD-04 §4.4 FR14.1 + §4.5 FR15.1 + §4.7/§4.9 decision log + §4.11 comparator + STRATEGY §9
context_surface:
  - src/raptor/packet/state.py         # NEW: PacketStateMachine + transition table + can_promote(gate,reviewers)
  - src/raptor/packet/decisions.py     # NEW: ONE variant-scoped append-only hash-chained decision log (path=sha256(variant id); genesis/idempotency/lock+fsync/replay; no classification_versions write)
  - src/raptor/packet/comparator.py    # NEW: reveal-only AAVC envelope; decision-before-reveal
  - configs/packet/comparator.yaml     # NEW: pinned AAVC DOI/checksum/commit + match-method vocabulary
reference_files:                       # <=4
  - src/raptor/packet/model.py         # Task-A packet + DecisionLogRecord + ExternalComparator shapes
  - src/raptor/packet/hashing.py       # Task-A decision_record_hash (chain)
  - docs/prd/PRD-06-benchmark-eval-harness.md  # gate status semantics PASS/FAIL/UNDERPOWERED/UNVERIFIED (AC10/AC15)
  - docs/reference/aavc-prior-art-audit-2026-07.md  # AAVC reveal-only controls (AC17)
acceptance_criteria:
  - {text: "AC10 exact transition table + gate enum + reviewer role/count/distinctness; production_policy_unapproved->POLICY_BLOCKED; T3/T9 require non-null direction", type: mechanical}
  - {text: "AC11 variant-scoped decision-log conservation; NO classification_versions write", type: mechanical}
  - {text: "AC14 supersession immutability (no prior-hash mutation)", type: mechanical}
  - {text: "AC15 no external-ready without approved policy + non-null direction + gate PASS + two distinct reviewers + mask ruling + primary grounding", type: mechanical}
  - {text: "AC16 pattern approval advances 0 member variants", type: mechanical}
  - {text: "AC17 AAVC reveal-only (excluded from core + stripped from FIRST_PASS; decision-before-reveal; reconciliation append-only)", type: mechanical}
  - {text: "AC18 primary grounding gates external readiness", type: mechanical}
  - {text: "AC20 first-pass double-blinding enforced in delivery (reveal_allowed decision-before-reveal for RECONCILIATION)", type: mechanical}
  - {text: "AC23 variant-scoped decision-log identity: one log/variant across versions; genesis prev_hash 64 zeroes; record_id idempotency; lock+fsync; replay detects fork/gap/tamper/cross-variant", type: mechanical}
preservation_set:                      # §9.1 frozen — byte-unchanged
  - src/raptor/scorer/**
  - src/raptor/eval/**
  - src/raptor/kb/store.py             # classification_versions NOT written this increment
  - src/raptor/packet/model.py         # Task-A output (do not edit; extend in new modules)
invert_failure_modes:
  - "A reviewer/pattern decision is written to classification_versions -> decision-log laundering (item 1)."
  - "Approving BP4 Strong + PM2 Supporting advances its 1,222 members -> Slot-3 failure mode 2 (laundering)."
  - "A decision edits history in place instead of appending a hash-chained record -> audit bypass."
  - "The decision log is addressed from a raw/unsafe variant identity, forks/gaps, or replays to a different variant identity -> decision-log identity breach (r3-4)."
  - "A duplicate record_id with a divergent payload is silently accepted instead of failing loud -> idempotency breach (r3-4)."
  - "EXTERNAL_SUBMISSION_READY reachable without an approved policy + non-null direction + gate PASS + two distinct reviewers -> H4/H13 hollow green (r3-3)."
  - "AAVC enters criteria/combiner or the RECONCILIATION view/reveal is served before the independent decision-with-confidence -> false-authority reveal breach (item 9/r3-2)."
out_of_scope: packet model/build (Task A); render/queue/calibration (Task B); the LLM narrative call; the KB adapter; ClinVar submission; any real external release.
na_allowed: false
prompt_manifest:
  slot1_id+hash: "docs/prompts/prd04-workflow/slot1-intent.md @ sha256:ad08e12ca349fc59ad346c70144a40e7e4a9080008dc5a245c87ad01e4562062"
  slot2_id+hash: "docs/prompts/prd04-workflow/slot2-workflow-contract.md @ sha256:23e12528c915f2bfd725934869da132f6ff5ac76e851d91fa456427bb7c0954d"
  slot3: "Write decisions ONLY to the ONE variant-scoped append-only hash-chained decision log (path = sha256(canonical variant identity); genesis prev_hash = 64 zeroes; record_id idempotency; OS exclusive lock + append/flush/fsync; replay-verified), never classification_versions; pattern approval never advances a member variant; production_policy_unapproved -> POLICY_BLOCKED and T3/T9 require a non-null direction; EXTERNAL_SUBMISSION_READY requires an approved policy + non-null direction + gate PASS + two distinct QMG sign-offs + mask ruling + primary grounding; AAVC is reveal-only, decision-before-reveal, stripped from FIRST_PASS, never criteria/combiner."
    slot3_id+hash: "docs/prompts/prd04-workflow/slot3-preservation.md @ sha256:0267af8157815b6a7053f733c307e74a393ae3cb61ca973d2dbf118d0e3b31c9"
    intent_block_present: true
```

---

## 12. Diff scope (this revision task)

- **Modified (planning/specification only):**
  - `docs/prd/PRD-04-candidate-evidence-packet.md` (this file — r2 closed 10 findings (§0a); **r3 closes 5 further findings (§0b): disposition precedence, first-pass double-blinding, state guards, decision-log identity, exact provenance schemas**).
  - `docs/prompts/prd04-packet/slot2-packet-contract.md` (r2 rewrite + **r3**: exhaustive disposition precedence, `FirstPassPacketView`/three views, `production_policy_unapproved` state guard + non-null-direction T9, variant-scoped decision-log identity, pinned `ScorerProvenance`/`PrimaryEvidenceRef`).
  - `docs/prompts/prd04-packet/slot3-preservation.md` (r2 rewrite + **r3**: first-pass double-blinding, disposition-precedence integrity, variant-scoped decision-log identity, provenance-schema fidelity).
  - `docs/prompts/prd04-packet/slot1-planner.md` (minimal r3 touch: first-pass double-blinding + fail-loud disposition precedence).
  - `docs/prompts/prd04-packet/manifest.json` (recalculated SHA-256 + revision status → r3).
- **Ready-preflight artifacts (OPERATING_MODEL §3.1; planning only):**
  - `docs/prd/PRD-04-candidate-evidence-packet.md` §11.1–11.3 `prompt_manifest` placeholders filled with the persisted slot ids + SHA-256 for the three implementation-contract families.
  - `docs/prompts/prd04-core/**`, `docs/prompts/prd04-surfaces/**`, `docs/prompts/prd04-workflow/**` (new three-slot implementation contracts + manifests for doer tasks A/B/C; roles: Gemini 3.1 Pro tester, Claude Sonnet 5 doer, GPT-5.5 checker).
  - `docs/prompts/prd04-packet/manifest.json` (authorized planning outputs + Ready-preflight history entry).
- **No code, tests, or `configs/`** touched. No stage/commit/push. Implementation lands later via the loop against §10/§11.

## 13. Open questions

- **Production candidate-direction policy (FR5):** confirm the Oracle-pinned criteria set + point cutoffs in
  `configs/packet/candidate_direction.yaml`, consistent with (but not importing) the eval combiner
  (PROGRAM item 8). Until pinned, `candidate_direction=null` (`production_policy_unapproved`) and packets
  are `POLICY_BLOCKED` for direction progression (still first-pass evidence-reviewable).
- **`requires_heldout_mask` lineage (ADR-0009):** the PS1/PM5/PM1/PP2/BP1 external disposition
  (`masked`→`allowed`) awaits the PRD-08 Oracle ruling; the packet reads the lineage now and derives
  `masked` by validation-dominant precedence (FR4.1) and blocks external promotion (AC10/AC22).
- **Primary-evidence policy scope (FR4.2/AC18/AC21):** confirm the exact `primary_required` set — the
  default is any included/deferred functional/literature (PS3 / `literature_unvalidated`) claim plus every
  criterion config-flagged `primary_required: true`, unknown **failing closed**; confirm the config flag
  location (`schema.yaml` vs `candidate_direction.yaml`).
- **Decision-log root + reveal confidence scale (FR14.1/FR25):** confirm the decision-log storage root
  under which `sha256(canonical_variant_spdi).jsonl` lives, and the `independent_decision` confidence
  scale/vocabulary that `reveal_allowed` gates on.
- **Reviewer identity/role registry (STRATEGY §9):** where qualified-reviewer identity/role/distinctness is
  asserted for sign-off (config vs KB) — a data decision; the decision-log record shape (FR12/FR25) is
  source-agnostic.
- **Narrative template catalog (FR7):** confirm the approved `configs/packet/narrative_templates.yaml`
  template set + field slots; the LLM call that emits a plan (model/prompt) is out of the offline build —
  confirm the prompt-manifest pins when the narrative-plan generator is wired.
- **AAVC comparator envelope (FR27):** confirm the pinned DOI/checksum/commit + SPDI match-method vocabulary
  in `configs/packet/comparator.yaml`; non-exact matches remain provisional until reference-backed SPDI
  equivalence is confirmed.
