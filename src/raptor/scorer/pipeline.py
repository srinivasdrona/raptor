"""PRD-01 sec 10.4 `pipeline.py` — FR2-FR8: parse -> policy -> write-to-KB.

`run_scorer` enforces conservation (R-A10): every input `BiasRecord` is
accounted for as exactly one of {emitted evidence set (possibly empty, if
no included criterion fired), a manual-review routing} -- never a silent
drop. A source-contract/reproducibility breach (e.g. `BiasContractError`
surfacing from the injected `bias_source`) is NEVER caught into the manual
queue here -- it propagates (fail loud, matches the PRD-02 `run_ingest`
`ReferenceChecksumMismatchError` precedent) all the way out of
`run_scorer`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .bias_source import BiasSource
from .config import ScorerConfig
from .contract import BiasContractError
from .model import EvidenceRecord, ManualReviewItem
from .parse import parse_rationale
from .policy import assert_no_double_count, check_edge_cases, check_out_of_scope_gene
from .report import ScorerReport


def _config_pins(config: ScorerConfig) -> dict[str, Any]:
    pins_dict = getattr(config, "pins_dict", None)
    if callable(pins_dict):
        try:
            return pins_dict()
        except Exception:
            return {}
    return {}


def run_scorer(config: ScorerConfig, bias_source: BiasSource, store: Any) -> ScorerReport:
    """For each `BiasRecord` from `bias_source`: parse -> policy (edge-case
    routing / no-double-count) -> stage grounded `EvidenceRecord`s or a
    `ManualReviewItem`; then `store.publish(run_id)`.

    Stages the scorer's full criterion vocabulary (`config.acmg_criteria`)
    for registration into the KB's `evidence_kinds` reference table
    (FR9/AC7 extensibility hook) -- migration 0001 seeds only 9
    (tier, criterion) pairs and the scorer emits more. Staged, not written
    eagerly: registration is applied atomically inside `store.publish()`
    (before staged evidence rows, so the FK is satisfied) and rolled back
    with everything else if the run fails, so a failed run never mutates
    `evidence_kinds` (PRD-01 sec 10.3 no-state-change-on-failure).
    """
    run_id = uuid.uuid4().hex
    generated_at = datetime.now(timezone.utc).isoformat()

    # Materialize the input once so the pre-flight source-contract check
    # below runs BEFORE any KB mutation (validate-before-mutate). BIAS
    # output is a source-contract: exactly one row per variant_id. A
    # repeated variant_id is drift/corruption in the upstream BIAS output,
    # not a per-record failure -- fail loud (never route to manual) and
    # leave published state (incl. `evidence_kinds`) completely untouched
    # (auditability, R-A10-adjacent: a failed run is a no-op).
    records = list(bias_source.records())
    seen_variant_ids_preflight: set[str] = set()
    for record in records:
        vid = record.variant_id
        if vid in seen_variant_ids_preflight:
            raise BiasContractError(
                f"duplicate variant_id {vid!r} in BIAS output — "
                "source-contract violation (one row per variant expected)"
            )
        seen_variant_ids_preflight.add(vid)

    for criterion, spec in (config.acmg_criteria or {}).items():
        store.stage_evidence_kind(
            run_id,
            tier="tier1",
            criterion=criterion,
            direction=spec["direction"],
            strength_vocab=list(spec["strength_vocab"]),
        )

    tool_version = f"bias-wrapper:{config.bias_version}"
    env_versions = {
        "bias_version": str(config.bias_version),
        "bias_data_version": str(config.bias_data_version),
    }
    pins = _config_pins(config)
    included = set(config.included_criteria or [])

    def _provenance() -> str:
        return store.build_provenance(
            tool_version=tool_version,
            source="bias_output",
            source_snapshot_version=str(config.bias_data_version),
            env_versions=env_versions,
            originating_run=run_id,
            timestamp=generated_at,
        )

    total_input = 0
    seq_in_run = 0
    evidence_records: list[EvidenceRecord] = []
    manual_queue_records: list[ManualReviewItem] = []
    variant_outcomes: list[dict[str, str]] = []
    seen_variant_ids: set[str] = set()

    def _route_to_manual(
        *, record, reason: str, failure_stage: str, error_code: str,
        attempted_coords: str, source_ref_id, row_provenance: str,
    ) -> None:
        item = ManualReviewItem(
            variant_id=record.variant_id,
            reason=reason,
            failure_stage=failure_stage,
            error_code=error_code,
            attempted_coords=attempted_coords,
            raw_input=record.variant_id,
        )
        manual_queue_records.append(item)
        store.stage_manual_queue(
            run_id,
            raw_input=item.raw_input,
            source_ref_id=source_ref_id,
            failure_stage=item.failure_stage,
            error_code=item.error_code,
            reason=item.reason,
            config_pins=pins,
            provenance=row_provenance,
            created_at=generated_at,
            attempted_coords=item.attempted_coords,
        )
        variant_outcomes.append({"variant_id": record.variant_id, "outcome": "manual_review"})

    try:
        for record in records:
            total_input += 1

            # Pre-flight (above, pre-mutation) already validated no
            # duplicate variant_ids exist; this is a defensive assert only.
            vid = record.variant_id
            assert vid not in seen_variant_ids, (
                f"unexpected duplicate variant_id {vid!r} past pre-flight check"
            )
            seen_variant_ids.add(vid)

            row_provenance = _provenance()
            attempted_coords = (
                f"{record.chromosome}:{record.position}:{record.ref_allele}:{record.alt_allele}"
            )

            source_ref_id = store.stage_source_ref(
                run_id,
                source="bias_output",
                snapshot_id=str(config.bias_data_version),
                snapshot_date=str(config.bias_data_version),
                source_file_checksum="n/a",
                raw_value=attempted_coords,
                provenance=row_provenance,
                accession=record.variant_id,
                row_locator=attempted_coords,
                resolver_status="resolved",
            )

            # R-A3/v1-scope: a gene RAPTOR has no pinned policy for must
            # never be silently scored -- ALWAYS on, not gated by
            # `edge_cases` (unlike the predicates in check_edge_cases).
            out_of_scope_reason = check_out_of_scope_gene(record, config)
            if out_of_scope_reason is not None:
                _route_to_manual(
                    record=record,
                    reason=out_of_scope_reason,
                    failure_stage="scope_check",
                    error_code="OUT_OF_SCOPE_GENE",
                    attempted_coords=attempted_coords,
                    source_ref_id=source_ref_id,
                    row_provenance=row_provenance,
                )
                continue

            # FR8: edge-case routing takes precedence over auto-scoring --
            # never silently scored (R-A3).
            edge_case_reason = check_edge_cases(record, config)
            if edge_case_reason is not None:
                _route_to_manual(
                    record=record,
                    reason=edge_case_reason,
                    failure_stage="edge_case_routing",
                    error_code="EDGE_CASE_ROUTED",
                    attempted_coords=attempted_coords,
                    source_ref_id=source_ref_id,
                    row_provenance=row_provenance,
                )
                continue

            # FR4: parse is faithful to EVERY fired criterion (PP5/BP6
            # included) -- policy decides what's actually emitted below.
            all_calls = parse_rationale(record.criteria, config.strength_map)
            assert_no_double_count(all_calls)

            included_calls = sorted(
                (c for c in all_calls if c.criterion in included), key=lambda c: c.criterion
            )
            if not included_calls:
                # Accounted for (R-A10): zero included criteria fired, so
                # nothing to write -- not an edge case, not a drop.
                variant_outcomes.append(
                    {"variant_id": record.variant_id, "outcome": "no_evidence"}
                )
                continue

            assert_no_double_count(included_calls)

            # §10.3/10.7: an emitted strength must be within that
            # criterion's configured strength_vocab -- a fired criterion
            # whose mapped strength falls outside its vocab must NEVER be
            # emitted with a nonsensical strength; route the whole record
            # to manual review instead (conservation, R-A10: the variant
            # gets exactly one outcome, not a mix of scored+manual).
            out_of_vocab_call = None
            for call in included_calls:
                vocab = (config.acmg_criteria.get(call.criterion) or {}).get(
                    "strength_vocab", []
                )
                if call.strength not in vocab:
                    out_of_vocab_call = call
                    break
            if out_of_vocab_call is not None:
                _route_to_manual(
                    record=record,
                    reason=(
                        f"strength_out_of_vocab: criterion {out_of_vocab_call.criterion!r} "
                        f"fired with strength {out_of_vocab_call.strength!r}, which is not in "
                        f"its configured strength_vocab {config.acmg_criteria.get(out_of_vocab_call.criterion, {}).get('strength_vocab')!r}"
                    ),
                    failure_stage="strength_validation",
                    error_code="STRENGTH_OUT_OF_VOCAB",
                    attempted_coords=attempted_coords,
                    source_ref_id=source_ref_id,
                    row_provenance=row_provenance,
                )
                continue

            store.stage_variant(
                run_id,
                variant_id=record.variant_id,
                gene=record.gene_name,
                class_=record.variant_type,
                provenance=row_provenance,
                source_ref_ids=source_ref_id,
            )

            for call in included_calls:
                store.stage_evidence_added(
                    run_id,
                    seq_in_run=seq_in_run,
                    variant_id=record.variant_id,
                    tier="tier1",
                    criterion=call.criterion,
                    strength=call.strength,
                    direction=call.direction,
                    source_ref_id=source_ref_id,
                    row_provenance=row_provenance,
                    event_provenance=row_provenance,
                    event_timestamp=generated_at,
                    supporting_record=call.rationale,
                )
                seq_in_run += 1
                evidence_records.append(
                    EvidenceRecord(
                        variant_id=record.variant_id,
                        tier="tier1",
                        criterion=call.criterion,
                        strength=call.strength,
                        direction=call.direction,
                        rationale=call.rationale,
                        gene_name=record.gene_name,
                        transcript=record.transcript,
                    )
                )
            variant_outcomes.append({"variant_id": record.variant_id, "outcome": "scored"})

        store.publish(run_id)
    except Exception:
        # A contract/reproducibility breach (e.g. BiasContractError from
        # the source, or a publish() failure) must propagate -- never get
        # swallowed into a manual-queue item. This only cleans up any
        # not-yet-published staging for this run before re-raising.
        discard = getattr(store, "discard_staging", None)
        if callable(discard):
            try:
                discard(run_id)
            except Exception:
                pass
        raise

    return ScorerReport.build(
        run_id=run_id,
        generated_at=generated_at,
        total_input=total_input,
        evidence_records=evidence_records,
        manual_queue=manual_queue_records,
        variant_outcomes=variant_outcomes,
    )

