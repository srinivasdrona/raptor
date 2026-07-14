#!/usr/bin/env python3
"""Run the real masked held-out evaluation through RAPTOR's terminal gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from raptor.eval.benchmark import build_benchmark
from raptor.eval.config import load_config as load_eval_config
from raptor.eval.harness import run_eval
from raptor.eval.live_source import BiasEvidenceSource
from raptor.eval.mask_attestation import verify_mask_attestation
from raptor.eval.model import GateDecision, LabeledVariant, ScopeGateDecision
from raptor.eval.report import report_to_dict
from raptor.eval.predictor_aggregation import load_aggregation_spec
from raptor.eval.predictor_policy import (
    PredictorPolicyError,
    load_predictor_policy,
    verify_predictor_policy_hashes,
)
from raptor.eval.scope_gate import decide_scope_gate
from raptor.eval.split import split_benchmark
from raptor.eval.terminal_source import (
    PredictorCorrectedEvidenceSource,
    ProductionVocabEvidenceSource,
)
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.model import NormalizedVariant, RawVariant
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer
from raptor.scorer.config import load_config as load_scorer_config

_AGGREGATION_SPEC = ROOT / "configs" / "eval" / "predictor_aggregation.yaml"
_CORRECTION_CODE = (
    ROOT / "src" / "raptor" / "eval" / "predictor_aggregation.py",
    ROOT / "src" / "raptor" / "eval" / "terminal_source.py",
)
_REBUILT_MASKED_CRITERIA = frozenset({"PS1", "PM5", "PP2", "BP1"})
_ALLOWED_SKIPPED_CRITERIA = frozenset({"PM1"})
_MANIFEST_LINE_RE = re.compile(r"^([0-9a-fA-F]{64}) \*(.+)$")


def _blocked(reason: str) -> GateDecision:
    return GateDecision(
        status="BLOCKED_POLICY",
        stratum="",
        reason=reason,
        vus_authorized=False,
        per_stratum={},
    )


def compute_report_scope_gate(
    metrics: dict,
    config,
    skipped: set[str] | None = None,
) -> ScopeGateDecision | None:
    """Legacy-runner-compatible pure helper (checker finding 3): compute the
    v2 `report.scope_gate` value WITHOUT executing a real gate run.

    Returns `None` when `config.scope_authorization` is absent -- the
    runner must then attach NO `scope_gate` at all, preserving v1 report
    hash/render/envelope byte-for-byte. When present, computes
    `decide_scope_gate` and applies the same fail-closed parity-skip
    demotion as the v1 gate: any evaluation-only criterion exclusion
    (`skipped`) that would otherwise let a scope/full-spectrum authorization
    stand is withheld (forced to the most restrictive, `NONE_VALIDATED`
    state) -- a skipped criterion can never authorize a research scope.
    """
    if config.scope_authorization is None:
        return None

    decision = decide_scope_gate(metrics, config)
    skipped = skipped or set()
    if skipped and (
        decision.full_spectrum_vus_authorized or any(decision.research_scope_flags.values())
    ):
        decision = ScopeGateDecision(
            schema_version=decision.schema_version,
            scopes=decision.scopes,
            full_spectrum_status="UNVERIFIED",
            full_spectrum_vus_authorized=False,
            research_scope_flags={name: False for name in decision.research_scope_flags},
            governance_state="NONE_VALIDATED",
            governance_statement=config.scope_authorization["governance_statements"]["NONE_VALIDATED"],
            research_use_disclaimer=decision.research_use_disclaimer,
            reason=(
                "all scope metric thresholds may have passed, but evaluation-only criterion "
                f"exclusions {sorted(skipped)!r} break full production parity; never authorize "
                "a research scope on a parity break"
            ),
        )
    return decision


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_return_manifest(path: Path) -> dict[str, str]:
    """Verify the flat returned package against its x64 SHA-256 manifest."""
    if not path.is_file():
        raise ValueError(f"return manifest does not exist: {path}")
    verified: dict[str, str] = {}
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        match = _MANIFEST_LINE_RE.match(raw_line.strip())
        if match is None:
            raise ValueError(f"malformed return-manifest line {line_no}: {raw_line!r}")
        expected, remote_path = match.groups()
        name = Path(remote_path.replace("\\", "/")).name
        if name in verified:
            raise ValueError(f"duplicate return-manifest basename: {name}")
        local_path = path.parent / name
        if not local_path.is_file():
            raise ValueError(f"returned artifact missing locally: {name}")
        actual = _sha256(local_path)
        if actual.lower() != expected.lower():
            raise ValueError(
                f"returned artifact hash mismatch for {name}: expected={expected} actual={actual}"
            )
        verified[name] = actual
    if not verified:
        raise ValueError("return manifest contains no artifacts")
    return verified


def _verify_return_control_files(
    verified_return: dict[str, str],
    return_dir: Path,
    *,
    automatable_criteria,
    declared_skips: set[str],
) -> tuple[set[str], set[str]]:
    """Require x64 success and a manifest-bound, operator-acknowledged skip list."""
    status_name = "TERMINAL_STATUS.txt"
    skip_name = "evaluation_skip_list.txt"
    for name in (status_name, skip_name):
        if name not in verified_return:
            raise ValueError(f"required control file {name} is not covered by the return manifest")
    status = (return_dir / status_name).read_text(encoding="utf-8").strip()
    if status != "SCORED_MASKED":
        raise ValueError(
            f"x64 terminal status must be 'SCORED_MASKED', got {status!r}"
        )
    operational_skips = {
        line.strip().upper()
        for line in (return_dir / skip_name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    evaluation_skips = operational_skips.intersection(
        {str(value).strip().upper() for value in automatable_criteria}
    )
    if declared_skips != evaluation_skips:
        raise ValueError(
            f"declared skipped criteria {sorted(declared_skips)!r} do not equal "
            f"the returned evaluation exclusions {sorted(evaluation_skips)!r}"
        )
    return operational_skips, evaluation_skips


def _require_verified_return_artifact(
    verified_return: dict[str, str],
    return_dir: Path,
    path: str | Path,
    *,
    label: str,
) -> None:
    candidate = Path(path).resolve()
    expected = (return_dir / candidate.name).resolve()
    if candidate != expected:
        raise ValueError(
            f"{label} must be read from the verified return directory: "
            f"expected={expected} got={candidate}"
        )
    if candidate.name not in verified_return:
        raise ValueError(
            f"{label} {candidate.name} is not covered by the return manifest"
        )


class _CanonicalBiasNormalizer:
    def __init__(self, reference_root: Path, ingest_config_path: Path) -> None:
        self._config = load_ingest_config(ingest_config_path)
        self._normalizer = SeqRepoGenomicNormalizer(reference_root)

    def normalize(
        self,
        chromosome: str,
        position: int,
        ref: str,
        alt: str,
        accession: str,
    ) -> str:
        raw = RawVariant(
            chromosome=accession,
            position=position,
            ref=ref,
            alt=alt,
            gene="",
            variation_id="",
            snapshot_id="masked-heldout-eval",
            snapshot_date="",
            source_file_checksum="",
            row_locator=f"{chromosome}:{position}",
            raw_source_value=f"{chromosome}:{position}:{ref}:{alt}",
        )
        outcome = self._normalizer.normalize(raw, self._config)
        if not isinstance(outcome, NormalizedVariant):
            raise ValueError(
                f"failed to canonicalize BIAS row {raw.raw_source_value}: "
                f"{outcome.error_code}: {outcome.reason}"
            )
        return outcome.variant_id


def _load_frozen_benchmark(path: Path, labels_snapshot: str) -> list[LabeledVariant]:
    required = frozenset({"variant_id", "label", "variant_class", "source", "snapshot"})
    rows: list[LabeledVariant] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"benchmark line {line_no} is invalid JSON") from exc
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError(
                f"benchmark line {line_no} fields must be exactly {sorted(required)!r}"
            )
        if row["snapshot"] != labels_snapshot:
            raise ValueError(
                f"benchmark line {line_no} snapshot {row['snapshot']!r} != {labels_snapshot!r}"
            )
        rows.append(
            LabeledVariant(
                variant_id=str(row["variant_id"]),
                label=str(row["label"]),
                review_status="criteria provided, multiple submitters, no conflicts",
                submitter_count=2,
                source=str(row["source"]),
                snapshot=str(row["snapshot"]),
                raptor_influenced=False,
                variant_class=str(row["variant_class"]),
            )
        )
    if not rows:
        raise ValueError("frozen benchmark is empty")
    return rows


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictor-policy", required=True)
    parser.add_argument("--bias-tsv")
    parser.add_argument("--manifest")
    parser.add_argument("--benchmark")
    parser.add_argument("--mask-ledger")
    parser.add_argument("--remask-audit")
    parser.add_argument("--return-manifest")
    parser.add_argument("--reference-root")
    parser.add_argument(
        "--eval-config",
        default=str(ROOT / "configs" / "eval" / "tsc2.yaml"),
    )
    parser.add_argument(
        "--scorer-config",
        default=str(ROOT / "configs" / "acmg" / "tsc.yaml"),
    )
    parser.add_argument(
        "--ingest-config",
        default=str(ROOT / "configs" / "ingest" / "tsc.yaml"),
    )
    parser.add_argument(
        "--aggregation-config",
        default=str(_AGGREGATION_SPEC),
    )
    parser.add_argument("--skipped-criterion", action="append", default=[])
    parser.add_argument("--output-report")
    parser.add_argument("--output-json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        policy = load_predictor_policy(args.predictor_policy)
    except PredictorPolicyError as exc:
        print(_blocked(f"predictor-policy artifact missing or malformed: {exc}"))
        return 0
    if not policy.approved:
        print(
            _blocked(
                f"predictor-policy artifact is not approved (status={policy.status!r}); "
                "cannot authorize masked held-out metrics"
            )
        )
        return 0
    try:
        verify_predictor_policy_hashes(policy, args.aggregation_config, _CORRECTION_CODE)
    except PredictorPolicyError as exc:
        print(_blocked(f"predictor-policy provenance mismatch: {exc}"))
        return 0

    # `_parse_args` owns the actual parser; report missing runtime inputs
    # consistently without opening labels or scorer output.
    runtime_required = (
        "bias_tsv",
        "manifest",
        "benchmark",
        "mask_ledger",
        "remask_audit",
        "return_manifest",
        "reference_root",
    )
    missing = [
        f"--{name.replace('_', '-')}"
        for name in runtime_required
        if not getattr(args, name)
    ]
    if missing:
        raise SystemExit(
            "approved predictor policy requires the complete masked runtime inputs: "
            + ", ".join(missing)
        )

    verified_return = _verify_return_manifest(Path(args.return_manifest))
    return_dir = Path(args.return_manifest).parent
    _require_verified_return_artifact(
        verified_return,
        return_dir,
        args.bias_tsv,
        label="BIAS TSV",
    )
    _require_verified_return_artifact(
        verified_return,
        return_dir,
        args.mask_ledger,
        label="mask ledger",
    )
    _require_verified_return_artifact(
        verified_return,
        return_dir,
        args.remask_audit,
        label="remask audit",
    )
    attestation = verify_mask_attestation(
        args.manifest,
        args.mask_ledger,
        args.remask_audit,
    )
    eval_config = load_eval_config(args.eval_config)
    scorer_config = load_scorer_config(args.scorer_config)
    declared_skips = {
        str(value).strip().upper() for value in args.skipped_criterion
    }
    operational_skips, skipped = _verify_return_control_files(
        verified_return,
        return_dir,
        automatable_criteria=eval_config.automatable_criteria,
        declared_skips=declared_skips,
    )
    invalid_skips = skipped - _ALLOWED_SKIPPED_CRITERIA
    if invalid_skips:
        raise ValueError(
            f"unsupported terminal evaluation exclusions: {sorted(invalid_skips)!r}"
        )
    normalizer = _CanonicalBiasNormalizer(
        Path(args.reference_root),
        Path(args.ingest_config),
    )
    source = BiasEvidenceSource(
        args.bias_tsv,
        args.manifest,
        eval_config,
        scorer_config,
        normalizer,
        authorized_masked_criteria=_REBUILT_MASKED_CRITERIA,
    )
    corrected_source = PredictorCorrectedEvidenceSource(
        source,
        load_aggregation_spec(args.aggregation_config),
    )
    # Production-vocabulary parity (AFTER the predictor correction, BEFORE
    # `run_eval`): a corrected call whose strength is outside its
    # criterion's `scorer_config.acmg_criteria[...].strength_vocab` is never
    # scored -- the whole variant is routed to manual review, matching
    # `raptor.scorer.pipeline`'s STRENGTH_OUT_OF_VOCAB production behavior.
    production_source = ProductionVocabEvidenceSource(
        corrected_source,
        scorer_config.acmg_criteria,
        eval_config.automatable_criteria,
    )

    labeled = _load_frozen_benchmark(Path(args.benchmark), eval_config.labels_snapshot)
    benchmark_rows = build_benchmark(labeled, eval_config)
    _, frozen_holdout = split_benchmark(benchmark_rows, eval_config)
    expected_holdout = {row.variant_id for row in frozen_holdout}
    actual_holdout = set(source.variant_ids)
    if expected_holdout != actual_holdout:
        raise ValueError(
            "frozen benchmark split does not exactly equal the scored manifest: "
            f"missing={len(expected_holdout - actual_holdout)} "
            f"unexpected={len(actual_holdout - expected_holdout)}"
        )

    report = run_eval(eval_config, labeled, production_source)
    if report.gate.status == "PASS" and skipped:
        report.gate = GateDecision(
            status="UNVERIFIED",
            stratum=report.gate.stratum,
            reason=(
                "all numeric thresholds passed, but evaluation-only criterion exclusions "
                f"{sorted(skipped)!r} break full production parity; never authorize VUS scoring"
            ),
            vus_authorized=False,
            per_stratum=report.gate.per_stratum,
        )

    # v2 scope-specific research-authorization gate (ADDITIVE, wired for the
    # NEXT run only -- this script is not executed by this track). Delegates
    # to the pure `compute_report_scope_gate` helper (checker finding 3):
    # `None` when `eval_config.scope_authorization` is absent (v1-compatible,
    # no `scope_gate` attached), else the v2 decision with the same
    # fail-closed parity-skip demotion as the v1 gate immediately above.
    report.scope_gate = compute_report_scope_gate(report.metrics, eval_config, skipped=skipped)

    report.config_pins.update(
        {
            "bias_tsv_sha256": _sha256(Path(args.bias_tsv)),
            "manifest_sha256": attestation.manifest_sha256,
            "mask_ledger_sha256": attestation.ledger_sha256,
            "remask_audit_sha256": attestation.remask_audit_sha256,
            "return_manifest_sha256": _sha256(Path(args.return_manifest)),
            "predictor_policy_source_hash": policy.predictor_source_hash,
            "predictor_policy_correction_hash": policy.correction_hash,
            "predictor_policy_decision_reference": policy.decision_reference,
            "mask_authorized_criteria": sorted(_REBUILT_MASKED_CRITERIA),
            "operational_skipped_criteria": sorted(operational_skips),
            "evaluation_skipped_criteria": sorted(skipped),
            "lineage_audit_hash": source.lineage_report.content_hash(),
            "predictor_correction_counts": corrected_source.correction_counts(),
            "production_vocab_manual_routed_counts": production_source.manual_routed_counts,
            "verified_return_artifact_count": len(verified_return),
        }
    )

    rendered = report.render()
    envelope = {
        "report": report_to_dict(report),
        "content_hash": report.content_hash(),
        "predictor_policy": asdict(policy),
        "mask_attestation": asdict(attestation),
        "lineage_audit": {
            **source.lineage_report.to_dict(),
            "authorized_masked_criteria": sorted(_REBUILT_MASKED_CRITERIA),
            "effective_blocking_criteria": sorted(
                set(source.lineage_report.blocking_criteria)
                - _REBUILT_MASKED_CRITERIA
            ),
        },
        "verified_return_artifacts": dict(sorted(verified_return.items())),
    }
    if args.output_report:
        report_path = Path(args.output_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    if args.output_json:
        json_path = Path(args.output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(rendered)
    print(f"content_hash: {report.content_hash()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
