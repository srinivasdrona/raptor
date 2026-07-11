# Slot 3 — PRD-04 Task B (surfaces) preservation and inversion

## Preserve — frozen, byte-unchanged (§9.1; the checker fails any diff that touches these)

- `src/raptor/scorer/**` — the scorer stays criterion-level; surfaces only render packet fields.
- `src/raptor/eval/**` (esp. `combine.py`, `harness.py`) — **not** imported by any surface module; census
  patterns are selection metadata, never a restated eval combiner.
- `src/raptor/kb/store.py` — no KB read/write from the surface path.
- **`src/raptor/packet/model.py`** — Task-A output: do **not** edit; consume the packet, `NarrativePlan`,
  `PacketView`, and `redact_for_first_pass` and extend only in the new surface modules.
- No code, tests, configs, existing PRDs, strategy, program, decisions, or risk documents are modified
  beyond the authorized Task-B outputs.

New coverage is **append-only in NEW modules** (§9.2): `src/raptor/packet/{render,queue}.py`,
`configs/packet/{render,selection,narrative_templates}.yaml`, and the Task-B `tests/packet/**`.

## Task-specific failure modes to invert (PRD §11.2 `invert_failure_modes` — verbatim)

1. **Freeform-fact leak (item 3).** A narrative plan with an unknown `template_id` or an unresolved field
   path renders anyway. Fix: the template-constrained narrative plan is mechanically decidable — every
   `template_id ∈ catalog` and every bound path resolves to a packet field, else **fail loud**; reviewer
   freeform lives only in `reviewer_notes`, excluded from the generated narrative (AC9).
2. **Impossible-cell coverage (item 7).** Calibration coverage enumerates a Cartesian product of empty
   cells. Fix: deterministic set coverage over **populated observed atoms only**, per-dimension, never a
   cross-product; the report distinguishes populated/covered/impossible-unpopulated (AC12).
3. **Eval counts become a production oracle (item 6).** Census patterns are used as direction cutoffs.
   Fix: census pattern facts are **selection metadata pinned to the census snapshot**, never cutoffs or
   criteria inclusion (AC12).
4. **First-pass double-blinding breach (r3-2).** The candidate direction, signed points, or the AAVC
   comparator appear in the `FIRST_PASS` render/projection. Fix: `redact_for_first_pass` +
   `render_markdown(..., view=FIRST_PASS)` strip **both** the RAPTOR candidate direction (and signed
   points / policy id / census direction label) **and** the entire `external_comparators` envelope, while
   retaining per-criterion strength/direction (AC4/AC20).
5. **Reviewer sees a machine direction (r3-2).** The queue/reviewer-delivery surface serves the full /
   `OPERATOR` view instead of the `FIRST_PASS` projection. Fix: the queue index and reviewer-delivery
   surface consume **only** the `FIRST_PASS` projection; the full JSON / `OPERATOR` view is never a
   first-pass reviewer input (AC20).

If any implementation shortcut weakens one of these assertions, **stop** rather than editing a frozen
file (including Task-A `model.py`) or a pre-authored test.
