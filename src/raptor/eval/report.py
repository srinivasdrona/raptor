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
from dataclasses import InitVar, asdict, dataclass, field
from typing import Any, Dict, List

from .model import DirectionVerdict, GateDecision, Metrics, ScopeGateDecision


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


def _direction_verdict_payload(v: DirectionVerdict) -> dict:
    return {
        "stratum": v.stratum,
        "direction": v.direction,
        "precision_lb": v.precision_lb,
        "recall_lb": v.recall_lb,
        "precision_threshold": v.precision_threshold,
        "recall_threshold": v.recall_threshold,
        "actual_count": v.actual_count,
        "called_count": v.called_count,
        "min_count": v.min_count,
        "coverage_adequate": v.coverage_adequate,
        "metric_status": v.metric_status,
        "scope_status": v.scope_status,
        "reasons": list(v.reasons),
    }


def _scope_gate_payload(scope_gate: ScopeGateDecision) -> dict:
    """v2 scope-gate payload (additive): only ever called when
    `EvalReport.scope_gate is not None` -- `content_hash()` MUST NOT call
    this for a `None` scope_gate (v1 hash back-compat, AC-S7/D2)."""
    return {
        "schema_version": scope_gate.schema_version,
        "scopes": {
            key: _direction_verdict_payload(v) for key, v in sorted(scope_gate.scopes.items())
        },
        "full_spectrum_status": scope_gate.full_spectrum_status,
        "full_spectrum_vus_authorized": scope_gate.full_spectrum_vus_authorized,
        "research_scope_flags": dict(sorted(scope_gate.research_scope_flags.items())),
        "governance_state": scope_gate.governance_state,
        "governance_statement": scope_gate.governance_statement,
        "research_use_disclaimer": scope_gate.research_use_disclaimer,
        "reason": scope_gate.reason,
        "authorization_blockers": sorted(scope_gate.authorization_blockers),
    }


def report_to_dict(report: "EvalReport") -> dict:
    """Pure report-serialization helper (checker finding 5, GPT-5.4):
    `EvalReport.scope_gate` is an `InitVar`-backed plain attribute (not a
    real `dataclasses.fields()` member, see the field docstring below), so
    raw `dataclasses.asdict(report)` never includes a `scope_gate` key
    either way. This helper starts from `asdict(report)` and adds the
    `scope_gate` payload back in ONLY when `report.scope_gate is not None`
    -- a v1-shaped report (`scope_gate is None`) never serializes a
    `scope_gate` key at all (never a `scope_gate: null`), while a v2 report
    includes the full, JSON-safe scope-gate payload. Callers building a
    report envelope (e.g. `scripts/run_masked_holdout_eval.py`) MUST use
    this helper (not raw `asdict(report)`) to get the v2 key back.

    Restored legacy gate contract (Gemini RED, 6491b00): `gate` is a
    mandatory, non-optional `GateDecision` on every real `EvalReport` (base
    v1 contract, commit 329a799) -- there is no gate-less v2 report shape.
    A hand-built report that nonetheless carries `gate is None` (typing
    says non-optional, but nothing stops a caller from constructing one
    with a mocked/bypassed type checker) must fail loud HERE, before any
    serialization is attempted -- defense-in-depth, never silently emit a
    v2-only envelope the legacy builder cannot consume."""
    if report.gate is None:
        raise TypeError(
            "EvalReport.gate is None -- gate is a mandatory legacy (v1) field; "
            "report_to_dict() refuses to serialize a report with no gate decision"
        )
    payload = asdict(report)
    if report.scope_gate is not None:
        payload["scope_gate"] = _scope_gate_payload(report.scope_gate)
    return payload


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
    #: v1 VUS-authorization gate decision (base contract, commit 329a799):
    #: mandatory, non-optional -- there is no gate-less v2 report shape.
    #: `render()`/`content_hash()` may assume a real `GateDecision` here,
    #: exactly as the base did (the v2 `scope_gate` section is additive and
    #: unaffected either way, sec ADR-0011).
    gate: GateDecision
    oracle_blind_findings: List[str] = field(default_factory=list)
    code_version: str = ""
    config_pins: Dict[str, Any] = field(default_factory=dict)
    #: v2 scope-specific authorization gate (ADDITIVE, optional). `None` is
    #: the fully v1-compatible default -- `content_hash()` excludes this key
    #: entirely when `None` so a v1 report's hash is byte-identical (D2/
    #: AC-S7); `render()` only appends a scope-authorization section when
    #: present.
    #:
    #: Checker finding 5 (GPT-5.4): declared as an `InitVar`, NOT a real
    #: `dataclasses.fields()` member, captured into a plain instance
    #: attribute (same public name) by `__post_init__`. This means raw
    #: `dataclasses.asdict(report)`/`dataclasses.fields(report)` never see
    #: a `scope_gate` key at all -- so a v1-shaped report (`scope_gate is
    #: None`) never serializes a `scope_gate: null` key. Reading/writing
    #: `report.scope_gate` afterwards (`self.scope_gate`, `report.scope_gate
    #: = ...`) behaves exactly like a normal attribute -- `content_hash()`/
    #: `render()` are unaffected.
    scope_gate: InitVar["ScopeGateDecision | None"] = None

    def __post_init__(self, scope_gate: "ScopeGateDecision | None" = None) -> None:
        self.scope_gate = scope_gate

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
        # v2 scope-gate (ADDITIVE): only folded into the hash when present --
        # a v1-shaped report (`scope_gate=None`, the default) must hash
        # byte-identically to before this field existed (D2/AC-S7).
        if self.scope_gate is not None:
            payload["scope_gate"] = _scope_gate_payload(self.scope_gate)
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
        nothing legitimate to report a number for. `gate` is mandatory (base
        v1 contract, commit 329a799, restored in 6491b00) -- there is no
        gate-less v2 report shape; the v2 `scope_gate` section (if present)
        is unaffected either way.

        The reserved pooled `overall` stratum IS printed in this general
        descriptive metrics table alongside the per-class strata (base
        v1 contract, commit 329a799) -- it is a purely descriptive,
        cross-class aggregate row here. `overall` is excluded only from the
        v2 scope-specific section below: `_render_scope_gate()`, scope
        authorization, governance reasons, and scope-verdict rendering
        (AC-S5 parity with `decide_scope_gate`), never from this general
        table."""
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
        if self.scope_gate is not None:
            lines.extend(self._render_scope_gate())
        return "\n".join(lines)

    def _render_scope_gate(self) -> List[str]:
        """v2 scope-specific research-authorization section (ADDITIVE) --
        only appended when `scope_gate is not None` (v1 reports render
        unchanged). Never states a bare global "PASS" -- the authoritative
        human-facing output is the narrow research-scope flags plus the
        exact preregistered governance statement and the separate,
        mandatory `research_use_disclaimer` (never merged into the
        statement text)."""
        sg = self.scope_gate
        lines: List[str] = []
        lines.append("--- v2 scope-specific research authorization (preregistered, non-clinical) ---")
        lines.append(f"scope_gate schema_version: {sg.schema_version}")
        lines.append("scopes:")
        for key, v in sorted(sg.scopes.items()):
            precision_t_str = f"{v.precision_threshold:.4f}" if isinstance(v.precision_threshold, (int, float)) else "none"
            recall_t_str = f"{v.recall_threshold:.4f}" if isinstance(v.recall_threshold, (int, float)) else "none"
            lines.append(
                f"  - {key}: metric_status={v.metric_status} coverage_adequate={v.coverage_adequate} "
                f"scope_status={v.scope_status} precision_lb={v.precision_lb:.4f} "
                f"recall_lb={v.recall_lb:.4f} precision_threshold>={precision_t_str} "
                f"recall_threshold>={recall_t_str} actual_count={v.actual_count} "
                f"called_count={v.called_count} min_count={v.min_count}"
            )
        lines.append(f"full_spectrum_status: {sg.full_spectrum_status}")
        lines.append(f"full_spectrum_vus_authorized: {sg.full_spectrum_vus_authorized}")
        lines.append("research_scope_flags:")
        for name, flag in sorted(sg.research_scope_flags.items()):
            lines.append(f"  - {name}={flag}")
        lines.append(f"governance_state: {sg.governance_state}")
        lines.append(f"governance_statement: {sg.governance_statement}")
        lines.append(f"research_use_disclaimer: {sg.research_use_disclaimer}")
        if sg.authorization_blockers:
            lines.append("authorization_blockers:")
            for blocker in sorted(sg.authorization_blockers):
                lines.append(f"  - {blocker}")
        else:
            lines.append("authorization_blockers: none")
        lines.append(f"scope_gate reason: {sg.reason}")
        return lines
