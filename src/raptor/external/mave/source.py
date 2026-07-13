"""MAVE score record contract + loader.

`MaveScoreRecord` is the only shape RAPTOR consumes from a MAVE source (a
clean data boundary, mirroring `raptor.scorer.bias_source.BiasTsvSource`'s
arm's-length TSV boundary for BIAS). `load_score_records` enforces the
column contract fail-closed (a `variant`/`hgvs` identity column and a
numeric `score` column are both required) before parsing any row, and
supports either a local fixture path or an injected `fetcher` callable so
unit tests never touch a real network.

`parse_mavedb_scoreset_csv` is the separate, MaveDB-specific raw CSV parser
(the actual MaveDB "scores" export: `accession,hgvs_nt,hgvs_splice,hgvs_pro,
score`) used by the fetch/report scripts -- it has no `variant_id`/
`reference` columns; those are resolved later via `identity.py`'s exact
hgvsc match against a canonical source, never guessed here.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple, Sequence

_IDENTITY_COLUMNS = ("variant_id", "hgvs_c", "hgvs_nt")
_REQUIRED_SCORE_COLUMN = "score"


class ScoreContractError(ValueError):
    """Raised when a MAVE score source does not honor the required column
    contract (a variant/hgvs identity column + a numeric `score` column)."""


@dataclass(frozen=True)
class MaveScoreRecord:
    """One MAVE functional-score row, resolved (or not yet resolved) to a
    canonical SPDI `variant_id`. `hgvs_c`/`reference` are carried alongside
    for exact-match identity joins (`identity.py`) -- never used to *guess*
    a genomic position on their own."""

    variant_id: str | None
    hgvs_c: str | None
    score: float
    reference: str | None = None


class MaveRawScoreRow(NamedTuple):
    """One row of the raw MaveDB scoreset CSV, before any identity join."""

    accession: str
    hgvs_c: str
    hgvs_pro: str
    score: float


def _looks_like_url(path_or_url: str | Path) -> bool:
    return isinstance(path_or_url, str) and (
        path_or_url.startswith("http://") or path_or_url.startswith("https://")
    )


def _sniff_delimiter(header_line: str) -> str:
    return "\t" if "\t" in header_line else ","


def _read_text(path_or_url: str | Path, fetcher: Callable[[str], str] | None) -> str:
    if _looks_like_url(path_or_url):
        if fetcher is None:
            raise ScoreContractError(
                f"{path_or_url!r} is a URL but no fetcher was injected -- "
                "real network access is never performed implicitly"
            )
        return fetcher(str(path_or_url))
    return Path(path_or_url).read_text(encoding="utf-8")


def _assert_contract(header: Sequence[str], *, source: str) -> None:
    if not any(column in header for column in _IDENTITY_COLUMNS):
        raise ScoreContractError(
            f"{source}: missing a variant/hgvs identity column "
            f"(expected one of {_IDENTITY_COLUMNS!r}); got {list(header)!r}"
        )
    if _REQUIRED_SCORE_COLUMN not in header:
        raise ScoreContractError(
            f"{source}: missing the required numeric 'score' column; got {list(header)!r}"
        )


def load_score_records(
    path_or_url: str | Path,
    entry: object,
    *,
    fetcher: Callable[[str], str] | None = None,
) -> list[MaveScoreRecord]:
    """Load `MaveScoreRecord`s from a local fixture path or (via an injected
    `fetcher`) a remote URL. `entry` is accepted for call-site symmetry with
    the source register (a future revision may cross-check `entry.sha256`
    here); today the contract check is purely structural. Fails loud
    (`ScoreContractError`) before parsing any row if the identity/score
    column contract is not honored."""
    del entry  # reserved for future sha256 cross-check; contract is structural today
    source = str(path_or_url)
    text = _read_text(path_or_url, fetcher)
    reader = csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text.splitlines()[0]))
    rows = list(reader)
    if not rows:
        return []
    header = rows[0]
    _assert_contract(header, source=source)
    idx = {name: i for i, name in enumerate(header)}

    records: list[MaveScoreRecord] = []
    for row in rows[1:]:
        if not row:
            continue
        variant_id = row[idx["variant_id"]] if "variant_id" in idx else None
        hgvs_c = row[idx["hgvs_c"]] if "hgvs_c" in idx else (
            row[idx["hgvs_nt"]] if "hgvs_nt" in idx else None
        )
        reference = row[idx["reference"]] if "reference" in idx else None
        records.append(
            MaveScoreRecord(
                variant_id=variant_id,
                hgvs_c=hgvs_c,
                score=float(row[idx["score"]]),
                reference=reference,
            )
        )
    return records


def parse_mavedb_scoreset_csv(path: str | Path) -> list[MaveRawScoreRow]:
    """Parse the raw MaveDB scoreset export
    (`accession,hgvs_nt,hgvs_splice,hgvs_pro,score`) into `MaveRawScoreRow`s.
    Rows with a missing/blank `score` (e.g. synonymous controls excluded from
    the assay) are dropped -- never coerced to `0.0`."""
    rows: list[MaveRawScoreRow] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"accession", "hgvs_nt", "hgvs_pro", "score"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ScoreContractError(
                f"{path}: raw MaveDB CSV missing required columns {sorted(required)!r}; "
                f"got {reader.fieldnames!r}"
            )
        for raw in reader:
            score_text = (raw["score"] or "").strip()
            if not score_text or score_text.upper() in {"NA", "NAN"}:
                continue
            rows.append(
                MaveRawScoreRow(
                    accession=raw["accession"],
                    hgvs_c=raw["hgvs_nt"],
                    hgvs_pro=raw["hgvs_pro"],
                    score=float(score_text),
                )
            )
    return rows


__all__ = [
    "MaveScoreRecord",
    "MaveRawScoreRow",
    "ScoreContractError",
    "load_score_records",
    "parse_mavedb_scoreset_csv",
]
