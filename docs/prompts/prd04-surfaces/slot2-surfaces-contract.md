# Slot 2 — PRD-04 Task B: surfaces (render + queue + calibration)

## Contract

- **Task:** `prd04-packet-surfaces`
- **Goal:** Deterministic Markdown render with template-narrative-plan expansion + CSV/JSONL queue index
  + calibration-batch selection with populated-atom coverage, over the Task-A packet.
- **Motivating artifact:** `docs/prd/PRD-04-candidate-evidence-packet.md`
  (r3, source commit `9adbd7b`; read especially §4.3 output surfaces, §4.4 no-false-authority /
  first-pass blinding, §4.6 review scaling, FR7 narrative plan, FR17 coverage, §10.3 module layout,
  §11.2 task spec).
- **Sequencing:** second of three sequenced doer tasks (A → B → C).
- **Depends on:** `prd04-packet-core` (Task A) — consumes its `model.py` packet + `NarrativePlan` +
  `PacketView` + `redact_for_first_pass`; do not edit Task-A output.

## Context surface

Create only:

- `src/raptor/packet/config.py` — extend Task-A config with Task-B render/narrative/selection models
  and strict path loaders; do not change Task-A model behavior
- `src/raptor/packet/render.py` — deterministic Markdown; template expansion; markers unavoidable in
  OPERATOR/RECONCILIATION; `PacketView` views; `FIRST_PASS` strips direction + comparator
- `src/raptor/packet/queue.py` — CSV/JSONL queue (from `FIRST_PASS` projection) + `select_calibration_batch`
  + `coverage_report`
- `configs/packet/render.yaml`   — deterministic render options + non-authoritative markers (FR14) +
  first-pass comparator-hiding rule (FR27)
- `configs/packet/selection.yaml` — calibration selection policy (observed-atom coverage dims + pinned
  seed) + census snapshot id
- `configs/packet/narrative_templates.yaml` — approved template catalog (`template_id` → body with named
  field slots) for FR7

Do not create the core (Task A) or workflow (Task C) modules. Do not edit any frozen file (§9.1),
including Task-A `src/raptor/packet/model.py`.

## Reference files (four maximum — PRD §11.2)

1. `src/raptor/packet/model.py`   — Task-A packet + `NarrativePlan` + `PacketView` + `redact_for_first_pass` (dependency)
2. `src/raptor/scorer/report.py`  — deterministic render/canonicalization pattern
3. `data/census/tsc_vus_clinvar_2026-07-07_stats.json` — 30 observed patterns; 238/1,333; 1,222 (coverage oracle)
4. `docs/reference/aavc-prior-art-audit-2026-07.md` — first-pass double-blinding rule (both machine directions)

## Public API (copied verbatim from PRD §10.3 — implement exactly; you may add, never weaken)

- **`render.py`** — `render_markdown(packet, config, *, view: PacketView) -> str`: deterministic template
  expansion of the narrative plan (FR7); non-authoritative markers + state + gate status unavoidable in
  `OPERATOR`/`RECONCILIATION`; the `FIRST_PASS` render consumes `redact_for_first_pass` and carries no
  candidate direction / signed points / comparator (FR10/FR14/FR14.1/FR27/AC20).
- **`queue.py`** — `build_queue_index(packets, config) -> QueueIndex` (CSV + JSONL, built from the
  `FIRST_PASS` projection for reviewer delivery) + `select_calibration_batch(packets, selection_config)
  -> Batch` + `coverage_report(...)` distinguishing populated/covered/impossible atoms
  (FR11/FR13/FR17), deterministic.

## Exact Task-B schemas and signatures

Task B extends `packet.config` with frozen models and path-only loaders:

- `NarrativeTemplate(template_id: str, body: str, required_bindings: tuple[str, ...])`.
- `NarrativeCatalog(config_version: str, templates: Mapping[str, NarrativeTemplate])`.
- `RenderConfig(config_version: str, non_authoritative_marker: str,
  first_pass_heading: str, operator_heading: str, reconciliation_heading: str,
  narrative_catalog: NarrativeCatalog)`.
- `SelectionConfig(config_version: str, census_snapshot_id: str, seed: int,
  required_dimensions: tuple[str, ...], expected_atoms: Mapping[str, tuple[str, ...]])`.
  `required_dimensions` is exactly `pattern | gene | variant_class | edge_flag`; expected atoms may
  declare known catalog atoms but never create a Cartesian product.
- `load_narrative_catalog(path: str | Path) -> NarrativeCatalog`,
  `load_render_config(path: str | Path) -> RenderConfig`,
  `load_selection_config(path: str | Path) -> SelectionConfig`; unknown/missing/blank fields raise
  `PacketConfigError`. `render.yaml` references `narrative_templates.yaml` by repository-relative path.

Task B defines these frozen output models in `queue.py`:

- `QueueRow(packet_id: str, evidence_core_hash: str, canonical_spdi: str, gene: str,
  review_state: str, gate_status: str, quality_flags: tuple[str, ...], contradiction: bool)`.
  It deliberately has no candidate direction, points, policy id, pattern stratum, or comparator.
- `QueueIndex(rows: tuple[QueueRow, ...])` with deterministic `to_csv() -> str` and
  `to_jsonl() -> str`; rows sort by `(gene, canonical_spdi, packet_id)`.
- `CoverageReport(populated: Mapping[str, tuple[str, ...]],
  covered: Mapping[str, tuple[str, ...]], impossible_unpopulated: Mapping[str, tuple[str, ...]],
  missing: Mapping[str, tuple[str, ...]])`; all keys are the four dimensions, values sorted.
  Coverage is complete iff every populated atom is covered. Impossible/unpopulated is
  `config.expected_atoms[dimension] - populated[dimension]` and is reported, never selected.
- `Batch(packets: tuple[CandidateEvidencePacket, ...], selected_packet_ids: tuple[str, ...],
  coverage: CoverageReport)`.
- `coverage_report(all_packets, selected_packets, selection_config) -> CoverageReport`.
- `select_calibration_batch(packets, selection_config) -> Batch`: universe is the complete input packet
  collection; deterministically chooses a minimal greedy set that first covers each populated
  `pattern_id`, then remaining gene/class/edge atoms, breaking ties by
  `sha256(f"{seed}:{packet_id}")`. It never uses candidate direction or census stratum as a cutoff.
  Re-running with the same universe/config is byte-identical.

`render_markdown(packet, config, *, view: PacketView) -> str` is exact. Narrative field paths use
dot-separated dataclass attributes plus numeric tuple indexes (for example `entries.0.criterion`);
unknown template ids, missing/extra bindings, unresolved paths, or bindings to fields absent from
`FirstPassPacketView` raise `PacketValidationError`. The renderer never evaluates arbitrary
expressions. `FIRST_PASS` calls `redact_for_first_pass` before field resolution and cannot render
candidate/comparator/pattern fields. `OPERATOR` renders candidate direction (including null reason)
only adjacent to the configured non-authoritative marker, review state and gate status.

`configs/packet/narrative_templates.yaml` has exactly `config_version` and a `templates` mapping;
`render.yaml` has exactly the six `RenderConfig` source fields (with
`narrative_templates_path` replacing the loaded object); `selection.yaml` has exactly the five
`SelectionConfig` fields. All are strict, config-driven and carry no hidden defaults.

## Narrative — template-constrained plan (PRD FR7 / §4.4)

The model may **only** select and order **approved template ids** and bind **packet field paths** — a
`NarrativePlan = [ {template_id, field_bindings{path: packet_field_path}} ]`. A deterministic renderer
expands templates against the bound packet fields; the model authors no arbitrary factual text or
citations. Any freeform note is reviewer-authored, lives in `reviewer_notes`, is excluded from the
generated narrative, and is never marked fact-safe. The check is mechanically decidable: every
`template_id ∈ catalog` and every bound path resolves to an existing packet field, else **fail loud**.

## First-pass double-blinding (PRD §4.4 FR14.1 / AC20 — enforce in every delivery surface)

`redact_for_first_pass(packet)` and `render_markdown(..., view=FIRST_PASS)` contain **no**
`candidate_direction`, `null_reason`, `signed_points`/`per_criterion_points`, candidate-direction policy
id/version, census-selection direction label, or `external_comparators` key/value — while **retaining**
per-criterion strength/direction and the evidence trail. The queue index and reviewer-delivery surface
consume **only** the `FIRST_PASS` projection; the full JSON / `OPERATOR` view is never delivered as a
first-pass reviewer input.

## Calibration coverage (PRD FR17 / §4.6 — populated observed atoms only)

Deterministic set coverage over **populated observed atoms only**: all 30 observed patterns, each
observed gene, each observed variant class, each observed edge flag — as independent per-dimension
observed sets, **never** a cross-product of empty cells. The census pattern facts (238 candidate-LP, 20
patterns; 1,333 candidate-LB, 10 patterns; BP4 Strong + PM2 Supporting = 1,222) are **selection metadata
pinned to the census snapshot**, never cutoffs. The coverage report distinguishes
`populated`/`covered`/`impossible-unpopulated`; re-run identical.

## Acceptance criteria (PRD §11.2 / §6 — the AC subset this task must satisfy; verbatim)

- **AC9** template-narrative-plan validity (approved templates + resolvable field paths; reviewer notes
  excluded) *(mechanical)*
- **AC12** calibration selection determinism + populated-atom coverage (populated/covered/impossible)
  *(mechanical)*
- **AC13** renderer/queue consistency *(mechanical)*
- **AC4** direction (incl. `null`) never rendered as classification; absent from `FIRST_PASS` *(mechanical)*
- **AC20** first-pass double-blinding: `FIRST_PASS` render/projection strips candidate direction + signed
  points + policy id + comparator; queue/reviewer delivery consume only `FIRST_PASS` *(mechanical)*

Independent oracles: hand-built expected Markdown/queue fixtures (AC13); the census stats file's recorded
counts (AC12) — never the implementation's own output. `na_allowed: false`.

## Out of scope

Packet model/build (Task A); state machine + decision log + comparator reveal (Task C); the LLM
narrative call; any external release.

## Verification

Run the pre-authored Gemini tests for Task B and the full suite; show the frozen preservation set
(including Task-A `model.py`) is byte-unchanged. The GPT checker re-verifies AC9/12/13/4/20 against the
commands in your `VERIFICATION` block.
