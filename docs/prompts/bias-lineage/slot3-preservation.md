# Slot 3 — Preservation & inversion guard (BIAS lineage audit & fail-closed gate)

## Preserve (semantics that must not change)

- **Scorer parsing faithfulness.** `parse_rationale` still emits **every** fired criterion (incl.
  PP5/BP6/PS4/PS1/PM5/PM1/PP2/BP1/PS3) — the lineage audit consumes those calls; it must not change
  which calls the parser produces. The frozen oracle
  (`tests/scorer/test_oracle_parsing.py`, `fixtures/bias_output_slice.tsv`, `expected_evidence.json`)
  stays byte-unchanged.
- **CP-1 scored-set semantics.** `combine.implied_direction`'s scored set is the sole would-be-scored
  predicate. The audit must agree with it and **never** diverge; `oracle_allowed` gates only the BLOCK
  disposition, never the combiner's scored set.
- **FORBIDDEN_CRITERIA structural ban.** `eval.config.FORBIDDEN_CRITERIA = {PP5,BP6,PS4}` and its
  load-time/combiner enforcement remain; the tsc.yaml/tsc2.yaml PP5/BP6/PS4 exclusions stay.
- **eval = production parity.** `included_criteria == automatable_criteria` remains an asserted invariant.
- **Labels boundary (R-A2/H1).** No benchmark/held-out/label file is reachable from the policy loader,
  registry check, or audit; the census file is read for **incidence annotation only**, never for lineage.
- **Arm's-length AGPL boundary (ADR-0007).** RAPTOR never imports or copies `bias_2015`/AGPL BIAS code.
  The policy carries lineage **facts + source citations** (file·symbol·line), never BIAS source text.
- **Config-as-policy.** The can-fire set, lineage classes, dispositions, transitive-suspect set, **and the
  version-pinned `markers:` vocabulary** live in `configs/eval/bias_lineage.yaml` (schema-validated), never
  hardcoded in the audit code and never in a separate `clinvar_markers.yaml` (which does not exist).
- **Audit ≠ enforcement.** `audit_lineage` is total — it always returns the complete report (including
  `blocked=True`) and never raises merely because blockers exist; only `enforce_lineage(report)` raises
  `LineageGateError` (iff `report.blocked`). `detection_source ∈ {static_lineage, marker_detected,
  transitive_suspect_only}` is advisory and separate from the policy `lineage_class` taxonomy.

## Reconciliations the doer MAY make (not weakening — correcting source-verified drift)

- Removing the **phantom** `BS3`/`BS4` from `included_criteria`/`automatable_criteria` (they are BIAS
  stubs and can never fire), **and** correcting the `configs/acmg/tsc.yaml::acmg_criteria` registry so it
  equals `can_fire` (the 19): the BS3/BS4 registry entries are replaced by source-derived `PS3`/`BS2`
  (direction/strength-vocab only — neither is included/automatable; BS2 stays `deferred`). This is a
  correction, not a test/config weakening. `configs/acmg/tsc.yaml` and `configs/eval/tsc2.yaml` are the
  **only** two existing production surfaces this task edits.
- Adding explicit dispositions for `PS3` (deferred — assay-validity review) and `BS2` (**deferred** —
  its population/control source is label-independent, but a TSC-specific penetrance/age/mosaicism policy
  decision is still owed; `decision_dependency: bs2-policy`, PROGRAM.md item 6). **Lineage class is not
  approval:** BS2's label-independent source must not be promoted to `allowed`, `included`, or
  `automatable` without the named `bs2-policy` decision.
- Expanding the fail-closed `transitive_suspect` net to the full ADR-0009 static-lineage set
  `[PS1, PM5, PM1, PP2, BP1]` (PRD-08's `[PM5,PM1,PP2]` was incomplete — amended).

## Prohibited (weakening tests/config to match an implementation)

- Do **not** shrink `policy.can_fire` to the census fired-set (13) so the audit "passes"; the oracle is
  static (evaluator can return >0), not dynamic incidence.
- Do **not** relax the fail-closed schema to default-allow an unrecognized lineage class, disposition, or
  marker.
- Do **not** clear a statically-suspect criterion because no ClinVar marker matched.
- Do **not** add BS3/BS4 to `can_fire` (or any stub) to make the partition test pass.
- Do **not** move a criterion into `oracle_allowed` to silence a block; `oracle_allowed` stays empty
  until a named Oracle decision.
- Do **not** promote `BS2` (or any `label_independent_*` criterion) into `included`/`automatable`, or to
  an `allowed` disposition, on the basis of its lineage class. Source-independence is **not** policy
  approval: BS2 stays `deferred` with `decision_dependency: bs2-policy` until that named decision is made.
- Do **not** treat a stub's supplemental (external-call) firing as impossible; a nonzero stub firing is
  fail-closed and must block unless explicitly authorized — never silently no-op'd.
- Do **not** import a label/benchmark file or any `bias_2015` module to make a test convenient.
- Do **not** make `audit_lineage` raise on blockers; it must return a total report (`blocked=True`) — only
  `enforce_lineage` raises `LineageGateError`. The adapter calls audit→enforce; the CLI audits, persists +
  prints, then enforces/exits non-zero.
- Do **not** reintroduce a `configs/eval/clinvar_markers.yaml` dependency; the `markers:` vocab is embedded
  in `bias_lineage.yaml` (single source of truth) and every record's `rationale_markers` is validated against it.
- Do **not** overload `detection_source` onto `lineage_class`, or emit a fake lineage class for a
  marker-invisible criterion: BP1's `lineage_class` stays `aggregate_clinvar` and its
  `detection_source` is `transitive_suspect_only` (the exact expected value).
- Do **not** leave `configs/acmg/tsc.yaml::acmg_criteria` carrying phantom BS3/BS4 (or omitting PS3/BS2):
  the registry must equal `can_fire` (kind `registry_can_fire_drift`), while `included`/`automatable` stay
  14 and PS3/BS2 remain unincluded.

## Highest-risk inversion failures

1. **Dynamic-incidence lineage laundering.** Treating the 6,618-row census fired-set as the can-fire set
   (or letting a high fired-count "prove" a criterion safe / a 0-count criterion irrelevant). This
   silently drops the six can-fire-but-0-count criteria (PS4/PM1/PP2/BS1/BP1/BP6) from the gate and lets
   a scored ClinVar-derived criterion re-enter through usage frequency. **Guard:** AC-L1/AC-L10 — static
   oracle; disposition invariant to fired count.

2. **Marker-only detection misses BP1 (marker-invisible transitive).** BP1's rationale
   ("…where {path_per} of pathogenic variants are truncating…") contains **no** ClinVar token, yet its
   `truncating_gene_to_data` comparator is built from a ClinVar VCF. A marker-scan-only gate clears BP1
   and leaks a ClinVar-derived criterion graded against ClinVar labels (R-A2). **Guard:** AC-L5 —
   static-lineage/`transitive_suspect` net blocks BP1 with `detection_source != marker_detected`.

3. **Phantom-automation / coincidental-19 fail-open.** Trusting the docs' "19/28 automated" and RAPTOR's
   19-registry, so BS3/BS4 (stubs that can never fire) count as automated while PS3/BS2 (can-fire,
   omitted) leak past the gate undispositioned. The gate must reject `included ⊄ can_fire` and any
   omitted-can-fire-without-disposition, resolving the exact set from source rather than forcing 19.
   **Guard:** AC-L4/AC-L6 — `scored_not_can_fire` + `omitted_without_disposition` structured breaches.

4. **Lineage-laundering — source-independence read as policy approval.** Treating BS2's
   `label_independent_population` lineage as if it were an `allowed`/inclusion decision: setting BS2 to
   `allowed`, or silently promoting it into `included_criteria`/`automatable_criteria`, or scoring it.
   BS2's population/control source is label-independent, but the TSC-specific penetrance/age/mosaicism
   call is a **separate, still-pending** policy decision (`decision_dependency: bs2-policy`, PROGRAM.md
   item 6) this task does **not** make. **Guard:** AC-L6/AC-L13 — BS2 carries `deferred` validation +
   production disposition with a required `decision_dependency`; it is a valid intentional omission,
   cannot be included without the named decision (`deferred_included_without_decision`), and fires only as
   reported-not-scored (`would_be_scored=False`), never silently approved.

No production code, tests, strategy, program, or risk documents are modified by this planning task. The
untracked `docs/prd/PRD-04-candidate-evidence-packet.md` is neither modified nor deleted.
