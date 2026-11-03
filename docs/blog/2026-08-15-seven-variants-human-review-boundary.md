# Seven $TSC2$ Variants Reached the Human-Review Boundary—And the Panel Still Failed

> **Status: research-only progress report — 2026-08-15.**
> RAPTOR does **not** issue authoritative variant classifications, does **not** authorize a
> VUS worklist or a ClinVar submission, and does **not** support diagnosis or treatment
> decisions. Nothing below is a clinical finding. No panel was selected. No panel was
> approved. No human reviewer has accepted any claim.

Two things happened in RAPTOR's Mechanism Atlas this month, and they point in opposite
directions.

Seven $TSC2$ variants produced evidence packages that passed every deterministic gate the
system has and stopped, exactly as designed, at the boundary where a human being has to
take over. That is the machinery working.

Separately, the formal attempt to assemble a scientifically *independent* contrast panel
returned `INFEASIBLE_PANEL`. Not "inconclusive." Not "ran out of time." The search finished,
exhaustively, and found that no admissible panel exists on the evidence currently available.

Both are true. This post explains why, and what we changed afterwards — additively, and
labelled `POST_HOC`, because the one thing you must never do is retune a rubric so that a
result you already saw looks better.

## What the Mechanism Atlas is, and what its gates do

The Mechanism Atlas records *observed mechanism evidence* about $TSC1$/$TSC2$ variants from
primary literature and direct datasets: effects on transcript and splicing, on protein
abundance and complex formation, on mTORC1 signalling, and on cell and tissue phenotype —
always bound to the experimental system in which they were measured. It is deliberately
classification-free. It does not decide whether a variant is pathogenic.

Evidence reaches the Atlas through eight gates. Gates 1–7 are deterministic and mechanical:
canonical GRCh38 identity and official replay; source resolution against a hash-pinned
catalogue with licence and lawful-access checks; from-disk content-hash recomputation;
**exact-span verification**, where a `text-char:<start>:<end>` slice of deterministically
extracted text must hash to the published value; assay and model-system context capture;
contradiction and null-result disclosure; and the classification/leakage firewall that keeps
ClinVar-derived labels out of mechanism evidence entirely.

Gate 8 is different. Gate 8 is a named, qualified human being reading the span and deciding
whether it means what the record says it means. **Gates 1–7 verify provenance and
deterministic fidelity. They do not verify biology.** Passing them earns a package the right
to be reviewed — nothing more.

## The seven variants and the eight decisions waiting at Gate 8

Seven variants currently sit at that boundary:

- $p.\mathrm{Arg611Gln}$ — the Phase 2 anchor
- $p.\mathrm{Ile723Val}$
- $p.\mathrm{Arg1743Gly}$
- $p.\mathrm{Thr509Pro}$
- $p.\mathrm{Leu916Pro}$
- $p.\mathrm{Asp1656Tyr}$
- $p.\mathrm{Arg308Trp}$

They carry **eight** claim-level human-review decisions: two for the anchor, which has two
independently verified spans, plus one for each of the six technical-cohort variants.

$R611Q$'s two verified spans:

| Source | Span locator |
|---|---|
| PMC4843954 | `text-char:20956:21353` |
| PMC11593644 | `text-char:31054:31266` |

The six technical-cohort spans:

| Variant | Source | Span locator |
|---|---|---|
| $p.\mathrm{Ile723Val}$ | PMC11593644 | `text-char:33327:33537` |
| $p.\mathrm{Arg1743Gly}$ | PMC11593644 | `text-char:39217:39353` |
| $p.\mathrm{Thr509Pro}$ | PMC11593644 | `text-char:39217:39353` |
| $p.\mathrm{Leu916Pro}$ | PMC7154745 | `text-char:40192:40583` |
| $p.\mathrm{Asp1656Tyr}$ | PMC7154745 | `text-char:39831:40011` |
| $p.\mathrm{Arg308Trp}$ | PMC7154745 | `text-char:34213:34515` |

Two details matter more than they look.

$p.\mathrm{Thr509Pro}$ and $p.\mathrm{Arg1743Gly}$ resolve to the **same** span, because the
source reports them in a joint statement. RAPTOR does not split a joint statement into two
individual magnitudes. Inventing a per-variant effect size that the source never reported is
fabrication, and the pipeline refuses to do it — so both variants carry the joint locator and
the reviewer sees exactly what the authors wrote.

$p.\mathrm{Asp1656Tyr}$ is the more instructive case. Its source-reported context is a
minigene/splicing observation. The variant is a missense change at the DNA level, but the
evidence in that source is about **splicing**, not about a protein-only mechanism. Missense
identity does not imply a protein-only mechanism, and a system that quietly re-labels a
splicing observation as a protein-function observation has laundered its own evidence. The
context travels with the statement.

**Every one of these packages passed Gates 1–7. Every one is blocked at Gate 8. The accepted
claim count is zero.** These are not classifications, not pathogenicity calls, and not
evidence directions. They are verified representations of what a cited source says, waiting
for someone qualified to read them.

## These seven are not the panel

This is the distinction most likely to be misread, so it gets its own section.

The anchor plus the six-variant cohort (`tsc2-gate-smoke-v1`, cohort hash
`99462b30…9832388`) is an **engineering repeatability** exercise. It asks: does the machinery
behave identically across diverse situations — does it resolve identity, verify spans,
capture context, disclose contradictions, and abstain when it should? It answered yes, six
times out of six, with zero earlier-gate failures.

The **formal independent-validation panel attempt** is a completely separate artifact: a
35-record candidate universe, a frozen selection protocol (v1.0.4), its registration, a
candidate-universe lock and an identity-map lock, all pinned by hash before the run. It asks
a scientific question: does the mechanism ontology generalize on *independently sourced,
assay-diverse* evidence?

Only the second question needs source independence, because only the second makes a
generalization claim. Conflating them is how a green engineering result gets quietly promoted
into a scientific one.

## Exactly why no panel exists

On 2026-08-06 the reviewed selector ran and returned `INFEASIBLE_PANEL`. The full 35-row
disposition audit is committed. The cause is specific:

- **35 records** entered. **10** identities were unresolved. **10** more were attrited as
  access- or licence-blocked. **1** was the anchor, excluded by design. That left **14**
  eligible records — none of which were selected, because no admissible combination existed.
- **Zero established source lineages.** All **37** attributable observations, and 32 of the
  35 records, carried unknown lineage and were conservatively pooled into a single
  `LG:UNKNOWN-POOL`. Lineage is established by verified mapping, never by counting distinct
  author lists, journals or PMIDs — and unknown lineage is pooled, not optimistically split.
- **The eligible evidence was narrow**: two assay kinds, one broad model-system category, and
  a dominant mTORC1 reporter readout.
- **P2 and D3 interacted, but they were not the only strict-level limitations.** A hash-bound
  post-hoc diagnostic found that removing the minimum established-source-group constraint (P2)
  alone or the assay-concentration cap (D3) alone left every level infeasible. Removing both
  was still insufficient at L0-R5. Feasible subsets appeared only at R6/R7, after the
  preregistered ladder had also relaxed C5, P1, D1, P3 and D2. This names an exact modified
  constraint set — it is *not* a relaxation proposal, not a selection, and not a panel.
- **The search completed.** All **24** fixed-size attempts (sizes 7, 6 and 5 across ladder
  levels L0–R7) terminated `INFEASIBLE_COMPLETE`, with a maximum of **714** nodes expanded
  against a **5,000,000** budget and zero relaxation steps applied.

That last point is what turns a null result into evidence. The search did not stop early. It
looked at everything and found nothing. **The shortage is in the substrate, not the
algorithm.**

## Specialist-lab dominance is not "bad evidence"

Tuberous sclerosis complex is rare. The labs that publish careful functional work on $TSC2$
missense alleles are few, and they build on each other's constructs, assays and reagents.
That is what a healthy rare-disease field looks like.

It is also why the independence constraint failed. Same-lab and same-lineage evidence can be
excellent evidence — carefully controlled, reproducible, exactly the work you want done. It
is simply **not independent replication**. Two results from one lineage do not become two
independent confirmations because they appear in two papers. The distinction is about
statistical and epistemic independence, not about quality, and treating dependent evidence as
independent is one of the most effective ways to manufacture false confidence.

So the honest reading is not "the evidence is bad." It is: *the evidence packages did not
fail; the independence claim the panel was built to support is not currently supportable.*

## The correction: an additive, versioned, post-hoc rubric

The v1.0.4 rubric could express only one thing: is a strictly independent panel feasible? It
had no way to say "these packages are fine, and the field is sparse." Collapsing those into a
single `INFEASIBLE_PANEL` is the same failure class RAPTOR already hit once, when a coarse
`FAIL` conflated insufficient data with poor performance and policy exclusion — the failure
that produced the tiered v3 re-adjudication and [ADR-0013](../DECISIONS.md#adr-0013--tiered-gate-v3-post-hoc-re-adjudication-and-prospective-validation-lock).

The response is the same shape, and it is deliberately conservative:

- **The machine result is immutable.** `INFEASIBLE_PANEL` under protocol v1.0.4 stands,
  unedited, unretracted and still published.
- **A new rubric adds a second, separately labelled field.** Under
  [`atlas-panel-rubric-v2.yaml`](../project/specs/atlas-panel-rubric-v2.yaml) the contextual
  outcome is **`EXPERT_ADJUDICATION_REQUIRED`**, with `panel_selected: false`,
  `panel_approved: false`, `expert_adjudication: PENDING`,
  `independent_validation: NOT_ESTABLISHED` and a claim ceiling of `NONE_NO_PANEL_EXISTS`.
- **`EXPERT_ADJUDICATION_REQUIRED` is a pending state, not a result.** It is not a pass, not a
  partial pass, and not a provisional panel. If no qualified expert ever adjudicates, the
  terminal published state remains `INFEASIBLE_PANEL` with no panel.
- **The whole layer is `POST_HOC`,** written nine days after the run with full knowledge of
  its outcome. On the one axis where the two rubrics genuinely differ in strength, v2 is
  *weaker*: the frozen run was prospectively registered; this interpretation was not.

The rubric reports fifteen independent axes rather than one verdict, and it defines a general
evolution workflow for any future rubric change: record the nuance first; classify the cause
(implementation defect, policy defect, data scarcity, disease-context mismatch, new evidence);
freeze the old rubric and result; version semantically; prefer aggregate or blinded evidence;
separate authorship from review; **apply symmetrically to the entire eligible universe**;
publish a side-by-side transition matrix; mark `POST_HOC`; and activate prospectively only
through a new registration. The governing rule is blunt: never tune a rubric to make one
observed result look better.

## What an expert can and cannot do

A future named, signed adjudication could reach `EXPERT_ADJUDICATED_RARE_DISEASE_PANEL`,
`PANEL_NOT_JUSTIFIED` or `MORE_EVIDENCE_REQUIRED`. Only four dimensions are contextually
adjudicable — the minimum number of independent lineages (P2), the assay-concentration cap
(D3), model-system diversity (D2), and panel balance/size — and contextualizing any of them
**lowers** the claim ceiling to scarcity-limited rare-disease research.

Nine dimensions are non-waivable by anyone: canonical identity and official replay; source
provenance and lawful access; exact-span verification; assay/model context; contradiction and
null-result disclosure; dedupe and collision accounting; complete dispositions; the
classification/leakage firewall; and immutable inputs and run records. And there is a hard
ceiling on human authority: **an expert can lower a claim, but cannot convert dependent
evidence into independent replication.** Adjudicated same-lineage evidence is still
same-lineage evidence.

Any such decision must record reviewer identity and qualifications, conflicts of interest,
scope, rationale, which dimensions were contextualized and which were explicitly not, the
resulting claim ceiling, limitations, an expiry date, re-review triggers, and signatures.
**As of today, zero such records exist.**

## What is designed but not run

Two panel products remain designs only under
[ADR-0017](../DECISIONS.md#adr-0017--dual-atlas-panel-products-a-post-result-technical-coverage-panel-separated-from-a-still-blocked-independent-validation-panel):
a **Technical Coverage Panel** (engineering; claim ceiling `ENGINEERING_PIPELINE_BEHAVIOUR`)
and an **Independent Validation Panel** (scientific; `BLOCKED_SOURCE_DIVERSITY`). Neither has
been executed, neither has membership, and no technical-panel artifact may ever satisfy an
independent-validation gate.

Separately, RAPTOR RescueScreen is a designed, research-only, downstream lane for turning
*reviewed* mechanism hypotheses into experimentally testable ones. All five of its entry gates
are currently `NOT_SATISFIED` — chiefly because Gate 8 is blocked and the accepted-claim count
is zero — so no stage is reachable. No screen has been run, no compound is named, and nothing
in this program constitutes a treatment, therapy, dose or combination claim of any kind.

## Verify it yourself

- Frozen run record:
  [`tsc2_phase2_panel_selection_run_2026-08-06.json`](../../data/atlas/tsc2_phase2_panel_selection_run_2026-08-06.json)
  — SHA-256 `5f5b0918a24fcaa737877a15e393773f20c584c531517133e9c8b7e7574cfffd`
- Rubric v2: [`atlas-panel-rubric-v2.yaml`](../project/specs/atlas-panel-rubric-v2.yaml)
  — SHA-256 `b7a642c94486fcaf7ee33639f72d8075dde183754dfc7b7e6fbcdb38d7213d05`
- Post-hoc readjudication artifact:
  [`tsc2_phase2_panel_rubric_v2_readjudication_2026-08-15.json`](../../data/atlas/tsc2_phase2_panel_rubric_v2_readjudication_2026-08-15.json)
  — self-excluding content SHA-256
  `5fad899e1ab915d9b3564d871e0ed37d355492402b08153f375e75a281287d44`
- Constraint-interaction diagnostic:
  [`tsc2_phase2_panel_constraint_diagnostic_2026-08-15.json`](../../data/atlas/tsc2_phase2_panel_constraint_diagnostic_2026-08-15.json)
  — self-excluding content SHA-256
  `32f085ccf7ee9236a5fda48e7877bd282e137cc679faf3492f70f123f94ab696`
- Decision record: [ADR-0019](../DECISIONS.md#adr-0019--versioned-atlas-interpretation-rubrics-a-scarcity-aware-post-hoc-contextual-layer-over-an-immutable-machine-result)
- Public source, span and gate manifests: [`data/atlas/runs/2026-08-03/`](../../data/atlas/runs/2026-08-03/)
  — catalogue hash `5d83d8b5e7c3c4923dc6dae038530360db47760abe8c3f86fbc26f3d5821b22e`,
  $TSC2$ pack hash `1294478c6d112f91e5719ee345d2b5be1925567ec4f4abdff50b0e092ff08927`
- Sources cited above, all CC BY 4.0: PMC4843954 (PMID 26703369, DOI 10.1002/humu.22951),
  PMC11593644 (PMID 39596632, DOI 10.3390/genes15111432), PMC7154745 (PMID 31799751,
  DOI 10.1002/humu.23963)
- Panel product designs: [`atlas-panel-products-v1.yaml`](../project/specs/atlas-panel-products-v1.yaml);
  RescueScreen design: [`structural-rescue-screen-v1.yaml`](../project/specs/structural-rescue-screen-v1.yaml)
- Method and program status: [`METHOD.md`](../../METHOD.md), [`PROGRAM.md`](../PROGRAM.md)

Article bodies are not redistributed. To reproduce a span, retrieve the cited source from its
official URL, run the documented deterministic extraction, confirm the published extracted-text
SHA-256, then verify the `text-char` slice.

---

The uncomfortable summary: RAPTOR's most interesting result this month is a negative one, and
the correct response to it was not to make it smaller. Seven variants got as far as machinery
can take them. The panel that would have made a scientific claim about them does not exist,
and saying so plainly — then adding a clearly labelled, clearly weaker, post-hoc reading
beside it rather than on top of it — is the whole method.
