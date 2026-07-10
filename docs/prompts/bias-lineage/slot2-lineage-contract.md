# Slot 2 — Lineage contract: public API, config, output, acceptance criteria, DoR task specs

> Planner-authored build/test surface. The test-author writes AC tests from **this file + the source
> surfaces in slot 1 only**, before the doer. The doer implements to pass (may add, not weaken). All facts
> below are derived from the pinned BIAS source (commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`); every
> row cites a source anchor. Dynamic census counts are annotations, never the oracle for membership.

---

## 0. Source-derived truth (the tester's independent oracle)

### 0.1 All 28 rationale slots (a)
BIAS always emits a nested `rationale` dict with **every** ACMG-2015 code, defaulting to score 0
(`bias_variant_classification.apply_ACMG_codes` L315–324 assembles `pvs/ps/pm/pp/ba/bs/bp`; each
`get_p*`/`get_b*` aggregator inserts a `(score, text)` tuple per code, stubs inserting `(0, "")`):

```
PVS1 · PS1 PS2 PS3 PS4 · PM1 PM2 PM3 PM4 PM5 PM6 · PP1 PP2 PP3 PP4 PP5
BA1 · BS1 BS2 BS3 BS4 · BP1 BP2 BP3 BP4 BP5 BP6 BP7
```

### 0.2 Criteria with implemented evaluators that CAN FIRE (b) — **19** (NOT RAPTOR's 19)
A criterion is *can-fire* iff its evaluator can return score > 0. Derived statically:

| Criterion | BIAS anchor (file · symbol) | census incidence¹ |
|---|---|---|
| PVS1 | `pathogenic_classifiers.get_pvs` (L6–114) | 150 |
| PS1  | `pathogenic_classifiers.get_ps1` (L146–196) | 110 |
| PS3  | `pathogenic_classifiers.get_ps3` (L213–268) | 46 |
| PS4  | `pathogenic_classifiers.get_ps4` (L271–343) | 0 |
| PM1  | `pathogenic_classifiers.get_pm1` (L384–433) | 0 |
| PM2  | `pathogenic_classifiers.get_pm2` (L436–499) | 6609 |
| PM4  | `pathogenic_classifiers.get_pm4` (L541–603) | 176 |
| PM5  | `pathogenic_classifiers.get_pm5` (L622–687) | 147 |
| PP2  | `pathogenic_classifiers.get_pp2` (L770–843) | 0 |
| PP3  | `pathogenic_classifiers.get_pp3` (L845–966) | 2226 |
| PP5  | `pathogenic_classifiers.get_pp5` (L978–997) | 3 |
| BA1  | `benign_classifiers.get_ba1` (L6–43) | 1 |
| BS1  | `benign_classifiers.get_bs1` (L62–114) | 0 |
| BS2  | `benign_classifiers.get_bs2` (L116–176) | 34 |
| BP1  | `benign_classifiers.get_bp1` (L247–268) | 0 |
| BP3  | `benign_classifiers.get_bp3` (L299–351) | 7 |
| BP4  | `benign_classifiers.get_bp4` (L353–516) | 3696 |
| BP6  | `benign_classifiers.get_bp6` (L526–546) | 0 |
| BP7  | `benign_classifiers.get_bp7` (L548–616) | 127 |

¹ From `data/census/...stats.json::criterion_firing`. **Annotation only.** Six can-fire criteria fired 0
times (PS4/PM1/PP2/BS1/BP1/BP6) yet remain can-fire. Census dynamic fired-set = 13 ≠ static can-fire = 19.

### 0.3 Structurally forbidden / deferred stubs (d) — **9** (cannot fire from internal evaluators)
Return `""` / score 0 unconditionally from BIAS's own `get_*` evaluators; the only way a value ever
appears is the **external supplemental-call path**
(`bias_variant_classification.merge_supplemental_codes_into_rationale_dict` L206–217):

`PS2` (`get_ps2` L198), `PM3` (`get_pm3` L501), `PM6` (`get_pm6` L689), `PP1` (`get_pp1` L759),
`PP4` (`get_pp4` L968), `BS3` (`get_bs3` L178), `BS4` (`get_bs4` L189), `BP2` (`get_bp2` L270),
`BP5` (`get_bp5` L518). Partition invariant: `can_fire (19) ⊎ structural_stub (9) == all_28`.

**Supplemental firing is fail-closed, not silently impossible.** These nine cannot fire from BIAS's
internal evaluators, but the supplemental-call path *can* inject a non-zero `(score, text)` from an
external source. A nonzero supplemental stub is therefore **not** a no-op or an impossibility — it is
**fail-closed**: any stub code (∉ `can_fire`) firing with non-zero score is a breach (audit rule (ii),
§1.4) and **blocks** unless that criterion is explicitly authorized (`oracle_allowed` / a named
decision). The gate must treat a nonzero supplemental stub as an unauthorized firing to be surfaced,
never as something that cannot happen.

### 0.4 RAPTOR policy today (c) — the drift the gate must surface, then correct
**Current (drifted) config, pre-correction:**
- `scorer.included_criteria` == `eval.automatable_criteria` = **16**:
  `PVS1 PS1 PM1 PM2 PM4 PM5 PP2 PP3 BA1 BS1 BS3 BS4 BP1 BP3 BP4 BP7` (BS3/BS4 phantom — §0.5 D2).
- `eval.config.FORBIDDEN_CRITERIA` = **3**: `PP5 BP6 PS4`.
- `scorer.acmg_criteria` registry = 19 codes but the **wrong 19**: `included (16) + FORBIDDEN (3)` carries
  phantom **BS3/BS4** and **omits** can-fire **PS3/BS2** — it is **not** `can_fire` (§0.2).

**Required correction (this task's authorized config edits, §1.6):**
- `included_criteria`/`automatable_criteria` drop BS3/BS4 → **14**:
  `PVS1 PS1 PM1 PM2 PM4 PM5 PP2 PP3 BA1 BS1 BP1 BP3 BP4 BP7`.
- `scorer.acmg_criteria` registry becomes **exactly `can_fire` (the 19 of §0.2)**: the BS3/BS4 registry
  entries are replaced by source-derived **PS3** and **BS2** (direction/strength-vocab for registry
  presence only — **neither is included/automatable**; BS2 stays `deferred`).
- After correction `set(scorer_config.acmg_criteria) == policy.can_fire` holds; otherwise the registry
  check raises `registry_can_fire_drift` (§1.3).

### 0.5 Discrepancies the gate MUST surface (resolve from source, do not force to 19)
- **D1 — omitted can-fire, no disposition:** `PS3` (fired 46) and `BS2` (fired 34) can fire but are
  neither scored, forbidden, nor recorded with a rationale. **Both take explicit `deferred`
  dispositions** — PS3 pending assay-validity review; **BS2 pending a TSC-specific
  penetrance/age/mosaicism policy decision (`decision_dependency: bs2-policy`, PROGRAM.md item 6).**
  BS2's label-independent population/control lineage does **not** make it `allowed`; neither is scored,
  included, or automated by this task.
- **D2 — phantom automation:** `BS3` and `BS4` are in `included_criteria`/`automatable_criteria` but are
  BIAS stubs (§0.3) — they can never emit evidence. Policy claims criteria the pinned engine cannot
  produce. `included ⊆ can_fire` is currently **false**.
- **D3 — transitive ClinVar scored:** `PS1 PM5 PM1 PP2 BP1` are ClinVar-comparator-derived (ADR-0009,
  §0.6) and currently scored. **`BP1`'s rationale text contains no ClinVar marker** (see §0.6) so
  marker-detection alone misses it; only static lineage / the transitive-suspect net catches it.
- **D4 — "19/28" is coincidental:** RAPTOR's 19-registry ≠ BIAS 19-can-fire; they differ by
  `{BS3,BS4}` (RAPTOR-only, phantom) vs `{PS3,BS2}` (can-fire, omitted).

### 0.6 Lineage classification (the tester's oracle: derived from the *loaders*, not the rationale text)

| Criterion | Lineage class | Direct/transitive source dependency · BIAS data anchor | Validation disposition | Production disposition | Rationale marker present? |
|---|---|---|---|---|---|
| PVS1 | label_independent_reference_or_predictor | gnomAD LOEUF (`find_lof_genes.py`), VEP/Nirvana consequence, ABSplice `PVS1_PP3_BP4_BP7_splice_dict` | allowed | allowed | no ClinVar marker |
| PM2  | label_independent_population | gnomAD AF + 1000G AF + LOEUF | allowed | allowed | no |
| PM4  | label_independent_reference_or_predictor | consequence + `PM4_BP3_chrom_to_repeat_regions` (`join_coding_and_repeats.py`) | allowed | allowed | no |
| PP3  | label_independent_reference_or_predictor | computational predictors / splice dict | allowed | allowed | no |
| BA1  | label_independent_population | gnomAD/1000G population AF | allowed | allowed | no |
| BS1  | label_independent_population | gnomAD/1000G AF + LOEUF | allowed | allowed | no |
| BS2  | label_independent_population | gnomAD/1000G homozygous/hemizygous + control ACs, disease/inheritance (**label-independent source ≠ policy approval**) | deferred (**D1: TSC penetrance/age/mosaicism policy owed — `decision_dependency: bs2-policy`**) | deferred (`decision_dependency: bs2-policy`) | no |
| BP3  | label_independent_reference_or_predictor | `PM4_BP3_chrom_to_repeat_regions` | allowed | allowed | no |
| BP4  | label_independent_reference_or_predictor | computational predictors / splice dict | allowed | allowed | no |
| BP7  | label_independent_reference_or_predictor | ABSplice + phyloP + synonymous consequence | allowed | allowed | no |
| PS1  | cross_variant_clinvar | `PS1_gene_mut_to_data` ← `generate_pathogenic_aa_list.py` (**ClinVar Nirvana JSON**) | requires_heldout_mask | allowed (full comparator) | maybe (AA-change phrasing; may lack literal "clinvar") |
| PM5  | cross_variant_clinvar | `PM5_gene_aa_to_var_data` ← `generate_pathogenic_aa_list.py` (**ClinVar**) | requires_heldout_mask | allowed | maybe |
| PM1  | aggregate_clinvar | `chrom_to_pathogenic_domain` ← `generate_domain_lists.py` (**ClinVar VCF** + UniProt) | requires_heldout_mask | allowed | maybe |
| PP2  | aggregate_clinvar | `PP2_missense_pathogenic_gene_to_region_list` ← `find_missense_pathogenic_genes_and_path_trunc_genes.py` (**ClinVar VCF** + gnomAD RMC) | requires_heldout_mask | allowed | maybe |
| BP1  | aggregate_clinvar | `BP1_truncating_gene_to_data` ← `find_missense_pathogenic_genes_and_path_trunc_genes.py` (**ClinVar VCF**) | requires_heldout_mask | allowed | **NO — text says "where {path_per} of pathogenic variants…", no ClinVar token** |
| PS4  | same_variant_clinvar | `PS4_clinvar_submitter_counts` ← `generate_clinvar_submitter_counts.py` (**ClinVar submission_summary**; own-variant submitter count fallback when no GWAS) | forbidden | forbidden | yes ("independent ClinVar submitters") |
| PP5  | same_variant_clinvar | `variant.clinvar_significance` + `clinvar_review_status` (same variant, via Nirvana) | forbidden | forbidden | yes ("reported … in ClinVar as VCV…") |
| BP6  | same_variant_clinvar | `variant.clinvar_significance` (same variant, via Nirvana) | forbidden | forbidden | yes |
| PS3  | literature_unvalidated | `PS3_lit_gene_mut_to_data`/`lit_variant_to_data` ← `extract_from_avada_track.py` (**AVADA full-text ML extraction; ~50% precision noted in source**) | deferred (assay-validity review) | deferred | no ClinVar marker ("as established by AVADA") |
| stubs (§0.3) | manual_or_external_input | supplemental external-call injection only; never computed internally | forbidden — a nonzero supplemental injection is fail-closed (blocks) unless explicitly authorized | forbidden | n/a |
| any other | unknown | fail-closed default bucket | forbidden | forbidden | n/a |

**Disposition roll-up of the 19 can-fire (each explicit; total = 19, do not force):**
`allowed` (label-independent **and** policy-approved) = **9**: PVS1 PM2 PM4 PP3 BA1 BS1 BP3 BP4 BP7 ·
`requires_heldout_mask` (transitive ClinVar) = **5**: PS1 PM5 PM1 PP2 BP1 ·
`forbidden` (same-variant ClinVar) = **3**: PS4 PP5 BP6 ·
`deferred` = **2**: PS3 (literature / assay-validity review) · **BS2** (label-independent
population/control source, but a TSC-specific penetrance/age/mosaicism policy decision is still owed —
`decision_dependency: bs2-policy`).

**Lineage class ≠ approval.** A `label_independent_*` lineage means the *source* is not the ClinVar
label; it does **not** by itself grant an `allowed` disposition or inclusion. BS2's source-independence
must never be laundered into a validation/production approval: its disposition stays `deferred` and it is
neither scored nor automated until the named `bs2-policy` decision is made.

---

## 1. Public API / config / output files (the exact surface the doer must build)

> Smallest coherent eval-side surface. The scorer package never imports it. Reuses `BiasTsvSource`,
> `parse_rationale`, `eval.config.{VALID_CRITERIA,FORBIDDEN_CRITERIA}`. No AGPL BIAS import.

### 1.1 Config — single machine-readable source of truth
`configs/eval/bias_lineage.yaml` — schema-validated, version-pinned:
- `bias_version: "3.0.0"`, `bias_commit: "ade13f206f3e2c2efe3ec92715d974645fc8da8f"`.
- `lineage_classes:` the **exhaustive** taxonomy enum (fail-closed): `label_independent_population`,
  `label_independent_reference_or_predictor`, `same_variant_clinvar`, `cross_variant_clinvar`,
  `aggregate_clinvar`, `literature_unvalidated`, `manual_or_external_input`, `unknown`.
- `dispositions:` enum `allowed`, `requires_heldout_mask`, `forbidden`, `deferred`.
- `all_criteria:` the 28 codes; `structurally_forbidden:` the 9 stubs (each `{criterion, reason,
  bias_anchor}`); `can_fire:` the 19.
- `records:` one entry **per can-fire criterion** (exactly the 19, keyed):
  `{lineage_class, source_dependencies:{direct:[...], transitive:[...]}, bias_anchors:[file·symbol·lines],
  data_artifacts:[loader/generator names], validation_disposition, production_disposition,
  rationale_markers:[...], notes, decision_dependency}` (per §0.6).
- `oracle_allowed:` list, **empty**; no wildcard/regex/catch-all (schema rejects).
- `markers:` the **version-pinned ClinVar-marker vocabulary — the single source of truth, embedded here**
  (there is **no** separate marker file): `bias_version`-pinned, case-insensitive tokens / bounded phrases
  tied to BIAS v3.0.0 (e.g. `clinvar`, `vcv`, `clinvar pathogenic rate`, `clinvar benign rate`,
  `independent clinvar submitters`) — **no regex / wildcard / catch-all** (schema rejects). Every record's
  `rationale_markers` token MUST be ∈ `markers` or the load raises (§1.2). `configs/eval/clinvar_markers.yaml`
  does **not** exist and is **never** referenced.
- `transitive_suspect:` **derived** = every record with `lineage_class ∈ {cross_variant_clinvar,
  aggregate_clinvar}` = `[PS1, PM5, PM1, PP2, BP1]` (fail-closed net; must include BP1 — marker-invisible).
- Reuses `configs/{acmg/tsc,eval/tsc2}.yaml` for CP-1/registry reconciliation only (no external marker file).

### 1.2 `src/raptor/eval/lineage_policy.py`
- `load_lineage_policy(path) -> LineagePolicy` — schema-validate + fail-closed:
  - every `records` key ∈ `VALID_CRITERIA` and ∈ `can_fire`; `set(records) == set(can_fire)` exactly.
  - every `lineage_class` ∈ taxonomy enum; every `validation_disposition`/`production_disposition` ∈
    disposition enum; every referenced `rationale_markers` token ∈ the embedded `markers:` vocab — **unknown
    class, disposition, or marker raises** (`LineagePolicyError`).
  - a `validation_disposition` or `production_disposition` of `deferred` **must** carry a non-empty
    `decision_dependency` naming the owed decision (BS2 → `bs2-policy`; PS3 → assay-validity review);
    a `deferred` record with an empty/absent `decision_dependency` **raises** (fail-closed — a deferral
    must name the decision it is waiting on, never silently self-resolve).
  - `can_fire ⊎ structurally_forbidden == all_criteria` (disjoint, exhaustive) else raise.
  - reject **duplicate**, **missing**, or **unknown** criterion codes (typed, structured sets).
  - `oracle_allowed ⊆ VALID_CRITERIA`; empty or explicitly-named only; wildcard → raise.
- `LineagePolicy` accessors: `.records`, `.can_fire`, `.transitive_suspect`, `.forbidden`,
  `.disposition_of(criterion)`, `.lineage_of(criterion)`.

### 1.3 `src/raptor/eval/lineage_registry.py` (exact-set meta-checks)
- `assert_registry_consistency(policy, scorer_config, eval_config) -> None`, raising
  `LineageRegistryMismatchError(sets_by_kind=...)` with structured kinds:
  - `set(scorer_config.included_criteria) == set(eval_config.automatable_criteria)` (eval = production).
  - `set(scorer_config.acmg_criteria) == policy.can_fire` (kind `registry_can_fire_drift`) — the scorer's
    ACMG registry must be **exactly** the 19 can-fire criteria (§0.2), not merely a superset of `included`.
    After the §1.6 correction the phantom `{BS3,BS4}` registry entries are replaced by source-derived
    `{PS3,BS2}`; a registry still carrying BS3/BS4 (or omitting PS3/BS2) trips this breach. **Registry
    membership ≠ inclusion:** PS3/BS2 are registered for vocab presence but stay out of
    `included_criteria`/`automatable_criteria` (BS2 `deferred`).
  - `included ⊆ policy.can_fire` — **any scored non-can-fire criterion is a breach** (kind
    `scored_not_can_fire`; surfaces D2 = `{BS3,BS4}`).
  - every `can_fire \ included` criterion carries an explicit `validation_disposition ∈ {forbidden,
    requires_heldout_mask, deferred}` **or** an Oracle `allowed` inclusion decision (kind
    `omitted_without_disposition`; surfaces D1 = `{PS3,BS2}` — both now `deferred`, a **valid intentional
    omission**, so a correctly-`deferred` BS2/PS3 does *not* trip this breach).
  - **Lineage class is not inclusion authority.** A `label_independent_*` lineage does **not** entitle a
    criterion to `included`/`automatable`: a criterion may carry `label_independent_population` lineage
    yet a `deferred` disposition (BS2). Any criterion whose `validation_disposition` or
    `production_disposition` is `deferred` (or `forbidden`) that nonetheless appears in
    `included_criteria`/`automatable_criteria` — without a satisfied/authorized `decision_dependency` —
    is a breach (kind `deferred_included_without_decision`). BS2 cannot be scored or automated without a
    separate named `bs2-policy` decision; source-independence must never be laundered into approval.
  - `FORBIDDEN_CRITERIA == {c ∈ can_fire : validation_disposition == forbidden}` (kind
    `forbidden_set_drift`); `transitive_suspect == {c : lineage ∈ clinvar_comparator}` (kind
    `transitive_set_drift`).
  - **Intentional subsets are allowed only via an explicit disposition** — no silent omission passes.

### 1.4 `src/raptor/eval/lineage_audit.py` (total audit + separate fail-closed enforcement)

> **Audit and enforcement are two functions.** `audit_lineage` is a **total** function: it always returns
> the complete `LineageAuditReport` (including `blocked=True`), and **never raises merely because blockers
> exist**. `enforce_lineage` is the only place a gate exception is raised. This resolves the prior
> contradiction between §1.4/FR-C7 (audit returns a report, CLI exits non-zero) and AC-L8 (a gate raises).

#### 1.4.1 `detection_source` — the exact advisory enum (defined once here)
`detection_source ∈ {static_lineage, marker_detected, transitive_suspect_only}`, assigned per fired
criterion by this precedence (advisory only — it never sets `lineage_class` or `disposition`):
1. `marker_detected` — the rationale text matched a token in the embedded `markers:` vocab (§1.1).
2. `transitive_suspect_only` — no marker matched **and** the criterion is in the derived
   `transitive_suspect` net (`lineage_class ∈ {cross_variant_clinvar, aggregate_clinvar}`).
   **BP1 with no marker is exactly `transitive_suspect_only`** (the one canonical value tests assert).
3. `static_lineage` — no marker matched and the criterion is not in the transitive net but its policy
   `lineage_class` is still a ClinVar class (`same_variant_clinvar`) — fail-closed static fallback.
`lineage_class` **always** remains the policy taxonomy (e.g. BP1 = `aggregate_clinvar`); `detection_source`
is a separate advisory field and is **never** a lineage-class value.

#### 1.4.2 `audit_lineage(records, policy, scorer_config, eval_config) -> LineageAuditReport` (total)
- Reads the **raw fired criteria** of each `BiasRecord` (`records: Iterable[BiasRecord]`) directly from the
  record's flattened rationale mapping — a criterion is *fired* iff its `(score, text)` tuple has
  `score > 0`. Scored/known calls reuse `parse_rationale`; **unknown/stub codes are classified from the raw
  mapping without requiring `parse_rationale` to succeed on them** (an unrecognized code must never abort
  the audit before it can be reported — see (ii)/(iii) below).
- Per-criterion `{criterion, total_fired, would_be_scored (CP-1), lineage_class, disposition,
  detection_source (§1.4.1), example_variant_ids (bounded, sorted)}` — incidence is reported; **incidence
  never sets lineage/disposition** (those come from `policy`).
- `blocked: bool`, `blocking_criteria`, `content_hash()` (excludes run metadata), `render()`.
- **Fail-closed block rule** (`report.blocked` is set, the audit still returns — it does not raise): a fired
  criterion blocks iff it is (i) `would_be_scored` with disposition ∈
  `{forbidden, requires_heldout_mask, deferred}` and not in `oracle_allowed`; **or** (ii) a code ∉ `can_fire`
  (unknown/stub) fired with non-zero score (supplemental external-call injection, §0.3); **or** (iii) a code
  ∉ `VALID_CRITERIA` fired. Under the current corrected config the scored `requires_heldout_mask` criteria
  **PS1/PM5/PM1/PP2/BP1** set `blocked=True` (§1.5 clarification).
- **Static-vs-dynamic distinction:** membership and disposition are static (from `policy`);
  marker-corroboration is advisory (`detection_source`) and can only *raise* suspicion, never *clear* a
  statically-suspect criterion (BP1 blocks with `detection_source == transitive_suspect_only`, no marker).
- **Deferred criteria are reported, not scored, never silently approved.** A `deferred` criterion (BS2, PS3)
  that fires under the current included set is reported with its raw `total_fired` and `would_be_scored=False`;
  it does **not** block and is **not** served, and does **not** become `allowed` by firing. The corrected
  registry keeps it out of the scored set; if it were ever moved in, rule (i) blocks it (disposition
  `deferred` ∈ the blocking set) until its named `decision_dependency` (e.g. `bs2-policy`) or `oracle_allowed`
  authorizes it — BS2 can never silently become approved. Direct-copy `forbidden` (PS4/PP5/BP6) is likewise
  reported with counts, `would_be_scored=False`, and never blocks by itself.

#### 1.4.3 `enforce_lineage(report) -> None` (the only gate)
- Raises typed `LineageGateError(report)` **iff `report.blocked`** (the exception carries the full report);
  returns `None` on a clean report. `audit_lineage` never calls it.
- **Adapter preflight** calls `audit_lineage(...)` then `enforce_lineage(report)` (audit → enforce).
- **Malformed policy/input** may still raise its own typed error (`LineagePolicyError`,
  `LineageRegistryMismatchError`, a source-contract error) — those are distinct from `LineageGateError`,
  which is reserved for a well-formed-but-`blocked` report.

#### 1.4.4 `scripts/bias_lineage_audit.py` — standalone CLI (exact contract)
- **Signature:** a **positional** BIAS TSV path plus a **required** `--output REPORT_JSON`:
  `bias_lineage_audit.py BIAS_TSV --output REPORT_JSON [--policy configs/eval/bias_lineage.yaml]`.
  Loads the policy + the full BIAS TSV via `BiasTsvSource` (the pinned 18-column contract; **never** a label
  file), runs `audit_lineage`.
- **Persistence + stdout:** always writes the canonical deterministic report JSON to `REPORT_JSON` **and**
  emits the **same canonical JSON** to stdout — regardless of exit code.
- **Exit + enforcement:** calls `enforce_lineage(report)`; exits **0** iff the report is clean, **non-zero**
  iff `report.blocked`. The report is persisted in **both** cases (a blocked run still writes + prints).

### 1.5 Current-config gate outcome (AC-L8 clarification, against the corrected config)
Against the **corrected** valid config (§1.6):
- **Scored → block.** The scored `requires_heldout_mask` criteria still in the included set —
  **PS1, PM5, PM1, PP2, BP1** — are `would_be_scored=True` with a blocking disposition, so `audit_lineage`
  sets `report.blocked=True` and `enforce_lineage(report)` raises `LineageGateError`.
- **Reported, not scored, not blocking.** Raw **PS3** and **BS2** fire but are `would_be_scored=False`
  (deferred, not included — the registry check prevents including a deferred criterion), so they are
  reported and do **not** block under the current config. **Direct-copy PS4/PP5/BP6** are likewise reported
  with counts, `would_be_scored=False`, and do not block by themselves (already `FORBIDDEN`).
- **Unknown/stub supplemental firing → block.** A stub code (∉ `can_fire`) or an unknown code
  (∉ `VALID_CRITERIA`) firing with non-zero score sets `blocked=True` (rules (ii)/(iii)); enforcement raises.

### 1.6 Authorized existing-config corrections (the only production surfaces this task edits)
Exactly two committed config files are corrected (source-verified drift, not weakening):
- **`configs/acmg/tsc.yaml`** — remove `BS3`/`BS4` from `included_criteria`; in the `acmg_criteria`
  registry, **replace the `BS3`/`BS4` entries with source-derived `PS3` and `BS2`** (direction +
  strength-vocab only, for registry/vocab presence) so the registry equals `can_fire` (§0.2). Neither PS3
  nor BS2 is added to `included_criteria`; BS2 stays `deferred`.
- **`configs/eval/tsc2.yaml`** — remove `BS3`/`BS4` from `automatable_criteria` (keeping
  `included_criteria == automatable_criteria`).
No other existing production surface is edited. New files (config `bias_lineage.yaml`, the three modules,
the CLI, and tests) are created per §1.1–§1.4.

### 1.7 Boundaries (carried, enforced by tests)
- No import of `raptor.eval.knowns`/`benchmark`; never opens benchmark/held-out/label artifacts
  (static import/path audit in a **new** module).
- No AGPL BIAS import/copy; policy holds citations + facts only.

---

## 2. Acceptance criteria (test-author writes these; independent oracle only)

- **AC-L1 (mechanical) — can-fire oracle is static.** A test **independently** enumerates can-fire by
  reading the pinned BIAS classifiers (evaluator can return >0) and asserts it equals `policy.can_fire`
  (the 19 of §0.2). A criterion with 0 census incidence is still present. Oracle: BIAS source, **not**
  the census, **not** RAPTOR config, **not** the audit output.
- **AC-L2 (mechanical) — 28-slot partition.** `can_fire ⊎ structurally_forbidden == all_28`, disjoint;
  a stub placed in `can_fire` (or vice versa) raises `LineagePolicyError`.
- **AC-L3 (mechanical) — fail-closed schema.** An unknown `lineage_class`, unknown `disposition`, a
  `rationale_markers` token absent from the vocab, a duplicate/missing/unknown criterion code, or a
  wildcard `oracle_allowed` each raises at load; `set(records)==can_fire` enforced.
- **AC-L4 (mechanical) — exact-set meta-tests.** `assert_registry_consistency` raises structured
  `scored_not_can_fire` for injected `{BS3,BS4}` in `included` (D2), `registry_can_fire_drift` for an
  `acmg_criteria` registry carrying `{BS3,BS4}` or omitting `{PS3,BS2}` (i.e. `!= can_fire`),
  `omitted_without_disposition` for an undispositioned omitted can-fire criterion (D1),
  `forbidden_set_drift`/`transitive_set_drift` on injected drift; the **corrected** config (registry ==
  `can_fire`, included == 14, BS2/PS3 deferred) passes.
- **AC-L5 (mechanical) — BP1 transitive net (D3).** On a synthetic BIAS record where BP1 fires with a
  rationale containing **no** ClinVar marker, `audit_lineage` returns a report with `blocked=True`, BP1 in
  `blocking_criteria`, `lineage_class == aggregate_clinvar`, and **`detection_source == transitive_suspect_only`**
  (the exact expected value); `enforce_lineage(report)` raises `LineageGateError`. Proves marker-detection is
  not required to block, and that `audit_lineage` reports rather than raises.
- **AC-L6 (mechanical) — PS3/BS2 dispositioned + lineage ≠ approval (D1).** PS3 resolves to
  `literature_unvalidated`/`deferred`; **BS2 resolves to `label_independent_population` lineage but
  `deferred` validation *and* production disposition with `decision_dependency: bs2-policy`** — its
  label-independent lineage does **not** make it `allowed`. Neither may remain silently omitted: a policy
  missing a disposition for either, **or a `deferred` record missing its `decision_dependency`**, fails
  `load_lineage_policy`/`assert_registry_consistency`.
- **AC-L7 (mechanical) — direct-copy forbidden reported not scored.** PS4/PP5/BP6 appear in the raw report
  with counts/examples, `would_be_scored=False`; `audit_lineage` does not mark them blocking and
  `enforce_lineage` does not raise on their account alone (already `FORBIDDEN`).
- **AC-L8 (mechanical) — audit reports, enforce gates, on scored suspect.** A fired scored criterion with a
  blocking disposition (the `requires_heldout_mask` set **PS1/PM5/PM1/PP2/BP1** under the corrected config)
  makes `audit_lineage` return `report.blocked=True` with those criteria in `blocking_criteria` — the audit
  **does not raise**. `enforce_lineage(report)` then raises `LineageGateError` carrying the full report;
  nothing served. Raw **PS3/BS2** (deferred, not in the included set) are reported with
  `would_be_scored=False` and do **not** block; the registry check forbids including a deferred criterion.
- **AC-L9 (mechanical) — unknown/stub firing fails.** A fired code ∉ `VALID_CRITERIA`, or a stub code
  (∉ `can_fire`) firing with non-zero supplemental score, makes `audit_lineage` set `blocked=True` (kind
  recorded) and `enforce_lineage` raise; it is classified straight from the raw fired mapping and is
  **never** dropped because `parse_rationale` cannot classify an unknown code.
- **AC-L10 (mechanical) — incidence never establishes lineage.** Two audits over the same BIAS records
  but with permuted/duplicated rows yield identical dispositions/`blocked`; a criterion's disposition is
  invariant to its fired count (a 0-count forbidden criterion is still forbidden; a high-count allowed one
  stays allowed). Determinism: identical inputs → identical `content_hash()`. `audit_lineage` is total
  (returns a report either way; only `enforce_lineage` raises).
- **AC-L11 (mechanical) — CLI exact contract.** Invoked as `bias_lineage_audit.py BIAS_TSV --output
  REPORT_JSON` (positional TSV, required `--output`): on a TSV with a scored suspect criterion it exits
  **non-zero**, and on a clean TSV exits **0**. In **both** cases it writes the canonical report JSON to
  `REPORT_JSON` **and** prints the **same canonical JSON** to stdout. Uses `BiasTsvSource` (18-column
  contract), never a label file.
- **AC-L12 (evidence-form) — label-blind + arm's-length.** New import/path audit proves
  `lineage_policy.py`/`lineage_registry.py`/`lineage_audit.py` never import
  `raptor.eval.knowns`/`benchmark`, never open label/benchmark/held-out files, and never import any
  `bias_2015`/AGPL BIAS module. A unique benchmark-truth sentinel placed only in a label file is absent
  from policy, audit state, and report. (Do not blacklist ordinary `P`/`B`/pathogenic/benign strings.)
- **AC-L13 (mechanical) — BS2 stays deferred; source-independence is not approval.** Proves BS2 cannot be
  scored/automated without a separate named policy decision:
  - **(a) valid intentional omission.** BS2 is absent from `included_criteria`/`automatable_criteria`,
    and because its disposition is `deferred` with `decision_dependency: bs2-policy`, that omission
    **passes** `assert_registry_consistency` (no `omitted_without_disposition` breach).
  - **(b) not includable by lineage.** Injecting BS2 into `included_criteria`/`automatable_criteria`
    while its disposition is `deferred` and `bs2-policy` is unsatisfied raises
    `LineageRegistryMismatchError(kind=deferred_included_without_decision)` — its
    `label_independent_population` lineage does **not** authorize inclusion.
  - **(c) reported, not scored, not approved.** On a BIAS output where BS2 fires, the audit reports its
    raw `total_fired` with `would_be_scored=False` and neither blocks nor serves it; BS2 never silently
    becomes `allowed`/approved by firing.

---

## 3. Definition-of-Ready doer task specs (≤4 reference files each; sequenced Policy → Registry → Audit)

### 3.1 Task — lineage policy + config
```yaml
task_id: bias-lineage-policy
goal: Persist configs/eval/bias_lineage.yaml (28/19/9 sets + per-criterion lineage records + embedded markers vocab) and a fail-closed loader.
reference_files:            # <=4
  - src/raptor/eval/config.py                 # VALID_CRITERIA / FORBIDDEN_CRITERIA / load pattern
  - src/raptor/scorer/config.py               # ScorerConfig loader + schema-validate idiom
  - docs/DECISIONS.md                         # ADR-0009 direct-copy vs transitive lineage
  - docs/prompts/bias-lineage/slot1-planner.md # BIAS v3.0.0 rationale phrasings -> markers vocab (no separate marker file)
acceptance_criteria: [AC-L1, AC-L2, AC-L3, AC-L6]
invert_failure_modes:
  - "Deriving can_fire from the census fired-set (13) instead of static evaluators (19) -> PS4/PM1/PP2/BS1/BP1/BP6 wrongly dropped."
  - "Copying a lineage class from the rationale English text -> BP1 mis-classed label_independent (its loader is ClinVar)."
  - "Silent default-allow for an unrecognized lineage_class/disposition/marker -> fail-open."
  - "Reusing a nonexistent configs/eval/clinvar_markers.yaml instead of embedding the markers vocab in bias_lineage.yaml (single source of truth)."
  - "Reading BS2's label_independent_population lineage as approval -> disposition set to allowed instead of deferred, or a deferred record left without its decision_dependency (bs2-policy)."
```

### 3.2 Task — exact-set registry meta-checks
```yaml
task_id: bias-lineage-registry
goal: assert_registry_consistency comparing can_fire vs acmg_criteria registry vs included vs automatable vs forbidden vs transitive (structured typed errors), AND correct configs/acmg/tsc.yaml + configs/eval/tsc2.yaml (drop phantom BS3/BS4; registry -> can_fire via source-derived PS3/BS2).
reference_files:
  - src/raptor/eval/lineage_policy.py         # (from 3.1) LineagePolicy accessors
  - configs/acmg/tsc.yaml                     # included_criteria + acmg_criteria registry (corrected here)
  - configs/eval/tsc2.yaml                    # automatable_criteria (corrected here)
  - src/raptor/eval/combine.py                # CP-1 scored-set semantics (must not diverge)
acceptance_criteria: [AC-L4, AC-L6, AC-L7, AC-L13]
invert_failure_modes:
  - "Accepting BS3/BS4 in included_criteria (phantom automation) -> policy asserts criteria BIAS can't emit."
  - "Leaving BS3/BS4 in the acmg_criteria registry (or omitting PS3/BS2) so registry != can_fire -> registry_can_fire_drift not caught."
  - "Adding PS3/BS2 to included_criteria/automatable_criteria when correcting the registry -> only the registry equals can_fire; included stays 14, BS2 deferred."
  - "Allowing an omitted can-fire criterion with no disposition -> PS3/BS2 leak past the gate unrecorded."
  - "Auto-including BS2 because its lineage is label_independent_population -> laundering source-independence into policy approval; BS2 needs the separate named bs2-policy decision (stays deferred)."
```

### 3.3 Task — output audit + fail-closed gate + CLI
```yaml
task_id: bias-lineage-audit
goal: total audit_lineage over BiasRecord fired calls (always returns report incl. blocked=True) + separate enforce_lineage raising LineageGateError iff blocked; standalone CLI (positional TSV + required --output).
reference_files:
  - src/raptor/scorer/parse.py                # parse_rationale (fired calls, faithful to every criterion)
  - src/raptor/scorer/bias_source.py          # BiasTsvSource (committed 18-column TSV boundary)
  - src/raptor/eval/lineage_policy.py         # (from 3.1) static disposition source of truth
  - data/census/tsc_vus_clinvar_2026-07-07_stats.json  # incidence annotation only (never lineage)
acceptance_criteria: [AC-L5, AC-L8, AC-L9, AC-L10, AC-L11, AC-L12]
invert_failure_modes:
  - "Making audit_lineage raise on blockers instead of returning a total report -> AC-L8/L10 (only enforce_lineage raises)."
  - "Requiring parse_rationale to classify an unknown/stub code before the audit can report it -> AC-L9 unknown-firing dropped."
  - "Clearing a statically-suspect criterion because no ClinVar marker matched -> BP1 leaks (D3); BP1 must be detection_source=transitive_suspect_only, blocked."
  - "CLI without a required --output, or not printing the same canonical JSON to stdout, or not persisting a blocked report -> AC-L11."
  - "Letting incidence set/relax a disposition -> a 0-count forbidden criterion wrongly passes, or usage 'proves' safety."
  - "Importing a label/benchmark file or a bias_2015 module into the audit -> R-A2 / AGPL breach."
```

na_allowed: false · out_of_scope: running BIAS/Nirvana; the Oracle ruling on the transitive bucket;
changing thresholds; the CI lower-bound gate; VUS scoring.
