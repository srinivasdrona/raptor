"""PRD-01 sec 10.4 `policy.py` — FR4 no-double-count audit + FR8 edge-case routing.

FR4: correlated predictors (CADD/REVEL/BIAS/domain) are already merged by
BIAS into a single fired int per criterion -- this module only ASSERTS that
invariant held (never re-merges/re-derives).

FR8/R-A3: `edge_cases` (config, `configs/acmg/edge_cases.yaml` policy keys)
gates predicates that override a BIAS auto-score with a manual-review
routing. Every predicate is driven entirely by config + the `BiasRecord`'s
own fields -- never a hardcoded fixture-specific variant/gene check.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from raptor.ingest.transcript_reconcile import (
    RECONCILED_VERSION_DELTA,
    reconcile_transcript_identity,
)

from .model import BiasRecord, CriterionCall


def _canonical_spdi(record: BiasRecord) -> str:
    """The canonical genomic SPDI a reference-backed normalizer or an
    upstream canonical-adapter/manifest enrichment step has already
    computed and staged into `record.provenance["canonical_spdi"]` -- the
    ONLY accepted identity PROOF for `reconcile_transcript_identity`.

    NEVER falls back to building a raw `chrom:pos:ref:alt` echo of the
    record's own already-known coordinates: that string is exactly what
    BIAS itself emitted, not an independently reference-validated
    identity. A record whose provenance carries no `canonical_spdi` (e.g.
    direct `BiasTsvSource` output, which parses BIAS's raw TSV columns
    only and never invokes a normalizer) yields `""` here, which
    `reconcile_transcript_identity` fails closed on
    (`canonical_identity_unverified`) rather than silently trusting."""
    return str(record.provenance.get("canonical_spdi") or "")


class DoubleCountError(ValueError):
    """FR4: an ACMG criterion fired more than once for the same variant in
    the same call set. BIAS itself dedups correlated predictors into one
    fired int per criterion, so this should never happen -- if it does,
    fail loud rather than silently pick/merge one."""


def assert_no_double_count(calls: Sequence[CriterionCall]) -> None:
    seen: set[str] = set()
    for call in calls:
        if call.criterion in seen:
            raise DoubleCountError(
                f"criterion {call.criterion!r} fired more than once in the same call set "
                "(FR4 no-double-count invariant violated)"
            )
        seen.add(call.criterion)


def check_edge_cases(record: BiasRecord, config: Any) -> str | None:
    """FR8: return a human-readable routing reason if `record` must go to
    manual review instead of being auto-scored, else `None`.

    Every predicate is gated by `config.edge_cases` (a plain dict of
    predicate-name -> enabled) -- disabled predicates never fire, and no
    predicate here inspects anything besides the record's own fields +
    config (never a fixture-specific variant_id/gene literal).
    """
    edge_cases = dict(getattr(config, "edge_cases", None) or {})

    # splice-region: BIAS's own `consequence` classification flags this
    # directly -- computational predictors are least reliable here (FR8).
    # `consequence` may be a single term or a compound (VEP `&`-joined,
    # or comma-joined) encoding -- match `splice_region_variant` as a
    # TOKEN of that compound, not by exact-string equality, so a variant
    # never slips through auto-scoring just because a splice-region call
    # is bundled with another consequence term.
    consequence_tokens = {
        token.strip()
        for token in re.split(r"[&,+]", record.consequence)
        if token.strip()
    }
    if edge_cases.get("splice_region") and "splice_region_variant" in consequence_tokens:
        return (
            f"splice_region: consequence {record.consequence!r} contains a splice-region "
            "variant token -- routed to manual review per edge_cases.yaml (FR8/R-A3)"
        )

    # non-MANE / ambiguous transcript: compare against this gene's pinned
    # transcript (config.genes, GP-6) -- never a hardcoded accession.
    #
    # Policy-blocker C: BIAS emits each record's raw `.4` transcript while
    # `config.genes` pins the MANE Select `.5` -- a pure version delta on
    # the SAME base accession describes the identical genomic change (the
    # canonical SPDI is version-independent, `ingest/normalizer.py`) and is
    # reconciled here rather than dumped to manual review
    # (`reconcile_transcript_identity`, `ingest/transcript_reconcile.py`).
    # A genuinely different base accession still fails loud -- this is a
    # correction of an over-block, never a weakening: only an exact base
    # match, backed by a VERIFIED canonical SPDI (read from
    # `record.provenance["canonical_spdi"]`, never a raw chr:pos echo), is
    # ever let through; the raw emitted transcript is kept as-is (never
    # silently coerced to the pinned accession). A record with no
    # canonical-adapter/manifest-supplied SPDI (e.g. direct `BiasTsvSource`
    # output) fails closed here (`canonical_identity_unverified`) instead
    # of being silently reconciled.
    if edge_cases.get("non_mane_transcript"):
        pinned_transcript = dict(getattr(config, "genes", None) or {}).get(record.gene_name)
        if pinned_transcript and record.transcript != pinned_transcript:
            reconciliation = reconcile_transcript_identity(
                record,
                _canonical_spdi(record),
                {record.gene_name: {"transcript_accession": pinned_transcript}},
            )
            if reconciliation.disposition != RECONCILED_VERSION_DELTA:
                return (
                    f"non_mane_transcript: record transcript {record.transcript!r} != "
                    f"gene {record.gene_name!r}'s pinned transcript {pinned_transcript!r} "
                    f"(reconciliation: {reconciliation.disposition}) "
                    "-- routed to manual review per edge_cases.yaml (FR8/R-A3)"
                )

    # mosaicism: BIAS's `consequence`/annotation text flags this explicitly
    # when present -- no mosaic-specific field exists in the v1 BIAS output
    # contract, so this checks the only place such a flag could appear.
    if edge_cases.get("mosaicism") and "mosaic" in record.consequence.lower():
        return (
            f"mosaicism: consequence {record.consequence!r} flags a mosaic call -- "
            "routed to manual review per edge_cases.yaml (FR8/R-A3)"
        )

    # PVS1 terminal-exon: BIAS's own PVS1 rationale explanation is where a
    # terminal-exon caveat would be named (BIAS decides the biology, RAPTOR
    # only routes on it) -- never re-derived from exon coordinates here.
    if edge_cases.get("pvs1_terminal_exon"):
        for criterion_key, value in record.criteria.items():
            if criterion_key.lower().startswith("pvs") and int(value[0]) > 0:
                explanation = str(value[1]).lower()
                if "terminal" in explanation or "last exon" in explanation:
                    return (
                        "pvs1_terminal_exon: PVS1 fired with a terminal-exon rationale -- "
                        "routed to manual review per edge_cases.yaml (FR8/R-A3)"
                    )

    return None


def check_out_of_scope_gene(record: BiasRecord, config: Any) -> str | None:
    """R-A3/v1-scope: return a routing reason if `record.gene_name` is not a
    key in `config.genes`, else `None`.

    This is an ALWAYS-ON safety invariant -- unlike `check_edge_cases`'s
    predicates it is not gated by `config.edge_cases` (there is no v1-scope
    "toggle": a gene RAPTOR has no pinned transcript/policy for must never
    be silently scored)."""
    genes = dict(getattr(config, "genes", None) or {})
    if record.gene_name not in genes:
        return (
            f"out_of_scope_gene: gene {record.gene_name!r} is not in the v1 scope "
            "config.genes -- routed to manual review (R-A3)"
        )
    return None
