"""Track `strength-policy-2026-07` — the deterministic, label-free strength
-policy MATERIALITY probe (PRD-08 strength-policy reconciliation, Slot 2).

Characterizes how often the pinned BIAS-3.0.0 source
(`configs/eval/bias_strength_ladder.yaml`) emits a (criterion, strength)
pair OUTSIDE the CURRENT production scorer's strength vocabulary
(`configs/acmg/*.yaml::acmg_criteria`), over a real, committed BIAS output
TSV -- never a label/benchmark/held-out file (ADR-0007/R-A2/H1, same
arm's-length boundary as `scripts/probe_bs2_firings.py`).

LABEL-FREE BY CONSTRUCTION: this probe reads ONLY BIAS's own fired
criteria + consequence + gene (never `acmgClassification`/ClinVar
significance/review status) to select which strength-policy behavior
would apply to a row. The one exception -- the "eval-only implied
pattern" breakdown -- reuses `raptor.eval.combine.implied_direction`,
which is ITSELF non-authoritative and computed purely from BIAS's own
fired criteria (never a ClinVar label); it is reported strictly as an
existing, already-non-authoritative eval-only signal, never as a truth
label, and this probe never branches its OWN out-of-vocab counting logic
on it. No held-out truth label is read or computed anywhere in this
module.

The probe reports two, clearly separated views for every "affected" row
(a row with >=1 out-of-vocab firing among the ladder's criteria):

* the EFFECTIVE view, under the real, loaded `configs/acmg/strength_policy.yaml`
  (which is `status: unapproved` at the time this probe was written --
  every affected row's effective disposition is `manual`, per
  `apply_strength_policy`'s fail-closed rule); and
* a clearly-named HYPOTHETICAL `recommended_scenario` view, which
  simulates (in-memory only, never persisted) what would happen if each
  record's `recommended_disposition`/`recommended_emit` metadata were
  promoted to `disposition`/`emit` and the policy were owner-approved --
  this is a planning aid, not a live/activated policy (this track does
  not wire the policy into eval/production, and this probe does not
  either).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from raptor.eval.combine import implied_direction
from raptor.eval.config import EvalConfig
from raptor.eval.config import load_config as load_eval_config
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import ScorerConfig
from raptor.scorer.config import load_config as load_scorer_config
from raptor.scorer.model import BiasRecord
from raptor.scorer.strength_policy import (
    StrengthLadder,
    StrengthPolicy,
    StrengthPolicyRecord,
    apply_strength_policy,
    load_strength_ladder,
    load_strength_policy,
)

#: SO consequence terms resolving to the `truncating`/`missense` variant
#: classes -- mirrors `scripts/build_tsc_calibration_batch.py`'s taxonomy
#: exactly (kept as a local, independent copy: scripts are not an
#: importable library in this repo).
_TRUNCATING_CONSEQUENCE_TERMS: frozenset[str] = frozenset({
    "frameshift_variant",
    "stop_gained",
    "stop_lost",
    "start_lost",
    "splice_donor_variant",
    "splice_acceptor_variant",
    "transcript_ablation",
})
_MISSENSE_CONSEQUENCE_TERMS: frozenset[str] = frozenset({"missense_variant", "protein_altering_variant"})


def _variant_class_for(consequence: str) -> str:
    terms = {term.strip() for term in consequence.split(",") if term.strip()}
    if terms & _TRUNCATING_CONSEQUENCE_TERMS:
        return "truncating"
    if terms & _MISSENSE_CONSEQUENCE_TERMS:
        return "missense"
    return "other"


def _family_direction(criterion: str) -> str:
    lead = criterion[0].upper()
    if lead == "P":
        return "pathogenic"
    if lead == "B":
        return "benign"
    raise ValueError(f"unknown criterion family for {criterion!r}")


@dataclass(frozen=True)
class MaterialityInputs:
    """The four declared, machine-readable inputs this probe reconciles --
    never a label/benchmark/held-out file."""

    ladder: StrengthLadder
    policy: StrengthPolicy
    scorer_config: ScorerConfig
    eval_config: EvalConfig


def load_materiality_inputs(
    *,
    ladder_path: str | Path = "configs/eval/bias_strength_ladder.yaml",
    policy_path: str | Path = "configs/acmg/strength_policy.yaml",
    scorer_config_path: str | Path = "configs/acmg/tsc.yaml",
    eval_config_path: str | Path = "configs/eval/tsc2.yaml",
) -> MaterialityInputs:
    scorer_config = load_scorer_config(scorer_config_path)
    ladder = load_strength_ladder(ladder_path)
    scorer_strength_vocab = {
        criterion: tuple(spec["strength_vocab"])
        for criterion, spec in scorer_config.acmg_criteria.items()
        if criterion in ladder.criteria
    }
    policy = load_strength_policy(policy_path, ladder=ladder, scorer_strength_vocab=scorer_strength_vocab)
    eval_config = load_eval_config(eval_config_path)
    return MaterialityInputs(
        ladder=ladder, policy=policy, scorer_config=scorer_config, eval_config=eval_config
    )


def _hypothetical_recommended_policy(policy: StrengthPolicy) -> StrengthPolicy:
    """Build an IN-MEMORY-ONLY, never-persisted simulation of `policy` with
    every record's `recommended_disposition`/`recommended_emit` promoted to
    `disposition`/`emit` (falling back to the record's own current
    disposition/emit when no recommendation is set), and `status`/
    `owner_approved` flipped to active -- so `apply_strength_policy` will
    actually exercise the proposed behavior instead of fail-closing to
    manual. This is a planning aid for the `recommended_scenario` report
    section only; it is never written back to
    `configs/acmg/strength_policy.yaml` and never used outside this probe.
    """

    def _promote(record: StrengthPolicyRecord) -> StrengthPolicyRecord:
        disposition = record.recommended_disposition or record.disposition
        if disposition in ("accept", "cap"):
            emit = record.recommended_emit or record.emit
        else:
            emit = None
        return replace(record, disposition=disposition, emit=emit)

    records = {
        criterion: {strength: _promote(rec) for strength, rec in per_strength.items()}
        for criterion, per_strength in policy.records.items()
    }
    gene_overrides = {
        gene: {
            criterion: {strength: _promote(rec) for strength, rec in per_strength.items()}
            for criterion, per_strength in per_gene.items()
        }
        for gene, per_gene in policy.gene_overrides.items()
    }
    return replace(policy, status="approved", owner_approved=True, records=records, gene_overrides=gene_overrides)


def _empty_bucket_counter() -> dict[str, Counter[str]]:
    return defaultdict(Counter)


def compute_materiality(bias_tsv_path: str | Path, inputs: MaterialityInputs) -> dict:
    """Run the materiality probe over `bias_tsv_path` and return the
    canonical, deterministic, non-identifying aggregate report. Never
    returns a per-variant chromosome/position/ref/alt/variant_id row."""
    path = Path(bias_tsv_path)
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    hypothetical_policy = _hypothetical_recommended_policy(inputs.policy)

    total_rows = 0
    affected_rows = 0
    out_of_vocab_by_criterion_strength: dict[str, Counter[str]] = _empty_bucket_counter()
    affected_by_gene: Counter[str] = Counter()
    affected_by_variant_class: Counter[str] = Counter()
    affected_by_eval_only_pattern: Counter[str] = Counter()
    affected_by_effective_disposition: Counter[str] = Counter()
    affected_by_recommended_disposition: Counter[str] = Counter()
    recommended_disposition_by_criterion_strength: dict[str, Counter[str]] = _empty_bucket_counter()

    for record in BiasTsvSource(path).records():
        total_rows += 1
        out_of_vocab_calls = _out_of_vocab_calls(record, inputs)
        if not out_of_vocab_calls:
            continue

        affected_rows += 1
        affected_by_gene[record.gene_name] += 1
        affected_by_variant_class[_variant_class_for(record.consequence)] += 1

        for criterion, strength in out_of_vocab_calls:
            out_of_vocab_by_criterion_strength[criterion][strength] += 1

        implied = _implied_pattern_for(record, inputs.eval_config)
        affected_by_eval_only_pattern[implied] += 1

        plain_record = {"variant_id": record.variant_id, "gene_name": record.gene_name}
        for criterion, strength in out_of_vocab_calls:
            call = {
                "criterion": criterion,
                "strength": strength,
                "direction": _family_direction(criterion),
                "rationale": "",
            }
            effective = apply_strength_policy(record=plain_record, call=call, policy=inputs.policy)
            affected_by_effective_disposition[effective.disposition] += 1

            hypothetical = apply_strength_policy(record=plain_record, call=call, policy=hypothetical_policy)
            affected_by_recommended_disposition[hypothetical.disposition] += 1
            recommended_disposition_by_criterion_strength[criterion][hypothetical.disposition] += 1

    return {
        "schema": "tsc-strength-policy-materiality-probe",
        "source": {
            "bias_tsv_path": str(path),
            "bias_tsv_sha256": source_sha256,
            "bias_version": inputs.ladder.bias_version,
            "bias_commit": inputs.ladder.bias_commit,
        },
        "policy": {
            "policy_id": inputs.policy.policy_id,
            "version": inputs.policy.version,
            "status": inputs.policy.status,
            "owner_approved": inputs.policy.owner_approved,
            "is_active": inputs.policy.is_active,
        },
        "corpus": {"total_rows": total_rows, "affected_rows": affected_rows},
        "out_of_vocab_emitted_by_criterion_strength": {
            criterion: dict(sorted(counts.items())) for criterion, counts in sorted(out_of_vocab_by_criterion_strength.items())
        },
        "affected": {
            "by_gene": dict(sorted(affected_by_gene.items())),
            "by_variant_class": dict(sorted(affected_by_variant_class.items())),
            "by_eval_only_implied_pattern": dict(sorted(affected_by_eval_only_pattern.items())),
            "by_effective_disposition": dict(sorted(affected_by_effective_disposition.items())),
        },
        "recommended_scenario": {
            "description": (
                "HYPOTHETICAL ONLY -- simulates every out-of-vocab call as if each "
                "record's recommended_disposition/recommended_emit metadata "
                "(configs/acmg/strength_policy.yaml) were promoted to disposition/"
                "emit and the policy were owner-approved. Not active, not wired "
                "into eval/production, and does not reflect the current "
                "effective (unapproved -> manual) behavior."
            ),
            "by_disposition": dict(sorted(affected_by_recommended_disposition.items())),
            "by_criterion_strength": {
                criterion: dict(sorted(counts.items()))
                for criterion, counts in sorted(recommended_disposition_by_criterion_strength.items())
            },
        },
    }


def _out_of_vocab_calls(record: BiasRecord, inputs: MaterialityInputs) -> list[tuple[str, str]]:
    """Return every (criterion, strength) BIAS fired for `record` among the
    ladder's criteria whose strength sits outside the CURRENT scorer vocab
    (`configs/acmg/*.yaml::acmg_criteria`). Never reads
    `record.acmg_classification`/ClinVar significance/review status."""
    out_of_vocab: list[tuple[str, str]] = []
    for criterion in inputs.ladder.criteria:
        fired = record.criteria.get(criterion.lower())
        if fired is None or fired[0] == 0:
            continue
        strength = inputs.scorer_config.strength_map.get(str(fired[0]))
        if strength is None:
            continue
        vocab = inputs.scorer_config.acmg_criteria.get(criterion, {}).get("strength_vocab", ())
        if strength not in vocab:
            out_of_vocab.append((criterion, strength))
    return out_of_vocab


def _implied_pattern_for(record: BiasRecord, eval_config: EvalConfig) -> str:
    """The existing, already-non-authoritative eval-only implied pattern
    (`raptor.eval.combine.implied_direction`) for `record`'s fired,
    automatable criteria -- reported as-is, never used to select this
    probe's OWN out-of-vocab counting logic."""
    calls = []
    automatable = set(eval_config.automatable_criteria)
    for criterion_key, (fired, _explanation) in record.criteria.items():
        if fired == 0:
            continue
        criterion = criterion_key.upper()
        if criterion not in automatable:
            continue
        strength = _SCORE_TO_STRENGTH.get(fired)
        if strength is None:
            continue
        calls.append((criterion, strength, _family_direction(criterion)))
    return implied_direction(calls, eval_config).implied


#: BIAS fired-int -> RAPTOR strength name (matches `configs/acmg/tsc.yaml`
#: `strength_map` and `constants.py::score_to_hum_readable` exactly).
_SCORE_TO_STRENGTH: Mapping[int, str] = {
    1: "supporting",
    2: "moderate",
    3: "strong",
    4: "very_strong",
    5: "stand_alone",
}


def canonical_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, sort_keys=True, indent=2)
