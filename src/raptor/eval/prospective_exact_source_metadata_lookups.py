"""raptor.eval.prospective_exact_source_metadata_lookups -- the ADR-0020
hard-wired, production-owned implementations of the
`published_archive_date_lookup`/`official_md5_lookup` ports consumed by
`raptor.eval.prospective_freeze.execute_transport_and_raw_freeze`.

Independent review finding (live-transport-bypass, round 5): confirmed
live `--execute` acquisition must import/execute ZERO caller-selected
Python/plugin code before the real archive GET. Before this module
existed, `scripts/run_clinvar_2026_08_prospective_freeze.py` resolved
both ports from CLI-supplied `--published-archive-date-lookup`/
`--official-md5-lookup` `"module:callable"` strings via
`importlib.import_module`. That was an arbitrary-code-execution surface
in its own right, independent of whatever the resolved callable itself
did: importing ANY module named on the command line runs that module's
full top-level code, unsandboxed, strictly between the real transport
`head()` and the real streamed `GET` -- long enough for it to do
anything at all (monkeypatch `_ExactSourceTransport`, open its own
sockets, mutate `sys.modules`/other modules' globals, replace
`prospective_freeze.execute_transport_and_raw_freeze` itself, etc.). The
transport-identity-pin defense added in an earlier round only detects
tampering with `type(transport).head`/`.stream_get`; it was never a
complete answer to "arbitrary code ran here at all", only a narrower
defense-in-depth check layered on top of it.

This module is now the ONE production implementation for both ports. It
is imported *statically* -- a plain `import` statement at the top of
`scripts/run_clinvar_2026_08_prospective_freeze.py`, resolved once at
Python's own module-load time, never from a runtime string -- and there
is no CLI option, environment variable, or config value anywhere in this
repository that can substitute a different module for either port during
a confirmed live `--execute` run. `--published-archive-date-lookup`/
`--official-md5-lookup` were removed from the CLI entirely (not merely
defaulted): supplying either flag is now an "unrecognized arguments"
argparse failure before anything else runs.

Both ports remain functionally UNFROZEN (see `docs/project/specs/
clinvar-2026-08-prospective-amendment-v2.yaml`,
`dataset_registration.unknown_until_post_approval_freeze
.ncbi_published_archive_date` / `.official_md5`): the real-world NCBI
metadata source for each has never been ratified by any prior round of
this contract, and this agent must never contact ClinVar/NCBI to work
one out. Rather than fabricate an unverified live-HTTP integration
against NCBI -- explicitly out of scope ("do not invent broad
dependency/tooling changes") -- both functions below fail closed: they
always raise `MetadataLookupNotYetImplementedError` before making any
network call of any kind. This keeps confirmed live `--execute`
permanently inert for stage 1/2 archive acquisition until a dedicated,
reviewed follow-up change lands a real implementation *in this same
module* (preserving the "one production-owned module, no CLI
selection" shape) -- never by reintroducing a caller-selected import
surface, and never by a human pasting a fabricated result to make a run
"succeed".

Testability: `execute_transport_and_raw_freeze` itself still accepts
`published_archive_date_lookup`/`official_md5_lookup` as plain injected
callables (ordinary dependency injection for unit tests, exactly like
its `transport` parameter) -- that is unaffected by this module and
carries no CLI-selectable surface of its own. Tests that specifically
want the CLI's own wiring to observe a successful lookup patch this
module's two attributes directly with `monkeypatch.setattr` -- a known,
static, production-owned symbol, never a dynamically-resolved
`"module:callable"` string.
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "MetadataLookupNotYetImplementedError",
    "published_archive_date_lookup",
    "official_md5_lookup",
]


class MetadataLookupNotYetImplementedError(RuntimeError):
    """Raised by both hard-wired production lookups below: the real NCBI
    metadata source for this port has never been ratified/implemented in
    this repository. Confirmed live `--execute` acquisition always fails
    closed here rather than accepting a caller-selected substitute
    implementation or a fabricated result."""


def published_archive_date_lookup(url: str) -> dict[str, Any]:
    """Hard-wired production `published_archive_date_lookup` port. Always
    raises `MetadataLookupNotYetImplementedError` -- see module
    docstring. Never opens a socket, never imports any other module."""
    raise MetadataLookupNotYetImplementedError(
        "published_archive_date_lookup has no ratified production NCBI source "
        f"in this repository yet; refusing to guess for url={url!r}. A real "
        "implementation must land in "
        "raptor.eval.prospective_exact_source_metadata_lookups (this module) "
        "via a dedicated, reviewed change -- never via a caller-selected CLI "
        "import and never by fabricating a result."
    )


def official_md5_lookup(url: str) -> dict[str, Any]:
    """Hard-wired production `official_md5_lookup` port. Always raises
    `MetadataLookupNotYetImplementedError` -- see module docstring. Never
    opens a socket, never imports any other module."""
    raise MetadataLookupNotYetImplementedError(
        "official_md5_lookup has no ratified production NCBI source in this "
        f"repository yet; refusing to guess for url={url!r}. A real "
        "implementation must land in "
        "raptor.eval.prospective_exact_source_metadata_lookups (this module) "
        "via a dedicated, reviewed change -- never via a caller-selected CLI "
        "import and never by fabricating a result."
    )
