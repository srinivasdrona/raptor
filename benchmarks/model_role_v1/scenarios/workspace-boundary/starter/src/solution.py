class WorkspaceBoundaryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def resolve_workspace_path(root, requested, resolver=None):
    raise NotImplementedError


def build_disposition_audit(root, requests, resolver=None):
    raise NotImplementedError
