#!/usr/bin/env python
"""Fetch and verify the pinned MaveDB TSC2 cliPE scoreset
(`urn:mavedb:00001201-a-1`) to its external, never-committed data path.

Mirrors `scripts/fetch_reference.py`'s pattern: atomic download-to-temp +
rename, sha256 verified against the pin in
`configs/external/mave_sources.yaml` BEFORE the file is ever promoted to its
final path, and a local-seam `--fetcher`/injectable download function so
tests never touch a real network. `--verify-only` never downloads; it only
re-checks an already-fetched file against the pin.

Raw MaveDB scores never live inside the repository -- the default
`--output` is under `RAPTOR_MAVE_EXTERNAL_ROOT`
(default `~/raptor-data/external/mavedb`), the same external-data root used
by the rest of the TSC2 MAVE track
(`D:\\AIProjects\\raptor-data\\external\\mavedb\\...` in this workstation's
layout).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

from raptor.external.mave.register import (
    ConfirmationPendingError,
    SourceRegisterEntry,
    SourceVerificationError,
    verify_registered_source,
)

EXTERNAL_ROOT_ENV = "RAPTOR_MAVE_EXTERNAL_ROOT"
DEFAULT_EXTERNAL_ROOT = Path.home() / "raptor-data" / "external" / "mavedb"
DEFAULT_CONFIG = Path("configs") / "external" / "mave_sources.yaml"
CHUNK_SIZE = 1024 * 1024


class MaveFetchError(RuntimeError):
    """Base error for MAVE scoreset fetch/verify failures."""


def resolve_external_root() -> Path:
    return Path(os.environ.get(EXTERNAL_ROOT_ENV) or DEFAULT_EXTERNAL_ROOT).expanduser()


def load_source_entry(config_path: Path, urn: str) -> tuple[SourceRegisterEntry, dict]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for raw in payload.get("sources", []):
        if raw.get("urn") == urn:
            entry = SourceRegisterEntry(
                urn=raw["urn"],
                gene=raw["gene"],
                transcript=raw["transcript"],
                license=raw["license"],
                sha256=raw.get("sha256") or "",
                variant_count=int(raw.get("variant_count", 0)),
                verification=raw.get("verification", "verified"),
            )
            return entry, raw
    raise MaveFetchError(f"no source register entry for {urn!r} in {config_path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_data_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def _default_fetcher(url: str, target: Path) -> None:
    with urllib.request.urlopen(url) as response, target.open("wb") as handle:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)


def fetch_and_verify(
    *,
    config_path: Path,
    urn: str,
    output_root: Path,
    verify_only: bool,
    downloader: Callable[[str, Path], None] = _default_fetcher,
) -> Path:
    entry, raw = load_source_entry(config_path, urn)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", urn).strip("-")
    gene = raw["gene"]
    target_dir = output_root / f"{gene}-clipe-{slug.split('mavedb-', 1)[-1]}"
    target = target_dir / "scores.csv"

    if not target.is_file():
        if verify_only:
            raise MaveFetchError(f"missing scoreset CSV at {target} (--verify-only set)")
        url = raw.get("api", {}).get("scores_csv")
        if not url:
            raise MaveFetchError(f"no scores_csv API URL registered for {urn!r}")
        target_dir.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.download")
        if temp_path.exists():
            temp_path.unlink()
        try:
            downloader(url, temp_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise
        os.replace(temp_path, target)

    observed_sha256 = sha256_file(target)
    observed_variant_count = count_data_rows(target)

    try:
        verify_registered_source(
            entry,
            observed_transcript=entry.transcript,
            observed_license=entry.license,
            observed_sha256=observed_sha256,
            observed_variant_count=observed_variant_count,
        )
    except ConfirmationPendingError:
        raise
    except SourceVerificationError as exc:
        raise MaveFetchError(
            f"fetched/on-disk scoreset at {target} failed source-register verification: {exc}"
        ) from exc

    return target


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urn", default="urn:mavedb:00001201-a-1")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="do not download; only verify an already-fetched scoreset against the pin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    output_root = args.output_root or resolve_external_root()
    try:
        target = fetch_and_verify(
            config_path=args.config,
            urn=args.urn,
            output_root=output_root,
            verify_only=args.verify_only,
        )
    except MaveFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"verified: {target} (sha256={sha256_file(target)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
