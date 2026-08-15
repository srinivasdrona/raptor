from pathlib import Path


class WorkspaceBoundaryError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def resolve_workspace_path(root, requested, resolver=None):
    root = Path(root)
    if not requested:
        raise WorkspaceBoundaryError("EMPTY_PATH")
    candidate = root / requested
    if ".." in Path(requested).parts:
        raise WorkspaceBoundaryError("PARENT_SEGMENT")
    if not str(candidate).startswith(str(root)):
        raise WorkspaceBoundaryError("RESOLVED_ESCAPE")
    return candidate


def build_disposition_audit(root, requests, resolver=None):
    dispositions = []
    for request in requests:
        try:
            resolved = resolve_workspace_path(root, request, resolver=resolver)
        except WorkspaceBoundaryError:
            continue
        dispositions.append(
            {"request": request, "status": "ACCEPT", "resolved_path": str(resolved)}
        )
    return {
        "schema": "workspace-disposition-audit-v1",
        "total": len(requests),
        "accepted": len(dispositions),
        "rejected": len(requests) - len(dispositions),
        "dispositions": dispositions,
    }
