# After the First Rerun: What the Frozen Masked Result Did—and Did Not—Show

> **Status: research-only progress report — 2026-07-23.**
> This is a follow-up to [*Before the First Score*](2026-07-10-before-the-first-score.md).
> RAPTOR still does **not** issue authoritative variant classifications, does **not**
> authorize a VUS worklist, and does **not** support diagnosis or treatment decisions.

The main lesson since July 10 is not that RAPTOR "worked." It is that the repo's
evidence discipline did what it was supposed to do: when the production-faithful masked
rerun could not support a broad claim, the system mostly **abstained**, the binding
missense gate stayed negative, and the public story had to get narrower rather than
broader.

That is disappointing. It is also the point of having a gate.

## What was unknown on July 10

In the July 10 pre-results post, the held-out exam had been prepared but not yet taken:
there was **no held-out precision/recall, no gate verdict, and no VUS run result to
report** ([first post](2026-07-10-before-the-first-score.md); [evaluation gate](../EVALUATION.md#evaluation-validation-gate)).

Since then, the repository gained three things:

1. a **production-faithful masked rerun** under the now-approved
   [`disabled_manual`](../DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)
   PP3/BP4 mode;
2. an **additive, post-hoc re-description** of that same frozen result under
   [ADR-0013](../DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock);
3. corrected packet-generation and a bounded **Mechanism Atlas Phase 1** code path.

What it still does **not** have is a full-spectrum VUS result backed by prospective evidence.

## The rerun was faithful to the approved policy—and that matters more than a prettier score

The key decision in [ADR-0012](../DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)
was to approve `disabled_manual`: PP3/BP4 remain part of the ACMG vocabulary and the
BIAS lineage model, but their **automated emission and scoring are disabled** for the
current masked rerun and packet direction logic.

That gave RAPTOR a narrower but cleaner question: what does the held-out benchmark show
under the policy that is actually approved today, rather than under a more permissive
predictor setup that still had unresolved lineage and transportability concerns
([ADR-0012](../DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun),
[program status](../PROGRAM.md),
[R2 aggregate](../../data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json)).

The frozen R2 record shows:

- **2,577** held-out rows preserved from the frozen benchmark
  ([benchmark stats](../../data/benchmark/tsc_clinvar_2026-07-07_stats.json));
- **2,577/2,577** identities removed by the mask, with **zero survivors**;
- **zero scored PP3/BP4 calls** under the approved `disabled_manual` mode; and
- a coarse missense-gate outcome that remained **negative**.

That is **not** a successful classification result. It is a faithful measurement of a
more conservative policy.

## ADR-0013 corrected the description, not the result

After R2, the repository added [ADR-0013](../DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)
and the corresponding
[tiered readjudication record](../../data/census/tsc_tiered_readjudication_2026-07-21.json).
The important methodological change is separation: **run integrity** is no longer
collapsed into **data sufficiency**, **conditional performance**, **policy parity**,
**coverage**, or **authorization**.

Just as important: this was a **post-hoc semantic correction only**. It did **not**
rerun scoring, change thresholds, read new labels, or create new evidence
([evaluation Part I §1.3](../EVALUATION.md#evaluation-v3-posthoc-prospective),
[evaluation Part II §7](../EVALUATION.md#evaluation-rubric-v3)).

Here is the current readout of the frozen R2 numbers:

| Scope | Frozen status now | Why it still does not become a go-ahead |
|---|---|---|
| Missense pathogenic | `NO_CALLS` / `NOT_ESTIMABLE` | 51 actual examples, 0 automated calls; PM1 parity remains blocked for this scope |
| Missense benign | `UNDERPOWERED` / `NOT_ESTIMABLE` | 103 actual examples, 9 calls; too few called examples for the powered floor |
| Truncating pathogenic | conditional performance `MET`; evidence `SUPPORTED_POSTHOC`; authorization `PENDING_PROSPECTIVE` | This is a post-hoc description of the frozen run, not a prospective validation |
| Full spectrum | `NOT_VALIDATED` / `NOT_AUTHORIZED` | No full-spectrum VUS release is unlocked by the v3 interpretation |

The prospective lock is explicit and narrow: the **next real validation** for any v3
scope must use the **first eligible NCBI ClinVar GRCh38 monthly archive dated on or
after 2026-08-01**, frozen before labels or scoring
([ADR-0013](../DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock),
[evaluation Part II §7](../EVALUATION.md#evaluation-rubric-v3)). That is a
pre-registration boundary, not a predicted outcome.

## The corrected 6,618-VUS census got smaller—and more honest

The current source of record for the all-VUS census is
[`tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json`](../../data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json).
It reports **internal review strata only**, not classifications
([census README](../../data/census/README.md),
[program status](../PROGRAM.md)).

| Census stratum | Current `disabled_manual` count | Historical PP3/BP4-active comparator |
|---|---:|---:|
| candidate-LP review | 157 | 238 |
| candidate-LB review | 7 | 1,333 |
| unresolved | 6,424 | 5,017 |
| manual | 30 | 30 |

The benign-side collapse is the most striking change. In the historical
PP3/BP4-active artifact, **1,222 of 1,333** candidate-LB directions came from one exact
pattern: **`BP4 Strong + PM2 Supporting`**
([historical stats](../../data/census/tsc_vus_clinvar_2026-07-07_stats.json)).

That does **not** prove a single policy switch explains every downstream difference. It
does show, in the current reconciled artifacts, how heavily the earlier benign-direction
counts depended on a PP3/BP4-active policy that is no longer the approved automated mode.

## Corrected review packets now exist as scaffolding, not as a release

The packet layer was corrected to match the current census rather than the older candidate
subset. The runbook and spec now target:

- **6,618** full operator packets across all four census strata;
- **blinded first-pass views** for external review;
- a **164-row priority subset** equal to **157 + 7**;
- and a deterministic **eight-case, hash-only Discovery sample**
  ([runbook](../reference/corrected-review-packets-runbook.md),
  [packet spec](../project/specs/corrected-review-packets-2026-07.yaml),
  [builder script](../../scripts/build_corrected_review_packets.py)).

Every candidate direction remains null for the same reason:

- `candidate_direction = null`
- `null_reason = production_policy_unapproved`
- `review_state = POLICY_BLOCKED`

Those packets are **evidence-review scaffolding**, not a worklist release, not a
classification batch, and not a substitute for expert adjudication
([runbook](../reference/corrected-review-packets-runbook.md),
[packet universe code](../../src/raptor/packet/corrected_universe.py),
[packet tests](../../tests/packet/test_corrected_real_data_integration.py)).

The full packet identities and artifacts are intentionally **not** committed. Public
writing should therefore point to the runbook, code path, and aggregate facts—not to local
external directories or raw variant identities.

## Mechanism Atlas Phase 1 merged—but it is intentionally synthetic

Another track did move forward: **Mechanism Atlas Phase 1** is now merged on current
`main` (merge `9709ec6`; follow-up status record at `1134c2e`). The repository history,
the project log, and the code all agree on the shape of that phase:

- a **generic, condition-agnostic core** in [`src/raptor/atlas/`](../../src/raptor/atlas/), split from disease-specific policy so reusable code does not hardcode TSC2 or mTOR assumptions while the scientific pilot stays TSC2-only;
- exactly one versioned **TSC2 disease pack** at
  [`configs/atlas/packs/tsc2/pack.yaml`](../../configs/atlas/packs/tsc2/pack.yaml);
- pack-bound hashes, exact source-span ownership, static import and classification-leakage
  guards, and eight deterministic promotion gates;
- optional, out-of-process **Discovery templates** under
  [`configs/atlas/discovery/`](../../configs/atlas/discovery/);
- and a project-log status recorded as **GPT-5.4-clean**, alongside the merged
  [`tests/atlas/`](../../tests/atlas/) Phase 1 suite, which currently runs **35 passing tests**
  ([ADR-0014](../DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary),
  [Atlas runbook](../project/atlas/ATLAS_RUNBOOK.md),
  [starter spec](../project/specs/mechanism-atlas-starter.yaml)).

What Phase 1 does **not** contain is just as important:

- **no real verified mechanism claims**;
- **no real grounding spans**;
- **no R611Q admission or conclusion**;
- **no second-disease support**;
- **no Phase 2 primary-source content yet**; and
- **no basis for saying the Atlas classifies VUS**.

That boundary is deliberate. The Atlas is infrastructure first, claim-making later
([Atlas runbook](../project/atlas/ATLAS_RUNBOOK.md),
[pack file](../../configs/atlas/packs/tsc2/pack.yaml),
[architecture boundary](../ARCHITECTURE.md)).

## Where Discovery fits

Discovery is being used here as an **optional research/orchestration lane**, not as the
deterministic source of truth. Its role is bounded to things like Bookshelf-backed
literature organization and out-of-process candidate import templates
([architecture §6b](../ARCHITECTURE.md),
[task graph](../../configs/atlas/discovery/task_graph.json)).

Any Discovery output stays **untrusted** until RAPTOR re-checks the identity, citations,
spans, ontology fit, conflict state, and classification leakage, and then receives named
human/oracle span review
([promotion code](../../src/raptor/atlas/promote.py),
[guards](../../src/raptor/atlas/guards.py)).

That means a Discovery failure—or a rejected Discovery candidate—cannot mutate an accepted
profile. It also means the separate private packet-auditor/contribution experiment is
still **pending**, not completed.

## Honest next steps

The next steps are narrower than the earlier pre-results roadmap, but more grounded:

1. **Recruit the right molecular geneticist and finalize the review protocol.** The packet
   machinery is only useful if expert adjudication actually happens
   ([strategy GP-3 and scope](../STRATEGY.md),
   [program priorities](../PROGRAM.md)).
2. **Run expert review on the corrected packets.** The 164-row priority subset exists for
   that purpose; it is not self-justifying evidence.
3. **Move Atlas Phase 2 into primary-source and citation-span resolution.** Then run a
   bounded native-vs-Discovery comparison on that grounded material, rather than assuming
   the orchestration lane helps by default
   ([Atlas runbook](../project/atlas/ATLAS_RUNBOOK.md),
   [Discovery context manifest](../../configs/atlas/discovery/context_manifest.json)).
4. **Execute the locked prospective gate on the first eligible ClinVar GRCh38 archive on or
   after 2026-08-01.** No substitute should be chosen because it looks favorable.
5. **Engage TSC Alliance / VCEP channels after, or alongside, the appropriate expert route.**
   That is a relationship and review problem, not a timeline to fabricate.

## Meta-learning: code reuse is not portability evidence

The most useful strategic correction from this month is simple: **reusing pipeline code is
not the same as proving condition portability**.

If RAPTOR ever expands beyond TSC, it cannot be by hardcoding another disease into the
core or by calling the pipeline "generic" because the modules look reusable. The repository
now makes the opposite commitment in [ADR-0014](../DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary):
condition expansion has to happen through a **versioned disease pack** and then through a
later, measured portability experiment.

No second disease is selected or supported today.

## What exists / what does not

| What exists now | What does not exist now |
|---|---|
| Frozen `disabled_manual` R2 rerun over 2,577 held-out rows | A full-spectrum VUS release backed by prospective evidence |
| Post-hoc tiered v3 interpretation of that same frozen aggregate | Any full-spectrum VUS authorization |
| A corrected 6,618-row internal review census | A non-null production candidate-direction policy |
| Corrected review-packet machinery for all 6,618 rows | A public worklist release |
| A 164-row priority subset for expert review | Expert-reviewed packet outcomes in the repository |
| Mechanism Atlas Phase 1 core + one TSC2 pack + Discovery templates | Real Atlas claims, spans, or R611Q conclusions |
| A design boundary for later portability testing | A selected or supported second disease |

## Direct repository links

**Core docs**

- [Strategy](../STRATEGY.md)
- [Evaluation](../EVALUATION.md)
- [Program status](../PROGRAM.md)
- [Architecture](../ARCHITECTURE.md)
- [Risk register](../RISK_REGISTER.md)
- [ADR-0012](../DECISIONS.md#adr-0012--pp3bp4-automated-emission-disabled-for-the-current-masked-rerun)
- [ADR-0013](../DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock)
- [ADR-0014](../DECISIONS.md#adr-0014--generic-mechanism-atlas-core-with-a-versioned-disease-pack-boundary)

**Rerun and census artifacts**

- [Frozen benchmark stats](../../data/benchmark/tsc_clinvar_2026-07-07_stats.json)
- [R2 masked rerun aggregate](../../data/census/tsc_masked_holdout_gate_disabled_manual_2026-07-21.json)
- [Tiered v3 readjudication](../../data/census/tsc_tiered_readjudication_2026-07-21.json)
- [Current disabled-manual VUS census](../../data/census/tsc_vus_clinvar_2026-07-07_disabled_manual_stats.json)
- [Historical PP3/BP4-active comparator](../../data/census/tsc_vus_clinvar_2026-07-07_stats.json)
- [Census artifact guide](../../data/census/README.md)

**Packet path**

- [Corrected packet runbook](../reference/corrected-review-packets-runbook.md)
- [Corrected packet spec](../project/specs/corrected-review-packets-2026-07.yaml)
- [Packet builder script](../../scripts/build_corrected_review_packets.py)
- [Packet universe implementation](../../src/raptor/packet/corrected_universe.py)
- [Packet validation tests](../../tests/packet/test_corrected_real_data_integration.py)

**Atlas path**

- [Atlas runbook](../project/atlas/ATLAS_RUNBOOK.md)
- [Atlas starter spec](../project/specs/mechanism-atlas-starter.yaml)
- [Atlas core](../../src/raptor/atlas/)
- [TSC2 disease pack](../../configs/atlas/packs/tsc2/pack.yaml)
- [Discovery templates](../../configs/atlas/discovery/)
- [Atlas tests](../../tests/atlas/)
