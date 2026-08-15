import copy

import pytest
import yaml

from solution import BundleValidationError, validate_release_bundle


def load(name):
    with open(f"artifacts/{name}.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_valid_bundle_reports_record_count():
    result = validate_release_bundle(
        load("registration"), load("universe"), load("map_lock"), load("map_manifest")
    )
    assert result["schema"] == "validation-result-v1"
    assert result["record_count"] == 2


def test_bad_registration_schema_fails_closed():
    registration = copy.deepcopy(load("registration"))
    registration["schema"] = "release-registration-v1"
    with pytest.raises(BundleValidationError) as caught:
        validate_release_bundle(
            registration, load("universe"), load("map_lock"), load("map_manifest")
        )
    assert caught.value.code == "REGISTRATION_SCHEMA"
