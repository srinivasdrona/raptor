class SnapshotPublishError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def publish_verified_snapshot(
    source_path, output_path, expected_sha256, before_publish=None
):
    raise NotImplementedError
