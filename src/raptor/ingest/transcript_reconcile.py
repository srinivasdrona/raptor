"""Policy-blocker C — `transcript_reconcile.py`: canonical-SPDI-keyed
transcript-identity reconciliation.

BIAS-3.0.0 emits each TSC1/TSC2 record annotated against the raw `.4`
RefSeq transcript version while RAPTOR production pins the MANE Select
`.5` (`configs/ingest/tsc.yaml`, `configs/acmg/tsc.yaml`). A pure version
delta on the SAME base accession describes the identical genomic change
(the canonical genomic SPDI a caller has already computed -- e.g.
`ingest/normalizer.py::SeqRepoGenomicNormalizer.normalize`'s `variant_id`
-- is invariant to the annotating transcript's version, since the
normalizer never even looks at a transcript, only chrom/pos/ref/alt), so
it is reconciled rather than dumped to manual review. A genuinely
different base accession, or a gene this reconciliation has no pinned
MANE identity for, fails loud instead -- never silently coerced.

This module never re-derives SPDI itself: the caller passes in whatever
canonical genomic SPDI it already computed via a reference-backed
normalizer or an upstream canonical-adapter/manifest enrichment step (see
`scripts/probe_transcript_reconciliation.py`). A record's own raw
`chrom:pos:ref:alt` echo is NEVER accepted as this proof -- that is
exactly the coordinate string the record itself already carries, not an
independently verified genomic identity -- so a missing/malformed SPDI,
one pinned to the wrong genomic accession, or (for an SNV) one whose
position/ref/alt disagree with the record's own fields, is fail-closed to
`canonical_identity_unverified` rather than silently trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


#: The dispositions this reconciliation can return (slot 2 sec 2.2).
RECONCILED_VERSION_DELTA = "reconciled_version_delta"
OUT_OF_SCOPE_GENE = "out_of_scope_gene"
TRANSCRIPT_BASE_MISMATCH = "transcript_base_mismatch"
CANONICAL_IDENTITY_UNVERIFIED = "canonical_identity_unverified"

# Canonical GRCh38 genomic SPDI syntax: `NC_######.<version>:<0-based
# position>:<deleted DNA or empty>:<inserted DNA or empty>` (matches the
# normalizer's own `bioutils.normalize` EXPAND-mode output shape, never
# re-derived here -- syntax validation only).
_CANONICAL_SPDI_RE = re.compile(r"^(NC_[0-9]{6}\.[0-9]+):([0-9]+):([ACGTN]*):([ACGTN]*)$")

#: Per-gene pinned GRCh38 genomic RefSeq accession -- mirrors the already
#: -reviewed `genome_accession` pin in `configs/ingest/tsc.yaml`. This is
#: ONLY a validation fallback: a caller whose own `config[gene]` block
#: already supplies `genome_accession` (e.g. loaded straight from that
#: file) always has its value used instead. It exists so a caller that
#: only has the scorer's flat gene->transcript pin (`configs/acmg/tsc.yaml`
#: `genes:` map, which carries no genomic accession of its own) can still
#: have a supplied SPDI's accession checked against the correct, already-
#: pinned genomic accession -- an explicit, reviewed, non-wildcard map of
#: exactly the two in-scope genes, never a default/guessed entry.
_PINNED_GENOME_ACCESSIONS: Mapping[str, str] = {
    "TSC1": "NC_000009.12",
    "TSC2": "NC_000016.10",
}


@dataclass(frozen=True)
class TranscriptReconciliation:
    """The outcome of reconciling one record's emitted transcript against
    its gene's pinned MANE identity, keyed on canonical genomic SPDI +
    base accession (never the raw transcript string alone)."""

    gene: str
    emitted_transcript: str
    pinned_transcript: str | None
    base_accession_match: bool
    version_delta: bool
    spdi: str
    disposition: str


def split_transcript_accession(accession: str) -> tuple[str, str | None]:
    """Split `NM_000548.4` into `("NM_000548", "4")`. An accession with no
    `.version` suffix returns `(accession, None)` -- never guessed."""
    if "." in accession:
        base, _, version = accession.rpartition(".")
        return base, version
    return accession, None


def _identity_verified(record: Any, spdi: str, expected_genome_accession: str | None) -> bool:
    """Validate `spdi` as canonical identity PROOF for `record`, never as a
    mere echo of the record's own coordinates:

    - `spdi` must match the canonical GRCh38 SPDI syntax
      (`NC_######.<version>:<0-based position>:<ref>:<alt>`) -- missing or
      malformed fails.
    - its genomic accession must equal `expected_genome_accession` (the
      in-scope gene's pinned genomic accession) -- wrong/unknown accession
      fails.
    - for an SNV (`record.variant_type == "SNV"`, case-insensitive), its
      0-based position/ref/alt must match `record.position - 1`/
      `record.ref_allele`/`record.alt_allele` exactly -- any mismatch
      fails. Non-SNV variant classes are not held to this exact-coordinate
      check (EXPAND-normalized indel representations may legitimately
      shift), but still require a matching accession above.
    """
    match = _CANONICAL_SPDI_RE.fullmatch(spdi or "")
    if match is None:
        return False

    accession, pos0_str, ref, alt = match.groups()
    if not expected_genome_accession or accession != expected_genome_accession:
        return False

    variant_type = str(getattr(record, "variant_type", "") or "").upper()
    if variant_type == "SNV":
        position = getattr(record, "position")
        ref_allele = getattr(record, "ref_allele")
        alt_allele = getattr(record, "alt_allele")
        if int(pos0_str) != int(position) - 1 or ref != ref_allele or alt != alt_allele:
            return False

    return True


def reconcile_transcript_identity(
    record: Any, spdi: str, config: Mapping[str, Any]
) -> TranscriptReconciliation:
    """Reconcile `record.transcript` against `record.gene_name`'s pinned
    MANE transcript in `config` (a per-gene mapping of
    `{transcript_accession, genome_accession, ...}`, e.g.
    `configs/ingest/tsc.yaml`), after first requiring `spdi` to be verified
    canonical identity PROOF for `record` -- never a raw `chrom:pos:ref:alt`
    echo of the record's own already-known coordinates.

    - `record.gene_name` absent from `config` (or not a per-gene block) ->
      `out_of_scope_gene` -- fail loud, never silently scored/re-attributed.
    - `spdi` missing/malformed, pinned to the wrong genomic accession, or
      (for an SNV) disagreeing with the record's own position/ref/alt ->
      `canonical_identity_unverified` -- fail loud, manual routing; a
      caller with no canonical-adapter/manifest-supplied SPDI (e.g. direct
      `BiasTsvSource` output) is fail-closed here, never silently trusted.
    - Same MANE base accession, any version (including identical) ->
      `reconciled_version_delta` -- in scope, not routed to manual review;
      `version_delta` records whether the version actually differs
      (provenance only, never coerced into the emitted transcript).
    - Different base accession -> `transcript_base_mismatch` -- fail loud,
      never silently coerced to the pinned accession.
    """
    gene_name = getattr(record, "gene_name")
    emitted_transcript = getattr(record, "transcript")

    gene_cfg = config.get(gene_name) if isinstance(config, Mapping) else None
    if not isinstance(gene_cfg, Mapping) or "transcript_accession" not in gene_cfg:
        return TranscriptReconciliation(
            gene=gene_name,
            emitted_transcript=emitted_transcript,
            pinned_transcript=None,
            base_accession_match=False,
            version_delta=False,
            spdi=spdi,
            disposition=OUT_OF_SCOPE_GENE,
        )

    pinned_transcript = str(gene_cfg["transcript_accession"])

    expected_genome_accession = gene_cfg.get("genome_accession") or _PINNED_GENOME_ACCESSIONS.get(
        gene_name
    )
    if not _identity_verified(record, spdi, expected_genome_accession):
        return TranscriptReconciliation(
            gene=gene_name,
            emitted_transcript=emitted_transcript,
            pinned_transcript=pinned_transcript,
            base_accession_match=False,
            version_delta=False,
            spdi=spdi,
            disposition=CANONICAL_IDENTITY_UNVERIFIED,
        )

    emitted_base, emitted_version = split_transcript_accession(emitted_transcript)
    pinned_base, pinned_version = split_transcript_accession(pinned_transcript)

    base_accession_match = emitted_base == pinned_base
    version_delta = base_accession_match and emitted_version != pinned_version
    disposition = RECONCILED_VERSION_DELTA if base_accession_match else TRANSCRIPT_BASE_MISMATCH

    return TranscriptReconciliation(
        gene=gene_name,
        emitted_transcript=emitted_transcript,
        pinned_transcript=pinned_transcript,
        base_accession_match=base_accession_match,
        version_delta=version_delta,
        spdi=spdi,
        disposition=disposition,
    )
