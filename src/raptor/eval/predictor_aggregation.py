"""Policy blocker A / slot 2 sec 2.2 `predictor_aggregation.py` -- an
arm's-length, config-driven re-derivation of the *intended* BIAS BP4/PP3
per-tool aggregation ("take the maximum per-tool strength, add a consensus
bump when >=2 tools agree at that maximum, then cap"), computed purely from
BIAS's OBSERVABLE `rationale` text + `configs/eval/predictor_aggregation.yaml`.

ARM'S-LENGTH BOUNDARY (ADR-0007, non-negotiable): this module never imports
`bias_2015`, never edits the vendored AGPL source, and never opens a
label/benchmark/held-out file. It only ANNOTATES -- it never overwrites
BIAS's emitted strength (`parse_rationale`/the scorer output are untouched).
`AggregationCorrection` always carries both `emitted_strength` (round-tripped
from the label, a parser-fidelity check) and `corrected_strength` (the
intended-spec re-derivation), so the divergence stays auditable rather than
silently fixed in place.

Source anchors (BIAS-2015 pinned commit `ade13f206f3e2c2efe3ec92715d974645fc8da8f`,
version 3.0.0): `pathogenic_classifiers.py::get_pp3` L944-954,
`benign_classifiers.py::get_bp4` L491-503 (the defect: a dead `best_score`
sentinel makes the emitted strength order-dependent rather than max-based);
`constants.py::score_to_hum_readable` (the weight-word vocabulary this module
inverts). See slot 2 sec 0/2 for the full derivation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

#: Canonical weight words the pinned BIAS-3.0.0 build can emit (per-tool
#: token weight AND the criterion-level strength-label suffix both draw
#: from this vocabulary -- `constants.py::score_to_hum_readable`). Any
#: config key outside this set is a schema drift (fail-closed at load).
_CANONICAL_WEIGHTS: frozenset[str] = frozenset({"supporting", "moderate", "strong", "very strong"})

#: Every predictor name the pinned BIAS-3.0.0 `pp3_tools`/`bp4_tools`
#: constants can name (union of both criteria). A config `tools` entry
#: outside this set is a schema drift (fail-closed at load).
_CANONICAL_TOOLS: frozenset[str] = frozenset({"phylop", "revel", "absplice", "alphamissense", "dann", "gerp"})

#: The only two criteria this correction spec covers (slot 2 sec 2.1).
_SUPPORTED_CRITERIA: frozenset[str] = frozenset({"PP3", "BP4"})

#: Rule keys allowed under `rule.pp3`/`rule.bp4` (fail-closed schema).
_PP3_RULE_KEYS: frozenset[str] = frozenset({"cap", "bump_min_score"})
_BP4_RULE_KEYS: frozenset[str] = frozenset({"cap", "bump_min_score", "single_supporting_floor"})


class AggregationSpecError(ValueError):
    """Raised on a missing/blank/unknown-key `predictor_aggregation.yaml` pin
    (fail-closed schema validation, slot 2 sec 2.2)."""


class AggregationUndecidableError(ValueError):
    """Raised when a fired PP3/BP4 rationale cannot be fully reconstructed
    into per-tool scores (an unrecognized weight word, tool name, or
    malformed token/label). Per AC-A4, an undecidable rationale must fail
    loud -- it is never silently passed through as if corrected."""


def _normalize_weight(word: str) -> str:
    """Normalize a weight word for lookup: case- and hyphen/space-
    insensitive. The pinned BIAS build itself emits both spellings of the
    top tier (`get_pp3`'s alphamissense branch: "very-strong";
    `get_bp4`'s revel branch: "very strong") -- both must resolve to the
    same score, since both are the SAME observable surface, not two
    different weights."""
    return " ".join(word.strip().lower().replace("-", " ").split())


@dataclass(frozen=True)
class CriterionRule:
    """The intended-spec aggregation parameters for one criterion (PP3 or
    BP4), pinned in config (slot 2 sec 2.1) -- never hardcoded."""

    cap: int
    bump_min_score: int
    single_supporting_floor: bool = False


@dataclass(frozen=True)
class AggregationSpec:
    """Frozen, schema-validated `predictor_aggregation.yaml` (slot 2 sec 2.1)."""

    bias_version: str
    bias_commit: str
    weight_to_score: Mapping[str, int]
    consensus_bump: int
    pp3_rule: CriterionRule
    bp4_rule: CriterionRule
    tools: Mapping[str, tuple[str, ...]]

    def rule_for(self, criterion: str) -> CriterionRule:
        if criterion == "PP3":
            return self.pp3_rule
        if criterion == "BP4":
            return self.bp4_rule
        raise AggregationSpecError(f"unsupported criterion {criterion!r} (only PP3/BP4 are specified)")


@dataclass(frozen=True)
class AggregationCorrection:
    """One PP3/BP4 rationale's emitted-vs-corrected aggregation result
    (slot 2 sec 2.2). Both strengths are always carried -- this module
    never overwrites BIAS's emitted value."""

    criterion: str
    emitted_strength: int
    corrected_strength: int
    per_tool_scores: Mapping[str, int] = field(default_factory=dict)
    consensus_applied: bool = False
    decidable: bool = True
    note: str = ""


def _require_mapping(raw: Any, ctx: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise AggregationSpecError(f"{ctx} must be a mapping, got {type(raw).__name__}")
    return raw


def _validate_weight_to_score(raw: Any) -> dict[str, int]:
    mapping = _require_mapping(raw, "`weight_to_score`")
    normalized: dict[str, int] = {}
    for key, value in mapping.items():
        norm_key = _normalize_weight(str(key))
        if norm_key not in _CANONICAL_WEIGHTS:
            raise AggregationSpecError(
                f"`weight_to_score` has an unknown weight key {key!r} "
                f"(must be one of {sorted(_CANONICAL_WEIGHTS)})"
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise AggregationSpecError(f"`weight_to_score[{key!r}]` must be an int, got {value!r}")
        normalized[norm_key] = int(value)
    missing = _CANONICAL_WEIGHTS - normalized.keys()
    if missing:
        raise AggregationSpecError(f"`weight_to_score` is missing required weight(s): {sorted(missing)}")
    return normalized


def _validate_criterion_rule(raw: Any, *, ctx: str, allowed_keys: frozenset[str]) -> CriterionRule:
    mapping = _require_mapping(raw, ctx)
    unknown = set(mapping.keys()) - allowed_keys
    if unknown:
        raise AggregationSpecError(f"{ctx} has unknown rule key(s): {sorted(unknown)}")
    if "cap" not in mapping:
        raise AggregationSpecError(f"{ctx} is missing required key 'cap'")
    if "bump_min_score" not in mapping:
        raise AggregationSpecError(f"{ctx} is missing required key 'bump_min_score'")
    cap = mapping["cap"]
    bump_min_score = mapping["bump_min_score"]
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise AggregationSpecError(f"{ctx}.cap must be a positive int, got {cap!r}")
    if isinstance(bump_min_score, bool) or not isinstance(bump_min_score, int) or bump_min_score < 1:
        raise AggregationSpecError(f"{ctx}.bump_min_score must be a positive int, got {bump_min_score!r}")
    single_supporting_floor = bool(mapping.get("single_supporting_floor", False))
    return CriterionRule(cap=int(cap), bump_min_score=int(bump_min_score), single_supporting_floor=single_supporting_floor)


def _validate_rule(raw: Any) -> tuple[int, CriterionRule, CriterionRule]:
    mapping = _require_mapping(raw, "`rule`")
    unknown = set(mapping.keys()) - {"aggregation", "consensus_bump", "pp3", "bp4"}
    if unknown:
        raise AggregationSpecError(f"`rule` has unknown key(s): {sorted(unknown)}")
    aggregation = mapping.get("aggregation")
    if aggregation != "max_plus_consensus":
        raise AggregationSpecError(f"`rule.aggregation` must be 'max_plus_consensus', got {aggregation!r}")
    consensus_bump = mapping.get("consensus_bump")
    if isinstance(consensus_bump, bool) or not isinstance(consensus_bump, int) or consensus_bump < 1:
        raise AggregationSpecError(f"`rule.consensus_bump` must be a positive int, got {consensus_bump!r}")
    if "pp3" not in mapping:
        raise AggregationSpecError("`rule` is missing required key 'pp3'")
    if "bp4" not in mapping:
        raise AggregationSpecError("`rule` is missing required key 'bp4'")
    pp3_rule = _validate_criterion_rule(mapping["pp3"], ctx="`rule.pp3`", allowed_keys=_PP3_RULE_KEYS)
    bp4_rule = _validate_criterion_rule(mapping["bp4"], ctx="`rule.bp4`", allowed_keys=_BP4_RULE_KEYS)
    return int(consensus_bump), pp3_rule, bp4_rule


def _validate_tools(raw: Any) -> dict[str, tuple[str, ...]]:
    mapping = _require_mapping(raw, "`tools`")
    unknown_top = set(mapping.keys()) - {"pp3", "bp4"}
    if unknown_top:
        raise AggregationSpecError(f"`tools` has unknown criterion key(s): {sorted(unknown_top)}")
    result: dict[str, tuple[str, ...]] = {}
    for crit_key in ("pp3", "bp4"):
        if crit_key not in mapping:
            raise AggregationSpecError(f"`tools` is missing required key {crit_key!r}")
        tool_list = mapping[crit_key]
        if not isinstance(tool_list, list) or not tool_list:
            raise AggregationSpecError(f"`tools.{crit_key}` must be a non-empty list")
        normalized_tools: list[str] = []
        for tool in tool_list:
            norm_tool = str(tool).strip().lower()
            if norm_tool not in _CANONICAL_TOOLS:
                raise AggregationSpecError(
                    f"`tools.{crit_key}` names an unknown predictor {tool!r} "
                    f"(must be one of {sorted(_CANONICAL_TOOLS)})"
                )
            normalized_tools.append(norm_tool)
        result[crit_key] = tuple(normalized_tools)
    return result


def load_aggregation_spec(path: str | Path) -> AggregationSpec:
    """Load + fail-closed-validate a `configs/eval/predictor_aggregation.yaml`
    file (slot 2 sec 2.2). Raises `AggregationSpecError` on any missing/
    blank/unknown-key pin -- never silently defaults."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AggregationSpecError(f"config root must be a mapping, got {type(raw).__name__}")

    bias_version = raw.get("bias_version")
    bias_commit = raw.get("bias_commit")
    if not isinstance(bias_version, str) or not bias_version.strip():
        raise AggregationSpecError("`bias_version` must be a non-blank string")
    if not isinstance(bias_commit, str) or not bias_commit.strip():
        raise AggregationSpecError("`bias_commit` must be a non-blank string")

    if "weight_to_score" not in raw:
        raise AggregationSpecError("missing required config key: 'weight_to_score'")
    weight_to_score = _validate_weight_to_score(raw["weight_to_score"])

    if "rule" not in raw:
        raise AggregationSpecError("missing required config key: 'rule'")
    consensus_bump, pp3_rule, bp4_rule = _validate_rule(raw["rule"])

    if "tools" not in raw:
        raise AggregationSpecError("missing required config key: 'tools'")
    tools = _validate_tools(raw["tools"])

    return AggregationSpec(
        bias_version=bias_version,
        bias_commit=bias_commit,
        weight_to_score=weight_to_score,
        consensus_bump=consensus_bump,
        pp3_rule=pp3_rule,
        bp4_rule=bp4_rule,
        tools=tools,
    )


def _parse_label(criterion: str, label: str, spec: AggregationSpec) -> int:
    """Round-trip BIAS's emitted strength int from the `CRITERION[_word]`
    label prefix (e.g. `PP3`, `PP3_moderate`, `BP4_strong`). A bare label
    with no `_word` suffix means BIAS's own `score_to_hum_readable[1] == ''`
    -- i.e. emitted strength 1 (supporting)."""
    if label == criterion:
        return 1
    prefix = criterion + "_"
    if not label.startswith(prefix):
        raise AggregationUndecidableError(
            f"rationale label {label!r} does not match expected criterion {criterion!r}"
        )
    word = _normalize_weight(label[len(prefix):])
    if word not in spec.weight_to_score:
        raise AggregationUndecidableError(
            f"rationale label {label!r} names an unrecognized strength word {word!r}"
        )
    return spec.weight_to_score[word]


def parse_per_tool_scores(criterion: str, rationale_text: str, spec: AggregationSpec) -> dict[str, int]:
    """Reconstruct `{tool: score}` from a fired PP3/BP4 rationale's
    observable `printout_text` tokens (`{weight} {tool} {value}`, weight
    possibly two words e.g. "very strong"). Raises
    `AggregationUndecidableError` on any token whose weight or tool name is
    not in `spec` -- never guesses, never returns a partial silently."""
    criterion = criterion.strip().upper()
    if criterion not in _SUPPORTED_CRITERIA:
        raise AggregationSpecError(f"unsupported criterion {criterion!r} (only PP3/BP4 are specified)")

    header, sep, rest = rationale_text.partition(";")
    if not sep:
        raise AggregationUndecidableError(
            f"rationale for {criterion} has no ';'-delimited per-tool token section: {rationale_text!r}"
        )

    tokens = [tok.strip() for tok in rest.split("|") if tok.strip()]
    if not tokens:
        raise AggregationUndecidableError(f"rationale for {criterion} has no per-tool evidence tokens: {rationale_text!r}")

    known_tools = spec.tools[criterion.lower()]
    per_tool_scores: dict[str, int] = {}
    for token in tokens:
        # Token shape is `{weight} {tool} {value}` where `weight` may
        # itself be one or two words (e.g. "very strong revel 0.688"): the
        # trailing token is always the numeric value, the one before it is
        # always the tool name, and everything else is the weight phrase.
        parts = token.split()
        if len(parts) < 3:
            raise AggregationUndecidableError(f"malformed per-tool token for {criterion}: {token!r}")
        tool = parts[-2].strip().lower()
        weight = _normalize_weight(" ".join(parts[:-2]))
        if tool not in known_tools:
            raise AggregationUndecidableError(
                f"per-tool token for {criterion} names an unrecognized predictor {tool!r}: {token!r}"
            )
        if weight not in spec.weight_to_score:
            raise AggregationUndecidableError(
                f"per-tool token for {criterion} has an unrecognized weight {weight!r}: {token!r}"
            )
        per_tool_scores[tool] = spec.weight_to_score[weight]

    del header  # header carries only the label + line count; unused here.
    return per_tool_scores


def _corrected_strength(
    criterion: str, per_tool_scores: Mapping[str, int], spec: AggregationSpec
) -> tuple[int, bool]:
    """Apply the intended max-plus-consensus-with-cap rule (slot 2 sec 0.1/
    2.1) to a reconstructed `per_tool_scores`. Returns `(corrected, consensus_applied)`."""
    rule = spec.rule_for(criterion)
    max_score = max(per_tool_scores.values())
    tied_tools = [tool for tool, score in per_tool_scores.items() if score == max_score]
    score = max_score
    consensus_applied = False
    if len(tied_tools) > 1 and max_score >= rule.bump_min_score:
        score += spec.consensus_bump
        consensus_applied = True
    if rule.single_supporting_floor and len(per_tool_scores) < 2 and score == 1:
        score = 0
    score = min(score, rule.cap)
    return score, consensus_applied


def recompute_strength(criterion: str, rationale_text: str, spec: AggregationSpec) -> AggregationCorrection:
    """Round-trip BIAS's emitted strength from `rationale_text` (parser
    fidelity) and compute the corrected strength per the intended spec
    (slot 2 sec 2.1/2.2). Pure function of `rationale_text` + `spec` --
    imports no `bias_2015`, reads no labels. Raises
    `AggregationUndecidableError` if the rationale cannot be fully
    reconstructed (AC-A4) -- never emitted as if corrected."""
    criterion = criterion.strip().upper()
    if criterion not in _SUPPORTED_CRITERIA:
        raise AggregationSpecError(f"unsupported criterion {criterion!r} (only PP3/BP4 are specified)")

    label = rationale_text.split(":", 1)[0].strip()
    emitted_strength = _parse_label(criterion, label, spec)
    per_tool_scores = parse_per_tool_scores(criterion, rationale_text, spec)
    corrected_strength, consensus_applied = _corrected_strength(criterion, per_tool_scores, spec)

    note = (
        f"{criterion}: emitted={emitted_strength} corrected={corrected_strength} "
        f"per_tool_scores={dict(sorted(per_tool_scores.items()))}"
    )
    return AggregationCorrection(
        criterion=criterion,
        emitted_strength=emitted_strength,
        corrected_strength=corrected_strength,
        per_tool_scores=dict(per_tool_scores),
        consensus_applied=consensus_applied,
        decidable=True,
        note=note,
    )
