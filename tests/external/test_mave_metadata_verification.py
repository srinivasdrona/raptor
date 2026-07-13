"""Regression coverage for the checker finding: license/transcript
"verification" must never be a self-comparison tautology
(`entry.transcript == entry.transcript`). These tests assert that the
observed transcript/license fed to `verify_registered_source` come from an
independently parsed MaveDB score-set *metadata* document
(`raptor.external.mave.metadata`), not from re-reading the same
`SourceRegisterEntry` under test."""
from __future__ import annotations

import json
import socket
from importlib import import_module
from pathlib import Path

import pytest


def _metadata_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.metadata")
    except ImportError as exc:
        pytest.fail(f"external MAVE metadata module is not implemented: {exc}")
    return {
        "ScoreSetMetadataError": module.ScoreSetMetadataError,
        "parse_score_set_metadata": module.parse_score_set_metadata,
        "extract_observed_transcript": module.extract_observed_transcript,
        "extract_observed_license": module.extract_observed_license,
        "observe_transcript_and_license": module.observe_transcript_and_license,
    }


def _register_api() -> dict[str, object]:
    module = import_module("raptor.external.mave.register")
    return {
        "SourceRegisterEntry": module.SourceRegisterEntry,
        "SourceVerificationError": module.SourceVerificationError,
        "verify_registered_source": module.verify_registered_source,
    }


_REAL_METADATA_RESPONSE = {
    "methodText": (
        "Variant allele frequencies were calculated ... Variants based on "
        "Refseq transcript NM_000548.5."
    ),
    "license": {"shortName": "CC0", "version": "1.0"},
    "numVariants": 208,
    "urn": "urn:mavedb:00001201-a-1",
}


def test_extract_observed_transcript_and_license_from_real_metadata_shape() -> None:
    """Fields modeled on the actual, live MaveDB API response for
    urn:mavedb:00001201-a-1 (fetched 2026-07-13): `methodText` names the
    transcript in free text, `license` is a structured {shortName, version}
    object -- neither is read off a SourceRegisterEntry."""
    api = _metadata_api()
    transcript, license_ = api["observe_transcript_and_license"](_REAL_METADATA_RESPONSE)
    assert transcript == "NM_000548.5"
    assert license_ == "CC0-1.0"


def test_extract_observed_transcript_rejects_missing_or_ambiguous_methodtext() -> None:
    api = _metadata_api()
    with pytest.raises(api["ScoreSetMetadataError"], match="transcript"):
        api["extract_observed_transcript"]({"methodText": "no accession mentioned here"})

    with pytest.raises(api["ScoreSetMetadataError"], match="more than one"):
        api["extract_observed_transcript"](
            {"methodText": "compares NM_000548.4 against NM_000548.5"}
        )


def test_extract_observed_license_rejects_missing_license_object() -> None:
    api = _metadata_api()
    with pytest.raises(api["ScoreSetMetadataError"], match="license"):
        api["extract_observed_license"]({"methodText": "NM_000548.5"})

    with pytest.raises(api["ScoreSetMetadataError"], match="shortName|version"):
        api["extract_observed_license"]({"license": {"shortName": "CC0"}})


def test_parse_score_set_metadata_fails_loud_on_malformed_json() -> None:
    api = _metadata_api()
    with pytest.raises(api["ScoreSetMetadataError"]):
        api["parse_score_set_metadata"]("not json")
    with pytest.raises(api["ScoreSetMetadataError"]):
        api["parse_score_set_metadata"]("[1, 2, 3]")


def test_verification_is_a_real_check_not_a_tautology_against_wrong_entry_fields() -> None:
    """The regression this test guards against: a call site that passes
    `observed_transcript=entry.transcript, observed_license=entry.license`
    can never fail regardless of what was actually fetched. Here `entry`
    deliberately carries WRONG transcript/license values while the
    independently-observed metadata carries the correct ones -- if the call
    site were still comparing `entry` to itself, this would spuriously pass
    (self-consistent) even though the entry itself is wrong. Feeding the
    genuinely independent, correct observation to a WRONG entry must fail
    loud, proving the check is real."""
    api = _register_api()
    metadata_api = _metadata_api()

    wrong_entry = api["SourceRegisterEntry"](
        urn="urn:mavedb:00001201-a-1",
        gene="TSC2",
        transcript="NM_999999.1",  # deliberately wrong
        license="MIT",  # deliberately wrong
        sha256="a" * 64,
        variant_count=208,
        verification="verified",
    )

    observed_transcript, observed_license = metadata_api["observe_transcript_and_license"](
        _REAL_METADATA_RESPONSE
    )

    # A tautological self-comparison (`entry.transcript == entry.transcript`)
    # would never raise here no matter what `wrong_entry` contains. The real,
    # independently-observed values must disagree with `wrong_entry` and
    # raise loud.
    with pytest.raises(api["SourceVerificationError"], match="transcript"):
        api["verify_registered_source"](
            wrong_entry,
            observed_transcript=observed_transcript,
            observed_license=observed_license,
            observed_sha256="a" * 64,
            observed_variant_count=208,
        )

    correct_entry = api["SourceRegisterEntry"](
        urn="urn:mavedb:00001201-a-1",
        gene="TSC2",
        transcript="NM_000548.5",
        license="CC0-1.0",
        sha256="a" * 64,
        variant_count=208,
        verification="verified",
    )
    api["verify_registered_source"](
        correct_entry,
        observed_transcript=observed_transcript,
        observed_license=observed_license,
        observed_sha256="a" * 64,
        observed_variant_count=208,
    )


def test_fetch_and_verify_uses_independently_fetched_metadata_not_entry_self_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end regression at the `scripts/fetch_mave_scoreset.py` call
    site: the injected metadata fetcher returns a document that disagrees
    with the register entry's pinned transcript/license; `fetch_and_verify`
    must raise (never silently pass by comparing `entry` to itself)."""
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    fetch_module = import_module("fetch_mave_scoreset")

    def _no_network(*args, **kwargs):
        raise AssertionError("real network is forbidden in unit tests")

    monkeypatch.setattr(socket, "create_connection", _no_network)

    config_path = tmp_path / "mave_sources.yaml"
    config_path.write_text(
        """
sources:
  - urn: "urn:mavedb:test-1"
    gene: TSC2
    transcript: NM_000548.5
    license: CC0-1.0
    variant_count: 1
    verification: verified
    sha256: "%s"
    api:
      score_set: "https://example.invalid/score-sets/test-1"
      scores_csv: "https://example.invalid/score-sets/test-1/scores"
"""
        % ("0" * 64),
        encoding="utf-8",
    )

    scores_payload = "accession,hgvs_nt,hgvs_splice,hgvs_pro,score\nacc1,c.1A>G,,p.M1V,0.5\n"

    import hashlib

    real_sha256 = hashlib.sha256(scores_payload.encode("utf-8")).hexdigest()
    config_path.write_text(config_path.read_text(encoding="utf-8").replace("0" * 64, real_sha256))

    def fake_downloader(url: str, target: Path) -> None:
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(scores_payload)

    # Metadata disagrees with the pinned entry's transcript -- an
    # independently-observed drift that a tautological self-comparison
    # could never catch.
    wrong_metadata_text = json.dumps(
        {
            "methodText": "Variants based on Refseq transcript NM_000548.4.",
            "license": {"shortName": "CC0", "version": "1.0"},
        }
    )

    def fake_metadata_fetcher(url: str) -> str:
        return wrong_metadata_text

    with pytest.raises(Exception, match="transcript"):
        fetch_module.fetch_and_verify(
            config_path=config_path,
            urn="urn:mavedb:test-1",
            output_root=tmp_path / "external",
            verify_only=False,
            downloader=fake_downloader,
            metadata_fetcher=fake_metadata_fetcher,
        )

    # Now with metadata that genuinely agrees with the pinned entry -- this
    # must succeed, proving the check is a real, passable comparison and not
    # merely inverted to always fail.
    correct_metadata_text = json.dumps(
        {
            "methodText": "Variants based on Refseq transcript NM_000548.5.",
            "license": {"shortName": "CC0", "version": "1.0"},
        }
    )

    def fake_metadata_fetcher_correct(url: str) -> str:
        return correct_metadata_text

    output_root = tmp_path / "external2"
    target = fetch_module.fetch_and_verify(
        config_path=config_path,
        urn="urn:mavedb:test-1",
        output_root=output_root,
        verify_only=False,
        downloader=fake_downloader,
        metadata_fetcher=fake_metadata_fetcher_correct,
    )
    assert target.is_file()
