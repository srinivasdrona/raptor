# RAPTOR — Operating Model (the build loop)

> **Status:** DRAFT v0.1 · **Owner:** @sdrona_microsoft · **Last updated:** 2026-07-08 · **Review cadence:** monthly + rule-graduation on any new failure class
>
> **Format:** recognized building blocks, not a bespoke invention — **RACI** (responsibility
> assignment), Scrum **Definition of Ready / Definition of Done** (the hand-off gates), the
> **design→build→review→eval** agentic loop, and the **three-slot prompt architecture** proven in the
> operator's OpenCell program (`srinivasdrona/opencell`, dev blog 2026-06-01).

---

## 0. Purpose & scope

This doc governs **how RAPTOR is built** (development-time process). It is *not* how RAPTOR runs —
that is `ARCHITECTURE.md`. It operationalizes **ADR-0003** (planner/doer/checker) and is the
mechanism behind the build-loop risks in `RISK_REGISTER.md` category H (H1, H3, H4, H9, H10, H11, H12).

**Binding sections:** §2 (roles), §4 (gates). Changing either is a process change → log in
`DECISIONS.md`. **Governing principles: GP-8** — a task is done when the *evidence* says so, never
because it was asked for or looks green; **GP-9** — no execution without a referenced artifact
(every task carries a `motivating_reference`; every claim resolves to a source, or is `UNVERIFIED`).

---

## 1. The loop

A **unit of work** = one task: a vertical slice, one bug-class fix, or one doc. Each flows:

```
   ┌────────── design ──────────┐
   │ Planner (Opus) writes a    │
   │ Task Spec + acceptance     │
   │ criteria (Definition of    │
   │ Ready)                     │
   └──────────────┬─────────────┘
                  ▼
   ┌────────── build ───────────┐
   │ Doer (Sonnet 5) implements │
   │ against the spec; emits a  │
   │ VERIFICATION block         │
   └──────────────┬─────────────┘
                  ▼
   ┌──── review / eval ─────────┐        DO-NOT-MERGE / WITH-CHANGES
   │ Checker (GPT) runs the     │──────────────┐
   │ gates (Definition of Done) │              │ back to design with the
   └──────────────┬─────────────┘              │ named failure mode
                  │ CLEAN                       ▼
                  ▼                     (re-spec, don't patch blind)
        Operator merges + (if externally meaningful) Oracle sign-off
```

**Entry to a stage requires the prior stage's artifact.** No silent hand-offs (a spec, a
VERIFICATION block, and a verdict are all written and persisted).

## 2. Roles, model assignment & RACI *(binding)*

| Role | Model / who | Owns |
|---|---|---|
| **Planner** | Claude **Opus** | Decompose; write Task Spec + the acceptance-test *contract* (which ACs/invariants); long-range reasoning. **No production code, no test code** — stays context-clean. |
| **Test-author** | **Gemini** (3.x) | Turn the spec's ACs into executable, assertion-specific tests **from the spec only (never sees the doer's code)**. Delegated/detached so planner context stays clean. |
| **Doer** | Claude **Sonnet 5** | Implement against the spec to pass the pre-authored tests; may *add* but not weaken them; own the change end-to-end; emit VERIFICATION. |
| **Checker** | **GPT (5.x)** | Adversarially run the gates; re-run independently; pass or return with a *named* failure mode. |
| **Operator** | @sdrona (human) | Accountable for the whole loop; merges; approves internal records. |
| **Oracle** | molecular geneticist (GP-3) | Domain-truth sign-off for any externally-meaningful output. |

**RACI per stage** (R=responsible, A=accountable, C=consulted, I=informed):

| Stage | Planner | Doer | Checker | Operator | Oracle |
|---|---|---|---|---|---|
| Design | **R** | C | C | **A** | C (domain tasks) |
| Build | C | **R** | I | **A** | – |
| Review/eval | I | C | **R** | **A** | C (domain tasks) |
| Merge / external sign-off | I | I | C | **R** | **A** (external only) |

**Hard rules**
1. **Checker family ≠ doer family** — adversarial review, not self-review (R-D1). GPT checks Sonnet's work; never Sonnet checks Sonnet.
2. **Test-author family ≠ doer family** — the tests must not share the code's blind spots (H2/H4 confirmation bias). Sonnet builds; **Gemini writes the tests**; GPT checks. Four families (Opus/Gemini/Sonnet/GPT) = maximal independence.
3. **The test-author writes from the spec only and never sees the doer's implementation** — tests encode the *requirement*, not the code.
4. Model *roles* are fixed; specific *versions* are config (GP-6), not hardcoded.
3. The **checker validates form, consistency, spec-conformance, and evidence — not domain truth.** Domain truth needs the Oracle (H11); acceptance criteria are typed accordingly (§3.1, §4 G4).

### 2.1 Escalation & disagreement

- **DO-NOT-MERGE is not operator-overridable** without a re-spec (a new Task Spec addressing the named failure mode).
- **Process disputes** (checker vs operator): a second checker instance adjudicates; the override rationale is logged in the work record.
- **Domain disputes** are resolved by the **Oracle**, never by the operator or an LLM (H11).
- **Contested oracle call:** if the operator or checker finds an artifact/evidence gap in an Oracle decision, it is escalated to a **second oracle** or labelled `UNVERIFIED`. The Oracle owns *domain truth*, but GP-9 still applies — "the expert said so" without a resolvable basis is UNVERIFIED, not authoritative.
- **Oracle unavailable:** any task carrying a `domain-truth` acceptance criterion is **blocked or labelled `UNVERIFIED`** and cannot be CLEAN (ties to STRATEGY graceful-degradation, R-E1).

## 3. Hand-off contracts

### 3.1 Task Spec — Planner → Doer *(Definition of Ready)*

```yaml
task_id:            # kebab-case, stable
goal:               # one sentence, testable
motivating_reference: # the ADR / STRATEGY §/ RISK id this task serves — no task without one  [GP-9]
context_surface:    # the files/functions to touch (point, don't make the doer hunt)
reference_files:    # ≤ 4; none > ~2000 lines (else use a long-context doer)  [H9]
acceptance_criteria:# list; each: {text, type: mechanical | evidence-form | domain-truth}
                    #   domain-truth criteria cannot be CLEAN without Oracle sign-off  [H11]
preservation_set:   # test/assertion IDs that must NOT change; checker fails any diff touching them  [H3]
invert_failure_modes: # 1–3 named ways this could go wrong (Beat-4 / Munger inversion)
out_of_scope:       # explicit; prevents scope spiral
na_allowed:         # true/false — if a fix may be honestly infeasible
na_requires:        # if na_allowed: the specific missing input + what would unblock  [H8]
```

**Definition-of-Ready preflight (before the doer runs).** The operator (or checker) verifies the spec
is complete *and* a `prompt_manifest` is persisted:
`{slot1_id+hash, slot2_id+hash, slot3 content or slot3_na_reason, intent_block_present: true}`.
A spec missing `acceptance_criteria`, `context_surface`, or a complete manifest is **not Ready** — the
unit is rejected *before* build, not after. This preflight is how slot omission (H10) is actually
caught.

### 3.2 Doer output — Doer → Checker

An **INTENT block** at turn 1 (restates the contract + a PM sanity-check sentence), the **change as a
persisted diff / patch / commit ID**, and a **VERIFICATION block**: evidence for *each* acceptance
criterion and *each* named failure mode, the test command + result, and the trace-cribbing lint
output. The doer's evidence is a *claim, not proof* — the checker re-verifies it (§3.3). A run that
ends with `finish_reason = token_cap` and no persisted diff/verdict is a **failure**, not a pass (H9).

### 3.3 Checker Verdict — Checker → Operator *(Definition of Done)*

The checker **re-runs what it can** (tests, lints) and **inspects the diff** — it never passes on the
doer's word (ADR-0003 "review/eval"). Anything it cannot independently verify is **not CLEAN**.

```yaml
verdict:        CLEAN | WITH-CHANGES | DO-NOT-MERGE
gates:          {G1: .., G2: .., ..}   # per-gate result + CHECKER-run evidence
verified_by:    checker                # confirms the checker (not the doer) re-ran the checks
diff_or_commit: # the artifact reviewed (commit / patch id)              [H4]
test_ids:       # tests that back each acceptance criterion              [H4]
commands_run:   # exact commands the CHECKER executed
contrary_case:  # strongest reason this could still be wrong / challenged premise  [H12]
notes:          # named failure mode(s) if not CLEAN — actionable, specific
```

Scoring: any **DO-NOT-MERGE** on any gate ⇒ unit fails; **WITH-CHANGES** ⇒ return for fix. **Only
CLEAN — backed by checker-run evidence — is "done."** A missing `contrary_case` is itself
WITH-CHANGES (guards sycophancy, H12). "Looks green" is not a verdict.

## 4. Gates — Definition of Done *(binding)*

Adapted from OpenCell's 5-gate critique, extended with the RAPTOR failure modes:

| Gate | Passes only if… | Guards |
|---|---|---|
| **G1 · Preservation** | No test/assertion in the spec's `preservation_set` is weakened, loosened, or deleted; the checker inspects the test diff. | **H3** |
| **G2 · No trace-cribbing** | A **checker-run** script (canonical forbidden-path globs + config/env + alias/AST checks, scoped to the pipeline package) confirms production code cannot read any benchmark/label/oracle artifact. Doer-pasted `RULE-8-CLEAN` is **not** sufficient. *(Manual until the script/CI hook exists — §10.)* | **H1** |
| **G3 · Non-triviality** | Every new/changed test asserts a *specific expected non-zero signal* — no "empty == empty at tolerance" pass. | **H2, H4** |
| **G4 · Acceptance met** | The checker **independently** reruns/inspects evidence per criterion. *Mechanical* and *evidence-form* criteria pass on checker-run evidence; *domain-truth* criteria are **not CLEAN without Oracle sign-off** — labelled `UNVERIFIED` and blocked from external use. "Unable to verify" ⇒ not CLEAN. | R-D1, **H11** |
| **G5 · Fail-fast** | Missing input raises at construction/first call — never silently returns `{}`/zeros/placeholder. | **H5** |
| **G6 · Honest N/A** | Any "can't be done" cites the specific missing input + an unblock proposal — not a bare skip. | **H8** |
| **G7 · Grounding** | Every factual/quantitative claim in the artifact names a **resolvable** reference (ADR / data record / PMID / DB accession / file+span); the checker resolves a sample. An unresolvable or missing reference ⇒ the claim is `UNVERIFIED` and the unit is not CLEAN. | **GP-9, H13, R-A6** |

Every gate result cited in a CLEAN verdict must be **checker-run evidence**, not the doer's report.

### 4.1 Test-authorship separation *(pre-facto defense — the highest-leverage rule)*

The PRD-03 build shipped 78 green tests that hid 5 real bugs, because the **doer wrote the code and
its tests in one pass** — the tests inherited the code's blind spots (confirmation bias; RISK_REGISTER
H2/H4). Post-facto the different-family checker caught them, but the cheaper fix is pre-facto:

- **For foundational / high-assurance modules, a dedicated *test-author* agent (Gemini — a different
  family from the Sonnet doer *and* the GPT checker) writes the acceptance-test contract — the spec's
  AC1..N as executable, assertion-specific tests — *before* the doer builds, and *from the spec only*
  (never seeing the doer's code).** The **planner owns the test *contract* (which ACs/invariants to
  cover) but delegates the test *code*** — keeping the planner context-clean for long-range reasoning
  while still breaking the confirmation-bias loop at build time (the test author ≠ the code author).
  Why Gemini and not the best single test-writer (Claude): the doer is Claude-family, so a Claude
  test-author would re-share the blind spot; independence beats raw single-model quality here.
- **The doer implements to make those tests pass; it may *add* tests but must not weaken, modify, or
  delete the pre-authored ones** (G1 preservation still applies).
- **Test the real API/publish path, not direct-table SQL** — integration gaps hid the `run_id` bug.
- **Property-based invariants** (`hypothesis`, allowed as a dev-only dep) are preferred for core
  invariants (e.g. "no variant publishes without a source_ref") — harder to game than hand-picked
  examples.
- **Self-audit / lint tests must be proven to catch a *known injected* violation** — the GP-6 audit
  that missed its own `CREATE TEMP TABLE` violation would have failed this meta-test.
- **Local models are NOT used for foundational test authoring** (quality risk: a weaker author can't
  catch a stronger doer's bugs; ARM/Ollama immaturity; heavy models want the 64GB workers not the
  32GB Queen). Reserve local models (Qwen2.5-Coder-14B/32B) for Tier-3 screening and later
  low-stakes/bulk generation — see ADR-0005.

This does **not** retire the checker — it is defense-in-depth (pre-facto lowers introduction; the
checker catches the remainder), and it moves confirmation-bias risk onto the test author, so the
planner derives tests strictly from the spec's ACs and the checker still re-runs independently.

## 5. Prompt composition — three slots *(guards H10)*

Slots **1 and 2 are always present**; **slot 3 is required whenever the doer can modify existing code
or tests**, else the manifest records an explicit `slot3_na_reason`. Slot presence is proven by the
`prompt_manifest` (§3.1); the Ready preflight rejects a task with an unexplained missing slot.

| Slot | Scope | Content |
|---|---|---|
| **1 · Prefix** (generic) | every task | Deliberate-action + the **INTENT block** requirement: name the contract → point at the surface → verbalize expected outcome → **invert** (name Beat-4 failure modes) → act, then verify. |
| **2 · Task template** (domain) | per work class | The probes/rules specific to this class of work (e.g. ACMG scoring, Tier-3 extraction, config edits). Grows by rule-graduation (§7). |
| **3 · Preservation directive** (case) | per run, when the doer can rewrite existing code/tests | Name the *specific* prior failure mode and the *specific* assertions that must not change. |

## 6. Integrity controls

| Control | Guards | Status | Mechanic |
|---|---|---|---|
| Checker ≠ doer family | R-D1 | **live** | Structural rule (§2) — the only control that exists today. |
| Checker re-runs evidence | R-D1, H4 | manual | Checker executes tests/lints + inspects diff; unverifiable ⇒ not CLEAN (§3.3). |
| Checker-integrity probe | R-D1 | planned | Operator injects a known-bad diff from a stored probe corpus **monthly + on any checker-model change**; a miss ⇒ freeze merges + re-review everything since the last passing probe. |
| Adversarial `contrary_case` | **H12** | manual | Required verdict field; its absence is WITH-CHANGES. "Specificity without structured doubt scored 0.0" (OpenCell Gold arm). |
| Trace-cribbing lint | **H1** | planned | Checker-run script (§4 G2); pre-commit/CI target. |
| Zero-commit / cap-death detection | **H9** | manual | Failure = no persisted diff/verdict **and** no explicit N/A, or `finish_reason = token_cap`; decompose + re-fire. |
| Post-merge CLEAN audit | R-D2 | planned | Random re-check of merged CLEAN units; a wrong CLEAN reopens the unit **and** graduates a rule (§8). |
| Operator-fatigue guard | R-D5 | manual | No domain-impacting or external merge at the end of a long session; sleep-on-it for any reclassification-affecting change. |
| Model/version pinning | R-C6 | manual | Persist `{provider, model_id, version/date, prompt-hash}` per task; a mid-task model change forces a rerun / new task. |
| Property-based tests (**Hypothesis**) | H2/H4 | dev-dep | Core invariants as properties over generated inputs; auto-shrinks failures. Preferred over example-only tests for critical invariants (ADR-0005). |
| Mutation testing (**mutmut**) | H2/H4, R-D2 | planned | Selective, on core modules: inject mutations; a surviving mutant = a hollow test. The mechanical anti-hollow-green detector (ADR-0005). |
| Agent least-privilege | R-C5, R-G4 | policy | A delegated agent is **workspace-confined**; destructive or external ops (file delete, dependency install, remote/DB write, external submit) **require approval**; **auto-approve is never shipped** for these. *(Adopted from ai4s/open-science safety defaults.)* |
| VERIFIED/UNVERIFIED labelling | H13/R-A6 | manual | Every quantitative claim labelled; "I don't know" is allowed. |

## 7. Delegation rules (guards H9)

- **One hypothesis / bug-class per task.** Enumerating 5+ failure modes in one task pushes a delegate
  into "write the plan, exit without doing it" — keep slot 3 to 1–3 named modes.
- **≤ 4 reference files; none > ~2000 lines.** A large reference file eats the budget before code is
  written; use a long-context doer for those.
- **Disable slow PreToolUse hooks before delegating** — per-tool-call hook latency causes stream
  disconnects and zero-commit deaths.
- **Detect and decompose:** a run with no persisted diff/verdict (or `finish_reason = token_cap`) is a **failure**, not a pass → split into narrower tasks and re-fire (H9).

## 8. Rule-graduation loop (the core discipline)

The loop's job is **not** zero first-try failures — it is **zero *tolerated* recurrence**: a repeat of
a named class, *or a CLEAN later found wrong*, must trigger escalation. When such a failure appears:

1. Name it (add a row to `RISK_REGISTER.md` if genuinely new — GP-8 applicability audit first).
2. Append a **permanent rule** to the relevant slot-2 task template.
3. Where cheap, encode it as a **CI lint / pre-commit gate** (the G2 trace-cribbing `grep` is the
   first candidate).
4. Add a **checker gate** if it can't be linted mechanically.

Every rule is "paid for" by exactly one real failure. One failure → one durable rule.

### 8.1 Graduated rules v1 — from the PRD-03 (KB) build

The five DO-NOT-MERGE failure modes, generalised into permanent slot-2 rules (apply to every module):

1. **Grounding on *every* groundable table, incl. many-source ones.** If "≥1 child" can't be a
   declarative FK (e.g. `variants`→`variant_source_refs`), enforce it at **publish-time validation**
   *and* the write API — plus a negative test that an ungrounded row fails. *(bug 1)*
2. **Every FR that names an API/publish path gets an integration test on that path, not just
   direct-table SQL.** *(bug 2 — dropped `run_id`)*
3. **Ledger-is-source-of-truth: any projection table is written via a ledger event; its test
   reconstructs it by replay** (incl. secondary fields like approvals). *(bug 3)*
4. **Schema/DDL lives in SQL/config, never hardcoded in Python** — and the GP-6 audit catches
   `CREATE TEMP/TEMPORARY TABLE`, not just `CREATE TABLE`. *(bug 4)*
5. **The full runtime contract is *verified*, not assumed** (e.g. `synchronous=FULL`), with a test
   that fails on downgrade. *(bug 5)*
6. **Self-audit/lint tests must catch a known injected violation** before they count (meta-test). *(cross-cutting)*

Until `docs/prompts/` templates exist, these live here and are pasted into build prompts as slot 2.

## 9. Artifacts & locations

| Artifact | Lives in |
|---|---|
| Task specs + checker verdicts | session/work log per task (persisted, not silent) |
| Slot templates (1/2/3) | `docs/prompts/` (planned) |
| Graduated rules + CI lints | `docs/prompts/` + `scripts/` / pre-commit config (planned) |
| Process decisions | `DECISIONS.md` |

## 10. Not yet automated (honest state)

- Gates are **checker-enforced by an LLM + operator eyeball**; **no gate is mechanically automated
  yet** — even the G2 trace-cribbing script/CI hook is *planned*, not built. Every §6 control marked
  `planned` does not exist today; only "checker ≠ doer family" is `live`. The manual cost is real
  (RISK_REGISTER R-D2/R-D3/R-D5).
- Spec/verdict **schemas and the `prompt_manifest` are conventions**, not yet validated by tooling.
- The checker-integrity probe and post-merge CLEAN audit (§6) are defined but **not yet scheduled/run**.
- **Nothing here is safe to trust unattended until the §6 `planned` controls ship** — consistent with
  RISK_REGISTER §9 (treat every green as provisional).

These gaps are why PROGRAM.md still lists the build-loop controls as *Open*.
