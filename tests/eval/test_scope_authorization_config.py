from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from raptor.eval.config import ConfigError, load_config


CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "eval" / "tsc2.yaml"
)
GOVERNANCE_STATEMENT = (
    "Full-spectrum VUS automation is not authorized. Evidence supports only the "
    "validated truncating-pathogenic scope; missense remains unvalidated."
)
RESEARCH_USE_DISCLAIMER = (
    "Research-evidence validation only; this authorizes no clinical classification, "
    "VUS worklist, or ClinVar submission."
)


def _authorization() -> dict:
    return {
        "schema_version": 2,
        "full_spectrum": {
            "requires": [
                "missense:pathogenic",
                "missense:benign",
                "truncating:pathogenic",
            ],
        },
        "research_scopes": {
            "truncating_pathogenic_research_scope_validated": {
                "requires": ["truncating:pathogenic"],
            },
        },
        "governance_statements": {
            "FULL_SPECTRUM": "Full spectrum research scopes validated.",
            "TRUNCATING_PATHOGENIC_ONLY": GOVERNANCE_STATEMENT,
            "NONE_VALIDATED": "No research scope is validated.",
        },
        "research_use_disclaimer": RESEARCH_USE_DISCLAIMER,
    }


def _raw_config() -> dict:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _write_config(tmp_path: Path, raw: dict, name: str = "eval.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_scope_authorization_block_is_optional_for_v1_configs(tmp_path: Path) -> None:
    raw = _raw_config()
    raw.pop("scope_authorization", None)

    config = load_config(_write_config(tmp_path, raw))
    assert config.scope_authorization is None


def test_real_tsc2_config_exposes_valid_scope_authorization() -> None:
    config = load_config(CONFIG_PATH)
    authorization = config.scope_authorization

    assert authorization["schema_version"] in {2, "2"}
    assert set(authorization["full_spectrum"]["requires"]) == {
        "missense:pathogenic",
        "missense:benign",
        "truncating:pathogenic",
    }
    assert authorization["research_scopes"][
        "truncating_pathogenic_research_scope_validated"
    ]["requires"] == ["truncating:pathogenic"]
    assert (
        authorization["governance_statements"]["TRUNCATING_PATHOGENIC_ONLY"]
        == GOVERNANCE_STATEMENT
    )
    assert authorization["research_use_disclaimer"] == RESEARCH_USE_DISCLAIMER


@pytest.mark.parametrize(
    "scope",
    ["missense:orange", "ghost:pathogenic"],
)
def test_unknown_scope_or_direction_is_rejected(
    tmp_path: Path, scope: str
) -> None:
    raw = _raw_config()
    raw["scope_authorization"] = _authorization()
    raw["scope_authorization"]["research_scopes"]["invalid_scope"] = {
        "requires": [scope],
    }

    with pytest.raises(ConfigError, match=r"(?i)scope|direction|stratum|registered"):
        load_config(_write_config(tmp_path, raw, f"{scope.replace(':', '-')}.yaml"))


def test_full_spectrum_requirement_cannot_be_narrowed(tmp_path: Path) -> None:
    raw = _raw_config()
    raw["scope_authorization"] = _authorization()
    raw["scope_authorization"]["full_spectrum"]["requires"].remove(
        "missense:benign"
    )

    with pytest.raises(ConfigError, match=r"(?i)pinned|full.spectrum|requires|lock"):
        load_config(_write_config(tmp_path, raw))


@pytest.mark.parametrize(
    "state",
    ["FULL_SPECTRUM", "TRUNCATING_PATHOGENIC_ONLY", "NONE_VALIDATED"],
)
@pytest.mark.parametrize("replacement", [None, "   "])
def test_all_governance_statements_are_required_and_nonblank(
    tmp_path: Path, state: str, replacement: str | None
) -> None:
    raw = _raw_config()
    raw["scope_authorization"] = _authorization()
    if replacement is None:
        del raw["scope_authorization"]["governance_statements"][state]
    else:
        raw["scope_authorization"]["governance_statements"][state] = replacement

    with pytest.raises(ConfigError, match=r"(?i)governance|statement|blank|required"):
        load_config(_write_config(tmp_path, raw))


@pytest.mark.parametrize("version", [1, "3", None])
def test_scope_authorization_schema_version_must_be_v2(
    tmp_path: Path, version
) -> None:
    raw = _raw_config()
    raw["scope_authorization"] = _authorization()
    raw["scope_authorization"]["schema_version"] = version

    with pytest.raises(ConfigError, match=r"(?i)schema|version|2"):
        load_config(_write_config(tmp_path, raw))


@pytest.mark.parametrize("replacement", [None, "", "   "])
def test_research_use_disclaimer_is_required_and_nonblank(
    tmp_path: Path, replacement: str | None
) -> None:
    raw = _raw_config()
    raw["scope_authorization"] = deepcopy(_authorization())
    if replacement is None:
        del raw["scope_authorization"]["research_use_disclaimer"]
    else:
        raw["scope_authorization"]["research_use_disclaimer"] = replacement

    with pytest.raises(ConfigError, match=r"(?i)research.use.disclaimer|disclaimer|blank|required"):
        load_config(_write_config(tmp_path, raw))
