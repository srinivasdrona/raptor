"""PRD-02 sec 10.3 `pipeline.py` — FR2/FR4/FR5/AC1: read -> normalize -> route -> write-to-KB.

`run_ingest` enforces AC1 conservation (`|input| = |normalized| + |queued|`,
0 dropped): every input row is staged as exactly one of a published
variant or a manual-queue record, each grounded (AC4) via a staged
`source_ref`, then published atomically through the injected `KBStore`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from .model import ManualQueueItem, NormalizedVariant
from .normalizer import ReferenceChecksumMismatchError
from .report import IngestReport


def _config_pins(config: object) -> dict[str, Any]:
    pins_dict = getattr(config, "pins_dict", None)
    if callable(pins_dict):
        try:
            return pins_dict()
        except Exception:
            return {}
    return {}


def run_ingest(config: object, reader: Iterable, normalizer: object, store: object) -> IngestReport:
    """FR2/FR4: read every row from `reader`, normalize it, and write the
    outcome to `store` (the injected PRD-03 `KBStore`) before publishing.

    Conservation (AC1) is structural: every row produces exactly one of a
    staged `NormalizedVariant` or `ManualQueueItem` -- a normalizer
    exception is caught per-row and itself routed to the manual queue
    (never a silent drop, R-A10) rather than aborting the whole run.
    """
    run_id = uuid.uuid4().hex
    generated_at = datetime.now(timezone.utc).isoformat()

    normalizer_cfg = dict(getattr(config, "normalizer", {}) or {})
    tool_version = f"{type(normalizer).__name__}:{normalizer_cfg.get('version', 'unknown')}"
    env_versions = {
        "normalizer_tool": str(normalizer_cfg.get("tool", "")),
        "normalizer_version": str(normalizer_cfg.get("version", "")),
        "assembly": str(getattr(config, "assembly", "")),
        "assembly_patch": str(getattr(config, "assembly_patch", "")),
        "mane_release": str(getattr(config, "mane_release", "")),
    }
    snapshot_version = str(getattr(config, "clinvar_snapshot_id", "") or "")
    pins = _config_pins(config)

    def _provenance() -> str:
        return store.build_provenance(
            tool_version=tool_version,
            source="clinvar_variant_summary",
            source_snapshot_version=snapshot_version,
            env_versions=env_versions,
            originating_run=run_id,
            timestamp=generated_at,
        )

    total_input = 0
    normalized_records: list[NormalizedVariant] = []
    manual_queue_records: list[ManualQueueItem] = []
    staged_variant_ids: set[str] = set()

    try:
        for raw in reader:
            total_input += 1
            row_provenance = _provenance()
            source_ref_id = store.stage_source_ref(
                run_id,
                source="clinvar_variant_summary",
                snapshot_id=raw.snapshot_id,
                snapshot_date=raw.snapshot_date,
                source_file_checksum=raw.source_file_checksum,
                raw_value=raw.raw_source_value,
                provenance=row_provenance,
                accession=raw.variation_id,
                row_locator=raw.row_locator,
                resolver_status="resolved",
            )

            try:
                outcome = normalizer.normalize(raw, config)
            except ReferenceChecksumMismatchError:
                # R-A11/FR8: a whole-run reproducibility breach -- fail loud,
                # never quietly route around it a row at a time (never into
                # the manual queue like a per-row normalization failure).
                raise
            except Exception as exc:  # R-A10: never let a per-row crash vanish the input
                coords = f"{raw.chromosome}:{raw.position}:{raw.ref}:{raw.alt}"
                outcome = ManualQueueItem(
                    raw_input=raw.raw_source_value,
                    source_ref=raw.variation_id,
                    failure_stage="normalize",
                    error_code="NORMALIZER_EXCEPTION",
                    reason=f"normalizer raised {type(exc).__name__}: {exc}",
                    attempted_coords=coords,
                    tool_error=repr(exc),
                    config_pins=pins,
                    run_id=run_id,
                    excluded_from_scorer=True,
                )

            if isinstance(outcome, NormalizedVariant):
                normalized_records.append(outcome)
                class_value = getattr(outcome.variant_class, "value", outcome.variant_class)
                if outcome.variant_id in staged_variant_ids:
                    # Collision policy (sec 2.1): many source rows -> one
                    # variant_id is expected -- link this row's source_ref
                    # to the already-staged variant rather than
                    # re-inserting (which would violate the variants PK).
                    store.stage_variant_source_ref(
                        run_id,
                        variant_id=outcome.variant_id,
                        source_ref_id=source_ref_id,
                        provenance=row_provenance,
                    )
                else:
                    store.stage_variant(
                        run_id,
                        variant_id=outcome.variant_id,
                        gene=outcome.gene,
                        class_=class_value,
                        provenance=row_provenance,
                        source_ref_ids=source_ref_id,
                        hgvs_g=outcome.hgvs_g,
                        hgvs_c=outcome.hgvs_c,
                        hgvs_p=outcome.hgvs_p,
                        hgvs_c_null_reason=outcome.hgvs_c_null_reason,
                        hgvs_p_null_reason=outcome.hgvs_p_null_reason,
                    )
                    staged_variant_ids.add(outcome.variant_id)
            elif isinstance(outcome, ManualQueueItem):
                manual_queue_records.append(outcome)
                store.stage_manual_queue(
                    run_id,
                    raw_input=outcome.raw_input,
                    source_ref_id=source_ref_id,
                    failure_stage=outcome.failure_stage,
                    error_code=outcome.error_code,
                    reason=outcome.reason,
                    config_pins=dict(outcome.config_pins or {}) or pins,
                    provenance=row_provenance,
                    created_at=generated_at,
                    attempted_coords=outcome.attempted_coords,
                    tool_error=outcome.tool_error,
                    excluded_from_scorer=1,
                )
            else:
                raise TypeError(f"normalizer returned unexpected outcome type: {type(outcome)!r}")

        store.publish(run_id)
    except Exception:
        # FR4: a failed run discards staging rather than leaving partial
        # state (publish() already does this on its own failures; this
        # covers failures earlier in the loop, e.g. a broken store call).
        discard = getattr(store, "discard_staging", None)
        if callable(discard):
            try:
                discard(run_id)
            except Exception:
                pass
        raise

    return IngestReport.build(
        run_id=run_id,
        generated_at=generated_at,
        total_input=total_input,
        normalized=normalized_records,
        manual_queue=manual_queue_records,
    )
