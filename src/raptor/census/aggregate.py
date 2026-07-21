"""raptor.census.aggregate — pure, non-identifying aggregate builder (ADR-0012).

`build_census_record` derives the ENTIRE emitted census record from its
injected inputs (strata + BIAS rows + manifest + run pins + bound config
hashes + the historical stats file): every count is computed fresh, never
read from this spec, the historical file (except for the reported delta),
or the masked gate. Production code here contains NO expected-count
literal (D3 / P1) -- change an input and every derived count moves.

Imports only `raptor.census.strata` (relative, packet-free),
`raptor.scorer.model`/`raptor.scorer.parse`, and `raptor.eval.knowns`
(`classify_variant`, reused verbatim for the corpus consequence-class
breakdown) -- NEVER `raptor.packet` (D1/P7).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from raptor.eval.knowns import classify_variant
from raptor.scorer.model import BiasRecord
from raptor.scorer.parse import parse_rationale

from .strata import STRENGTH_MAP, ManifestEntry, StratumEntry, _variant_class_for

#: Fixed schema/policy vocabulary (ADR-0012), not measured census data.
CENSUS_SCHEMA = "raptor.tsc.vus_census.disabled_manual.v1"
CENSUS_STATUS = "internal_non_authoritative_evidence_census"
POLICY_MODE = "disabled_manual"
NON_AUTHORITATIVE_BOUNDARY = (
    "A census organizes internal, eval-only review directions. It creates no "
    "public worklist, classification, research authorization, or clinical claim. "
    "Candidate LP/LB directions are non-authoritative review metadata only."
)

#: Static, qualitative limitations (no measured counts -- descriptive only).
CENSUS_LIMITATIONS: tuple[str, ...] = (
    "negative certified masked gate (legacy FAIL, v2 BLOCKED_POLICY, vus_authorized=false)",
    "PM1 evaluation parity blocker (authorization_blockers: evaluation_skipped_criteria:PM1)",
    "TSC2-region inputs annotated as NTHL1 require manual resolution",
    "BIAS emits .4 transcripts while production config pins .5 (transcript drift)",
    "PS1/PM5 use ClinVar-derived comparator resources pending held-out masking",
    "no expert approval; candidate directions are eval-only, non-authoritative",
)

#: The four recorded aggregate directions, keyed by their StratumEntry.stratum
#: token (manual_review is reported under the annotation_manual_review key).
_DIRECTION_KEYS: tuple[str, ...] = (
    "candidate_LP_review",
    "candidate_LB_review",
    "no_deterministic_resolution",
    "annotation_manual_review",
)


def _direction_label(stratum_token: str) -> str:
    return "annotation_manual_review" if stratum_token == "manual_review" else stratum_token


def _corpus_gene_for(gene_name: str) -> str:
    """Corpus gene-grouping only: NTHL1-annotated rows are known TSC2-region
    inputs mis-annotated to NTHL1 (see `limitations`), so the corpus gene
    breakdown folds them into TSC2 -- reusing the exact grouping convention
    already recorded in `data/census/tsc_vus_clinvar_2026-07-07_stats.json`'s
    own `corpus` field. This is a corpus-grouping label only; it never
    changes a row's `direction_by_gene` bucket, which stays keyed on the raw
    `gene_name`."""
    return "TSC2" if gene_name == "NTHL1" else gene_name


def _corpus_consequence_class_for(row: BiasRecord) -> str:
    """Corpus consequence-class grouping only: reuses `raptor.eval.knowns.
    classify_variant` (verbatim) against the row's own predicted protein
    change (`provenance["hgvsp"]`) -- the exact grouping convention already
    recorded in `tsc_vus_clinvar_2026-07-07_stats.json`'s `corpus` field.
    A `hgvsp`-implied "truncating" call is downgraded to "other" when the
    row's raw SO `consequence` itself still carries an `intron_variant` or
    `splice_region_variant` term: those rows are near-splice indels whose
    protein consequence is a computational prediction, never a confirmed
    exonic truncating call (conservative, matches `classify_variant`'s own
    "if it cannot be confidently parsed, never guess" contract). This is a
    corpus-grouping label only; `direction_by_consequence` below is a
    SEPARATE breakdown and intentionally keeps the raw SO-term-based
    `_variant_class_for(row.consequence)`."""
    hgvsp = row.provenance.get("hgvsp", "") if isinstance(row.provenance, Mapping) else ""
    variant_class = classify_variant(hgvsp)
    if variant_class == "truncating" and (
        "intron_variant" in row.consequence or "splice_region_variant" in row.consequence
    ):
        return "other"
    return variant_class


def _pattern_stats(strata_subset: Sequence[StratumEntry]) -> dict[str, Any]:
    variants = len(strata_subset)
    pattern_ids = [entry.pattern_id for entry in strata_subset if entry.pattern_id]
    counts = Counter(pattern_ids)
    exact_strength_patterns = len(counts)

    patterns_covering_90_percent = 0
    cumulative = 0
    threshold = 0.9 * variants
    for _pattern_id, count in counts.most_common():
        patterns_covering_90_percent += 1
        cumulative += count
        if cumulative >= threshold:
            break

    largest_pattern = None
    if counts:
        top_pattern_id, top_count = counts.most_common(1)[0]
        example = next(entry for entry in strata_subset if entry.pattern_id == top_pattern_id)
        largest_pattern = {
            "criteria": list(example.pattern_signature),
            "points": example.signed_points,
            "variants": top_count,
        }

    return {
        "variants": variants,
        "exact_strength_patterns": exact_strength_patterns,
        "patterns_covering_90_percent": patterns_covering_90_percent,
        "largest_pattern": largest_pattern,
    }


def _criterion_incidence_and_suppression(
    bias_rows: Iterable[BiasRecord],
) -> tuple[dict[str, int], dict[str, int]]:
    """Parse EVERY BIAS row's full (non-automatable-filtered) criteria table
    and derive (a) the raw fired-criterion incidence across all rows, and
    (b) the PP3/BP4 raw-firing + union suppression counts. Both are measured
    fresh from the immutable BIAS rows -- never read from any stats file."""
    criterion_incidence: Counter[str] = Counter()
    raw_pp3 = 0
    raw_bp4 = 0
    affected_union = 0
    for row in bias_rows:
        calls = parse_rationale(row.criteria, STRENGTH_MAP)
        fired = {call.criterion for call in calls}
        for criterion in fired:
            criterion_incidence[criterion] += 1
        has_pp3 = "PP3" in fired
        has_bp4 = "BP4" in fired
        if has_pp3:
            raw_pp3 += 1
        if has_bp4:
            raw_bp4 += 1
        if has_pp3 or has_bp4:
            affected_union += 1
    return dict(criterion_incidence), {
        "raw_pp3": raw_pp3,
        "raw_bp4": raw_bp4,
        "affected_union": affected_union,
        # Neither PP3 nor BP4 is in `eval_config.automatable_criteria` under
        # the approved disabled/manual policy -- this is a structural
        # invariant of the run, not a data-derived probe value.
        "scored_calls": 0,
    }


def build_census_record(
    *,
    strata: Sequence[StratumEntry],
    bias_rows: Sequence[BiasRecord],
    manifest: Sequence[ManifestEntry],
    run_pins: Any,
    bound_hashes: Mapping[str, str],
    historical_stats: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the non-identifying `raptor.tsc.vus_census.disabled_manual.v1`
    aggregate record from `strata` + `bias_rows` + `manifest` + `run_pins`
    (duck-typed: `.input_sha256`, `.output_sha256`, `.manifest_sha256`,
    `.source_snapshot`, `.code_commit`) + `bound_hashes` + `historical_stats`.

    Every count is DERIVED here; no expected-count literal is read from this
    module. `historical_stats` is read only to compute the reported delta.
    """
    manifest = tuple(manifest)
    bias_rows = tuple(bias_rows)
    strata = tuple(strata)

    manifest_by_vcf_key = {entry.vcf_key: entry for entry in manifest}
    strata_by_variant_id = {entry.variant_id: entry for entry in strata}

    # --- corpus (gene / consequence-class breakdown, derived from bias_rows) ---
    # The 30 NTHL1-annotated rows are TSC2-region inputs mis-annotated to
    # NTHL1 (a known transcript/gene annotation defect -- see `limitations`
    # and `data/census/tsc_vus_clinvar_2026-07-07_stats.json`'s own `corpus`
    # grouping, which is reused here verbatim): the corpus gene breakdown
    # folds them into TSC2, so `corpus` carries only TSC1/TSC2 gene keys.
    # `direction_by_gene` below is a SEPARATE breakdown and intentionally
    # keeps the raw (unmapped) `row.gene_name`.
    gene_counts = Counter(_corpus_gene_for(row.gene_name) for row in bias_rows)
    consequence_counts = Counter(_corpus_consequence_class_for(row) for row in bias_rows)
    corpus: dict[str, int] = {"total_vus": len(manifest)}
    corpus.update(gene_counts)
    corpus.update(consequence_counts)

    # --- run integrity ---
    run_integrity = {
        "bias_rows": len(bias_rows),
        "unique_raw_keys": len({row.variant_id for row in bias_rows}),
        "manifest_identities": len(manifest),
    }

    # --- aggregate direction counts (derived strictly from stratum labels) ---
    direction_counter: Counter[str] = Counter(_direction_label(entry.stratum) for entry in strata)
    directions = {key: direction_counter.get(key, 0) for key in _DIRECTION_KEYS}

    # --- pattern compression ---
    lp_strata = [entry for entry in strata if entry.stratum == "candidate_LP_review"]
    lb_strata = [entry for entry in strata if entry.stratum == "candidate_LB_review"]
    candidate_pattern_compression = {
        "candidate_LP_review": _pattern_stats(lp_strata),
        "candidate_LB_review": _pattern_stats(lb_strata),
    }

    # --- raw criterion incidence + PP3/BP4 suppression (from bias_rows) ---
    raw_bias_criterion_incidence, pp3bp4_suppression = _criterion_incidence_and_suppression(bias_rows)
    consumed_automated_criterion_incidence = {"PP3": 0, "BP4": 0}

    # --- point distribution (all strata, one band per signed_points value) ---
    points_counter: Counter[int] = Counter(entry.signed_points for entry in strata)
    point_distribution = {str(points): count for points, count in sorted(points_counter.items())}

    # --- direction-by-gene / direction-by-consequence (raw stratum labels) ---
    direction_by_gene: dict[str, Counter[str]] = {}
    direction_by_consequence: dict[str, Counter[str]] = {}
    for row in bias_rows:
        manifest_entry = manifest_by_vcf_key.get(row.variant_id)
        if manifest_entry is None:
            continue
        stratum_entry = strata_by_variant_id.get(manifest_entry.variant_id)
        if stratum_entry is None:
            continue
        direction = stratum_entry.stratum
        direction_by_gene.setdefault(row.gene_name, Counter())[direction] += 1
        conseq_class = _variant_class_for(row.consequence)
        direction_by_consequence.setdefault(conseq_class, Counter())[direction] += 1

    # --- historical comparison delta (read historical_stats only for this) ---
    historical_direction = historical_stats.get("raptor_current_policy_internal_direction", {})
    historical_comparison_superseded = {
        key: {
            "historical": historical_direction.get(key, 0),
            "disabled_manual": directions[key],
            "delta": directions[key] - historical_direction.get(key, 0),
        }
        for key in _DIRECTION_KEYS
    }

    return {
        "schema": CENSUS_SCHEMA,
        "status": CENSUS_STATUS,
        "snapshot": run_pins.source_snapshot,
        "policy_mode": POLICY_MODE,
        "non_authoritative_boundary": NON_AUTHORITATIVE_BOUNDARY,
        "code_commit": run_pins.code_commit,
        "source_hashes": {
            "input_vcf": run_pins.input_sha256,
            "bias_tsv": run_pins.output_sha256,
            "manifest": run_pins.manifest_sha256,
        },
        "bound_config_hashes": dict(bound_hashes),
        "run_integrity": run_integrity,
        "corpus": corpus,
        "raptor_current_policy_internal_direction": directions,
        "candidate_pattern_compression": candidate_pattern_compression,
        "raw_bias_criterion_incidence": raw_bias_criterion_incidence,
        "consumed_automated_criterion_incidence": consumed_automated_criterion_incidence,
        "pp3bp4_suppression": pp3bp4_suppression,
        "point_distribution": point_distribution,
        "direction_by_gene": {gene: dict(counter) for gene, counter in direction_by_gene.items()},
        "direction_by_consequence": {
            cls_: dict(counter) for cls_, counter in direction_by_consequence.items()
        },
        "historical_comparison_superseded": historical_comparison_superseded,
        "limitations": list(CENSUS_LIMITATIONS),
    }
