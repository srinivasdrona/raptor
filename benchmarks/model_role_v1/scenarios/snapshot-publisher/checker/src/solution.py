import hashlib
import json
from pathlib import Path


class SnapshotPublishError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def publish_verified_snapshot(
    source_path, output_path, expected_sha256, before_publish=None
):
    source_path = Path(source_path)
    output_path = Path(output_path)
    initial = source_path.read_bytes()
    if hashlib.sha256(initial).hexdigest() != expected_sha256:
        raise SnapshotPublishError("SOURCE_HASH")
    data = json.loads(initial)
    if before_publish:
        before_publish(source_path)
    payload = {
        "schema": "verified-snapshot-v1",
        "records": data["records"],
    }
    encoded = json.dumps(payload, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    output_path.write_bytes(encoded)
    return {
        "schema": "snapshot-publish-audit-v1",
        "source_sha256": expected_sha256,
        "record_count": len(data["records"]),
        "checks": ["SOURCE_HASH", "CANONICAL_SNAPSHOT"],
    }
