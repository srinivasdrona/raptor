# RAPTOR method

> **Purpose:** one-page engineering-method landing page  
> **Authority:** this page summarizes the method; the binding operating model is
> [`docs/STRATEGY.md` Part II](docs/STRATEGY.md#strategy-part-ii), the evaluation authority is
> [`docs/EVALUATION.md`](docs/EVALUATION.md), decisions are in
> [`docs/DECISIONS.md`](docs/DECISIONS.md), and failure controls are in
> [`docs/RISK_REGISTER.md`](docs/RISK_REGISTER.md).

RAPTOR is built around one rule:

> **An artifact is done when independently checked evidence says it is done, not when an agent
> produced it or a test suite looks green.**

The method separates intent, test authorship, implementation, adversarial review, scientific
adjudication, and external authorization. Each stage produces a persistent artifact that the next
stage must independently verify.

## The build loop

```text
intent / risk / decision
          |
          v
Opus planner: task spec + acceptance contract
          |
          v
Gemini test author: RED tests from the spec, before code
          |
          v
Sonnet doer: implementation against frozen tests
          |
          v
GPT checker: rerun, inspect, attack contrary cases
          |
     CLEAN? ----- no -----> named failure -> re-specify -> repeat
          |
         yes
          v
human operator merge
          |
          v
domain oracle, prospective gate, or external approval when required
```

Model families are separated deliberately. The planner does not write production code. The doer
does not author or weaken the acceptance tests. The checker does not accept the doer's verification
report as proof. A language-model CLEAN verdict is never a substitute for molecular-geneticist
adjudication or prospective scientific validation.

## Definition-of-Done gates

| Gate | Required evidence | Failure it prevents |
|---|---|---|
| **G1 Preservation** | Frozen tests and named assertions are unchanged unless a new contract explicitly replaces them | A doer weakening the test to make code pass |
| **G2 No trace-cribbing** | Production code cannot read benchmark labels, answer keys, or held-out truth | A model reproducing the expected answer instead of solving the task |
| **G3 Non-triviality** | Tests assert a specific, non-empty signal | Hollow-green `empty == empty` checks |
| **G4 Acceptance** | The checker independently reruns mechanical and evidence-form criteria | Rubber-stamp review |
| **G5 Fail-fast** | Missing, malformed, stale, or unlicensed inputs raise typed errors | Success-shaped defaults and silent drops |
| **G6 Honest N/A** | An infeasible item names the missing input and an unblock condition | Hiding incomplete work behind a skip |
| **G7 Grounding** | Every factual claim resolves to a versioned artifact, source, identifier, and where applicable an exact span | Fabricated or circular evidence |

Any gate failure returns the unit to design. `DO-NOT-MERGE` is not overridden by assertion; the
contract must be revised and checked again.

## Evidence and authorization ladder

This is an **explanatory map**, not a new gate or authority. It maps existing controls from
[`docs/EVALUATION.md`](docs/EVALUATION.md),
[`docs/STRATEGY.md` Part II](docs/STRATEGY.md#strategy-part-ii), and the cited ADRs into one
reader-facing sequence. The authoritative wording remains in those sources.

The map prevents evidence form from being mistaken for scientific or clinical authority. Higher
levels require new evidence; they are not automatic consequences of lower levels.

| Level | What has been established | What remains prohibited | Existing authority |
|---:|---|---|---|
| **L0 Hypothesis** | A question or candidate mechanism is stated | Treating it as observed evidence | Strategy GP-1/GP-2 |
| **L1 Located** | A candidate source or dataset identifier exists | Claiming the source supports the statement | Strategy GP-9 / G7 |
| **L2 Pinned** | Version, licence, checksum, and provenance are recorded | Treating metadata as a grounded claim | Strategy GP-5/GP-9 |
| **L3 Grounded** | A primary source or direct dataset and exact supporting span are verified | Treating one observation as a classification or general mechanism | [ADR-0015](docs/DECISIONS.md#adr-0015--atlas-internal-summaries-are-context-only-and-r611q-is-the-first-phase-2-anchor), G7 |
| **L4 Reproducible artifact** | Deterministic code, hashes, schemas, and tests reproduce the record | Claiming scientific performance | Strategy G1-G6 |
| **L5 Held-out evaluation** | Frozen label-blind data measure conditional performance and failure modes | Post-hoc authorization or deployment | Evaluation Parts I-II |
| **L6 Prospective evaluation** | A preregistered unseen snapshot clears the unchanged gate | Skipping policy approval or variant-level review | [ADR-0013](docs/DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock) |
| **L7 Expert adjudication** | A qualified domain expert accepts or rejects the evidence representation | Treating review as automatic VCEP/ClinVar approval | Strategy Part II Oracle / G4 |
| **L8 External authorization** | The applicable policy, institution, or expert body authorizes an external use | Extending authority to other scopes, diseases, or clinical decisions | Strategy scope and sign-off levels |

RAPTOR's current packet and Atlas artifacts occupy different levels. The packet generator and its
external review run are reproducible, non-authoritative review scaffolding; the packet-free census
is a separate 6,618-variant aggregate. The frozen R2 evaluation is negative or not-estimable for
the binding missense scopes; its tiered interpretation is post-hoc. Prospective validation and
expert adjudication remain separate gates.

## Controls around agents and data

- **One task, one worktree, one scoped diff.** Independent work runs on separate branches and is
  merged only after review.
- **Hash-bound inputs and outputs.** Source versions, configs, policies, commits, packet cores, and
  profile envelopes are pinned so drift is detectable.
- **Label-blind scoring.** Benchmark labels and ClinVar-derived answer-key paths are structurally
  separated from production evidence generation.
- **Source roles are explicit.** Internal summaries may seed searches but cannot ground claims.
  Reviews and ClinVar may provide context; accepted mechanism claims require a primary publication
  or direct dataset with an exact span.
- **Abstention is valid.** `UNKNOWN`, `UNVERIFIED`, `NO_CALLS`, `UNDERPOWERED`, and
  `NOT_ESTIMABLE` are preserved rather than coerced to zero or failure.
- **External use needs two keys.** The operator may approve internal records; externally meaningful
  classifications or submissions require a qualified molecular geneticist or appropriate expert
  body.

## Failure modes already caught

This method has changed RAPTOR's implementation and conclusions, not merely documented them:

| Failure caught | Durable response |
|---|---|
| ClinVar-derived PP5/BP6/PS4 and comparator leakage | Direct-copy criteria banned; upstream masking and criterion-lineage audit added ([ADR-0009](docs/DECISIONS.md#adr-0009--clinvar-derived-acmg-criteria-direct-copy-banned-pp5bp6ps4-transitive-deferred-to-audit)) |
| BIAS PP3/BP4 aggregation defects and uncalibrated composite policy | Reconstruction retained for audit; automated PP3/BP4 emission disabled ([ADR-0012](docs/DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)) |
| A coarse FAIL that conflated insufficient data, policy exclusion, and performance | Independent data-sufficiency, performance, parity, coverage, and authorization axes added; post-hoc status kept non-authorizing ([ADR-0013](docs/DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)) |
| Tests that passed while constructors, fixtures, or APIs were wrong | Separate test authorship, strict-stub probes, hash oracles, and repeated checker loops |
| Raw-byte versus canonical-LF hash confusion | Hash provenance labeled by surface; configs and committed artifacts use explicit, different rules |
| Citation/source spoofing, alias laundering, path traversal, and fabricated spans | Offline catalog resolver, checked local content, exact alias ownership, and `text-char` span binding ([ADR-0016](docs/DECISIONS.md#adr-0016--deterministic-offline-citation-resolver-and-phase-2-promotion-span-verification)) |
| The original generic-platform/empty-market premise | Premise withdrawn; strategy reset to a bounded TSC vertical ([ADR-0010](docs/DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)) |

Every real failure should produce one durable rule, test, gate, or explicit limitation. The target is
not zero first attempts; it is zero tolerated recurrence.

## How to inspect RAPTOR quickly

1. Read the two public checkpoints:
   [before scoring](docs/blog/2026-07-10-before-the-first-score.md) and
   [after the rerun](docs/blog/2026-07-23-after-the-first-rerun.md).
2. Inspect [`docs/PROGRAM.md`](docs/PROGRAM.md) for current state and
   [`docs/EVALUATION.md`](docs/EVALUATION.md) for the frozen/prospective gate.
3. Read ADRs 0009, 0010, 0012, 0013, 0014, 0015, and 0016 in
   [`docs/DECISIONS.md`](docs/DECISIONS.md).
4. Inspect the committed non-identifying records in [`data/census/`](data/census/) and the packet
   and Atlas runbooks.
5. Run targeted tests from a correctly provisioned environment:

```bash
python -m pytest tests/atlas tests/packet tests/census
```

Some integration tests require external reference data or optional dependencies and intentionally
fail or skip when those preconditions are absent. A green subset is not represented as a green
full-system validation.

## Control-plane status

The core loop is enforced by convention, frozen artifacts, tests, and independent review rather
than a fully automated orchestration service. Controls are reported in four distinct states:

| Status | Controls |
|---|---|
| **Live** | Checker/doer family separation; protected acceptance tests and preservation checks; label-blind scoring with targeted forbidden-import and predictor-leakage audits; hash-bound drift detection that rejects changed registered sources, configs, and artifacts. |
| **Pending execution** | Molecular-geneticist adjudication remains pending until a named qualified reviewer evaluates the prepared evidence. |
| **Blocked outcome** | The ADR-0013 August prospective-validation contract resolved to `BLOCKED_DATA`: its exact frozen URL returned 404, no alternate URL was substituted, and no archive bytes, labels or scores were accessed. Any future attempt requires a new explicit preregistration. |
| **Planned** | A generalized trace-cribbing lint beyond the targeted audits, checker mutation probes, post-merge random audits, automated source refresh, and a fully automated orchestration service. |

“Pending execution” means a defined gate is waiting on its required actor. “Planned” means the
control itself is not implemented. A blocked outcome is retained as a result rather than relabelled
as pending, and none of these states is presented as a live release control.
