class BundleValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise BundleValidationError(code)


def validate_release_bundle(registration, universe, map_lock, map_manifest):
    _require(registration.get("schema") == "release-registration-v2", "REGISTRATION_SCHEMA")
    _require(universe.get("schema") == registration.get("universe_schema"), "UNIVERSE_SCHEMA")
    _require(map_manifest.get("schema") == registration.get("map_lock_schema"), "MAP_LOCK_SCHEMA")
    _require(map_manifest.get("schema") == map_lock.get("manifest_schema"), "MAP_MANIFEST_SCHEMA")
    transcript_pins = {record.get("transcript_pin") for record in universe.get("records", [])}
    _require(transcript_pins == {registration.get("transcript_pin")}, "TRANSCRIPT_PIN")
    return {
        "schema": "validation-result-v1",
        "record_count": len(universe.get("records", [])),
        "checks": [
            "REGISTRATION_SCHEMA",
            "UNIVERSE_SCHEMA",
            "MAP_LOCK_SCHEMA",
            "MAP_MANIFEST_SCHEMA",
            "TRANSCRIPT_PIN",
        ],
    }
