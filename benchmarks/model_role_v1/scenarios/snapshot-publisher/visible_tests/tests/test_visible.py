import hashlib
from pathlib import Path

import pytest

from solution import SnapshotPublishError, publish_verified_snapshot


SOURCE = Path("artifacts/source.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_publishes_snapshot_and_audit(tmp_path):
    output = tmp_path / "snapshot.json"
    audit = publish_verified_snapshot(SOURCE, output, digest(SOURCE))
    assert output.exists()
    assert audit["schema"] == "snapshot-publish-audit-v1"
    assert audit["record_count"] == 2


def test_wrong_source_hash_fails_before_output(tmp_path):
    output = tmp_path / "snapshot.json"
    with pytest.raises(SnapshotPublishError) as caught:
        publish_verified_snapshot(SOURCE, output, "0" * 64)
    assert caught.value.code == "SOURCE_HASH"
    assert not output.exists()
