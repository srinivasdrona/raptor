"""One-way export of a :class:`MechanismProfile` to the external DisMech schema.

This export is intentionally one-way: it has no external schema
dependency and does not accept contributions back from DisMech. The
returned :class:`DisMechRecord` carries an equality-bound (not
hash-participating) audit copy of provenance for external consumers.
"""

from __future__ import annotations

from raptor.atlas.model import AtlasExportError, DisMechRecord, MechanismProfile


def export_dismech(profile: MechanismProfile) -> DisMechRecord:
    """Produce a one-way :class:`DisMechRecord` export from ``profile``.

    Raises :class:`AtlasExportError` if the profile has no resolved
    canonical SPDI to export.
    """

    if not profile.identity.spdi_canonical:
        raise AtlasExportError("cannot export a profile with no canonical SPDI")

    provenance_audit = {
        "source_pins": tuple(
            (pin.entry_id, pin.span.locator if pin.span else None)
            for pin in profile.provenance.source_pins
        ),
        "version_pins": profile.provenance.version_pins,
        "content_hashes": dict(profile.provenance.content_hashes),
    }

    return DisMechRecord(
        spdi_canonical=profile.identity.spdi_canonical,
        pack_binding=profile.pack_binding,
        claims=profile.claims,
        provenance=provenance_audit,
    )
