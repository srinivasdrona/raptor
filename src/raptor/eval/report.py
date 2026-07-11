"""PRD-06 sec 10.3 `report.py` — `EvalReport` + `render()` (FR10/AC9).

`EvalReport.content_hash()` follows the same pattern as `IngestReport`/
`ScorerReport` (PRD-02/PRD-01): a function only of deterministic content --
`run_id`/`generated_at` (run metadata) are excluded (R-A11). `render()`
produces the versioned results text: a result is citable only if it states
the labels/benchmark snapshot, per-class held-out size, every metric, and
the threshold status (met / not-met / not-yet-set -- EVAL_PLAN sec 5).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .model import GateDecision, Metrics


def _metrics_payload(metrics: Dict[str, Metrics]) -> dict:
    return {
        stratum: {
            "precision": m.precision,
            "recall": m.recall,
            "concordance": m.concordance,
            "benign_precision": m.benign_precision,
            "benign_recall": m.benign_recall,
            # Gate-fidelity (Arm C, additive): the 95% Clopper-Pearson lower
            # bounds the gate actually compares against -- included in the
            # content hash so two runs differing only in lower-bound math
            # (e.g. a stats.py regression) are NOT reported identical (AC7
            # determinism is preserved: same inputs -> same lower bounds ->
            # same hash; it is not weakened, only made more complete).
            "precision_lb": m.precision_lb,
            "recall_lb": m.recall_lb,
            "benign_precision_lb": m.benign_precision_lb,
            "benign_recall_lb": m.benign_recall_lb,
            "counts": dict(sorted(m.counts.items())),
            "gating": m.gating,
        }
        for stratum, m in sorted(metrics.items())
    }


def _per_stratum_payload(per_stratum: dict) -> dict:
    """Gate-fidelity (Arm C, additive): the `GateDecision.per_stratum` verdicts,
    JSON-safe and sorted, folded into the content hash so a per-stratum verdict
    change (e.g. `truncating` flipping FAIL) is never hash-invisible."""
    return {
        name: {
            "precision_lb": v.precision_lb,
            "recall_lb": v.recall_lb,
            "threshold": dict(sorted(v.threshold.items())),
            "met": v.met,
            "gating": v.gating,
            "powered": v.powered,
        }
        for name, v in sorted(per_stratum.items())
    }


@dataclass
class EvalReport:
    run_id: str
    generated_at: str
    labels_snapshot: str
    benchmark_size: int
    train_dev_size: int
    holdout_size: int
    holdout_label_counts: Dict[str, int]
    holdout_class_counts: Dict[str, int]
    metrics: Dict[str, Metrics]
    gate: GateDecision
    oracle_blind_findings: List[str] = field(default_factory=list)
    code_version: str = ""
    config_pins: Dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """Deterministic-content hash (FR9/AC7): excludes `run_id` and
        `generated_at` -- two runs on identical pinned inputs/config must
        produce an identical hash regardless of when/under-what-run-id they
        ran (R-A11). `code_version`/`config_pins` ARE included: both are
        constant/pinned across runs on the same inputs, so this stays
        deterministic (AC7) while restoring provenance (FR9)."""
        payload = {
            "labels_snapshot": self.labels_snapshot,
            "benchmark_size": self.benchmark_size,
            "train_dev_size": self.train_dev_size,
            "holdout_size": self.holdout_size,
            "holdout_label_counts": dict(sorted(self.holdout_label_counts.items())),
            "holdout_class_counts": dict(sorted(self.holdout_class_counts.items())),
            "metrics": _metrics_payload(self.metrics),
            "gate": {
                "status": self.gate.status,
                "stratum": self.gate.stratum,
                "reason": self.gate.reason,
                "vus_authorized": self.gate.vus_authorized,
                "per_stratum": _per_stratum_payload(self.gate.per_stratum),
            },
            "oracle_blind_findings": sorted(self.oracle_blind_findings),
            "code_version": self.code_version,
            "config_pins": json.loads(json.dumps(self.config_pins, sort_keys=True, default=str)),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def render(self) -> str:
        """The versioned `BENCHMARK_RESULTS`-style report text (FR10/AC9):
        states benchmark/labels snapshot, per-class held-out size, every
        metric, and threshold status. Gate-fidelity (Arm C): per-stratum
        lower bound + pre-registered threshold are both shown `.4f`-formatted
        (Python's default float repr of `0.90` is `"0.9"` -- no trailing
        zero -- so a raw `repr()` would not satisfy an auditor grepping for
        the exact pinned value). When `gate.status == "BLOCKED_POLICY"` (the
        terminal masked-rerun harness only) no metrics table is printed at
        all -- there is no authorized predictor-policy artifact, so there is
        nothing legitimate to report a number for."""
        lines: List[str] = []
        lines.append("RAPTOR Eval Report (PRD-06)")
        lines.append(f"run_id: {self.run_id}")
        lines.append(f"generated_at: {self.generated_at}")
        lines.append(f"code version: {self.code_version}")
        lines.append(f"config pins: {dict(sorted(self.config_pins.items()))}")
        lines.append(f"labels snapshot / benchmark version: {self.labels_snapshot}")
        lines.append(f"benchmark size: {self.benchmark_size}")
        lines.append(f"train/dev size: {self.train_dev_size}")
        lines.append(
            f"held-out size: {self.holdout_size} "
            f"(by label: {dict(sorted(self.holdout_label_counts.items()))}, "
            f"by class: {dict(sorted(self.holdout_class_counts.items()))})"
        )
        if self.gate.status == "BLOCKED_POLICY":
            lines.append(
                "metrics by stratum: WITHHELD -- gate status is BLOCKED_POLICY "
                "(no approved bp4pp3-predictor-policy artifact; no metric is authorized "
                "to be reported)"
            )
        else:
            lines.append("metrics by stratum:")
            for stratum, m in sorted(self.metrics.items()):
                lines.append(
                    f"  - {stratum}: precision={m.precision:.4f} recall={m.recall:.4f} "
                    f"concordance={m.concordance:.4f} benign_precision={m.benign_precision:.4f} "
                    f"benign_recall={m.benign_recall:.4f} "
                    f"precision_lb={m.precision_lb:.4f} recall_lb={m.recall_lb:.4f} "
                    f"benign_precision_lb={m.benign_precision_lb:.4f} "
                    f"benign_recall_lb={m.benign_recall_lb:.4f} "
                    f"counts={dict(sorted(m.counts.items()))} gating={m.gating}"
                )
                verdict = self.gate.per_stratum.get(stratum)
                if verdict is not None:
                    threshold = verdict.threshold or {}
                    precision_t = threshold.get("precision")
                    recall_t = threshold.get("recall")
                    precision_t_str = f"{precision_t:.4f}" if isinstance(precision_t, (int, float)) else "unset"
                    recall_t_str = f"{recall_t:.4f}" if isinstance(recall_t, (int, float)) else "unset"
                    lines.append(
                        f"    threshold: precision>={precision_t_str} recall>={recall_t_str} "
                        f"(95% CI lower bound) met={verdict.met} powered={verdict.powered} "
                        f"gating={verdict.gating}"
                    )
        if self.gate.status == "UNVERIFIED":
            threshold_status = "not-yet-set (UNVERIFIED)"
        elif self.gate.status == "PASS":
            threshold_status = "met"
        elif self.gate.status == "UNDERPOWERED":
            threshold_status = "not-evaluated (UNDERPOWERED -- stratum non-gating)"
        else:
            threshold_status = "not-met"
        lines.append(
            f"gate: status={self.gate.status} stratum={self.gate.stratum} "
            f"threshold status={threshold_status} vus_authorized={self.gate.vus_authorized}"
        )
        lines.append(f"gate reason: {self.gate.reason}")
        if self.oracle_blind_findings:
            lines.append("oracle-blind findings:")
            for finding in self.oracle_blind_findings:
                lines.append(f"  - {finding}")
        else:
            lines.append("oracle-blind findings: none")
        return "\n".join(lines)
