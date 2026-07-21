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
from raptor.eval.lineage_policy import load_lineage_policy
from raptor.eval.live_source import BiasEvidenceSource
from raptor.eval.mask_attestation import verify_mask_attestation
from raptor.eval.model import GateDecision, LabeledVariant, ScopeGateDecision
from raptor.eval.report import report_to_dict
from raptor.eval.predictor_policy import (
    PredictorPolicy,
    PredictorPolicyError,
    load_predictor_policy,
    verify_disabled_config_hashes,
    verify_runtime_bundle_hash,
)
from raptor.eval.scope_gate import canonical_scope_gate_reason, decide_scope_gate
from raptor.eval.split import split_benchmark
from raptor.eval.terminal_source import (
    PolicyDisabledEvidenceSource,
    ProductionVocabEvidenceSource,
)
from raptor.ingest.config import load_config as load_ingest_config
from raptor.ingest.model import NormalizedVariant, RawVariant
from raptor.ingest.normalizer import SeqRepoGenomicNormalizer
from raptor.scorer.config import load_config as load_scorer_config

_AGGREGATION_SPEC = ROOT / "configs" / "eval" / "predictor_aggregation.yaml"
#: The canonical BIAS lineage policy path (mirrors
#: `raptor.eval.live_source._LINEAGE_POLICY_PATH`) -- `main()` verifies
#: exactly this file's bytes via `verify_disabled_config_hashes` and then
#: `BiasEvidenceSource`/`load_lineage_policy` CONSUME the identical file;
#: never verify one lineage path and consume another (D12, planner rev 7).
_LINEAGE_POLICY_CONFIG = ROOT / "configs" / "eval" / "bias_lineage.yaml"
#: The disabled/manual runtime code bundle (D9/`runtime_bundle_hash_spec`):
#: the loader, the disabled evidence wrapper, and this runner itself.
_RUNTIME_BUNDLE_FILES = (
    ROOT / "src" / "raptor" / "eval" / "predictor_policy.py",
    ROOT / "src" / "raptor" / "eval" / "terminal_source.py",
    ROOT / "scripts" / "run_masked_holdout_eval.py",
)
#: PP3/BP4 -- the only criteria the approved disabled/manual policy strips
#: (planner D5); vocabulary + can-fire lineage stay retained elsewhere.
_DISABLED_CRITERIA = frozenset({"PP3", "BP4"})
#: The `decision_dependency` the disabled/manual lineage deferral names
#: (D12) -- asserted as defense-in-depth after config/lineage load.
_LINEAGE_DECISION_DEPENDENCY = "bp4pp3-predictor-policy"
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


def resolve_policy_state(
    policy: PredictorPolicy,
    scorer_config_path: str | Path,
    eval_config_path: str | Path,
    lineage_path: str | Path,
    runtime_bundle_paths,
) -> tuple[str, str]:
    """Pure mode/status dispatch + path-byte/hash checks (rev 6 pure seam).

    Opens NO held-out input (no manifest/benchmark/reference/mask/TSV) --
    only the three pinned config paths and the runtime code bundle are
    touched. Returns `(state, reason)` where `state` is one of
    `_POLICY_STATES`; only `APPROVED_DISABLED` may proceed
    (`build_policy_evidence_source`/`main` fail closed on every other
    state).
    """
    if policy.mode is None or policy.mode not in {"disabled_manual", "corrected_enabled"}:
        return (
            "UNSUPPORTED_MODE",
            "explicit disabled_manual mode required; status-only/legacy policy never "
            f"enables (schema={policy.schema!r})",
        )

    if policy.mode == "corrected_enabled":
        return (
            "CORRECTED_ENABLED_OUT_OF_SCOPE",
            "corrected/REVEL activation is out of scope; requires a new hash-bound "
            "owner decision (recommendation section 8)",
        )

    if policy.status != "approved":
        return (
            "PROPOSED_DISABLED",
            f"disabled/manual policy is proposed (status={policy.status!r}), not owner-approved",
        )

    try:
        verify_runtime_bundle_hash(policy, runtime_bundle_paths)
    except PredictorPolicyError as exc:
        return (
            "RUNTIME_BUNDLE_DRIFT",
            f"disabled/manual runtime code changed since approval (accidental byte drift, "
            f"not a tamper claim): {exc}",
        )

    try:
        verify_disabled_config_hashes(policy, scorer_config_path, eval_config_path, lineage_path)
    except PredictorPolicyError as exc:
        return (
            "CONFIG_DRIFT",
            f"disabled/manual approval is not bound to the actually-loaded production/eval/"
            f"lineage configs: {exc}",
        )

    return (
        "APPROVED_DISABLED",
        "approved disabled/manual policy; PP3/BP4 automation suppressed",
    )


def build_policy_evidence_source(source, state: str) -> PolicyDisabledEvidenceSource:
    """For `APPROVED_DISABLED` ONLY, wrap `source` in
    `PolicyDisabledEvidenceSource(disabled_criteria={PP3,BP4})`. Every other
    state fails closed here too -- this seam NEVER constructs
    `PredictorCorrectedEvidenceSource` (D1/D5; gpt_probes P1/P2)."""
    if state != "APPROVED_DISABLED":
        raise PredictorPolicyError(
            f"cannot build the disabled evidence source for policy state {state!r}; "
            "only an APPROVED_DISABLED policy may wrap PolicyDisabledEvidenceSource"
        )
    return PolicyDisabledEvidenceSource(source, disabled_criteria=_DISABLED_CRITERIA)


def build_disabled_policy_pins(
    policy: PredictorPolicy,
    disabled_source: PolicyDisabledEvidenceSource,
    scorer_config,
    eval_config,
    lineage_policy,
) -> dict:
    """Pure provenance dict (rev 6 pure seam) -- NO report/gate mutation.

    `pp3bp4_scored_calls` is DERIVED by re-walking every emitted call across
    `disabled_source.variant_ids` (idempotent -- `get_evidence` never
    double-counts), never a hardcoded literal; it is always `0` by
    construction of `PolicyDisabledEvidenceSource`, but the invariant is
    verified from the actual evidence, not assumed (gpt_probes P4).
    """
    disabled_criteria = tuple(sorted(disabled_source.disabled_criteria))

    scored_calls = 0
    for variant_id in disabled_source.variant_ids:
        for criterion, _strength, _direction in disabled_source.get_evidence(variant_id):
            if criterion in disabled_source.disabled_criteria:
                scored_calls += 1

    included = {str(c).strip().upper() for c in scorer_config.included_criteria}
    automatable = {str(c).strip().upper() for c in eval_config.automatable_criteria}

    dispositions = {
        lineage_policy.records[criterion].production_disposition
        for criterion in disabled_criteria
        if criterion in lineage_policy.records
    }
    if len(dispositions) == 1:
        lineage_disposition = next(iter(dispositions))
    else:
        lineage_disposition = "mixed:" + ",".join(sorted(dispositions))

    return {
        "policy_mode": policy.mode,
        "pp3bp4_automation_disabled": True,
        "pp3bp4_suppressed_counts": dict(disabled_source.suppressed_counts),
        "pp3bp4_suppressed_variant_count": len(disabled_source.suppressed_variant_ids),
        "pp3bp4_scored_calls": scored_calls,
        "pp3bp4_in_included_criteria": bool(set(disabled_criteria) & included),
        "pp3bp4_in_automatable_criteria": bool(set(disabled_criteria) & automatable),
        "pp3bp4_retained_in_vocabulary": True,
        "pp3bp4_lineage_disposition": lineage_disposition,
        "predictor_correction_applied": False,
        "production_config_hash": policy.production_config_hash,
        "eval_config_hash": policy.eval_config_hash,
        "lineage_policy_hash": policy.lineage_policy_hash,
        "runtime_bundle_hash": policy.runtime_bundle_hash,
        "predictor_policy_source_hash": policy.predictor_source_hash,
        "predictor_policy_correction_hash": policy.correction_hash,
        "predictor_policy_decision_reference": policy.decision_reference,
    }


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

    Final scope-gate blocker (explicit parity-authorization blocker): the
    demotion NEVER alters/hides a per-scope statistical verdict --
    `decision.scopes` (and therefore, e.g., a `truncating:pathogenic`
    scope that is genuinely `VALIDATED`) is carried through UNCHANGED. Only
    the non-statistical authorization surface is withheld: every
    authorization boolean/flag is forced `False`, `governance_state` is
    demoted to the most restrictive `NONE_VALIDATED`, and
    `full_spectrum_status` is set to `BLOCKED_POLICY` (a policy block, never
    a statistical PASS/FAIL/UNDERPOWERED verdict). The withholding is made
    explicit and machine-readable via `authorization_blockers`, one
    deterministic, sorted `"evaluation_skipped_criteria:{criterion}"` entry
    per skipped criterion -- never silent.
    """
    if config.scope_authorization is None:
        return None

    decision = decide_scope_gate(metrics, config)
    skipped = skipped or set()
    if skipped and (
        decision.full_spectrum_vus_authorized or any(decision.research_scope_flags.values())
    ):
        blockers = sorted(f"evaluation_skipped_criteria:{criterion}" for criterion in skipped)
        scope_statuses = {key: verdict.scope_status for key, verdict in decision.scopes.items()}
        reason = canonical_scope_gate_reason(scope_statuses, blockers)
        decision = ScopeGateDecision(
            schema_version=decision.schema_version,
            scopes=decision.scopes,
            full_spectrum_status="BLOCKED_POLICY",
            full_spectrum_vus_authorized=False,
            research_scope_flags={name: False for name in decision.research_scope_flags},
            governance_state="NONE_VALIDATED",
            governance_statement=config.scope_authorization["governance_statements"]["NONE_VALIDATED"],
            research_use_disclaimer=decision.research_use_disclaimer,
            authorization_blockers=blockers,
            reason=reason,
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

    # `resolve_policy_state` does the mode/status dispatch + the three
    # config path-byte hashes + `runtime_bundle_hash` WITHOUT opening any
    # held-out input (rev 6 pure seam). Every non-`APPROVED_DISABLED` state
    # -- malformed mode, `corrected_enabled` (out of scope this track),
    # proposed-not-approved, or a config/runtime-bundle drift -- fails
    # closed here, before any manifest/benchmark/reference/mask/TSV is
    # touched.
    state, reason = resolve_policy_state(
        policy,
        args.scorer_config,
        args.eval_config,
        _LINEAGE_POLICY_CONFIG,
        _RUNTIME_BUNDLE_FILES,
    )
    if state != "APPROVED_DISABLED":
        print(_blocked(f"{state}: {reason}"))
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
    # main() verifies AND consumes this exact canonical path (never a
    # different lineage file than the one `verify_disabled_config_hashes`
    # just hashed above, inside `resolve_policy_state`) -- D12/planner rev 7.
    lineage_policy = load_lineage_policy(_LINEAGE_POLICY_CONFIG)
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

    # Defense-in-depth (after load, on top of the pre-load hash checks in
    # `resolve_policy_state`): PP3/BP4 absent from both registries, parity
    # holds, and the lineage disposition is exactly `deferred` with the
    # expected `decision_dependency` (D4/D12; state_machine
    # `proceed_preconditions_all_required`).
    included_set = {str(c).strip().upper() for c in scorer_config.included_criteria}
    automatable_set = {str(c).strip().upper() for c in eval_config.automatable_criteria}
    if _DISABLED_CRITERIA & included_set:
        print(_blocked(
            "disabled/manual policy violated: PP3/BP4 present in scorer_config.included_criteria"
        ))
        return 0
    if _DISABLED_CRITERIA & automatable_set:
        print(_blocked(
            "disabled/manual policy violated: PP3/BP4 present in eval_config.automatable_criteria"
        ))
        return 0
    if included_set != automatable_set:
        print(_blocked(
            "disabled/manual policy violated: included_criteria != automatable_criteria"
        ))
        return 0
    for criterion in sorted(_DISABLED_CRITERIA):
        record = lineage_policy.records.get(criterion)
        if (
            record is None
            or record.validation_disposition != "deferred"
            or record.production_disposition != "deferred"
            or record.decision_dependency != _LINEAGE_DECISION_DEPENDENCY
        ):
            print(_blocked(
                f"disabled/manual policy violated: {criterion} lineage disposition is not "
                f"deferred/{_LINEAGE_DECISION_DEPENDENCY!r}"
            ))
            return 0

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
    # Disabled/manual proceed path (D5): strip + COUNT PP3/BP4 BEFORE
    # scoring -- REPLACES `PredictorCorrectedEvidenceSource`, which is never
    # constructed on this branch (preserved, unused, for a future
    # `corrected_enabled` activation).
    disabled_source = build_policy_evidence_source(source, state)
    # Production-vocabulary parity (AFTER disabled-mode suppression, BEFORE
    # `run_eval`): unchanged wrapper; a no-op on PP3/BP4 since they are no
    # longer automatable.
    production_source = ProductionVocabEvidenceSource(
        disabled_source,
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

    # Pure disabled/manual provenance (rev 6 pure seam) -- pp3bp4_scored_calls
    # is an asserted, evidence-derived invariant, never a hardcoded literal.
    pins = build_disabled_policy_pins(policy, disabled_source, scorer_config, eval_config, lineage_policy)
    assert pins["pp3bp4_scored_calls"] == 0, "disabled/manual policy must consume zero PP3/BP4 calls"

    report.config_pins.update(
        {
            "bias_tsv_sha256": _sha256(Path(args.bias_tsv)),
            "manifest_sha256": attestation.manifest_sha256,
            "mask_ledger_sha256": attestation.ledger_sha256,
            "remask_audit_sha256": attestation.remask_audit_sha256,
            "return_manifest_sha256": _sha256(Path(args.return_manifest)),
            "mask_authorized_criteria": sorted(_REBUILT_MASKED_CRITERIA),
            "operational_skipped_criteria": sorted(operational_skips),
            "evaluation_skipped_criteria": sorted(skipped),
            "lineage_audit_hash": source.lineage_report.content_hash(),
            "production_vocab_manual_routed_counts": production_source.manual_routed_counts,
            "verified_return_artifact_count": len(verified_return),
            **pins,
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
