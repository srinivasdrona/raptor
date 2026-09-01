"""Tests for the ADR-0008 x64 `resource_manifest_sha256` digest contract
(`raptor.eval.prospective_freeze.compute_resource_manifest_sha256` /
`resource_manifest_entries`; full spec in
`docs/ops/adr-0008-resource-manifest-digest.md`).

These tests never touch a real x64 worker, BIAS, Nirvana, or ClinVar --
they only exercise the pure, read-only digest computation against small
synthetic fixture files standing in for the three pinned checksum-manifest
files."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from raptor.eval.prospective_freeze import (
    RESOURCE_MANIFEST_DIGEST_SCHEMA,
    RESOURCE_MANIFEST_ENTRIES,
    ProspectiveInvalidStateError,
    assert_runtime_boundary,
    compute_resource_manifest_sha256,
    observe_runtime_identity,
    resource_manifest_entries,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = REPO_ROOT / "scripts" / "compute_adr0008_resource_manifest_sha256.py"

#: The three pinned filenames, in the pinned order, independent of the
#: production tuple -- a regression guard: if `RESOURCE_MANIFEST_ENTRIES`
#: itself is ever accidentally reordered/renamed, this test (not just the
#: golden-hash test) fails immediately with an obvious diff.
_EXPECTED_PINNED_ENTRIES = (
    ("nirvana_full_manifest", "nirvana-grch38-full.sha256.txt"),
    ("nirvana_updates_manifest", "nirvana-grch38-updates.sha256.txt"),
    ("bias_data_manifest", "bias-hg38-data.sha256.txt"),
)


def _write_pinned_manifests(directory: Path, contents: dict[str, bytes]) -> None:
    """`contents` maps pinned filename -> raw bytes to write for it."""
    for _entry_id, filename in RESOURCE_MANIFEST_ENTRIES:
        (directory / filename).write_bytes(contents[filename])


def test_pinned_entries_are_the_documented_three_manifests_in_order() -> None:
    assert RESOURCE_MANIFEST_ENTRIES == _EXPECTED_PINNED_ENTRIES
    assert RESOURCE_MANIFEST_DIGEST_SCHEMA == "raptor.eval.adr0008_resource_manifest_digest.v1"


def test_resource_manifest_entries_reads_raw_bytes_in_pinned_order(tmp_path: Path) -> None:
    _write_pinned_manifests(
        tmp_path,
        {
            "nirvana-grch38-full.sha256.txt": b"full-manifest-bytes\n",
            "nirvana-grch38-updates.sha256.txt": b"updates-manifest-bytes\n",
            "bias-hg38-data.sha256.txt": b"bias-manifest-bytes\n",
        },
    )
    entries = resource_manifest_entries(tmp_path)
    assert [e["id"] for e in entries] == [entry_id for entry_id, _ in RESOURCE_MANIFEST_ENTRIES]
    assert [e["filename"] for e in entries] == [filename for _, filename in RESOURCE_MANIFEST_ENTRIES]
    for entry, (_, filename) in zip(entries, RESOURCE_MANIFEST_ENTRIES):
        import hashlib

        assert entry["sha256"] == hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest()


@pytest.mark.parametrize("missing_filename", [f for _, f in RESOURCE_MANIFEST_ENTRIES])
def test_resource_manifest_entries_fails_closed_on_any_missing_pinned_file(
    tmp_path: Path, missing_filename: str
) -> None:
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    (tmp_path / missing_filename).unlink()
    with pytest.raises(FileNotFoundError, match=missing_filename):
        resource_manifest_entries(tmp_path)
    with pytest.raises(FileNotFoundError, match=missing_filename):
        compute_resource_manifest_sha256(tmp_path)


def test_resource_manifest_entries_does_not_fuzzy_match_a_renamed_pinned_file(tmp_path: Path) -> None:
    """A renamed pinned file (e.g. a version-suffixed filename) is rejected
    exactly like a missing file -- never silently discovered by a fuzzy or
    prefix match."""
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    renamed = tmp_path / "bias-hg38-data.sha256.txt"
    renamed.rename(tmp_path / "bias-hg38-data-v2.sha256.txt")
    with pytest.raises(FileNotFoundError, match="bias_data_manifest"):
        resource_manifest_entries(tmp_path)


def test_compute_resource_manifest_sha256_is_deterministic(tmp_path: Path) -> None:
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    first = compute_resource_manifest_sha256(tmp_path)
    second = compute_resource_manifest_sha256(tmp_path)
    assert first == second
    assert len(first) == 64
    assert first == first.lower()
    int(first, 16)  # must be valid hex


def test_compute_resource_manifest_sha256_changes_when_any_single_byte_changes(tmp_path: Path) -> None:
    base_contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, base_contents)
    baseline = compute_resource_manifest_sha256(tmp_path)

    for _entry_id, filename in RESOURCE_MANIFEST_ENTRIES:
        mutated_dir = tmp_path / f"mutated-{filename}"
        mutated_dir.mkdir()
        mutated_contents = dict(base_contents)
        mutated_contents[filename] = base_contents[filename] + b"X"
        _write_pinned_manifests(mutated_dir, mutated_contents)
        mutated_digest = compute_resource_manifest_sha256(mutated_dir)
        assert mutated_digest != baseline, f"digest did not change when {filename} content changed"


def test_compute_resource_manifest_sha256_binds_identity_and_order_not_just_a_byte_multiset(
    tmp_path: Path,
) -> None:
    """Swapping which pinned identity two files' bytes sit behind must
    change the digest, even though the exact same three byte-strings are
    present in both directories -- proving the digest binds identity/order,
    not merely an unordered set/multiset of per-file hashes."""
    straight = tmp_path / "straight"
    swapped = tmp_path / "swapped"
    straight.mkdir()
    swapped.mkdir()

    full_bytes = b"FULL-BYTES\n"
    updates_bytes = b"UPDATES-BYTES\n"
    bias_bytes = b"BIAS-BYTES\n"

    _write_pinned_manifests(
        straight,
        {
            "nirvana-grch38-full.sha256.txt": full_bytes,
            "nirvana-grch38-updates.sha256.txt": updates_bytes,
            "bias-hg38-data.sha256.txt": bias_bytes,
        },
    )
    # Same three byte-strings, but full/updates swapped between identities.
    _write_pinned_manifests(
        swapped,
        {
            "nirvana-grch38-full.sha256.txt": updates_bytes,
            "nirvana-grch38-updates.sha256.txt": full_bytes,
            "bias-hg38-data.sha256.txt": bias_bytes,
        },
    )

    assert compute_resource_manifest_sha256(straight) != compute_resource_manifest_sha256(swapped)


def test_compute_resource_manifest_sha256_is_sensitive_to_raw_bytes_including_eol_style(tmp_path: Path) -> None:
    """The digest reads raw bytes only (`Path.read_bytes()`, binary mode) --
    it never applies newline canonicalization, so a CRLF vs LF variant of
    the identical logical manifest content is (by design) a different
    digest, and re-reading the exact same bytes always reproduces the exact
    same digest regardless of host OS."""
    lf_dir = tmp_path / "lf"
    crlf_dir = tmp_path / "crlf"
    lf_dir.mkdir()
    crlf_dir.mkdir()

    lf_contents = {
        "nirvana-grch38-full.sha256.txt": b"line-one\nline-two\n",
        "nirvana-grch38-updates.sha256.txt": b"line-one\nline-two\n",
        "bias-hg38-data.sha256.txt": b"line-one\nline-two\n",
    }
    crlf_contents = {name: value.replace(b"\n", b"\r\n") for name, value in lf_contents.items()}

    _write_pinned_manifests(lf_dir, lf_contents)
    _write_pinned_manifests(crlf_dir, crlf_contents)

    assert compute_resource_manifest_sha256(lf_dir) != compute_resource_manifest_sha256(crlf_dir)
    # Re-reading byte-identical content (simulating a second host / a copy)
    # must reproduce the identical digest -- this is the actual
    # cross-platform reproducibility guarantee (same bytes -> same digest,
    # not same semantic content regardless of encoding).
    lf_dir_copy = tmp_path / "lf-copy"
    lf_dir_copy.mkdir()
    _write_pinned_manifests(lf_dir_copy, lf_contents)
    assert compute_resource_manifest_sha256(lf_dir) == compute_resource_manifest_sha256(lf_dir_copy)


def test_compute_resource_manifest_sha256_matches_golden_value_for_the_documented_algorithm(
    tmp_path: Path,
) -> None:
    """Locks the exact canonical-JSON serialization (`sort_keys=True`,
    `separators=(",", ":")`, `ensure_ascii=False`, UTF-8) this contract
    specifies (`docs/ops/adr-0008-resource-manifest-digest.md`) against a
    fixed, reproducible input -- a future accidental change to the envelope
    shape or the JSON canonicalization parameters fails this test even if
    every other property-style test above still happens to pass."""
    _write_pinned_manifests(
        tmp_path,
        {
            "nirvana-grch38-full.sha256.txt": b"AAA-content\n",
            "nirvana-grch38-updates.sha256.txt": b"BBB-content\n",
            "bias-hg38-data.sha256.txt": b"CCC-content\n",
        },
    )
    assert compute_resource_manifest_sha256(tmp_path) == (
        "ed2835c1f391ca9acf882122681dc2084eba91cd3cd12b43d984fadcfdb93c54"
    )


def test_assert_runtime_boundary_accepts_a_format_valid_computed_digest(tmp_path: Path) -> None:
    """Integration check: a real digest produced by
    `compute_resource_manifest_sha256` satisfies `assert_runtime_boundary`'s
    `resource_manifest_sha256` format check (64-hex lowercase) -- confirms
    the two surfaces (computation contract, runtime-boundary validation)
    agree on shape without `assert_runtime_boundary` itself needing to
    recompute or know the pinned value."""
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    digest = compute_resource_manifest_sha256(tmp_path)
    runtime_identity = {
        "worker_designation": "adr-0008-designated-x64-worker",
        "worker_arch": "x86_64",
        "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        "nirvana_banner": "3.18.1-0-g05f88047",
        "resource_manifest_sha256": digest,
    }
    assert_runtime_boundary(runtime_identity=runtime_identity)  # must not raise


def test_assert_runtime_boundary_still_rejects_a_non_hex_resource_manifest_value() -> None:
    runtime_identity = {
        "worker_designation": "adr-0008-designated-x64-worker",
        "worker_arch": "x86_64",
        "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        "nirvana_banner": "3.18.1-0-g05f88047",
        "resource_manifest_sha256": "not-a-real-digest",
    }
    with pytest.raises(ProspectiveInvalidStateError):
        assert_runtime_boundary(runtime_identity=runtime_identity)


@pytest.mark.parametrize("reported_machine", ["AMD64", "amd64", "x86_64"])
def test_runtime_identity_canonicalizes_native_x64_architecture_names(
    monkeypatch: pytest.MonkeyPatch,
    reported_machine: str,
) -> None:
    monkeypatch.setattr("raptor.eval.prospective_freeze.platform.machine", lambda: reported_machine)

    observed = observe_runtime_identity(
        worker_designation_probe=lambda: "adr-0008-designated-x64-worker",
        bias_commit_probe=lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_banner_probe=lambda: "3.18.1-0-g05f88047",
    )

    assert observed["worker_arch"] == "x86_64"


def test_runtime_identity_does_not_canonicalize_non_x64_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("raptor.eval.prospective_freeze.platform.machine", lambda: "aarch64")

    observed = observe_runtime_identity(
        worker_designation_probe=lambda: "adr-0008-designated-x64-worker",
        bias_commit_probe=lambda: "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        nirvana_banner_probe=lambda: "3.18.1-0-g05f88047",
    )

    assert observed["worker_arch"] == "aarch64"


def test_operator_script_matches_the_library_function(tmp_path: Path) -> None:
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    expected_digest = compute_resource_manifest_sha256(tmp_path)

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--checksums-dir", str(tmp_path), "--allow-non-x64-host"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    report = json.loads(result.stdout)
    assert report["resource_manifest_sha256"] == expected_digest
    assert [m["id"] for m in report["manifests"]] == [entry_id for entry_id, _ in RESOURCE_MANIFEST_ENTRIES]


def test_operator_script_refuses_on_a_non_x64_host_without_the_override_flag(tmp_path: Path) -> None:
    """This test's own host is not required to be x64 (RAPTOR's dev/CI hosts
    are typically ARM); the script must REFUSE (exit 2) on any non-x64 host
    unless `--allow-non-x64-host` is passed -- fail-closed by default for a
    contract whose whole point is ADR-0008 x64-worker-only execution."""
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--checksums-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    if result.returncode == 0:
        pytest.skip("this test host reports as x86_64/AMD64; the refusal path is not exercised here")
    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def test_operator_script_fails_closed_on_missing_manifest_file(tmp_path: Path) -> None:
    contents = {filename: f"{filename}-bytes".encode("utf-8") for _, filename in RESOURCE_MANIFEST_ENTRIES}
    _write_pinned_manifests(tmp_path, contents)
    (tmp_path / "bias-hg38-data.sha256.txt").unlink()

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--checksums-dir", str(tmp_path), "--allow-non-x64-host"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 2
    assert "REFUSED" in result.stderr
    assert "bias_data_manifest" in result.stderr
