#!/usr/bin/env python
"""Slot 3 — `scripts/build_pp3bp4_revel_mave_concordance.py` — non-gating
REVEL/MAVE functional concordance CLI (RAPTOR PP3/BP4 shadow policy, steps
2-7).

`build_mave_concordance_report` is a pure helper (Slot 2 Rule 7): MAVE
functional class/value is passed only to the concordance layer here, never
to the REVEL policy/classifier. The injected scorer receives ONLY a
`variant_id` -- never a MAVE functional class/value. The real report stays
`BLOCKED_DATA` while no attested REVEL score table exists; a synthetic
NON_GATING path may demonstrate the mechanism but never authorizes or
calibrates policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

#: Mandatory, separate disclaimer -- never merged into any governance/decision
#: statement, and never omitted (Rule 10). Contains the literal phrase
#: "research use only" (T-F1).
MAVE_RESEARCH_USE_DISCLAIMER = (
    "Research use only. This non-gating MAVE/REVEL functional concordance analysis "
    "authorizes no clinical classification, VUS worklist, ClinVar submission, "
    "calibration, or terminal-gate decision."
)

_DEFAULT_POLICY = "configs/eval/pp3bp4_candidate_policy.json"
_DEFAULT_SOURCE_REGISTER = "configs/eval/pp3bp4_source_register.yaml"


class MaveStatus(str, Enum):
    """Closed MAVE concordance status set. A `str` mixin so a caller may
    compare against either the enum member or the raw string value."""

    BLOCKED_DATA = "BLOCKED_DATA"
    NON_GATING = "NON_GATING"


@dataclass
class MaveConcordanceReport:
    """A non-gating REVEL/MAVE concordance result (Rule 7/T-F1).

    `gating_type` is ALWAYS `"NON_GATING"` regardless of `status`;
    `is_calibrated`/`clinical_use_authorized` are always `False` -- this
    report never authorizes or calibrates PP3/BP4 policy."""

    status: MaveStatus
    gating_type: str
    is_calibrated: bool
    clinical_use_authorized: bool
    disclaimer: str
    missing_artifact: str | None = None
    source: str | None = None
    policy_call_x_functional_class: dict = field(default_factory=dict)
    limitations: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value if isinstance(self.status, MaveStatus) else str(self.status),
            "gating_type": self.gating_type,
            "is_calibrated": self.is_calibrated,
            "clinical_use_authorized": self.clinical_use_authorized,
            "disclaimer": self.disclaimer,
            "missing_artifact": self.missing_artifact,
            "source": self.source,
            "policy_call_x_functional_class": dict(sorted(self.policy_call_x_functional_class.items())),
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _score_lookup_from_validated_rows(validated_rows: list[dict]) -> Callable[[str], float | None]:
    by_id = {row["variant_id"]: row.get("score") for row in validated_rows}

    def _lookup(variant_id: str) -> float | None:
        return by_id.get(variant_id)

    return _lookup


def _try_classify(score: float | None, policy: Any) -> str | None:
    """Best-effort REVEL classification for descriptive concordance display
    ONLY -- never required, never fed back into `policy`/`scorer` (Rule 7).
    Silently omitted when `policy` does not carry full pp3/bp4/indeterminate
    threshold config (e.g. a minimal duck-typed test policy)."""
    if score is None:
        return None
    if not (hasattr(policy, "pp3") and hasattr(policy, "bp4") and hasattr(policy, "indeterminate")):
        return None
    from raptor.eval.pp3bp4_candidate_policy import classify_revel

    return classify_revel(score, policy).name


def build_mave_concordance_report(
    score_table_path: str | Path | None = None,
    mave_data_path: str | Path | None = None,
    *,
    mave_records: list[dict] | None = None,
    validated_rows: list[dict] | None = None,
    attestation: Any = None,
    policy: Any = None,
    scorer: Callable[[str], float | None] | None = None,
) -> MaveConcordanceReport:
    """Build a non-gating REVEL/MAVE concordance report.

    `BLOCKED_DATA` when no validated score source (`validated_rows` +
    `attestation`, or an explicit `scorer`) is available -- e.g. when
    `score_table_path` is `None`/missing. Otherwise `NON_GATING`: MAVE
    records are matched to REVEL scores by `variant_id` ONLY (the scorer/
    lookup receives a single positional `variant_id` argument, never a
    functional class/value)."""
    if scorer is None and validated_rows is not None:
        scorer = _score_lookup_from_validated_rows(validated_rows)

    if scorer is None or (score_table_path is None and validated_rows is None):
        if scorer is None:
            return MaveConcordanceReport(
                status=MaveStatus.BLOCKED_DATA,
                gating_type="NON_GATING",
                is_calibrated=False,
                clinical_use_authorized=False,
                disclaimer=MAVE_RESEARCH_USE_DISCLAIMER,
                missing_artifact=(
                    "no attested structured REVEL score table is available "
                    f"(score_table_path={score_table_path!r})"
                ),
                source=str(mave_data_path) if mave_data_path is not None else None,
                limitations=[
                    "no REVEL dev score table has been produced or attested",
                    "this report demonstrates no MAVE/REVEL concordance value",
                ],
            )

    policy_call_x_functional_class: dict[str, dict] = {}
    for record in mave_records or []:
        variant_id = record["variant_id"]
        score = scorer(variant_id)
        call = _try_classify(score, policy) if policy is not None else None
        policy_call_x_functional_class[variant_id] = {
            "functional_class": record.get("functional_class"),
            "policy_call": call,
        }

    return MaveConcordanceReport(
        status=MaveStatus.NON_GATING,
        gating_type="NON_GATING",
        is_calibrated=False,
        clinical_use_authorized=False,
        disclaimer=MAVE_RESEARCH_USE_DISCLAIMER,
        missing_artifact=None,
        source=str(mave_data_path) if mave_data_path is not None else "injected mave_records",
        policy_call_x_functional_class=policy_call_x_functional_class,
        limitations=[
            "non-gating demonstration only; no clinical calibration or authorization",
            "MAVE functional class/value never reaches the REVEL policy/classifier",
        ],
    )


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_artifact_payload(*, report_date: str, policy_path: str, source_register_path: str) -> dict:
    """Build the deterministic `tsc2-pp3bp4-revel-mave-concordance/1`
    payload (content_hash excluded, added by the caller). The real
    artifact is always `BLOCKED_DATA` today -- no attested REVEL dev score
    table exists yet to compare against any MAVE scoreset."""
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy

    _, provenance = load_candidate_policy(policy_path, source_register_path)
    report = build_mave_concordance_report(score_table_path=None, mave_data_path=None)

    payload = {
        "schema": "tsc2-pp3bp4-revel-mave-concordance/1",
        "status": "BLOCKED_DATA",
        "validation_mode": "NON_GATING",
        "report_date": report_date,
        "policy_source_sha256": provenance.policy_source_sha256,
        "source_register_sha256": provenance.source_register_sha256,
        "source": "no MAVE scoreset wired for REVEL comparison yet",
        "missing_artifact": report.missing_artifact,
        "policy_call_x_functional_class": {},
        "limitations": report.limitations,
        "research_use_disclaimer": MAVE_RESEARCH_USE_DISCLAIMER,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-date", required=True, help="explicit report date/as-of (never wall clock)")
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--source-register", default=_DEFAULT_SOURCE_REGISTER)
    parser.add_argument("--output", required=True, type=Path, help="artifact output path")
    args = parser.parse_args(argv)

    payload = build_artifact_payload(
        report_date=args.report_date,
        policy_path=args.policy,
        source_register_path=args.source_register,
    )
    content_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    payload["content_hash"] = content_hash

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_bytes(payload))

    print(json.dumps({"status": payload["status"], "content_hash": content_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
