"""Offline coverage for the v3 ClinVar metadata policy lookups."""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.eval._clinvar_2026_08_prospective_red_helpers import REPO_ROOT

METADATA_MODULE = "raptor.eval.prospective_exact_source_metadata_lookups"


def _import_module() -> Any:
    import importlib

    return importlib.import_module(METADATA_MODULE)


def _registered_pins() -> dict[str, Any]:
    spec_path = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v3.yaml"
    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    registration = loaded["dataset_registration"]
    return {
        "registered_url": registration["exact_url"],
        **registration["metadata_source_pins"],
    }


def test_published_archive_date_lookup_returns_pinned_date_and_authority() -> None:
    module = _import_module()
    pins = _registered_pins()
    result = module.published_archive_date_lookup(pins["registered_url"])
    assert result == {
        "published_archive_date": "2026-08-06",
        "source_identity": pins["published_archive_date_authority"],
    }


@pytest.mark.parametrize("lookup_name", ("published_archive_date_lookup", "official_md5_lookup"))
def test_metadata_lookups_reject_unregistered_url(lookup_name: str) -> None:
    module = _import_module()
    pins = _registered_pins()
    lookup = getattr(module, lookup_name)
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        lookup(pins["registered_url"] + ".evil")
    assert exc_info.value.reason_code == module.URL_POLICY_REASON


def test_official_md5_lookup_records_pinned_upstream_checksum_absence_without_network_hooks() -> None:
    module = _import_module()
    pins = _registered_pins()
    assert tuple(inspect.signature(module.official_md5_lookup).parameters) == ("url",)

    result = module.official_md5_lookup(pins["registered_url"])
    assert result == {
        "official_md5": None,
        "upstream_checksum_available": False,
        "source_identity": pins["upstream_checksum_evidence_url"],
        "unavailable_reason": pins["upstream_checksum_unavailable_reason"],
        "verification_mode": module.CONTENT_VERIFICATION_MODE,
    }


@pytest.mark.parametrize(
    ("field", "value", "reason_fragment"),
    (
        ("upstream_checksum_available", True, "upstream_checksum_available"),
        ("upstream_checksum_evidence_url", "https://example.test/archive/", "evidence_url"),
        ("upstream_checksum_unavailable_reason", "", "unavailable_reason"),
        ("content_verification_mode", "UNSAFE", "content_verification_mode"),
    ),
)
def test_checksum_policy_configuration_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: Any,
    reason_fragment: str,
) -> None:
    module = _import_module()
    source = yaml.safe_load(
        (
            REPO_ROOT
            / "docs"
            / "project"
            / "specs"
            / "clinvar-2026-08-prospective-amendment-v3.yaml"
        ).read_text(encoding="utf-8")
    )
    source["dataset_registration"]["metadata_source_pins"][field] = value
    invalid_spec = tmp_path / "invalid.yaml"
    invalid_spec.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(module, "_REGISTRATION_SPEC_PATH", invalid_spec)

    with pytest.raises(module.MetadataLookupConfigurationError) as exc_info:
        module.official_md5_lookup(source["dataset_registration"]["exact_url"])
    assert reason_fragment in str(exc_info.value)
