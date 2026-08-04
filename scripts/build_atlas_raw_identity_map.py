#!/usr/bin/env python
"""Out-of-process acquisition adapter for the Atlas raw-identity replay mapper.

Fetches immutable official NCBI ClinVar E-utilities responses for every raw
discovered identity in a raw inventory, classifies each row using EXACTLY
the same shared, condition-agnostic derivation logic as
``raptor.atlas.identity_map`` (so the acquisition adapter and the runtime
loader can never independently drift on what "resolved" means), stages a
candidate-bearing external raw-identity map plus its candidate-free tracked
lock, and publishes both only after every row has been acquired and
independently verified.

This is the ONLY module in this implementation permitted to perform network
access (Decision Ledger IM-D4: "Core and selector remain offline; only the
acquisition adapter fetches."). Nothing under ``src/raptor/atlas`` imports
this module or any network-capable library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import yaml

from raptor.atlas.identity_map import (
    _classify_record,
    _compute_bundle_hash,
    _single_allowed_gene,
    _single_assembly_pin,
    _single_pinned_transcript,
    identity_map_content_hash,
    identity_map_lock_content_hash,
)
from raptor.atlas.model import (
    AtlasIdentityMapPathError,
    AtlasIdentityMapResponseError,
    AtlasIdentityMapSchemaError,
)
from raptor.atlas.pack import load_disease_pack

SEARCH_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
SUMMARY_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
TOOL_NAME = "raptor-atlas-identity-map"

_REQUESTS_PER_SECOND_NO_KEY = 3.0
_REQUESTS_PER_SECOND_WITH_KEY = 10.0
_MAX_ATTEMPTS = 3
_TRANSIENT_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})

_MAP_SCHEMA_ID = "atlas.raw_identity_map.v1"
_LOCK_SCHEMA_ID = "atlas.raw_identity_map_lock.v1"
_ACQUISITION_TOOL_RELATIVE_PATH = "acquisition-tool.py"


class _NcbiEUtilsTransport:
    """Default bounded transport: a plain HTTP GET against the NCBI
    E-utilities endpoints. Only constructed when the caller does not inject
    a transport (production default); every test injects its own transport
    fake instead."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout_seconds = timeout_seconds

    def get_json(self, endpoint: str, params: Mapping[str, str]) -> tuple[int, bytes]:
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


class _RateLimiter:
    """Paces outgoing requests to at most ``requests_per_second``, using the
    injected clock/sleep so tests never perform a real wait."""

    def __init__(
        self,
        *,
        requests_per_second: float,
        now_utc: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self._min_interval = 1.0 / requests_per_second
        self._now_utc = now_utc
        self._sleep = sleep
        self._last_call_at: Optional[datetime] = None

    def wait(self) -> None:
        now = self._now_utc()
        if self._last_call_at is not None:
            elapsed = (now - self._last_call_at).total_seconds()
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep(remaining)
        self._last_call_at = self._now_utc()


def _call_transport(
    transport: Any,
    endpoint: str,
    params: Mapping[str, str],
    *,
    sleep: Callable[[float], None],
    rate_limiter: _RateLimiter,
    what: str,
) -> bytes:
    """Call ``transport.get_json`` with bounded retry on transient HTTP
    statuses. Returns the RAW response bytes -- captured before any
    interpretation -- for a successful (HTTP 200, parseable, non-error)
    response. Any transport exception, non-200/non-transient status, or
    malformed/error JSON body is a hard acquisition failure and is NEVER
    represented as a zero-match result."""

    last_error: Optional[BaseException] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        rate_limiter.wait()
        try:
            status, body = transport.get_json(endpoint, dict(params))
        except Exception as exc:  # noqa: BLE001 - any transport exception is a hard failure
            last_error = exc
            if attempt < _MAX_ATTEMPTS:
                sleep(2.0 ** (attempt - 1))
                continue
            raise AtlasIdentityMapResponseError(
                f"{what}: transport raised {exc!r} after {attempt} attempt(s)"
            ) from exc

        if status == 200:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AtlasIdentityMapResponseError(
                    f"{what}: HTTP 200 body is not valid UTF-8 JSON"
                ) from exc
            if not isinstance(payload, dict) or payload.get("error"):
                raise AtlasIdentityMapResponseError(
                    f"{what}: E-utilities response reports an error: {payload!r}"
                )
            return body

        if status in _TRANSIENT_HTTP_STATUSES and attempt < _MAX_ATTEMPTS:
            sleep(2.0 ** (attempt - 1))
            continue

        raise AtlasIdentityMapResponseError(f"{what}: HTTP {status} is not a successful E-utilities response")

    raise AtlasIdentityMapResponseError(f"{what}: exhausted retries ({last_error!r})")


def _acquire_row(
    row: Mapping[str, Any],
    *,
    gene: str,
    transcript: str,
    disease_pack: Any,
    responses_root: Path,
    transport: Any,
    email: str,
    api_key: Optional[str],
    rate_limiter: _RateLimiter,
    sleep: Callable[[float], None],
) -> dict:
    """Acquire, capture, and independently classify one raw inventory row.
    Raises fail-closed on any incomplete/inconsistent official response;
    never falls back to a partial or "best effort" record."""

    raw_record_id = row["raw_record_id"]
    raw_identity_string = row["raw_identity_string"]
    hint = row["source_reported_consequence_hint"]

    search_params = {
        "db": "clinvar",
        "retmode": "json",
        "retmax": "20",
        "term": f"{raw_identity_string}[varname] AND {gene}[gene]",
        "tool": TOOL_NAME,
        "email": email,
    }
    if api_key:
        search_params["api_key"] = api_key

    search_body = _call_transport(
        transport, SEARCH_ENDPOINT, search_params, sleep=sleep, rate_limiter=rate_limiter,
        what=f"esearch for raw_record_id {raw_record_id!r}",
    )
    search_relative = f"search/{raw_record_id}.json"
    search_path = responses_root / search_relative
    search_path.parent.mkdir(parents=True, exist_ok=True)
    search_path.write_bytes(search_body)
    search_payload = json.loads(search_body.decode("utf-8"))

    idlist = search_payload.get("esearchresult", {}).get("idlist")
    if not isinstance(idlist, list):
        raise AtlasIdentityMapResponseError(
            f"esearch response for raw_record_id {raw_record_id!r} has a missing/malformed idlist"
        )

    summary_payloads: dict = {}
    summary_pins: list = []
    for uid in idlist:
        summary_params = {
            "db": "clinvar", "retmode": "json", "id": str(uid), "tool": TOOL_NAME, "email": email,
        }
        if api_key:
            summary_params["api_key"] = api_key

        summary_body = _call_transport(
            transport, SUMMARY_ENDPOINT, summary_params, sleep=sleep, rate_limiter=rate_limiter,
            what=f"esummary for raw_record_id {raw_record_id!r} uid {uid!r}",
        )
        summary_relative = f"summary/{raw_record_id}/{uid}.json"
        summary_path = responses_root / summary_relative
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_bytes(summary_body)
        summary_payload = json.loads(summary_body.decode("utf-8"))

        result = summary_payload.get("result")
        if not isinstance(result, dict) or uid not in result:
            raise AtlasIdentityMapResponseError(
                f"esummary response for raw_record_id {raw_record_id!r} uid {uid!r} is missing "
                "its own uid in 'result'"
            )
        summary_payloads[uid] = result[uid]
        summary_pins.append(
            {
                "uid": uid,
                "relative_path": Path(summary_relative).as_posix(),
                "sha256": hashlib.sha256(summary_body).hexdigest(),
                "byte_length": len(summary_body),
            }
        )

    derived = _classify_record(
        raw_record_id=raw_record_id,
        raw_identity_string=raw_identity_string,
        search_payload=search_payload,
        summary_payloads=summary_payloads,
        disease_pack=disease_pack,
    )

    # hgvs_p has no derivable ground truth in an ESummary response; the
    # transcript-qualified protein descriptor is a deterministic,
    # pack-parameterized (never disease-literal) construction.
    hgvs_p = f"{transcript}:{raw_identity_string}" if derived.identity_state == "resolved" else None

    return {
        "raw_record_id": raw_record_id,
        "raw_identity_string": raw_identity_string,
        "source_reported_consequence_hint": hint,
        "search_term": derived.search_term,
        "search_response_relative_path": Path(search_relative).as_posix(),
        "search_response_sha256": hashlib.sha256(search_body).hexdigest(),
        "search_count": derived.search_count,
        "summary_response_pins": summary_pins,
        "match_state": derived.match_state,
        "normalization_outcome": derived.normalization_outcome,
        "universe_key": derived.universe_key,
        "identity_state": derived.identity_state,
        "spdi_canonical": derived.spdi_canonical,
        "hgvs_c": derived.hgvs_c,
        "hgvs_p": hgvs_p,
        "transcript_pin": derived.transcript_pin,
        "residue_index": derived.residue_index,
        "codon_index": derived.codon_index,
        "consequence_class": derived.consequence_class,
        "scope_decision": derived.scope_decision,
        "exclusion_code": derived.exclusion_code,
    }


def _publish_exclusive(staged_path: Path, final_path: Path) -> None:
    """Create ``final_path`` from ``staged_path`` without ever overwriting
    an existing path. A competing path is preserved byte-for-byte and the
    build fails closed with no publication."""

    if final_path.exists() or final_path.is_symlink():
        raise AtlasIdentityMapPathError(f"refusing to publish over an existing path at {final_path}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        staged_path.rename(final_path)
    except OSError as exc:
        raise AtlasIdentityMapPathError(f"failed to publish {staged_path} to {final_path}: {exc}") from exc


def build_identity_map(
    raw_inventory_path: "str | os.PathLike[str]",
    pack_path: "str | os.PathLike[str]",
    external_output_root: "str | os.PathLike[str]",
    tracked_lock_output: "str | os.PathLike[str]",
    email: str,
    api_key: Optional[str] = None,
    *,
    transport: Optional[Any] = None,
    now_utc: Optional[Callable[[], datetime]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> tuple[Path, Path]:
    """Acquire every raw inventory row's official ClinVar responses,
    independently classify each, and publish a candidate-bearing external
    raw identity map plus a candidate-free tracked lock.

    Never overwrites an existing ``external_output_root`` or
    ``tracked_lock_output``; publishes only after every row has been
    acquired and independently verified; publishes nothing on any failed
    row, network error, or exhausted retry. ``transport``/``now_utc``/
    ``sleep`` are injectable seams -- production defaults are the bounded
    NCBI E-utilities transport, :func:`datetime.now` and :func:`time.sleep`.
    """

    raw_inventory_path = Path(raw_inventory_path)
    external_output_root = Path(external_output_root)
    tracked_lock_output = Path(tracked_lock_output)
    now_utc = now_utc or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    transport = transport or _NcbiEUtilsTransport()

    if not isinstance(email, str) or not email.strip():
        raise AtlasIdentityMapSchemaError("build_identity_map requires a nonblank operator email")

    # Collision pre-checks happen before any read/network/staging side
    # effect: a competing path must be preserved byte-for-byte.
    if external_output_root.exists() or external_output_root.is_symlink():
        raise AtlasIdentityMapPathError(
            f"refusing to acquire: external_output_root already exists at {external_output_root}"
        )
    if tracked_lock_output.exists() or tracked_lock_output.is_symlink():
        raise AtlasIdentityMapPathError(
            f"refusing to acquire: tracked_lock_output already exists at {tracked_lock_output}"
        )

    if not raw_inventory_path.is_file():
        raise AtlasIdentityMapPathError(f"raw inventory not found at {raw_inventory_path}")
    raw_bytes = raw_inventory_path.read_bytes()
    try:
        raw_manifest = yaml.safe_load(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise AtlasIdentityMapSchemaError(f"raw inventory at {raw_inventory_path} is not valid YAML") from exc
    if not isinstance(raw_manifest, dict) or not isinstance(raw_manifest.get("rows"), list):
        raise AtlasIdentityMapSchemaError(
            f"raw inventory at {raw_inventory_path} did not parse to a valid inventory mapping"
        )
    raw_inventory_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # A bare/unknown pack id (e.g. a synthetic test id) fails here via the
    # existing, reused ``load_disease_pack`` convention -- before any
    # transport call or staging side effect.
    disease_pack = load_disease_pack(str(pack_path))

    gene = _single_allowed_gene(disease_pack)
    transcript = _single_pinned_transcript(disease_pack)
    _single_assembly_pin(disease_pack)  # validated for its "exactly one" invariant

    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{external_output_root.name}.staging-",
            dir=str(_ensure_parent(external_output_root)),
        )
    )
    try:
        responses_root = staging_root / "official_responses"
        responses_root.mkdir(parents=True)

        rate_limiter = _RateLimiter(
            requests_per_second=(_REQUESTS_PER_SECOND_WITH_KEY if api_key else _REQUESTS_PER_SECOND_NO_KEY),
            now_utc=now_utc,
            sleep=sleep,
        )

        records = [
            _acquire_row(
                row, gene=gene, transcript=transcript, disease_pack=disease_pack,
                responses_root=responses_root, transport=transport, email=email, api_key=api_key,
                rate_limiter=rate_limiter, sleep=sleep,
            )
            for row in raw_manifest["rows"]
        ]

        tool_bytes = Path(__file__).resolve().read_bytes()
        (responses_root / _ACQUISITION_TOOL_RELATIVE_PATH).write_bytes(tool_bytes)
        tool_sha256 = hashlib.sha256(tool_bytes).hexdigest()

        bundle_sha256, file_count, byte_count = _compute_bundle_hash(responses_root)
        created_at = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")

        pack_binding = {
            "pack_id": disease_pack.pack_id,
            "pack_version": disease_pack.pack_version,
            "pack_content_hash": disease_pack.pack_content_hash,
        }
        reference_binding = {
            "provider": "NCBI",
            "database": "clinvar",
            "transcript": transcript,
            "assembly": _single_assembly_pin(disease_pack),
        }

        manifest = {
            "schema": _MAP_SCHEMA_ID,
            "map_id": f"atlas-raw-identity-map-{disease_pack.pack_id}",
            "map_version": "1",
            "map_content_hash": "0" * 64,
            "created_at": created_at,
            "pack_binding": pack_binding,
            "reference_binding": reference_binding,
            "raw_inventory_binding": {
                "path": raw_inventory_path.name,
                "sha256": raw_inventory_sha256,
                "record_count": len(raw_manifest["rows"]),
            },
            "response_bundle": {
                "sha256": bundle_sha256,
                "file_count": file_count,
                "byte_count": byte_count,
            },
            "acquisition_tool": {
                "relative_path": _ACQUISITION_TOOL_RELATIVE_PATH,
                "sha256": tool_sha256,
            },
            "records": records,
        }
        manifest["map_content_hash"] = identity_map_content_hash(manifest)

        lock = {
            "schema": _LOCK_SCHEMA_ID,
            "lock_id": f"atlas-raw-identity-map-lock-{disease_pack.pack_id}",
            "lock_version": "1",
            "created_at": created_at,
            "map_id": manifest["map_id"],
            "map_version": manifest["map_version"],
            "map_content_hash": manifest["map_content_hash"],
            "map_record_count": len(records),
            "raw_inventory_content_hash": raw_inventory_sha256,
            "raw_inventory_record_count": len(raw_manifest["rows"]),
            "response_bundle_hash": bundle_sha256,
            "response_file_count": file_count,
            "response_byte_count": byte_count,
            "pack_binding": pack_binding,
            "reference_binding": reference_binding,
            "acquisition_tool_sha256": tool_sha256,
            "lock_content_hash": "0" * 64,
        }
        lock["lock_content_hash"] = identity_map_lock_content_hash(lock)

        (staging_root / "raw_identity_map.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

        lock_parent = _ensure_parent(tracked_lock_output)
        staged_lock_fd, staged_lock_name = tempfile.mkstemp(
            prefix=f".{tracked_lock_output.name}.staging-", dir=str(lock_parent)
        )
        os.close(staged_lock_fd)
        staged_lock_path = Path(staged_lock_name)
        staged_lock_path.write_text(yaml.safe_dump(lock, sort_keys=False), encoding="utf-8")

        # Publish only after every row has been acquired and independently
        # verified: the external bundle+map directory first, then the
        # candidate-free tracked lock -- never the reverse.
        _publish_exclusive(staging_root, external_output_root)
        try:
            _publish_exclusive(staged_lock_path, tracked_lock_output)
        except BaseException:
            if staged_lock_path.exists():
                staged_lock_path.unlink()
            raise
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise

    return external_output_root / "raw_identity_map.yaml", tracked_lock_output


def _ensure_parent(path: Path) -> Path:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-inventory", required=True, help="path to the raw discovery inventory YAML")
    parser.add_argument("--pack", required=True, help="disease pack id or explicit pack.yaml path")
    parser.add_argument(
        "--external-output-root", required=True,
        help="explicit external content root for the response bundle + candidate-bearing map",
    )
    parser.add_argument(
        "--tracked-lock-output", required=True,
        help="tracked, candidate-free lock output path (e.g. under configs/atlas/panels/<pack>/)",
    )
    parser.add_argument("--email", required=True, help="operator email for the NCBI E-utilities tool/email params")
    parser.add_argument("--api-key", default=None, help="optional NCBI API key (raises the rate limit)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    map_path, lock_path = build_identity_map(
        args.raw_inventory,
        args.pack,
        args.external_output_root,
        args.tracked_lock_output,
        args.email,
        args.api_key,
    )
    print(f"Published raw identity map: {map_path}")
    print(f"Published tracked lock: {lock_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
