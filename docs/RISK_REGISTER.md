# RAPTOR — Risk Register (Failure-Mode Analysis)

> **Status:** DRAFT v0.2 — *vertical TSC/mTOR reset* ([ADR-0010](DECISIONS.md#adr-0010--generic-platform-uniqueness-premise-falsified-vertical-tscmtor-research-evidence-strategy)) · **Owner:** @dronasrinivas (solo — see R-D5 bus-factor) · **Last updated:** 2026-07-22 (added R-A13/R-A14/R-A15, ADR-0012/ADR-0013 residue) · **Review cadence:** monthly + on any Sev-High trigger
>
> **Format:** standard risk register (ISO 31000-aligned): each risk has a *likelihood*, *impact*,
> *severity*, **leading indicator (how we detect it early)**, *preventive mitigation*, and
> *contingency (what we do if it fires)*. `STRATEGY.md` §10 is the distilled board-level summary and
> points here; `ARCHITECTURE.md` §11 holds *technical* debt only. This is the exhaustive source.
> **Category H is imported from the OpenCell program** (`srinivasdrona/opencell` dev blog +
> postmortems) — real eval-integrity/agent-execution failures already paid for once.
>
> **Authority note.** This register is the living control record. ADRs in [`DECISIONS.md`](DECISIONS.md)
> remain immutable accepted-history explanations; when likelihood, indicators, mitigation,
> contingency, or residual status changes, update this register without rewriting historical ADR bodies.

---

## 0. How to read this — and the one meta-risk

The whole product is **trust in an auditable classification**. Every failure below ultimately
degrades either *correctness* or *trust in correctness*. For a **solo, unattended, weekly** system
the deadliest meta-failure is **R-C1: it breaks or drifts silently and no one notices for weeks.**
Therefore the register is organised around **detection first** — a mitigation with no leading
indicator is treated as *not mitigated*.

**Scoring:** Likelihood/Impact ∈ {L, M, H}. **Severity** = existential (🔴), serious (🟠),
manageable (🟡). *Existential* = can kill the project or cause external harm.

### Top existential risks (the six to lose sleep over)

| # | Existential risk | Why it kills the project |
|---|---|---|
| **R-A1** | A wrong LP/LB classification reaches a family/clinician | Trust is the product; one publicised wrong call ends it. |
| **R-A2** | Validation is a mirage (benchmark overfit / circular labels / **trace-cribbing**) | "It passed" becomes meaningless; every downstream claim is unsafe. *(Concrete mechanisms in category H.)* |
| **R-C1** | Silent failure/drift in unattended runs | Solo operator finds out weeks late; stale/wrong data already emitted. |
| **R-E1** | No domain oracle is ever recruited | The differentiator (cross-linkage) is unvalidatable; even PS3 strength is unchecked. |
| **R-F1** | Built but unused / unfunded | No wedge, no sustainability → dies regardless of quality. |
| **R-G1** | Perceived/actual "AI practising medicine" | Reputational + regulatory backlash despite disclaimers. |

---

## ADR ↔ risk crosswalk (current authority index)

| Risk ID | Related ADRs | Why the linkage exists now |
|---|---|---|
| **R-A2** | ADR-0009 | The ClinVar-derived-criteria decision is the current anti-circularity / anti-answer-key boundary. |
| **R-A11** | ADR-0006 | Cross-DB fingerprinting and reproducibility limitations are explicitly deferred there. |
| **R-A12** | ADR-0010 | The vertical-reset decision withdrew the uniqueness premise and created this residual adoption/competition framing risk. |
| **R-A13** | ADR-0013 | Post-hoc / prospective-lock wording comes directly from the tiered v3 decision. |
| **R-A14** | ADR-0013 | Data-sufficiency versus failure semantics are the core reporting split ADR-0013 introduced. |
| **R-A15** | ADR-0011, ADR-0013 | Scope-authorization wording and the prospective lock jointly define the overclaim boundary. |
| **R-B2** | ADR-0007 | The arm's-length AGPL boundary preserves licensing options but keeps commercial-use diligence live. |
| **R-B6** | ADR-0007, ADR-0008 | The AGPL boundary and x64-worker placement jointly create and mitigate the annotation-host dependency. |
| **R-D1** | ADR-0003, ADR-0005 | The adversarial checker loop and separated test authorship are the primary controls against rubber-stamping. |
| **R-F3** | ADR-0010 | Competitor/obsolescence handling changed when the uniqueness premise was withdrawn. |
| **H1** | ADR-0009 | Direct-copy / comparator-dependent ClinVar criteria were audited and restricted to block answer-key leakage. |
| **H2 / H4** | ADR-0005 | Separated authorship, property-based tests, and mutation testing are the current anti-hollow-green controls. |

---

## 1. Cross-cutting detection & controls (address many risks at once)

These are **new work items** the register depends on; without them, many mitigations below are hollow.

| Control | Addresses | What it is |
|---|---|---|
| **Canary set** | R-A3, R-A6, R-B1, R-C1 | A fixed set of variants with *known* expected outputs, re-run **every** pipeline. Any drift in canary results → halt + alert. Catches silent regressions in data, scoring, or model behaviour. |
| **Heartbeat / dead-man's switch** | R-C1, R-C4 | Each weekly run emits success + summary. **No success signal by a deadline → alert the operator.** Absence is itself an alarm. |
| **Held-out benchmark split** | R-A2 | Train/dev vs **frozen held-out test**; never tune on test; report only on held-out. |
| **Source-contract tests** | R-B1 | Schema/format assertions on ClinVar/gnomAD/LitVar2/PubMed responses; fail **loudly** on upstream change, don't silently mis-parse. |
| **Hard cloud-spend cap** | R-C3 | Per-run budget ceiling in LiteLLM; abort + alert on breach. |
| **Two-key rule** | R-A1, R-E2, R-G1 | No externally-meaningful classification / ClinVar submission without **both** operator *and* qualified geneticist sign-off. |
| **Checker-integrity probe** | R-D1 | Periodically inject a known-bad change; confirm the GPT checker *catches* it. Tests the checker, not just the doer. |
| **Immutable evidence ledger + run-IDs** | R-C2, R-A11 | Event-sourced inputs; atomic publish; reproducible recompute; nothing mutates in place. |
| **Answer-key / trace-cribbing lint** | H1 | CI grep gate: **production code may not read** benchmark/label/oracle files (Rule-8 analog from OpenCell). Forbid `open/loadmat/np.load/read_csv` of any answer-key artifact inside the pipeline package. |
| **Oracle-blind cross-checks** | H1, H2 | Validation checks that **never see the label** (internal consistency, allele-frequency sanity, mass-of-evidence) — laundering the answer can't pass a check that doesn't have the answer. |
| **Non-triviality (anti-hollow-green) assertions** | H2, H4 | Every test/canary must assert a *specific expected non-zero signal*; reject "both sides empty at tolerance" passes; audit that each check actually asserts something. |
| **Assertion-lock / preservation directive** | H3 | Build-loop gate + diff review: **no pre-existing test or assertion is weakened or deleted** by the doer; the checker fails any diff that touches locked assertions. |
| **Stub/placeholder scanner + fail-fast** | H5 | CI scan for placeholder/stub values in the pipeline; fail-fast on missing input (never silently return `{}`/zeros). |
| **Rule-graduation loop** | H6–H13, R-D2/D3 | Every real failure produces a *permanent codified rule* (+ a CI lint where cheap) so the same class cannot recur. The register/rules file grows one rule per failure. |
| **Referential integrity (GP-9)** | R-A6, H13, H1 | Schema requires a resolvable `source_ref` on every evidence row/criterion/decision; a **citation resolver** rejects unresolvable PMIDs/accessions; **span-grounding** requires the verbatim supporting text; anything unreferenced ⇒ `UNVERIFIED`, non-authoritative (can't cross a threshold or be submitted). |

---

## 2. A · Scientific / validity failures — *the system produces wrong or untrustworthy science*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-A1** | Wrong LP/LB call reaches a family/clinician | M | H | 🔴 | Canary drift; reviewer disagreement rate ↑ | Two-key rule; human sign-off (STRATEGY §9); conservative thresholds; "hypothesis not verdict" labelling | Public correction protocol; retract submission; freeze external output |
| **R-A2** | Validation mirage — benchmark overfit or circular labels | M | H | 🔴 | Held-out vs dev gap widens; benchmark overlaps RAPTOR-influenced labels | Held-out split; freeze benchmark by date/source; exclude RAPTOR-touched labels (STRATEGY §7) | Re-baseline on a fresh, provenance-clean set; discount prior results |
| **R-A3** | ACMG mis-application on edge cases (PVS1 terminal exon, transcript choice, mosaicism, splice) | M | M | 🟠 | Canary edge-case variants fail; curator flags | Encode edge-case rules in `configs/acmg/*.yaml`; per-gene calibration; BIAS-2015 limits documented | Route class to manual review; suppress auto-scoring for that class |
| **R-A6** | Tier-3 LLM hallucination; citation-fidelity mistaken for claim-correctness (the "answer-key" trap) | H | H | 🔴 | Verifier reject rate; spot-audit mismatch | Deterministic citation + variant-match + source-span gate; **runtime evidence verifier ≠ build checker**; per-premise ceiling (STRATEGY §6) | Quarantine extraction; require human PS3 confirmation |
| **R-A2b** | Cross-linkage produces plausible-but-wrong mechanistic links (oracle-poverty) | H | M | 🟠 | Oracle rejects sample links | Ship as *cited hypothesis only*; pre-registered evidence grammar; reserve "discovery" for gap-map (GP-1/2) | Relabel/withdraw link; never present as validated |
| **R-A2c** | **Distribution shift** — validation set (known variants, enriched for easy null/truncating calls) is systematically *easier* than the VUS deployment set (enriched for hard missense); metrics on knowns overestimate real VUS performance | H | H | 🔴 | Missense-only held-out P/R ≪ overall P/R; class-stratified gap | **Stratify metrics by variant class**; gate on the **missense** held-out number, not overall; weight benchmark toward missense; validate on knowns before any VUS run ([EVALUATION Part I §1.1](EVALUATION.md#evaluation-validation-gate)) | Do not deploy on VUS on overall metrics alone; report per-class; expand missense labels via Oracle |
| **R-A8** | PS3 assay-strength miscalibrated (weak assay treated as strong) | M | M | 🟠 | Oracle audit of strength calls | Assay-validity rubric; strength capped without oracle sign-off | Downgrade to "supporting"; queue for expert |
| **R-A9** | Reference-data errors inherited silently (gnomAD/CADD/REVEL/ClinVar) | M | M | 🟡 | Canary; cross-source disagreement | Cross-source sanity checks; record source version | Flag variant; exclude suspect field |
| **R-A10** | Genome-build / transcript mismatch → silent wrong-variant evidence | M | H | 🟠 | Normalization mismatch counters | Normalization as first-class stage (pinned MANE + build) before scoring/matching | Halt affected variants; renormalize |
| **R-A11** | Non-reproducibility — same input, different output (LLM nondeterminism) | M | M | 🟠 | Re-run diff on fixed input | Temperature 0; pinned model/prompt versions; deterministic Tier 1/2; store provenance | Mark record non-reproducible; re-extract with pinned config |
| **R-A12** | **Absence-of-output misread as absence-of-demand or of capability** — zero indexed TSC-specific campaigns / zero VCEP ClinVar submissions read as a market opening or as "no competitor exists" (falsified-premise residue, ADR-0010) | M | M | 🟠 | Strategy claims rest on "no one else"/"they need us" with no named adopter | Treat the 2026-06-16 metric as **narrow + dated** (no *indexed TSC-specific campaign* found + unresolved institutional/adoption question); capable general platforms exist (`docs/reference/competitive-landscape-2026-07.md`); require a **named adopter** before assuming demand (R-F1) | Re-scope to "under-served vertical"; withdraw uniqueness language; validate demand with a real user |
| **R-A13** | **Post-hoc-interpretation laundering** — tiered gate v3's re-adjudication (ADR-0013) of the frozen R2 masked-holdout aggregate is misrepresented, in prose or reporting, as prospective validation or as new evidence, rather than as a re-description of the same frozen numbers | M | H | 🟠 | Doc/report language using "validated"/"passed"/"new result" for v3 without the `SUPPORTED_POSTHOC`/`PENDING_PROSPECTIVE` qualifier | `no_new_evidence_statement` embedded in the v3 record itself; v3 config kept standalone from the policy-bound `tsc2.yaml`; every doc referencing v3 must pair it with the prospective-registration lock ([EVALUATION Part I §1.3](EVALUATION.md#evaluation-v3-posthoc-prospective), [Part II §7](EVALUATION.md#evaluation-rubric-v3)) | Correct the claim in place; add explicit "post-hoc, no new evidence" caveat; audit for downstream reuse |
| **R-A14** | **Underpowered-data semantics conflated with failure** — v3's `NO_CALLS`/`UNDERPOWERED`/`NOT_ESTIMABLE` states (e.g. missense:pathogenic 51 actual/0 called; missense:benign 103 actual/9 called, below `min_count_per_class: 36`) are read as proof the predictor performs poorly, rather than as "insufficient data to estimate" | M | M | 🟡 | Language stating missense "fails" or "performs badly" instead of "not yet estimable" | Independent data-sufficiency axis in v3 (never coerced to zero); explicit `null` for undefined conditional metrics; docs must cite the actual/called counts alongside the status | Restate with the correct axis; add the underlying counts; do not extrapolate to a performance claim |
| **R-A15** | **Authorization overclaim** — a scope whose v3 evidence status is `SUPPORTED_POSTHOC` (e.g. truncating:pathogenic) or whose authorization is `PENDING_PROSPECTIVE`/`NOT_AUTHORIZED` is described, in any doc or external communication, as authorized, validated, or usable for a VUS worklist, clinical classification, or ClinVar submission | L | H | 🟠 | Any doc pairing a v3 status with "authorized"/"validated"/"worklist-ready" absent the prospective-validation PASS | Mandatory `research_use_disclaimer` ([EVALUATION Part II §5b](EVALUATION.md#evaluation-v2-scope-authorization) / [§7](EVALUATION.md#evaluation-rubric-v3)); `authorization_status` never set to `AUTHORIZED` in code or config until the prospective-registration lock (first eligible ClinVar GRCh38 archive ≥2026-08-01) PASSes | Retract the claim; reissue with correct authorization status; block any downstream worklist release |

## 3. B · Data / dependency failures — *external inputs break or bind us legally*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-B1** | Upstream schema/API change breaks pipeline silently | H | M | 🟠 | Source-contract test fails | Contract tests on every source; version-pin; fail loud | Pause pipeline; patch parser before next run |
| **R-B2** | Data-license change or non-commercial data leaks into commercial-use output | L | H | 🟠 | Licensing-matrix audit | Per-field licensing matrix; research-only vs redistributable output modes | Strip restricted fields; notify affected users |
| **R-B3** | Copyright — non-OA full text sent to cloud models | M | H | 🟠 | Full-text policy audit; source flag | Automated extraction restricted to PMC OA; non-OA → manual queue | Purge; incident review |
| **R-B4** | Freshness lag — stale synthesis launders outdated claims | M | M | 🟠 | Freshness-lag KPI breaches threshold | Designed-in re-validation loop (GP-5); freshness is a KPI | Flag stale records; prioritise re-run |
| **R-B5** | Retraction/superseded source not caught → bad evidence persists | M | M | 🟡 | Retraction-feed trigger | Retraction trigger → invalidate + recompute + audit diff | Manual sweep; posterior recompute |
| **R-B6** | Tier-1/2 annotation-host dependency — BIAS-2015/Nirvana are x64-only + AGPL, can't run on the ARM Queen; cross-machine hop couples Tier-1/2 to an x64 worker | M | M | 🟡 | Worker unreachable / annotator version drift | Run BIAS+Nirvana on a pinned x64 worker at arm's-length (ADR-0007/0008); scorer talks to a BIAS *port*; treat BIAS output as a source-contract (version-pinned, R-B1-style); v1 builds/validates the wrapping layer against BIAS fixtures so the hop isn't on the build critical path | Fail loud on port/contract drift; queue affected variants; re-run on a healthy worker |

## 4. C · Technical / operational failures — *the system breaks or can't run*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-C1** | **Silent failure/drift in unattended runs** | H | H | 🔴 | **Heartbeat missed; canary drift** | Heartbeat/dead-man's switch; canary set every run; Prefect run history + failure alert | Operator paged; last-good state retained; investigate before next publish |
| **R-C2** | State corruption / partial write (SQLite) | M | H | 🟠 | Ledger integrity check | Single-writer Queen; run-scoped staging; atomic publish; immutable ledger | Roll back staging; restore last-good snapshot |
| **R-C3** | Cost blowup (bug or paper-heavy event floods cloud) | M | M | 🟡 | Per-run spend nears cap | Hard spend cap in LiteLLM; local-first routing | Abort run; alert; investigate |
| **R-C4** | Fleet/transport failure (SSH tunnels drop, VM down, Azure 2-session cap) | M | M | 🟡 | Heartbeat; tunnel health check | Tunnel health checks; retries; local-first bypass of Azure cap | Degrade to available nodes; defer batch |
| **R-C5** | Secret leakage (keys in git/logs) | L | H | 🟠 | Pre-commit secret scan | Secrets in Queen env/secret store only; never in repo/config; log redaction | Rotate keys; purge history; incident review |
| **R-C6** | Model/provider deprecation or behaviour change | M | M | 🟡 | Canary; provider changelog | Config-driven routing (GP-6); pinned versions; fallbacks | Re-route to fallback; re-validate prompts |
| **R-C7** | **Stale/replayed promotion approval or partial git/GitHub transaction creates the wrong or duplicate proposal** | M | H | 🟠 | Receipt/base/hash mismatch; duplicate branch/PR; transaction journal stops between branch and PR | Signed closed receipt bound to candidate/source/baseline/policy and exact V2-S2/V2-S3 hashes; maximum 24-hour validity; create-only deterministic ref; receipt-scoped saga and exact idempotent replay | Freeze the proposal; do not rebase or repair; inspect the retained draft/branch; require a fresh full cycle for any changed input |

## 5. D · Process / governance failures — *how it's built and decided*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-D1** | Checker rubber-stamps (loop not actually adversarial) or loop skipped under time pressure | M | H | 🟠 | Checker-integrity probe fails; commits without verdict | Checker ≠ doer family (ADR-0003); integrity probe; written spec+verdict required | Halt loop; re-review backlog; strengthen gate |
| **R-D2** | Decision drift — scope/strategy changes with no ADR; docs diverge from reality | H | M | 🟠 | Doc-drift review finds mismatch | ADR required for any §5/§9 change; monthly consistency pass; rubber-duck at milestones | Reconcile via superseding ADR; re-sync docs |
| **R-D3** | Documentation rot / internal contradiction | H | M | 🟡 | Milestone doc review | Rubber-duck/checker pass on docs each milestone (done 2026-07-08) | Fix + re-review |
| **R-D4** | Context loss across sessions/compactions | M | M | 🟡 | Re-litigated decisions reappear | Docs + ADRs + config as durable source of truth; preserve session artifacts | Rebuild context from docs, not memory |
| **R-D5** | **Bus factor — one operator; illness/burnout/job change** | M | H | 🔴 | Cadence slips; long inactivity | Everything in git + docs + config so project is *resumable by another*; sessions preserved | Documented handoff; graceful pause, not silent death |
| **R-D6** | Scope creep — building the gated mTOR extension before the measurable half is proven (violates GP-2/GP-13) | M | M | 🟠 | Phase-gate check | Hard phase gates (STRATEGY §7); Tier-1/2 proven before Tier-3 trusted; oracle-first gate for Phase 3 | Re-sequence; shelve premature work |
| **R-D7** | **Vertical-scope creep / vertical-washing** — "all things TSC/mTOR" re-inflates the frozen horizontal scope; generic ambition relabelled as "TSC" (Slot-3 failure mode 1) | M | H | 🟠 | A feature lacks a named user / artifact / validator / falsifier / why-not-generic; >1 mTOR condition opened at once | **GP-13** gate on every feature; mTOR extensions **one at a time**; §9 out-of-scope list; ADR required to widen scope | Reject/park the feature; re-derive scope from GP-13; superseding ADR only if scope truly must change |
| **R-D8** | **Proposal automation is mistaken for approval or exceeds its authority by touching protected refs/paths, changing PR readiness, or merging** | L | H | 🟠 | Main/protected diff; non-draft PR; auto-merge request; route or rollback side effect | Separate post-V2 ADR/spec; exact path/ref allowlists; draft-only GitHub adapter; no ready/approve/merge/branch-protection operations; CI + independent checker | Revoke the gate credential; freeze/close proposal manually; audit refs and protected files; restore only through reviewed git history |

## 6. E · Human / domain-expertise failures

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-E1** | **No domain oracle ever recruited** | M | H | 🔴 | Phase-3 gate blocked; no candidate by milestone | Oracle-first gate (GP-3): Phase 3 cannot start without one; begin recruitment early | **Graceful degradation:** ship as TSC evidence engine only (narrow version still valuable); shelve cross-linkage |
| **R-E2** | Operator-as-oracle overreach (non-biologist makes calls beyond competence) | M | H | 🟠 | Oracle audit finds errors | Two-key rule; codified criteria only; explicit "not a biologist" boundary | Restrict operator authority to internal records |
| **R-E3** | Expert disagrees at the *premise* level (rejects the evidence grammar) | M | M | 🟠 | Oracle review of grammar | Pre-register grammar *with* the geneticist before building the layer | Revise grammar; delay layer until agreed |
| **R-E4** | **Expert-oracle bottleneck** — expert review is the throughput limit for candidate packets/atlas; the whole vertical is rate-limited by scarce expert time | H | M | 🟠 | Review backlog grows; packets emitted ≫ packets reviewed | Rank for highest expert-value-per-hour; batch/triage; recruit the oracle early (GP-3); success measured in **reviewed** packets, not emitted ones (STRATEGY §8) | Narrow to the highest-yield stratum; defer low-value packets; add reviewers |

## 7. F · Adoption / sustainability / competitive failures — *even if it works, it dies*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-F1** | **Built but unused / unfunded** | M | H | 🔴 | No named first users; no funding path | Name a wedge (first 10 users); TSC VCEP triage as concrete hook; sustainability answer by Phase 4 | Pivot to the one adopting user segment; reduce scope to what's used |
| **R-F2** | Sustainability — public tier has no funding model | M | H | 🟠 | Cost > runway | Constrain architecture for near-$0 ops now; explicit Phase-4 funding answer | Narrow to self-funding core; pause public tier |
| **R-F3** | Competitor/obsolescence — a funded team ships a TSC-capable product first, or the TSC VCEP suddenly activates | M | M | 🟠 | Landscape monitor (the named vendors; PubMed/ClinVar/GitHub) | Uniqueness premise already **withdrawn** (ADR-0010); differentiate on **open benchmark + auditability + freshness**, not on being first/only; monitor `docs/reference/competitive-landscape-2026-07.md` | Reposition as the auditable/continuous TSC layer; collaborate; do **not** abandon TSC assets (competitor-overreaction, Slot-3 failure mode 3) |
| **R-F4** | **Commoditized generic engine** — a funded generic variant-interpretation platform commoditizes the reused ACMG/LLM layer | M | M | 🟠 | A vendor offers the generic layer cheaper/better than RAPTOR could build | **Reuse/buy** the generic engine (GP-4), don't rebuild it; keep the moat in the **TSC-vertical evidence/atlas**, not generic methodology | Swap in the commodity engine behind the vertical; re-anchor value on TSC evidence |
| **R-F5** | **Vendor substitution** — a vendor ships a TSC-specific vertical that substitutes RAPTOR outright | L | H | 🟠 | A competitor announces a TSC-specific evidence/curation product | Move first on the open TSC benchmark + auditability + freshness; build curator relationships; stay collaboration-ready | Collaborate/integrate; contribute the open benchmark; narrow to the still-unserved niche |
| **R-F6** | **Community/adoption dependency** — the vertical needs a TSC curator/research community that may not engage | M | H | 🟠 | No curator/researcher trials packets or the atlas | Name a wedge; make packets low-friction and expert-reviewable; sustainability answer (Phase 4) | Reduce scope to the one engaged user segment; direct outreach |

## 8. G · Trust / legal / ethical failures — *the trust that is the product*

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **R-G1** | Perceived/actual "AI practising medicine" → backlash/regulatory | M | H | 🔴 | Framing feedback; misuse reports | Hard scope disclaimers (STRATEGY §9); "enabler not decision-support"; no prescribing language; human sign-off | Legal review; tighten framing; restrict access |
| **R-G2** | Misuse — a hypothesis treated as a clinical decision → downstream harm/liability | M | H | 🟠 | Misuse report; access pattern | Explicit ceilings on every output; "cited hypothesis" labelling; not patient-facing | Access controls; usage terms; incident response |
| **R-G3** | Regulatory reclassification as SaMD despite disclaimers | L | H | 🟠 | Regulatory guidance shifts | Keep out-of-scope boundary bright (§9); document intended use; no clinical claims | Legal counsel; adjust scope/features |
| **R-G4** | **Privacy / human-subjects** — patient-level, lab-private, or controlled-access data enters RAPTOR, or any such data is sent to a cloud model | L | H | 🟠 | Data-source audit; ingest allowlist | **GP-10**: public-data-only; any exception is governed (consent/IRB/DUA) with a record; controlled/private data never sent to third-party models | Purge; incident review; notify data owner |
| **R-G5** | **False authority from polished non-authoritative output** — eval-only candidate packets/atlas *look* authoritative and get treated as classifications (Slot-3 failure mode 2) | M | H | 🟠 | Downstream use of a packet as a verdict; missing non-authoritative labelling | Non-authoritative/eval-only labelling on every candidate direction; no volume/throughput headline (STRATEGY §8); human sign-off before any external classification (§9); "candidate direction ≠ (re)classification" | Withdraw/relabel the output; add ceilings; incident review (links R-A6, H4, H13) |

---

## 8.5 H · Eval-integrity & agent-execution failures — *imported from OpenCell (already paid for once)*

> Source: `srinivasdrona/opencell` dev blog (esp. 2026-06-01 "seven rules… rule eight",
> 2026-06-14, 2026-06-24) + `plan.md` ("hollow green" hunts). These are the failures a
> planner/test-author/doer/checker loop over an oracle actually hits. **H1 is the concrete mechanism behind the
> R-A2 existential.**
>
> **Applicability audit (GP-8 — not imported wholesale):** these were screened for RAPTOR-fit, not
> copied because OpenCell had them.
> - **Genuinely product-relevant, and some *more* so for RAPTOR than OpenCell:** H1 (RAPTOR's
>   benchmark labels are an on-disk answer key that a code path can echo), **H6** and **H7** (RAPTOR
>   *mandates* config-driven ACMG weights/thresholds per GP-6 — that config *is* the grader, so a
>   wrong or silently-renamed key mis-scores everything), H2, H5, H11.
> - **Real but build-loop (not product) risks** — they hit the agentic loop, cross-ref
>   [STRATEGY Part II §0](STRATEGY.md#operating-model-purpose): H3, H9, H10, H12.
> - **Lower value:** H4, H8 (minor severity here); **H13 is a facet of R-A6**, kept only as a pointer,
>   not a distinct risk.

| ID | Failure mode | L | I | Sev | Leading indicator | Preventive mitigation | Contingency |
|---|---|---|---|---|---|---|---|
| **H1** | **Trace-cribbing / oracle leakage** — the pipeline reads the benchmark/label answer into the production path so validation passes without real computation ("green by reading the answer out of the oracle file") | M | H | 🔴 | Answer-key lint hit; oracle-blind check fails while label-check passes | Answer-key/trace-cribbing lint (Rule-8 analog); oracle-blind cross-checks; keep answer keys physically out of the pipeline's read scope | Quarantine result; remove leak; re-run oracle-blind; graduate a rule |
| **H2** | **Hollow / vacuous green** — a check passes because both sides are empty/trivial at tolerance, or a schema level is never actually validated | M | M | 🟠 | Non-triviality assertion fails; "assert-something" coverage | Anti-hollow-green assertions; calibrate tolerances to the smallest meaningful signal | Rebuild the check to assert a real signal |
| **H3** | **Silent assertion weakening/deletion by the doer** — the builder loosens or deletes the very tests that would fail | M | H | 🟠 | Diff touches locked assertions; preservation gate | Assertion-lock / preservation directive; checker gate "no pre-existing assertion weakened/deleted" | Revert; re-run with assertions locked |
| **H4** | **Unbacked / aspirational green** — status marked PASS with no test/implementation behind it; caveat annotations read past by humans *and* agents | H | M | 🟠 | Green with no linked reproducible artifact | Every green cites a commit + test-id; scoreboard audit; no "(annotation)" greens | Demote to UNVALIDATED; reconcile board |
| **H5** | **Silent placeholder/stub persists** — a placeholder value lives in the real pipeline undetected (OpenCell: 22 days) | M | M | 🟠 | Placeholder scanner; fail-fast triggers | Stub scanner; fail-fast on missing input; no silent `{}`/zeros | Replace; audit history for contaminated outputs |
| **H6** | **Wrong grader/rubric** — the eval criteria themselves are wrong; the score improves because the grader changed, not the system | M | H | 🟠 | Score jump correlates with a rubric edit, not a system change | Version + review the rubric; rubric changes are logged decisions; report "system improved" vs "grader changed" separately | Re-score prior results under the corrected rubric |
| **H7** | **Config/string drift silently mutes a step** — one renamed key/string disables a criterion, undetected because tests still pass at tolerance | M | M | 🟠 | Strict config-schema validation; per-criterion canary | Fail on unknown/renamed config keys; canary that would catch a muted criterion | Fix key; re-run affected variants |
| **H8** | **Successful-looking deferral / lazy N/A** — hard cases dodged by claiming "insufficient evidence" | M | M | 🟡 | N/A rate rises; N/A without a specific missing-input citation | N/A must name the specific missing observable + what would unblock it (Gate-6 analog) | Re-audit the N/A backlog |
| **H9** | **Delegation dies with no output / over-broad task fails** — a sub-agent exits at token cap with zero commits; a combined prompt fails where split prompts succeed | H | M | 🟠 | Zero-commit exit; token-cap death | Narrow task scope; require written spec + verdict; detect zero-commit runs; disable slow PreToolUse hooks | Decompose into narrower tasks and re-fire |
| **H10** | **Guardrail silently omitted from a run** — the standard prefix/gate stops being applied to some tasks (OpenCell: slot-1 dropped from L2 prompts) | M | M | 🟠 | Prompt-composition checklist; missing INTENT/VERIFICATION block | Compose every task from mandatory slots; checklist that guardrails are present | Re-run under full composition |
| **H11** | **LLM checker cosplaying as domain authority** — the model's confident domain verdict is trusted as expert validation ("AI panels cosplaying as scientists") | M | H | 🟠 | Checker asserts domain *truth* beyond form/consistency | Checker validates form/consistency/spec-conformance only; domain truth needs the human oracle (GP-3) | Route domain claims to the oracle |
| **H12** | **Agreement-mode sycophancy** — the agent agrees with the operator's chosen framing instead of stress-testing it | M | M | 🟡 | Reviews only ever support the chosen path | Adversarial critique arm; require the checker to argue the inverse; *"specificity without structured doubt is worse"* (OpenCell Gold arm scored 0.0) | Re-review adversarially |
| **H13** | **Unverified confidence / fabricated numbers as fact** *(facet of R-A6 — pointer, not a distinct risk)* | M | M | 🟡 | Unlabeled quantitative claim | VERIFIED/UNVERIFIED labelling; "I don't know" is allowed; citation required | Strip or verify the claim |

---

- **Highest residual risk today:** R-E1 (no oracle), R-C1 (silent failure), and **H1 (trace-cribbing)** —
  all currently *unmitigated in implementation* (controls in §1 are planned, not built). Until §1
  controls exist, treat every automated output — **and every green** — as provisional.
- **Review cadence:** monthly, and immediately on any 🔴 trigger. Each review updates likelihood,
  status, and whether the §1 control actually exists yet.
- **Status legend:** *Open* (no mitigation built), *Mitigating* (control in progress), *Controlled*
  (leading indicator live + mitigation in place), *Accepted* (residual risk consciously accepted).
  All rows are **Open** at v0.1 until the §1 controls ship.

## 10. Explicitly out of scope for this register

Operator personal/financial/career risk (e.g., leaving a job to pursue RAPTOR) is a *personal*
decision, not a project risk; only its durable project footprint (R-D5 bus factor, R-F2
sustainability) is tracked here.
