#!/usr/bin/env python3
"""Build the R611Q package-v2 addendum: an append-only wrapper over the
immutable literature-v1/synthesis-v1/structure-readiness-v1 RescueScreen
evidence pack, the unreviewed Atlas expert packet/form, and the reviewed
2026-09-16 literature delta bundle.

Real (post-Terra-approval) usage::

    python scripts/build_r611q_package_v2_addendum.py \\
        --repo-root /path/to/raptor \\
        --v1-packet /path/to/raptor-data/atlas/r611q-expert-review-v1/R611Q_EXPERT_REVIEW_PACKET.md \\
        --v1-form /path/to/raptor-data/atlas/r611q-expert-review-v1/R611Q_EXPERT_REVIEW_FORM.yaml \\
        --delta-bundle-root /path/to/raptor-data/external/r611q-literature-delta-review/r611q-literature-delta-review-2026-09-16 \\
        --output-root /path/to/raptor-data/external/r611q-package-v2

Offline self-test usage (no real repository/external files are touched)::

    python scripts/build_r611q_package_v2_addendum.py \\
        --config configs/rescuescreen/r611q_package_v2_addendum.yaml \\
        --output-root /tmp/external-out \\
        --repository-summary-dir /tmp/repo-summary-out \\
        --offline
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, MutableMapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.rescuescreen.package_v2 import (  # noqa: E402
    PackageV2Error,
    _mkdir_tracked,
    _reject_symlink_ancestry,
    _require_outside_repo,
    build_r611q_package_v2_addendum,
    build_repository_summary,
    render_external_package,
)

DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "rescuescreen" / "r611q_package_v2_addendum.yaml"


# ---------------------------------------------------------------------------
# Config loading and defaulting
# ---------------------------------------------------------------------------


def _load_config(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackageV2Error(f"cannot read config: {path}: {exc}") from exc
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PackageV2Error(f"config is not valid YAML: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PackageV2Error(f"config must parse to a mapping: {path}")
    return parsed


def _deep_merge_defaults(config: MutableMapping[str, Any], defaults: MutableMapping[str, Any]) -> None:
    """Fill in any key missing from ``config`` from ``defaults``, recursively.

    Never overrides a key the caller's config already provides.
    """

    for key, default_value in defaults.items():
        if key not in config:
            config[key] = copy.deepcopy(default_value)
        elif isinstance(config[key], MutableMapping) and isinstance(default_value, MutableMapping):
            _deep_merge_defaults(config[key], default_value)


def _default_repo_root() -> Path:
    return REPO_ROOT


def _resolve_output_root(config: dict[str, Any]) -> Path:
    output_config = config.get("output", {})
    env_var = output_config.get("environment_variable")
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var]).expanduser()
    default_root = output_config.get("default_root", "~/raptor-data/external/r611q-package-v2")
    return Path(default_root).expanduser()


def _require_or_raise(condition: bool, message: str) -> None:
    if not condition:
        raise PackageV2Error(message)


# ---------------------------------------------------------------------------
# Offline synthetic fixture (never touches real repository/external files)
# ---------------------------------------------------------------------------


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class _OfflineFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo_root = root / "repo"
        self.packet_path = root / "atlas" / "R611Q_EXPERT_REVIEW_PACKET.md"
        self.form_path = root / "atlas" / "R611Q_EXPERT_REVIEW_FORM.yaml"
        self.delta_bundle_root = root / "delta"
        self.config_defaults: dict[str, Any] = {}

    def build(self) -> None:
        self._build_v1_repository_package()
        self._build_atlas_expert_inputs()
        self._build_delta_bundle()

    def merge_into(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(config)
        _deep_merge_defaults(merged, self.config_defaults)
        return merged

    def _write_v1_group(self, group_key: str, directory_name: str) -> dict[str, Any]:
        directory = self.repo_root / "data" / "rescuescreen" / "r611q" / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        file_a = f"{group_key}-alpha.txt".replace("_", "-")
        file_b = f"{group_key}-beta.txt".replace("_", "-")
        (directory / file_a).write_bytes(f"offline synthetic {group_key} alpha\n".encode("utf-8"))
        (directory / file_b).write_bytes(f"offline synthetic {group_key} beta\n".encode("utf-8"))

        entries = sorted(
            (
                (_sha256_bytes((directory / name).read_bytes()), name)
                for name in (file_a, file_b)
            ),
            key=lambda item: item[1],
        )
        manifest_text = "".join(f"{digest}  {name}\n" for digest, name in entries)
        manifest_bytes = manifest_text.encode("utf-8")
        manifest_path = directory / "manifest.sha256"
        manifest_path.write_bytes(manifest_bytes)

        relative_directory = directory.relative_to(self.repo_root).as_posix()
        return {
            "directory": relative_directory,
            "manifest_path": f"{relative_directory}/manifest.sha256",
            "manifest_sha256": _sha256_bytes(manifest_bytes),
            "manifest_byte_length": len(manifest_bytes),
            "files_listed": len(entries),
        }

    def _build_v1_repository_package(self) -> None:
        literature_pin = self._write_v1_group("literature", "literature-v1")
        synthesis_pin = self._write_v1_group("synthesis", "synthesis-v1")
        structure_pin = self._write_v1_group("structure", "structure-readiness-v1")

        readiness_dir = self.repo_root / "data" / "rescuescreen" / "r611q"
        readiness_dir.mkdir(parents=True, exist_ok=True)
        readiness_bytes = (
            "# Offline synthetic RescueScreen evidence readiness summary\n\n"
            "This is a self-contained fixture used only by --offline smoke runs. "
            "It is never written under a real repository path.\n"
        ).encode("utf-8")
        readiness_path = readiness_dir / "RESCUESCREEN_EVIDENCE_READINESS_SUMMARY.md"
        readiness_path.write_bytes(readiness_bytes)

        self.config_defaults["v1_repository_package"] = {
            "literature": literature_pin,
            "synthesis": synthesis_pin,
            "structure_readiness": structure_pin,
            "readiness_summary": {
                "path": "data/rescuescreen/r611q/RESCUESCREEN_EVIDENCE_READINESS_SUMMARY.md",
                "sha256": _sha256_bytes(readiness_bytes),
                "byte_length": len(readiness_bytes),
            },
        }

    def _build_atlas_expert_inputs(self) -> None:
        self.packet_path.parent.mkdir(parents=True, exist_ok=True)
        packet_bytes = (
            "# Offline synthetic Atlas expert-review packet v1\n\n"
            "## Claim A\n\nSynthetic claim A content.\n\n"
            "## Claim B\n\nSynthetic claim B content.\n\n"
            "**Overall packet outcome:** unreviewed.\n"
        ).encode("utf-8")
        self.packet_path.write_bytes(packet_bytes)

        form_mapping = {
            "schema": "atlas.expert_review_form.v1",
            "packet_status": "unreviewed",
            "candidate_run_id": "offline-synthetic-run",
            "variant": {"gene": "TSC2", "hgvs_p": "NP_000539.2:p.Arg611Gln"},
            "bindings": {"packet_content_hash": _sha256_bytes(packet_bytes)},
            "reviewer": {"name": None, "credentials": None, "role": None},
            "claims": [
                {"claim_id": "r611q-claim-0", "source_id": "offline-source-0", "decision": None},
                {"claim_id": "r611q-claim-1", "source_id": "offline-source-1", "decision": None},
            ],
            "scope_statement": "Offline synthetic scope statement.",
        }
        form_bytes = yaml.safe_dump(form_mapping, sort_keys=False, allow_unicode=True).encode("utf-8")
        self.form_path.write_bytes(form_bytes)

        self.config_defaults["atlas_expert_packet_v1"] = {
            "packet": {"sha256": _sha256_bytes(packet_bytes), "byte_length": len(packet_bytes)},
            "form": {"sha256": _sha256_bytes(form_bytes), "byte_length": len(form_bytes)},
            "state": {"proposed_claims": 2, "accepted_claims": 0, "gate_8": "BLOCKED_HUMAN_REVIEW"},
        }
        self._packet_sha256 = _sha256_bytes(packet_bytes)
        self._form_sha256 = _sha256_bytes(form_bytes)

    def _build_delta_bundle(self) -> None:
        normalized_dir = self.delta_bundle_root / "normalized"
        reviewed_dir = self.delta_bundle_root / "reviewed"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        reviewed_dir.mkdir(parents=True, exist_ok=True)

        boundary_quote = (
            "Offline synthetic co-immunoprecipitation sentence reporting a grouped "
            "TSC2-TSC2 self-association result for the R611Q, R905Q and N1620S "
            "substitutions together."
        )
        boundary_quote_hash = _sha256_bytes(boundary_quote.encode("utf-8"))
        secondary_quote = "Offline synthetic unrelated secondary-review sentence."
        secondary_quote_hash = _sha256_bytes(secondary_quote.encode("utf-8"))

        candidate_spans = [
            {
                "candidate_id": "offline-cand-001",
                "article_identity": {"pmid": "00000001"},
                "exact_quote": boundary_quote,
                "exact_quote_sha256": boundary_quote_hash,
                "locator": "text-char:0:120",
            },
            {
                "candidate_id": "offline-cand-002",
                "article_identity": {"pmid": "00000002"},
                "exact_quote": secondary_quote,
                "exact_quote_sha256": secondary_quote_hash,
                "locator": "text-char:0:60",
            },
        ]
        review_records = [
            {
                "candidate_id": "offline-cand-001",
                "source_id": "PMID:00000001",
                "article_identity": {"pmid": "00000001"},
                "source_role": "DIRECT_ALLELE_EXPERIMENT",
                "primary_result_state": "PRIMARY_R611Q_RESULT",
                "baseline_relation": "NARROWS",
                "delta_value": "NEW_PRIMARY_OBSERVATION",
                "proposition_ids": ["P_COMPLEX_BINDING"],
                "acceptance_state": "PROPOSED_UNACCEPTED",
                "gate_8_change": "NONE",
                "human_gate_8_effect": "NONE",
            },
            {
                "candidate_id": "offline-cand-002",
                "source_id": "PMID:00000002",
                "article_identity": {"pmid": "00000002"},
                "source_role": "SECONDARY_REVIEW",
                "primary_result_state": "SECONDARY_SYNTHESIS_ONLY",
                "baseline_relation": "NO_DIRECT_RELATION",
                "delta_value": "SECONDARY_ONLY",
                "proposition_ids": [],
                "acceptance_state": "PROPOSED_UNACCEPTED",
                "gate_8_change": "NONE",
                "human_gate_8_effect": "NONE",
            },
        ]

        candidate_spans_bytes = (
            "\n".join(json.dumps(row, sort_keys=True) for row in candidate_spans) + "\n"
        ).encode("utf-8")
        review_records_bytes = (
            "\n".join(json.dumps(row, sort_keys=True) for row in review_records) + "\n"
        ).encode("utf-8")
        addendum_bytes = (
            "# Offline synthetic literature-delta addendum\n\n"
            "One direct grouped boundary observation; no accepted claims; Gate 8 blocked.\n"
        ).encode("utf-8")

        (normalized_dir / "candidate-spans.jsonl").write_bytes(candidate_spans_bytes)
        (reviewed_dir / "review-records.jsonl").write_bytes(review_records_bytes)
        (reviewed_dir / "R611Q_LITERATURE_DELTA_ADDENDUM.md").write_bytes(addendum_bytes)

        manifest: dict[str, Any] = {
            "schema": "raptor.external.r611q_literature_delta_review_bundle.v1",
            "bundle_id": "offline-synthetic-delta",
            "artifacts": [
                {
                    "relative_path": "normalized/candidate-spans.jsonl",
                    "sha256": _sha256_bytes(candidate_spans_bytes),
                    "byte_length": len(candidate_spans_bytes),
                },
                {
                    "relative_path": "reviewed/review-records.jsonl",
                    "sha256": _sha256_bytes(review_records_bytes),
                    "byte_length": len(review_records_bytes),
                },
                {
                    "relative_path": "reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md",
                    "sha256": _sha256_bytes(addendum_bytes),
                    "byte_length": len(addendum_bytes),
                },
            ],
            "counts": {"article_rows": 2, "exact_alias_candidate_sources": 2, "candidate_span_count": 2, "accepted_claims": 0},
            "source_role_counts": {
                "DIRECT_ALLELE_EXPERIMENT": 1,
                "SECONDARY_REVIEW": 1,
                "ALLELE_BEARING_MODEL_CONTEXT": 0,
                "CLINICAL_CASE_IDENTITY": 0,
            },
            "baseline_relation_counts": {"NARROWS": 1, "NO_DIRECT_RELATION": 1, "CONTRADICTS": 0},
            "input_hashes": {
                "atlas_expert_packet_sha256": self._packet_sha256,
                "atlas_expert_form_sha256": self._form_sha256,
            },
        }
        manifest["content_hash"] = _sha256_bytes(_canonical_json_bytes(
            {k: v for k, v in manifest.items() if k != "content_hash"}
        ))
        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_path = self.delta_bundle_root / "bundle_manifest.json"
        self.delta_bundle_root.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(manifest_bytes)

        self.config_defaults["literature_delta"] = {
            "manifest_relative_path": "bundle_manifest.json",
            "schema": "raptor.external.r611q_literature_delta_review_bundle.v1",
            "manifest_file_sha256": _sha256_bytes(manifest_bytes),
            "manifest_byte_length": len(manifest_bytes),
            "required_artifacts": {
                "candidate_spans": {
                    "relative_path": "normalized/candidate-spans.jsonl",
                    "sha256": _sha256_bytes(candidate_spans_bytes),
                    "byte_length": len(candidate_spans_bytes),
                },
                "review_records": {
                    "relative_path": "reviewed/review-records.jsonl",
                    "sha256": _sha256_bytes(review_records_bytes),
                    "byte_length": len(review_records_bytes),
                },
                "addendum": {
                    "relative_path": "reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md",
                    "sha256": _sha256_bytes(addendum_bytes),
                    "byte_length": len(addendum_bytes),
                },
            },
            "frozen_counts": {
                "article_rows": 2,
                "exact_alias_candidate_sources": 2,
                "candidate_spans": 2,
                "direct_grouped_experiments": 1,
                "patient_621_model_contexts": 0,
                "clinical_occurrences": 0,
                "secondary_reviews": 1,
                "narrowing_relations": 1,
                "contradictions": 0,
                "accepted_claims": 0,
            },
        }

        self.config_defaults.setdefault("output", {})
        self.config_defaults["output"].setdefault(
            "repository_summary",
            {
                "directory": "data/rescuescreen/r611q/package-v2-addendum",
                "json_path": "data/rescuescreen/r611q/package-v2-addendum/package_summary.json",
                "readme_path": "data/rescuescreen/r611q/package-v2-addendum/README.md",
            },
        )
        self.config_defaults["output"].setdefault(
            "environment_variable", "RAPTOR_R611Q_PACKAGE_V2_ROOT"
        )
        self.config_defaults["output"].setdefault(
            "default_root", "~/raptor-data/external/r611q-package-v2"
        )


def _materialize_offline_fixture(fixture_root: Path) -> _OfflineFixture:
    fixture = _OfflineFixture(fixture_root)
    fixture.build()
    return fixture


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="pins/output config YAML")
    parser.add_argument("--repo-root", type=Path, default=None, help="repository root containing data/rescuescreen/r611q/*-v1")
    parser.add_argument("--v1-packet", type=Path, default=None, help="path to the external v1 R611Q_EXPERT_REVIEW_PACKET.md")
    parser.add_argument("--v1-form", type=Path, default=None, help="path to the external v1 R611Q_EXPERT_REVIEW_FORM.yaml")
    parser.add_argument("--delta-bundle-root", type=Path, default=None, help="root of the reviewed literature-delta bundle")
    parser.add_argument("--output-root", type=Path, default=None, help="external package output root (create-only)")
    parser.add_argument(
        "--repository-summary-dir", type=Path, default=None,
        help="repository directory to write package_summary.json/README.md into (create-only)",
    )
    parser.add_argument(
        "--no-write-repository-summary", action="store_true",
        help="compose and render the external package but skip the repository summary",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="verify and compose everything in memory; write nothing",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help=(
            "use built-in synthetic fixtures for any of --repo-root/--v1-packet/--v1-form/"
            "--delta-bundle-root that is not explicitly given; never touches real repository "
            "or external files"
        ),
    )
    args = parser.parse_args(argv)

    offline_fixture_dir: str | None = None
    try:
        config = _load_config(args.config)

        needs_offline_fixture = args.offline and (
            args.repo_root is None
            or args.v1_packet is None
            or args.v1_form is None
            or args.delta_bundle_root is None
        )

        if needs_offline_fixture:
            offline_fixture_dir = tempfile.mkdtemp(prefix="r611q-pv2a-offline-")
            fixture = _materialize_offline_fixture(Path(offline_fixture_dir))
            config = fixture.merge_into(config)
            repo_root = args.repo_root or fixture.repo_root
            v1_packet_path = args.v1_packet or fixture.packet_path
            v1_form_path = args.v1_form or fixture.form_path
            delta_bundle_root = args.delta_bundle_root or fixture.delta_bundle_root
            # Offline convenience mode is internally adapted to always use the
            # synthetic fixture's own configured repository-summary path; a
            # caller-provided --repository-summary-dir that does not match it
            # is not passed through, so the production create-only/
            # exact-target rule below is never relaxed for a real run.
            effective_repository_summary_dir = None
        else:
            repo_root = args.repo_root or _default_repo_root()
            v1_packet_path = args.v1_packet
            v1_form_path = args.v1_form
            delta_bundle_root = args.delta_bundle_root
            effective_repository_summary_dir = args.repository_summary_dir
            missing = [
                flag
                for flag, value in (
                    ("--v1-packet", v1_packet_path),
                    ("--v1-form", v1_form_path),
                    ("--delta-bundle-root", delta_bundle_root),
                )
                if value is None
            ]
            if missing:
                parser.error(
                    "missing required arguments for a non-offline run: " + ", ".join(missing)
                )

        result = build_r611q_package_v2_addendum(
            config=config,
            repo_root=repo_root,
            v1_packet_path=v1_packet_path,
            v1_form_path=v1_form_path,
            delta_bundle_root=delta_bundle_root,
        )

        boundary = result["boundary"]
        print(
            "R611Q package-v2 addendum: boundary selected "
            f"(source_role={boundary['source_role']}, "
            f"primary_result_state={boundary['primary_result_state']}, "
            f"baseline_relation={boundary['baseline_relation']})"
        )

        if args.dry_run:
            print("R611Q package-v2 addendum dry run: OK (no files written)")
            return 0

        repo_root_resolved = Path(repo_root).resolve()
        output_root = args.output_root if args.output_root is not None else _resolve_output_root(config)
        output_root = Path(output_root).expanduser().resolve()
        package_id = config["output"]["package_id"]
        repository_summary_target = config["output"]["repository_summary"]["directory"]
        package_dir = output_root / package_id
        write_repository_summary = not args.no_write_repository_summary

        # --- Preflight everything before any write, in the required order:
        # (1) repository-summary target, (2) external output root/package
        # path. Building the summary bytes below is pure/in-memory only.
        summary_dir: Path | None = None
        summary_json_path: Path | None = None
        summary_readme_path: Path | None = None
        if write_repository_summary:
            configured_summary_dir = (repo_root_resolved / repository_summary_target).resolve()
            if effective_repository_summary_dir is not None:
                provided_summary_dir = Path(effective_repository_summary_dir).resolve()
                if provided_summary_dir != configured_summary_dir:
                    raise PackageV2Error(
                        "--repository-summary-dir must resolve exactly to the configured "
                        f"summary directory {configured_summary_dir}; got {provided_summary_dir}"
                    )
            summary_dir = configured_summary_dir
            _reject_symlink_ancestry(summary_dir, "repository summary directory")
            _require_or_raise(
                not summary_dir.exists(),
                f"repository summary directory already exists (create-only contract): {summary_dir}",
            )
            json_name = Path(config["output"]["repository_summary"]["json_path"]).name
            readme_name = Path(config["output"]["repository_summary"]["readme_path"]).name
            summary_json_path = summary_dir / json_name
            summary_readme_path = summary_dir / readme_name
            _reject_symlink_ancestry(summary_json_path, "repository summary JSON path")
            _reject_symlink_ancestry(summary_readme_path, "repository summary README path")
            _require_or_raise(
                not summary_json_path.exists() and not summary_readme_path.exists(),
                f"repository summary target already exists (create-only contract): {summary_dir}",
            )

        _require_outside_repo(output_root, repo_root_resolved, "external package output root")
        _reject_symlink_ancestry(output_root, "external package output root")
        _reject_symlink_ancestry(package_dir, "external package path")
        _require_or_raise(
            not package_dir.exists(),
            f"external package path already exists (create-only contract): {package_dir}",
        )

        # --- Publish the repository summary first (its own staged, tracked,
        # all-or-nothing write), then the external package last, so a summary
        # failure never leaves a finalized external package behind.
        created_summary_root: Path | None = None
        if write_repository_summary:
            assert summary_dir is not None and summary_json_path is not None and summary_readme_path is not None
            summary, readme = build_repository_summary(
                input_hashes=result["input_hashes_summary"],
                output_hashes=result["output_hashes_summary"],
                accepted_claim_count=result["impact"]["accepted_claims"],
                gate_8_state=result["impact"]["gate_8"],
                stage_execution_authorized=result["impact"]["stage_execution_authorized"],
            )
            summary_json_text = json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

            created_summary_root = _mkdir_tracked(summary_dir)
            try:
                summary_json_path.write_text(summary_json_text, encoding="utf-8")
                summary_readme_path.write_text(readme, encoding="utf-8")
            except BaseException:
                if created_summary_root is not None:
                    shutil.rmtree(created_summary_root, ignore_errors=True)
                else:
                    for path in (summary_json_path, summary_readme_path):
                        if path.exists():
                            path.unlink()
                raise
            print(f"R611Q package-v2 addendum: repository summary written: {summary_dir}")

        try:
            package_dir, written = render_external_package(
                output_root,
                package_id=package_id,
                repository_summary_target=repository_summary_target,
                artifacts=result["external_artifacts"],
                repo_root=repo_root_resolved,
            )
        except BaseException:
            # The repository summary already succeeded (if enabled); an
            # external-publication failure must not leave it behind. Remove
            # only what this invocation created: prefer the single tracked
            # created root (preflight already guaranteed summary_dir did not
            # exist beforehand), falling back to the two specific files if
            # for some reason the root was not tracked. Never a pre-existing
            # ancestor and never a broad/wildcard deletion.
            if write_repository_summary:
                if created_summary_root is not None:
                    shutil.rmtree(created_summary_root, ignore_errors=True)
                elif summary_json_path is not None and summary_readme_path is not None:
                    for path in (summary_json_path, summary_readme_path):
                        if path.exists():
                            path.unlink()
            raise
        print(f"R611Q package-v2 addendum: external package written: {package_dir} ({len(written)} files)")

        return 0
    except (PackageV2Error, OSError) as exc:
        print(f"r611q-package-v2-addendum error: {exc}", file=sys.stderr)
        return 1
    finally:
        if offline_fixture_dir is not None:
            shutil.rmtree(offline_fixture_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
