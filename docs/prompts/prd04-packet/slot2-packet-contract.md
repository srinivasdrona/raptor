# Slot 2 — PRD-04 candidate evidence packet

## Output

Create only:

- `docs/prd/PRD-04-candidate-evidence-packet.md`

## Goal

Specify a versioned, expert-reviewable **candidate evidence packet** and queue index for every TSC
VUS. RAPTOR must present a grounded point of view:

- `candidate_LP_review`
- `candidate_LB_review`
- `no_deterministic_resolution`
- `manual_review`

These are never final classifications. Provisional packets can be generated before validation;
externally usable worklists require benchmark PASS, corrected policy and qualified expert sign-off.

## Sources

- `docs/STRATEGY.md` GP-1/3/5/6/8/9/11/13, §§6–9
- `docs/PROGRAM.md` census/priorities/PRD-04 sequencing
- `docs/DECISIONS.md` ADR-0009/0010
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json`
- `docs/prd/PRD-01-tier12-acmg-scorer.md`
- `docs/prd/PRD-03-kb-schema-provenance-ledger.md`
- `docs/prd/PRD-06-benchmark-eval-harness.md`
- `docs/prd/PRD-08-live-eval-evidence-adapter.md`
- `src/raptor/scorer/model.py`, `report.py`
- `src/raptor/kb/store.py` classification/evidence history

## Required packet model

Pin a machine-readable schema with at least:

- packet schema/version, packet id/content hash;
- run/config/code/model/prompt/source snapshot pins;
- canonical variant identity, gene, transcript, consequence/class;
- raw fired criteria and rationale;
- criterion lineage/source class;
- policy disposition: included/excluded/masked/unverified/manual;
- evidence source references and resolvable spans/records;
- criterion strength/direction;
- candidate-direction policy/version and signed point calculation;
- contradictions and quality/manual flags;
- excluded evidence and exclusion reason;
- missing-evidence categories and grounded next-evidence action;
- structured LLM draft narrative in a **non-authoritative** section, with model/prompt hash and no new
  facts beyond packet fields;
- review state and per-criterion expert decisions;
- final human disposition and sign-off identity/role/date/rationale;
- revision/supersession history.

Separate deterministic packet content/hash from non-deterministic narrative and run metadata.

## Output surfaces

First increment only:

- JSON packet source of record;
- deterministic Markdown packet rendering;
- CSV/JSONL queue index;
- reviewer decision JSON (accept/reject/adjust/request-evidence/retain-VUS);
- batch/pattern metadata.

No frontend, API server, authentication system, Prefect flow, clinical-report template, ClinVar
submission automation, or patient communication.

## Review scaling

Encode the measured pattern facts from the census source:

- 238 candidate-LP variants, 20 exact strength patterns, six cover 90%;
- 1,333 candidate-LB variants, 10 patterns; BP4 Strong + PM2 Supporting covers 1,222.

Define:

- representative calibration-batch selection across every pattern, gene, variant class and edge flag;
- pattern-level decision distinct from variant-level sign-off;
- 100% individual review before any external LP claim;
- LB stratified sampling for policy validation, but per-variant sign-off before any external
  reclassification;
- disagreement capture and global-policy rerun rather than fixture-specific patches;
- dual-review calibration and inter-reviewer agreement fields.

## Packet state machine

Specify a fail-closed state machine such as:

- `DRAFT_PROVISIONAL`
- `POLICY_BLOCKED`
- `READY_FOR_EXPERT_REVIEW`
- `EXPERT_CHANGES_REQUESTED`
- `EXPERT_APPROVED_INTERNAL`
- `SECOND_REVIEW_APPROVED`
- `EXTERNAL_SUBMISSION_READY`
- `SUPERSEDED`

Only name states that are mechanically testable. Benchmark FAIL/UNDERPOWERED, unresolved criterion
lineage, missing canonical identity, or unverified source blocks promotion.

## Acceptance criteria

Assertion-specific ACs must cover:

- schema completeness and unknown-field handling;
- deterministic serialization/hash;
- no label/oracle leakage;
- candidate direction never rendered as classification;
- source resolution;
- exact point arithmetic and policy version;
- exclusion/unverified visibility;
- contradiction preservation;
- LLM narrative cannot introduce facts/criteria/citations;
- state-transition authorization;
- expert decision conservation/audit history;
- pattern/calibration selection determinism and coverage;
- renderer/queue consistency;
- supersession immutability;
- no external-ready state without PASS + required reviewers.

Include a Definition-of-Ready Task Spec and preservation set. Gemini will author tests before Sonnet
implementation; GPT checks. Decompose implementation if more than four reference files are required.

## Initial prototype

The PRD should authorize representative provisional packets before policy/gate completion, using
fixtures or safe internal census records. It must not authorize public release or imply that 1,571
variants are reclassified.
