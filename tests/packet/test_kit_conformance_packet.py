from __future__ import annotations

from dataclasses import replace

from raptor.testkit.invariants import assert_determinism, assert_fail_loud_propagates

import test_packet_core as core


def test_packet_core_wires_determinism_invariant() -> None:
    api = core._api()
    packet_input = core._packet_input(api)
    config = core._packet_config(api)

    def run(items, _store):
        return [api["build_packet"](item, config) for item in items]

    assert_determinism(
        run,
        [packet_input],
        lambda: None,
        lambda packets: packets[0].evidence_core_hash,
    )


def test_packet_core_wires_fail_loud_invariant() -> None:
    api = core._api()
    valid = core._packet_input(api)
    invalid = replace(
        valid,
        identity=replace(valid.identity, canonical_spdi=""),
    )
    config = core._packet_config(api)

    def run(items, _store):
        return [api["build_packet"](item, config) for item in items]

    assert_fail_loud_propagates(run, [invalid], lambda: None)
