---
applyTo: "**"
---

# Mandatory RAPTOR Python environment

Run every Python, pip, pytest, lint, type-check, build, and RAPTOR module command
through WSL2 Ubuntu and `/home/sdrona/raptor`.

```powershell
wsl.exe -e bash -lc "source ~/raptor/bin/activate && cd /mnt/d/AIProjects/raptor-worktrees/panel-products-rescue-screen && python -m pytest ..."
```

For direct module execution, use `PYTHONPATH=src` unless the worktree was
deliberately installed into the venv. Never fall back to native Windows Python.
Before reporting validation, verify `sys.executable` is
`/home/sdrona/raptor/bin/python`.

The isolated x64 Nirvana/BIAS workflow remains the sole exception and must run
on its designated x64 worker under ADR-0008.
