import os
import ast
from pathlib import Path

def test_ac5_forbidden_import_audit():
    repo_root = Path(__file__).parent.parent.parent
    src_dir = repo_root / "src" / "raptor"
    
    scorer_dir = src_dir / "scorer"
    ingest_dir = src_dir / "ingest"
    
    def check_dir(d):
        if not d.exists():
            return
        for root, _, files in os.walk(d):
            for file in files:
                if file.endswith(".py"):
                    path = Path(root) / file
                    text = path.read_text(encoding="utf-8")
                    assert "raptor.eval.knowns" not in text, f"Forbidden import found in {path}"
    
    check_dir(scorer_dir)
    check_dir(ingest_dir)
