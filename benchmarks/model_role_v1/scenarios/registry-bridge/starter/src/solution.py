class BundleValidationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_release_bundle(registration, universe, map_lock, map_manifest):
    raise NotImplementedError
