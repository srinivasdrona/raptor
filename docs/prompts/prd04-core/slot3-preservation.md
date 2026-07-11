# Slot 3 — PRD-04 Task A (packet core) preservation and inversion

## Preserve — frozen, byte-unchanged (§9.1; the checker fails any diff that touches these)

- `src/raptor/scorer/**`, `tests/scorer/**` (esp. `tests/scorer/test_ac6_no_trace_cribbing.py` + the
  parsing oracle) — the packet **consumes** `CriterionCall`/`EvidenceRecord` **shapes** via an injected
  `PacketInput`; it does not modify or re-tier the scorer.
- `src/raptor/eval/**` (esp. `combine.py`, `harness.py`, `lineage_policy.py`/`lineage_registry.py`/
  `lineage_audit.py`) — **not** imported by packet generation; the packet consumes `load_lineage_policy`
  **output** only (FR4.1) and never edits the policy or invents lineage. A *production*
  candidate-direction policy is a **separate** config-pinned surface (FR5), never the eval combiner.
- `configs/eval/bias_lineage.yaml` — read-only lineage source of record.
- `src/raptor/kb/store.py` public API + its tests — the packet reads **no** KB table directly and writes
  **no** `classification_versions` row this increment (the KB→`PacketInput` adapter is a future surface,
  §10.6).
- The frozen held-out / labels artifacts and their PRD-06/PRD-07 loaders — no packet module reads them;
  the packet reads an injected `PacketInput` (FR24/AC3).
- No code, tests, configs, existing PRDs, strategy, program, decisions, or risk documents are modified
  beyond the authorized Task-A outputs (§10.3). New code lands only under `src/raptor/packet/**`,
  `configs/packet/**`, `tests/packet/**`.

New coverage is **append-only in NEW modules** (§9.2): the Task-A `src/raptor/packet/{model,build,
direction,hashing,config}.py`, `configs/packet/{schema,candidate_direction}.yaml`, and the Task-A
`tests/packet/**`.

## Task-specific failure modes to invert (PRD §11.1 `invert_failure_modes` — verbatim)

1. **Eval / production / label leak (H1).** Packet build imports `eval.combine` or reads a
   label/benchmark/KB file. Fix: assemble from the injected `PacketInput`; import no `eval.*` combiner;
   read no label/benchmark/oracle/KB file (structural + forbidden-path/import audit, AC3).
2. **R-A2 circularity (ADR-0009).** A forbidden (PP5/BP6/PS4) criterion is scored, not excluded. Fix:
   `validation == forbidden` → **excluded** with `direct_copy_forbidden` (AC7/AC22).
3. **Lineage drift (item 10).** The packet invents its own lineage instead of reading
   `bias_lineage.yaml`. Fix: consume `load_lineage_policy` output; preserve **both** raw dispositions
   verbatim; never invent lineage in code (AC7).
4. **Disposition-precedence breach (r3-1).** A `requires_heldout_mask` criterion (PS1/PM5/PM1/PP2/BP1)
   resolves to `included` because `production == allowed`. Fix: validation dominates —
   `requires_heldout_mask` → **masked regardless of production** (AC7/AC22).
5. **Silent-`included` default (r3-1).** An unmapped disposition combination silently defaults to
   `included` instead of failing loud. Fix: the exhaustive precedence **fails loud** on any unknown
   pairing; never silently `included` (AC22).
6. **Eval combiner becomes a production oracle (item 6).** `candidate_direction` is emitted non-null
   under an unapproved policy. Fix: unapproved policy → `candidate_direction=null,
   null_reason=production_policy_unapproved`, `POLICY_BLOCKED`; census pattern facts are selection
   metadata, never cutoffs; no `eval.combine` restated (AC4/AC6).
7. **Provenance laundering (item 2 / r3-5).** A BIAS row is constructed as a `PrimaryEvidenceRef`, or a
   `ScorerProvenance` drops a required field. Fix: pinned two-level provenance — exactly one all-required
   `ScorerProvenance` (a BIAS row, distinct type, **never** primary); `PrimaryEvidenceRef`
   resolved/unresolved predicate; unknown `primary_required` fails closed (AC5/AC21).
8. **Non-deterministic core (R-A11).** `evidence_core_hash` includes the narrative/comparator/`run_id`.
   Fix: the evidence core excludes narrative, comparators, and run metadata; the four hash domains are
   distinct and stable (AC2/AC19).

If any implementation shortcut weakens one of these assertions, **stop** rather than editing a frozen
file or a pre-authored test.
