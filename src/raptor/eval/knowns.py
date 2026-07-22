"""PRD-07 sec 10.2/10.3 `knowns.py` — the label-side ClinVar knowns loader.

Reads a ClinVar `variant_summary.txt`(.gz) snapshot, contract-checks +
gene-filters (TSC1/TSC2) it, dependency-injects a `Normalizer` (PRD-02) to
resolve each row's identity to the canonical `variant_id`, and emits
`LabeledVariant` rows (label + provenance only -- FR8/AC6). This module
lives strictly on the EVAL side: it must never be imported by
`raptor.scorer` or `raptor.ingest` (AC5) -- it reads label + identity
columns only and emits no scorer input, closing the R-A2 circularity loop
from the labels side (the ingest/normalizer side never sees a label).

Row outcomes are conserved (R-A10): a row that fails to normalize (an
imprecise/non-ACGT `ManualQueueItem`) is recorded in `self.skipped` and
never silently dropped or force-fit into a fabricated `LabeledVariant`.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterator, List

from ..ingest.contract import SourceContractError, VariantSummaryContract
from ..ingest.model import ManualQueueItem, NormalizedVariant, RawVariant
from ..ingest.normalizer import Normalizer
from ..ingest.reader import (
    _HEX64_RE,
    SourceChecksumMismatchError,
    _open_text,
    _parse_position,
    _sha256_file,
)
from .config import EvalConfig
from .model import LabeledVariant

#: The canonical ClinVar `ClinicalSignificance` -> scoreable-label map
#: (EVAL_PLAN sec 2). ANY string not explicitly listed here (drug response,
#: risk factor, not provided, association, other, multi-condition combos,
#: ...) is deliberately NOT force-fit into a real class -- it maps to the
#: `_NON_SCOREABLE` sentinel, which `benchmark.build_benchmark` excludes.
_CLINSIG_MAP: dict[str, str] = {
    "Pathogenic": "P",
    "Likely pathogenic": "LP",
    "Likely benign": "LB",
    "Benign": "B",
    "Pathogenic/Likely pathogenic": "P",
    "Benign/Likely benign": "B",
    "Uncertain significance": "VUS",
    # VUS sub-tiers (VUS-high/mid/low) are an OPTIONAL ClinGen point-based
    # refinement, NOT an ACMG/AMP 2015 standard tier -- normalize to the
    # standard `VUS` term (no new tier invented). VUS is excluded from the
    # scored truth set like any Uncertain-significance call.
    "VUS-high": "VUS",
    "VUS-mid": "VUS",
    "VUS-low": "VUS",
    "Conflicting interpretations of pathogenicity": "Conflicting",
    "Conflicting classifications of pathogenicity": "Conflicting",
}

#: Case-insensitive lookup built from `_CLINSIG_MAP` (round-2 MINOR-1) --
#: `map_clinical_significance` is whitespace/case robust, since ClinVar
#: source strings can drift in case or carry stray leading/trailing
#: whitespace without a real change in clinical meaning.
_CLINSIG_MAP_LOWER: dict[str, str] = {k.lower(): v for k, v in _CLINSIG_MAP.items()}

#: The `", low penetrance"` modifier is a qualifier on an otherwise-normal
#: base term (e.g. `"Pathogenic, low penetrance"`, or the aggregate combo
#: `"Pathogenic/Likely pathogenic, low penetrance"`) -- round-2 MAJOR-1
#: strips this ONE specific suffix (generically, for ANY base term) before
#: lookup. Other modifiers (`, risk allele`, `, association`, ...) change
#: clinical meaning and are deliberately NOT stripped -- they stay
#: `_NON_SCOREABLE`.
_LOW_PENETRANCE_SUFFIX = ", low penetrance"

#: Deliberately NOT in {P, LP, LB, B} and NOT "VUS"/"Conflicting" -- so an
#: unrecognized `ClinicalSignificance` string is excluded by
#: `benchmark.build_benchmark` (its `_SCOREABLE_LABELS` check) rather than
#: silently miscounted as a real class.
_NON_SCOREABLE = "NON_SCOREABLE"

#: The two genes this benchmark is scoped to (PRD-07 sec 3).
_TARGET_GENES: tuple[str, ...] = ("TSC1", "TSC2")

#: Parses a `p.` token shape into `(ref_aa, pos, rest)`, e.g.
#: `Arg611Gln` -> `("Arg", "611", "Gln")`, `R611Q` -> `("R", "611", "Q")`,
#: `Arg611Ter` -> `("Arg", "611", "Ter")`. Conservative -- anything that
#: does not match this shape (`delins`, complex HGVS, ...) is never guessed.
_TOKEN_RE = re.compile(r"^([A-Za-z]{3}|[A-Za-z])(\d+)(.+)$")

#: A single amino-acid code, three-letter or one-letter (e.g. `Gln`/`Q`) --
#: used to confirm `rest` names exactly one amino acid (a simple
#: substitution), never a `delins`/complex change.
_SINGLE_AA_RE = re.compile(r"^([A-Za-z]{3}|[A-Za-z])$")

#: The initiator methionine, three-letter or one-letter spelling -- a
#: change at position 1 away from Met is a start-loss (LoF), not a
#: missense (round-2 MAJOR-2).
_INITIATOR_MET = frozenset({"Met", "M"})

#: The 20 standard 3-letter amino-acid codes plus selenocysteine/
#: pyrrolysine (round-3 MAJOR-1) -- stored capitalized, compared
#: case-insensitively. Anything NOT in this set (`Del`, `Dup`, `Xaa`,
#: `Zzz`, ...) is never a real amino acid, so `ref_aa`/`rest` naming one of
#: those is never a substitution -- never `missense`.
_AA3 = frozenset(
    {
        "Ala", "Arg", "Asn", "Asp", "Cys", "Gln", "Glu", "Gly", "His", "Ile",
        "Leu", "Lys", "Met", "Phe", "Pro", "Ser", "Thr", "Trp", "Tyr", "Val",
        "Sec", "Pyl",
    }
)

#: The 20 standard 1-letter amino-acid codes plus selenocysteine (`U`) and
#: pyrrolysine (`O`) (round-3 MAJOR-1) -- compared uppercased. `X` (an
#: unknown/placeholder residue) is deliberately NOT included.
_AA1 = frozenset(
    {
        "A", "R", "N", "D", "C", "Q", "E", "G", "H", "I", "L", "K", "M", "F",
        "P", "S", "T", "W", "Y", "V", "U", "O",
    }
)


def _is_canonical_aa(code: str) -> bool:
    """`True` iff `code` is a canonical 3-letter or 1-letter amino-acid code
    (round-3 MAJOR-1) -- case-insensitive. Rejects non-aa tokens like `Del`,
    `Dup`, `Xaa`, `Zzz`, `X` that happen to share the 3-letter (or 1-letter)
    shape but do not name a real residue."""
    if len(code) == 3:
        return code.capitalize() in _AA3
    if len(code) == 1:
        return code.upper() in _AA1
    return False


#: Extracts the `p.` HGVS token out of a ClinVar `Name` field. ClinVar's
#: `c.`-form `Name` wraps the protein consequence in parentheses, e.g.
#: `"NM_000548.5(TSC2):c.1832G>A (p.Arg611Gln)"` -> `"Arg611Gln"`. HGVS
#: protein-accession forms present a BARE `p.` with no wrapping parens, e.g.
#: `"NP_0123456.1:p.Arg97ProfsTer23"` -> `"Arg97ProfsTer23"`; both must be
#: parsed (the paren form is tried first, then the bare form).
_PROTEIN_TOKEN_RE = re.compile(r"\(p\.([^)]*)\)")
_PROTEIN_TOKEN_BARE_RE = re.compile(r"(?<![A-Za-z])p\.(\(?[A-Za-z0-9_?*=^]+\)?)")


def map_clinical_significance(sig: str, cfg: EvalConfig | None = None) -> str:
    """Map a raw ClinVar `ClinicalSignificance` string to a scoreable label
    (`"P"`/`"LP"`/`"LB"`/`"B"`), `"VUS"`, `"Conflicting"`, or the
    `_NON_SCOREABLE` sentinel for anything else (AC1). `cfg` is accepted
    for a uniform call signature but not currently consulted -- the map is
    a fixed, canonical clinical vocabulary, not a config-tunable pin.

    Whitespace/case robust (round-2 MINOR-1): the input is stripped and
    looked up case-insensitively. The `", low penetrance"` modifier is
    generically stripped (case-insensitively, re-stripping whitespace)
    before lookup (round-2 MAJOR-1), so it composes with ANY base term --
    including aggregate combos like
    `"Pathogenic/Likely pathogenic, low penetrance"` -- without needing a
    dedicated map entry per combo. Other modifiers (`, risk allele`,
    `, association`, ...) are NOT stripped -- they change clinical meaning
    and must stay `_NON_SCOREABLE`."""
    s = (sig or "").strip()
    if s.lower().endswith(_LOW_PENETRANCE_SUFFIX):
        s = s[: -len(_LOW_PENETRANCE_SUFFIX)].strip()
    return _CLINSIG_MAP_LOWER.get(s.lower(), _NON_SCOREABLE)


def classify_variant(name: str) -> str:
    """Parse the `p.` HGVS token out of a ClinVar `Name` field and classify
    it as `"missense"`, `"truncating"`, or `"other"` (AC2). Conservative: if
    the `p.` token cannot be confidently parsed as a substitution, this
    returns `"other"`, NEVER `"missense"`.

    Round-2 MAJOR-2 key insight: `Ter`/`*` means TRUNCATING only as the
    ALT (`aa -> Ter`, a nonsense change) -- never as the REF (`Ter -> aa`,
    a stop-loss, which extends the protein and is not truncating). The
    ordered rules below (see PRD-07 checker round-2) also exclude the
    initiator-Met (start-loss) from the missense stratum, and unwrap a
    predicted-consequence token like `p.(Arg611Gln)` down to its inner
    substitution."""
    match = _PROTEIN_TOKEN_RE.search(name or "")
    if not match:
        # No parenthesized `(p...)`: try a bare `p.` token (HGVS protein-
        # accession form, e.g. `NP_0123456.1:p.Arg97ProfsTer23`).
        match = _PROTEIN_TOKEN_BARE_RE.search(name or "")
    if not match:
        return "other"
    # Strip surrounding parentheses and whitespace, e.g. a predicted
    # `p.(Arg611Gln)` -> `Arg611Gln`.
    token = match.group(1).strip(" ()")
    if not token or token == "=":
        return "other"  # no p. token / empty / synonymous notation
    token_lower = token.lower()
    if token_lower.startswith("ter") or token_lower.startswith("*"):
        # REF is the stop codon -- stop-loss, NOT truncating (case-folded,
        # round-3 MAJOR-1: e.g. lowercase `ter1808arg`).
        return "other"
    if "ext" in token_lower:
        # A stop-loss EXTENSION (e.g. `Ter1808ArgextTer3`) makes a LONGER
        # protein -- it is not a truncating (nonsense/frameshift) change.
        return "other"
    if "fs" in token_lower:
        return "truncating"  # frameshift

    tok_match = _TOKEN_RE.match(token)
    if not tok_match:
        return "other"  # unparseable -- never guess "missense"
    ref_aa, pos, rest = tok_match.groups()
    # Normalize each side to its own case system (3-letter -> capitalized,
    # 1-letter -> uppercased) for comparison (round-3 MAJOR-1: case-folded
    # marker/AA logic, e.g. lowercase `met1val`/`arg611gln`).
    ref_norm = ref_aa.capitalize() if len(ref_aa) == 3 else ref_aa.upper()
    rest_norm = rest.capitalize() if len(rest) == 3 else rest.upper()

    if pos == "1" and ref_norm in _INITIATOR_MET:
        # Initiator-Met change is a start-loss (LoF), not a missense.
        return "other"
    if rest_norm in ("Ter", "*"):
        return "truncating"  # nonsense: aa -> stop
    if (
        _SINGLE_AA_RE.match(rest)
        and _is_canonical_aa(ref_aa)
        and _is_canonical_aa(rest)
        and len(ref_aa) == len(rest)
        and ref_norm != rest_norm
    ):
        return "missense"  # simple, canonical aa substitution
    return "other"  # synonymous, delins, unknown/placeholder aa, or other complex change


def _matched_target_gene(gene_symbol_field: str) -> str | None:
    """Same multi-gene-row handling as
    `ingest.reader.ClinVarVariantSummaryReader._gene_matches` -- ClinVar's
    `GeneSymbol` is usually an exact symbol, but multi-gene (CNV/SV) rows
    encode it as `"subset of N genes: A:B:C:..."`. Each `:`-separated token
    is stripped before comparison, so a leading-space token (e.g. the
    `" TSC1"` left over after splitting `"subset of N genes: TSC1:PKD1"`)
    still matches. Returns whichever of TSC1/TSC2 matched, or `None`."""
    field = gene_symbol_field or ""
    if field == "":
        return None
    for gene in _TARGET_GENES:
        if field == gene:
            return gene
        if ":" in field:
            tokens = [t.strip() for t in field.split(":")]
            if gene in tokens:
                return gene
    return None


def _source_for_review_status(review_status: str) -> str:
    """Map ClinVar `ReviewStatus` to a label-source-hierarchy key that is a
    real key in `benchmark._SOURCE_RANK` (EVAL_PLAN sec 2)."""
    rs = (review_status or "").strip().lower()
    if rs in ("reviewed by expert panel", "practice guideline"):
        return "clingen_vcep"
    if rs.startswith("criteria provided, multiple submitters, no conflicts"):
        return "clinvar_2star_concordant"
    return "clinvar"


class LabeledVariantReader:
    """Iterable of `LabeledVariant` rows read + gene-filtered + identity-
    resolved from a ClinVar `variant_summary` snapshot (PRD-07 sec 10.3).

    Dependency-injects a `Normalizer` (PRD-02 port) to resolve each row's
    genomic identity -- this module never re-implements SPDI normalization,
    and never hardcodes a concrete normalizer import at module scope, so
    the eval/labels side stays decoupled from any concrete ingest impl.
    """

    def __init__(
        self,
        path: str | Path,
        config: EvalConfig,
        normalizer: Normalizer,
        *,
        snapshot_id: str | None = None,
        snapshot_date: str | None = None,
    ):
        self.path = Path(path)
        self.config = config
        self.normalizer = normalizer
        self._snapshot_id = snapshot_id or str(getattr(config, "labels_snapshot", "") or "")
        self._snapshot_date = snapshot_date or ""
        #: skipped-with-reason records (AC3/kit conservation) -- a row that
        #: could not be normalized to a trustworthy identity, never a
        #: silent drop.
        self.skipped: List[dict] = []

        #: The real sha256 of the source file (round-2 MINOR-2) -- always
        #: computed and stored, pin or no pin, so a frozen benchmark's
        #: exact source file is recoverable for audit even when no pin was
        #: supplied.
        self.source_file_checksum: str = _sha256_file(self.path)

        pinned = str(getattr(config, "clinvar_snapshot_file_checksum", "") or "")
        if pinned and _HEX64_RE.match(pinned):
            if pinned.lower() != self.source_file_checksum.lower():
                raise SourceChecksumMismatchError(
                    f"clinvar snapshot checksum mismatch for {self.path}: "
                    f"pinned {pinned!r} != actual sha256 {self.source_file_checksum!r} "
                    "-- refusing to ingest a different labels file than pinned "
                    "(FR1/FR5/AC4)"
                )

    def __iter__(self) -> Iterator[LabeledVariant]:
        with _open_text(self.path) as f:
            reader = csv.reader(f, delimiter="\t")
            try:
                header = next(reader)
            except StopIteration:
                return
            VariantSummaryContract.assert_columns(header)
            idx = {name: i for i, name in enumerate(header)}

            for row_num, row in enumerate(reader, start=2):
                if not row:
                    continue
                gene_symbol_field = row[idx["GeneSymbol"]]
                gene = _matched_target_gene(gene_symbol_field)
                if gene is None:
                    continue

                variation_id = row[idx["VariationID"]]
                chromosome = row[idx["ChromosomeAccession"]]
                position = _parse_position(row[idx["PositionVCF"]])
                ref = row[idx["ReferenceAlleleVCF"]]
                alt = row[idx["AlternateAlleleVCF"]]
                raw = RawVariant(
                    chromosome=chromosome,
                    position=position,
                    ref=ref,
                    alt=alt,
                    gene=gene,
                    variation_id=variation_id,
                    snapshot_id=self._snapshot_id,
                    snapshot_date=self._snapshot_date,
                    source_file_checksum="",
                    row_locator=str(row_num),
                    # Label-free by construction (H1/AC5) -- the normalizer
                    # is the scorer-side identity path and must never see
                    # the ClinicalSignificance label or any other row data;
                    # it only needs the coordinates it already has above.
                    raw_source_value=f"{chromosome}\t{position}\t{ref}\t{alt}",
                )
                outcome = self.normalizer.normalize(raw, self.config)

                if isinstance(outcome, ManualQueueItem):
                    self.skipped.append(
                        {
                            "variation_id": variation_id,
                            "row_locator": str(row_num),
                            "error_code": outcome.error_code,
                            "reason": outcome.reason,
                        }
                    )
                    continue

                if not isinstance(outcome, NormalizedVariant):
                    raise TypeError(
                        f"Normalizer.normalize returned {outcome!r} for VariationID "
                        f"{variation_id!r} -- expected a NormalizedVariant or "
                        "ManualQueueItem (AC1 conservation: every row must yield "
                        "exactly one of them, never a silent drop)"
                    )

                submitters_raw = row[idx["NumberSubmitters"]].strip()
                submitter_count = int(submitters_raw) if submitters_raw else 0
                review_status = row[idx["ReviewStatus"]]

                yield LabeledVariant(
                    variant_id=outcome.variant_id,
                    label=map_clinical_significance(row[idx["ClinicalSignificance"]]),
                    review_status=review_status,
                    submitter_count=submitter_count,
                    source=_source_for_review_status(review_status),
                    snapshot=self._snapshot_id,
                    raptor_influenced=False,
                    variant_class=classify_variant(row[idx["Name"]]),
                )


def load_known_labels(
    path: str | Path, config: EvalConfig, normalizer: Normalizer
) -> List[LabeledVariant]:
    """Load the full, order-stable list of `LabeledVariant`s from a ClinVar
    `variant_summary` snapshot (PRD-07 sec 10.3). Snapshot id/date default
    to `config.labels_snapshot` (see `LabeledVariantReader`)."""
    reader = LabeledVariantReader(path, config, normalizer)
    return list(reader)
