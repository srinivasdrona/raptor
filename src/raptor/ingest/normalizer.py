"""PRD-02 sec 10.3 `normalizer.py` — FR2: the `Normalizer` port + the real
genomic-SPDI implementation.

`SeqRepoGenomicNormalizer` computes the canonical GRCh38 genomic SPDI
(`variant_id`, sec 2.1) from raw VCF-style coordinates + a local, pinned,
checksummed reference FASTA -- reusing `bioutils.normalize` (biocommons,
GP-4: a recognized implementation, not a hand-rolled parser) for the
actual trim/roll/expand algebra, and `pysam.FastaFile` (htslib, the
standard indexed-FASTA reader) for random-access reference lookups
without loading whole chromosomes into memory.

`bioutils.normalize(..., mode=EXPAND)` performs exactly the "fully
justified" repeat-expansion normalization that the NCBI Variation
Services SPDI API (the AC3 independent oracle, sec 10.5) also produces --
verified byte-for-byte against the AC3 fixture during development.

c./p. projection needs transcript<->genome alignment (UTA) and is out of
scope for this increment (sec 10.6): every `NormalizedVariant` this class
returns has `hgvs_c = hgvs_p = None` with `*_null_reason =
"awaiting_uta_projection"`.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Protocol

from .classify import classify_variant
from .model import ManualQueueItem, NormalizationOutcome, NormalizedVariant, RawVariant, VariantClass

#: Env var pointing at the local reference root (sec 10.1); falls back to a
#: conventional path so `SeqRepoGenomicNormalizer()` (no-arg construction,
#: as the tests call it) still works out of the box once populated.
SEQREPO_ROOT_ENV = "RAPTOR_SEQREPO_ROOT"
DEFAULT_SEQREPO_ROOT = Path.home() / "raptor-refseq"

#: Values ClinVar uses to mark "no precise VCF coordinate" (imprecise SV/CNV
#: rows, FR3 -> manual queue, never forced through the genomic normalizer).
_MISSING_TOKENS = {"na", "", "-"}

#: A literal, precise VCF-style allele must be non-empty ACGT only. Anything
#: else -- symbolic SV/CNV notation (`<DEL>`, `<DUP>`, `<INS>`), a no-call
#: (`.`), an ambiguity/no-call base (`N`), or the ClinVar/VCF spanning-
#: deletion marker (`*`) -- is not a literal sequence and must never be fed
#: to the SPDI normalizer as if it were one (FR3).
_ACGT_RE = re.compile(r"^[ACGT]+$")

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class Normalizer(Protocol):
    """FR2 port: dependency-injected so structural ACs can run offline
    against a fake (sec 10.4), while AC3 correctness is validated only
    against a real implementation + real reference + independent oracle."""

    def normalize(self, raw: RawVariant, config: object) -> NormalizationOutcome: ...


class ReferenceNotAvailableError(RuntimeError):
    """Raised when the pinned genomic reference FASTA is not present locally."""


class ReferenceChecksumMismatchError(RuntimeError):
    """Raised when a pinned reference FASTA's sha256 (`config.reference_checksums`)
    disagrees with the file's actual sha256 -- R-A11/FR8: a whole-run
    reproducibility breach, never proceed on an unverified reference."""


def _sha256_file(path: Path) -> str:
    """Real sha256 of `path`, read in fixed-size chunks (never the whole
    file at once)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


class SeqRepoGenomicNormalizer:
    """Real `Normalizer` impl (FR2): genomic SPDI + `hgvs_g` from a local
    reference, no network calls at run time (R-A11 reproducibility).

    Reference layout: `{reference_root}/{genomic_accession}.fasta` (+ a
    `.fai` index, built once via `pysam.faidx`) for each genome accession
    referenced by the ingest config's gene blocks -- e.g.
    `NC_000009.12.fasta`, `NC_000016.10.fasta` (sec 10.1: only the pinned
    gene chromosomes, not a full SeqRepo/fleet snapshot).
    """

    def __init__(self, reference_root: str | os.PathLike | None = None):
        root = reference_root or os.environ.get(SEQREPO_ROOT_ENV) or str(DEFAULT_SEQREPO_ROOT)
        self.reference_root = Path(root)
        if not self.reference_root.is_dir():
            raise ReferenceNotAvailableError(
                f"reference root {self.reference_root} does not exist -- set "
                f"{SEQREPO_ROOT_ENV} or populate the default path with the pinned "
                "genomic FASTA(s) (sec 10.1)"
            )
        self._fasta_cache: dict[str, object] = {}
        #: accession -> actual on-disk sha256, computed at most once per
        #: run (the expensive part); the *comparison* against the current
        #: config's pin still happens on every `_fasta_for` call below, since
        #: a reused normalizer may later be handed a different (wrong) pin
        #: for the same, already-cached FASTA (sec fix-2).
        self._actual_hash: dict[str, str] = {}

    # ------------------------------------------------------------------
    def _fasta_for(self, accession: str, config: object = None):
        if accession not in self._fasta_cache:
            import pysam  # local import: only needed once real reference data is used

            path = self.reference_root / f"{accession}.fasta"
            if not path.is_file():
                raise ReferenceNotAvailableError(f"no reference FASTA for {accession!r} at {path}")
            self._fasta_cache[accession] = pysam.FastaFile(str(path))
        else:
            path = self.reference_root / f"{accession}.fasta"
        # R-A11/FR8: verify against *this call's* config on every invocation
        # -- never skip just because some earlier call (possibly with a
        # different/no pin) already loaded the FASTA.
        self._verify_reference_checksum(accession, path, config)
        return self._fasta_cache[accession]

    def _verify_reference_checksum(self, accession: str, path: Path, config: object) -> None:
        """R-A11/FR8: if `config.reference_checksums` pins a sha256 for this
        accession, the FASTA on disk must match it -- fail loud (never
        route to manual queue) on a mismatch, since an unverified/altered
        reference silently corrupts every variant normalized against it,
        not just one row. No entry pinned -> proceed unchecked.

        Runs on every call (a reused normalizer must reverify per-config),
        but only ever hashes the file itself once per accession."""
        reference_checksums = getattr(config, "reference_checksums", None) or {}
        expected = reference_checksums.get(accession)
        if not expected:
            return
        actual = self._actual_hash.get(accession)
        if actual is None:
            actual = _sha256_file(path)
            self._actual_hash[accession] = actual
        if str(expected).lower() != actual.lower():
            raise ReferenceChecksumMismatchError(
                f"reference FASTA checksum mismatch for {accession!r} at {path}: "
                f"pinned {expected!r} != actual sha256 {actual!r} -- refusing to "
                "normalize against an unverified/altered reference (R-A11/FR8)"
            )

    @staticmethod
    def _is_imprecise(raw: RawVariant) -> bool:
        try:
            pos = int(raw.position)
        except (TypeError, ValueError):
            return True
        if pos <= 0:
            return True
        ref = (raw.ref or "").strip().lower()
        alt = (raw.alt or "").strip().lower()
        return ref in _MISSING_TOKENS or alt in _MISSING_TOKENS

    @staticmethod
    def _is_symbolic_or_invalid(raw: RawVariant) -> bool:
        """FR3: a precise-coordinate row can still carry a symbolic ALT
        (`<DEL>`/`<DUP>`/`<INS>`), a no-call (`.`), an ambiguity base (`N`),
        or the spanning-deletion marker (`*`) -- none of these are a
        literal inserted/deleted sequence, so neither `ref` nor `alt` may
        be treated as one unless both are non-empty ACGT-only strings."""
        ref = (raw.ref or "").strip().upper()
        alt = (raw.alt or "").strip().upper()
        return not (_ACGT_RE.match(ref) and _ACGT_RE.match(alt))

    def normalize(self, raw: RawVariant, config: object) -> NormalizationOutcome:
        coords = f"{raw.chromosome}:{raw.position}:{raw.ref}:{raw.alt}"

        if self._is_imprecise(raw):
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="classify",
                error_code="IMPRECISE_COORDS",
                reason=(
                    "variant lacks precise VCF-style coordinates (imprecise "
                    "SV/CNV or unresolved PositionVCF) -- FR3 routes these to "
                    "manual queue, never forced"
                ),
                attempted_coords=coords,
                tool_error=None,
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        if self._is_symbolic_or_invalid(raw):
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="classify",
                error_code="SYMBOLIC_OR_INVALID_ALLELE",
                reason=(
                    f"ref={raw.ref!r}/alt={raw.alt!r} is not a literal ACGT "
                    "allele (symbolic SV/CNV notation, no-call, or ambiguity "
                    "base) -- FR3 routes these to manual queue, never treated "
                    "as a literal inserted/deleted sequence"
                ),
                attempted_coords=coords,
                tool_error=None,
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        try:
            fasta = self._fasta_for(raw.chromosome, config)
            chrom_len = fasta.get_reference_length(raw.chromosome)
        except ReferenceChecksumMismatchError:
            # R-A11/FR8: a whole-run reproducibility breach -- fail loud,
            # never quietly route around it a row at a time.
            raise
        except Exception as exc:  # reference missing/unreadable -> manual queue, not a crash
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="normalize",
                error_code="REFERENCE_UNAVAILABLE",
                reason=f"could not load reference sequence for {raw.chromosome!r}",
                attempted_coords=coords,
                tool_error=repr(exc),
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        ref = raw.ref.strip().upper()
        alt = raw.alt.strip().upper()
        position = int(raw.position)
        start0 = position - 1
        end0 = start0 + len(ref)

        try:
            ref_from_reference = _fetch(fasta, raw.chromosome, start0, end0).upper()
        except Exception as exc:
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="normalize",
                error_code="REFERENCE_UNAVAILABLE",
                reason=f"could not read reference sequence at {raw.chromosome}:{position}",
                attempted_coords=coords,
                tool_error=repr(exc),
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        if ref_from_reference != ref:
            # [blocker] R-A10: never silently "correct" a mismatched input
            # REF into the reference-derived variant -- a wrong/mismatched
            # REF is exactly the coordinate/build-mismatch failure this
            # module exists to catch.
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="normalize",
                error_code="REF_MISMATCH",
                reason=(
                    f"input REF {ref!r} does not match the reference sequence "
                    f"{ref_from_reference!r} at {raw.chromosome}:{position} -- "
                    "likely a coordinate or genome-build mismatch"
                ),
                attempted_coords=coords,
                tool_error=None,
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        try:
            (norm_start, norm_end), norm_alt = _spdi_normalize(
                fasta, raw.chromosome, chrom_len, start0, end0, alt
            )
            norm_ref = _fetch(fasta, raw.chromosome, norm_start, norm_end)
        except Exception as exc:
            return ManualQueueItem(
                raw_input=raw.raw_source_value,
                source_ref=raw.variation_id,
                failure_stage="normalize",
                error_code="NORMALIZATION_FAILED",
                reason="SPDI normalization against the reference sequence failed",
                attempted_coords=coords,
                tool_error=repr(exc),
                config_pins=_pins(config),
                run_id="",
                excluded_from_scorer=True,
            )

        variant_id = f"{raw.chromosome}:{norm_start}:{norm_ref}:{norm_alt}"
        variant_class = classify_variant(ref, alt)

        # hgvs_g: only emitted for the unambiguous SNV case, which matches the
        # independently-derived AC3 oracle exactly (raw 1-based VCF position).
        # Indel/MNV genomic HGVS uses the 3'-anchored nomenclature convention
        # (distinct from this left-anchored VCF/SPDI representation) and is
        # NOT independently verifiable in this increment (no oracle covers
        # it, sec 10.5: "excluded, not guessed") -- left `None` rather than
        # fabricated, matching the AC3 fixture's own oracle-derivation policy.
        hgvs_g = f"{raw.chromosome}:g.{position}{ref}>{alt}" if variant_class == VariantClass.SNV else None

        return NormalizedVariant(
            variant_id=variant_id,
            hgvs_g=hgvs_g,
            hgvs_c=None,
            hgvs_p=None,
            hgvs_c_null_reason="awaiting_uta_projection",
            hgvs_p_null_reason="awaiting_uta_projection",
            variant_class=variant_class,
            gene=raw.gene,
            variation_id=raw.variation_id,
            snapshot_id=raw.snapshot_id,
            snapshot_date=raw.snapshot_date,
            source_file_checksum=raw.source_file_checksum,
            row_locator=raw.row_locator,
            raw_source_value=raw.raw_source_value,
        )


def _pins(config: object) -> dict:
    pins_dict = getattr(config, "pins_dict", None)
    if callable(pins_dict):
        try:
            return pins_dict()
        except Exception:
            return {}
    return {}


def _fetch(fasta, accession: str, start: int, end: int) -> str:
    if start >= end:
        return ""
    return fasta.fetch(accession, start, end)


class _LazyFastaSequence:
    """Adapts a `pysam.FastaFile` accession to the `sequence` protocol
    `bioutils.normalize` expects (indexable + `__len__`) without loading the
    whole chromosome into memory -- only the small windows `normalize()`
    actually touches are fetched from the indexed FASTA."""

    __slots__ = ("_fasta", "_name", "_length")

    def __init__(self, fasta, name: str, length: int):
        self._fasta = fasta
        self._name = name
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, key):
        if isinstance(key, slice):
            start = 0 if key.start is None else max(0, key.start)
            stop = self._length if key.stop is None else min(self._length, key.stop)
            return _fetch(self._fasta, self._name, start, stop)
        if key < 0 or key >= self._length:
            raise IndexError(key)
        return _fetch(self._fasta, self._name, key, key + 1)


def _spdi_normalize(fasta, accession: str, chrom_len: int, start0: int, end0: int, alt: str):
    """Fully-justified (SPDI-canonical) normalization via `bioutils.normalize`
    (`mode=EXPAND`): trims the common prefix/suffix then expands the allele
    across any flanking repeat, matching NCBI's contextual-SPDI algorithm.

    `bounds` caps how far `normalize()` may roll/expand; grown geometrically
    only if the result touches the current window edge (i.e. the repeat
    region is larger than assumed), so ordinary variants stay O(1) reference
    reads while pathological cases are still handled correctly.
    """
    from bioutils.normalize import NormalizationMode, normalize

    seq = _LazyFastaSequence(fasta, accession, chrom_len)
    radius = 2000
    max_radius = 1_000_000
    while True:
        bounds = (max(0, start0 - radius), min(chrom_len, end0 + radius))
        (norm_start, norm_end), (_, norm_alt) = normalize(
            seq, (start0, end0), (None, alt), mode=NormalizationMode.EXPAND, bounds=bounds
        )
        hit_left = norm_start <= bounds[0] and bounds[0] > 0
        hit_right = norm_end >= bounds[1] and bounds[1] < chrom_len
        if not (hit_left or hit_right) or radius > max_radius:
            return (norm_start, norm_end), norm_alt
        radius *= 4
