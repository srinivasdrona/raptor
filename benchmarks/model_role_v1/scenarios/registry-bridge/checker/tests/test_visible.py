import yaml

from solution import validate_release_bundle


def load(name):
    with open(f"artifacts/{name}.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_happy_path_shape_only():
    result = validate_release_bundle(
        load("registration"), load("universe"), load("map_lock"), load("map_manifest")
    )
    assert result["schema"] == "validation-result-v1"
    assert result["record_count"] == 2
