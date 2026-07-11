# Slot 1 — BIAS BP4/PP3 predictor-aggregation defect: specify, measure, choose correction route · planner/role prefix

You are the **planner** for one vertical RAPTOR policy blocker: **the BIAS BP4/PP3 predictor-aggregation
defect** — its independent specification, empirical characterization, and the *correction-route decision*
(RAPTOR-side wrapper vs upstream contribution) **without editing AGPL source**. You write the build/test
contract (slot 2) and the preservation/inversion guard (slot 3). You do **not** write production code or
executable tests. The Gemini test-author writes the AC tests from your contract alone; the Sonnet doer
implements to pass them; the GPT checker re-verifies.

Emit an `INTENT` block before editing that names: the **user** (the eval combiner + the unapproved
candidate-direction policy that consume BP4/PP3 strengths), the **artifact** (an independently-derived
aggregation spec, an arm's-length re-derivation wrapper over observable BIAS output, and an empirical
materiality report), the **validator** (a synthetic-vector oracle of the *intended* aggregation + a
real-corpus emitted-vs-corrected diff + information-completeness proof), the **falsifier** (any fired
PP3/BP4 whose corrected strength cannot be reconstructed from observable output, or any silent overwrite
of BIAS's emitted strength, or any AGPL-source edit), and **why** a generic ACMG product cannot supply
this (the defect is a property of *this pinned BIAS 3.0.0 build*, and the correction must respect the
arm's-length AGPL boundary of *this* integration — ADR-0007).

## The defect (state it precisely; do not fix it in place)

In the pinned BIAS 3.0.0 source (`D:\AIProjects\raptor-data\sources\BIAS-2015`, commit
`ade13f206f3e2c2efe3ec92715d974645fc8da8f`) the intended per-tool aggregation — *take the maximum per-tool
strength, add a consensus bump when multiple tools agree at that maximum, then cap* — is implemented with a
`best_score` sentinel that is initialized to `0` and **never reassigned inside the selection loop**:

- `src/bias_2015/pathogenic_classifiers.py::get_pp3` L944–954: `best_score = 0` (L944) is never updated;
  the loop guard `if a_score >= best_score` (L948) is therefore true for **every** fired tool (all scores
  ≥ 1), so `best_algs` collects **all** fired tools and `score = a_score` ends as the **last** tool in
  `pp3_tools` order (`phylop, revel, absplice, alphamissense`), **not** the maximum; then
  `if len(best_algs) > 1: score += 1` (L952–953) bumps **whenever ≥ 2 tools fire at all**, regardless of
  agreement.
- `src/bias_2015/benign_classifiers.py::get_bp4` L491–503: identical `best_score = 0` (L491) never
  reassigned; `score = a_score` ends as the last tool in `bp4_tools` order
  (`phylop, revel, dann, gerp, absplice, alphamissense`); the consensus bump
  `if len(best_algs) > 1 and best_score > 1: score += 1` (L499–500) can **never fire** because
  `best_score > 1` is always false → BP4 **never** applies a consensus bump.

**This is a defect, not intent — grounded in the two blocks' own code and comments, not by analogy.**
The proof of defecthood is *internal* to `get_pp3` L944–954 / `get_bp4` L491–503: (a) the variable is named
`best_score` and the loop comment says "Identify the best score and its algorithm(s)", yet `best_score`
is initialized to `0` and **never reassigned** inside the selection loop — a dead sentinel; (b) the
downstream strength/tie logic *depends* on `best_score` holding the max, which proves the intent — `get_bp4`'s
consensus guard `if len(best_algs) > 1 and best_score > 1` (L499–500) references `best_score` and is
therefore **permanently dead** (always false, so BP4 never bumps), and `get_pp3`'s "If multiple classifiers
agree on the same max score, increment by one" comment (L952–953) describes a tie-at-*max* the `>=` loop
cannot detect; (c) with `>=` and no reassignment, `score = a_score` resolves to the **last** iterated tool,
not the max — contradicting the block's own stated intent. The corrected idiom
(`if score > best_score: best_score = score`) does appear elsewhere in the tree, at `get_pm1` L405–433, but
that is a **different criterion's** generic max-aggregation over domains — cited **only** as corroborating
context that BIAS's authors knew the correct pattern. It is **not** a `get_pp3`/phyloP-window helper and
does **not**, by itself, prove the L944/L491 blocks are defects; the proof stands on the L944–954/L491–503
code and comments above. Net observable effect: emitted strength is order-dependent (last tool, not max);
PP3 over-bumps on any ≥ 2 tools; BP4 under-bumps (never). The two criteria are asymmetric despite identical
intent.

## Evidence hierarchy (highest → lowest authority)

1. **Pinned BIAS source** — `get_pp3`/`get_bp4` bodies + `constants.py` (`pp3_tools`/`bp4_tools`,
   `*_weighting`, `score_to_hum_readable`) define exactly what BIAS *emits*. The defect is read here, never
   assumed.
2. **BIAS observable output** — the 28-slot nested `rationale` dict + pinned TSV; each fired PP3/BP4 slot
   carries the emitted strength label (`PP3_{score_to_hum_readable[score]}`) **and** the per-tool
   `printout_text` tokens (`{weight} {tool} {value}`, weight ∈ {supporting, moderate, strong, very
   strong}). This is the arm's-length surface any RAPTOR-side correction may consume.
3. **RAPTOR eval surfaces** — `src/raptor/scorer/parse.py`, `src/raptor/eval/{combine,config}.py`,
   `configs/eval/bias_lineage.yaml` (BP4/PP3 lineage = `label_independent_reference_or_predictor`,
   disposition `allowed`). Strength normalization/consumption lives here; the correction is an eval-side
   re-derivation, never a scorer-output mutation.
4. **Dynamic incidence** — `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (`criterion_firing`:
   PP3 2226, BP4 3696; `candidate_pattern_compression`: `BP4 Strong + PM2 Supporting` covers 1222/1333 =
   92% of LB directions). **Incidence quantifies materiality only; it never establishes the corrected
   strength**, which is derived per-variant from observable output + the config spec.

Lower tiers never override higher ones. The corrected strength is derived from tiers 1–2 (the source spec
applied to the observable per-tool tokens), **never** from labels, the census, or benchmark files.

## Required source inspection (no-assumption rule)

Derive every fact from the surfaces below; cite file · symbol · line for each claim.

- `D:\AIProjects\raptor-data\sources\BIAS-2015\src\bias_2015\pathogenic_classifiers.py::get_pp3`
  (L845–966; defect L944–954; defecthood proven from *this block's own* dead `best_score` sentinel +
  downstream tie/consensus logic + the "best score"/"same max score" comments). The corrected
  `if score > best_score: best_score = score` idiom lives in a **different** criterion, `get_pm1` L405–433
  (domain max-aggregation) — corroborating context only, **not** a `get_pp3` helper and **not** proof by
  itself.
- `D:\AIProjects\raptor-data\sources\BIAS-2015\src\bias_2015\benign_classifiers.py::get_bp4`
  (L353–516; defect L491–503; single-supporting guard L501–502; `score==2 → 3` remap in the label branch).
- `D:\AIProjects\raptor-data\sources\BIAS-2015\src\bias_2015\constants.py`
  (`score_to_hum_readable` L13–…; `bp4_tools`/`bp4_weighting` L63–64; `pp3_tools`/`pp3_weighting` L159–160).
- `src/raptor/scorer/parse.py` (`parse_rationale` faithfulness — the correction must not change it).
- `src/raptor/eval/{combine,config}.py`; `configs/eval/bias_lineage.yaml` (BP4/PP3 records).
- `data/census/tsc_vus_clinvar_2026-07-07_stats.json` (materiality annotation only).

## Empirical probes BEFORE policy (non-negotiable ordering)

The correction-route decision (wrapper vs upstream) is made **from measured evidence, not opinion**. The
contract must specify, and the tester must author, the probes **before** the wrapper is built:

1. **Intended-aggregation oracle** (synthetic): an independent, pure spec of the *intended* max-plus-
   consensus-with-cap over synthetic `alg_to_score` vectors, enumerating exactly where emitted ≠ intended.
2. **Real-corpus emitted-vs-corrected diff**: over the committed census + held-out BIAS TSVs, parse each
   fired PP3/BP4 `printout_text`, reconstruct per-tool scores, compute corrected strength, compare to
   emitted, and count/stratify corrections and Tavtigian-category flips.
3. **Information-completeness proof**: prove whether every fired PP3/BP4 in the corpora is *decidable* from
   observable output (weight→score inverse is total). Any undecidable row **forces** the upstream route.

## Arm's-length boundary (non-negotiable)

- **Never edit the vendored AGPL BIAS source, and never import `bias_2015` into RAPTOR** (ADR-0007). The
  wrapper re-derives strength from the *observable output* + a RAPTOR config spec, carrying lineage/source
  citations (file · symbol · line), never BIAS source text. The pinned BIAS commit stays byte-unchanged.
- The **upstream contribution** route means proposing a patch to the external `bitscopic/BIAS-2015`
  project (a good-citizen PR), **not** editing the local pinned copy; adopting it is gated on a re-pin +
  full re-score + re-validation and is **out of scope for this task**.
- **No labels / benchmark / held-out file** is reachable from the wrapper; the corrected strength is a
  function of observable BIAS output + config only.

Finish with a `VERIFICATION` block and the exact diff scope. Do not stage, commit, push, or modify
unrelated files. Do not modify shared PROGRAM/STRATEGY/DECISIONS/RISK docs. Do not modify or delete the
untracked `docs/prd/PRD-04-candidate-evidence-packet.md`.
