import hashlib
from pathlib import Path

from solution import publish_verified_snapshot


SOURCE = Path("artifacts/source.json")


def test_basic_publish(tmp_path):
    output = tmp_path / "snapshot.json"
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    audit = publish_verified_snapshot(SOURCE, output, expected)
    assert output.exists()
    assert audit["record_count"] == 2
