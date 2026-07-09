"""PRD-06 sec 10.3 `checks.py` — oracle-blind consistency checks (FR7/AC8).

These checks NEVER read a label (R-A2/H1): they flag internal
contradictions in the criterion-call evidence itself, e.g. a variant firing
both a benign `stand_alone` criterion (BA1) and a pathogenic `very_strong`
criterion (PVS1) -- laundering a label into a consistent-looking call can't
pass a check that never sees the label at all.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

CriterionCall = Tuple[str, str, str]


def oracle_blind_checks(evidence: Dict[str, Iterable[CriterionCall]]) -> List[str]:
    """Flag internal (label-blind) contradictions across each variant's
    fired criterion calls (FR7). `evidence` is `{variant_id: [(criterion,
    strength, direction), ...], ...}` -- no label is read or required.

    Currently checks: a benign `stand_alone`-strength call co-firing with a
    pathogenic `very_strong`-strength call on the same variant (e.g. BA1 +
    PVS1) -- the strongest possible direction contradiction.
    """
    findings: List[str] = []
    for variant_id, calls in evidence.items():
        benign_standalone = [
            c for c, strength, direction in calls if strength == "stand_alone" and direction == "benign"
        ]
        pathogenic_very_strong = [
            c for c, strength, direction in calls if strength == "very_strong" and direction == "pathogenic"
        ]
        for benign_criterion in benign_standalone:
            for pathogenic_criterion in pathogenic_very_strong:
                findings.append(
                    f"variant {variant_id}: contradictory criteria fired -- "
                    f"{benign_criterion} (benign, stand_alone) and {pathogenic_criterion} "
                    "(pathogenic, very_strong) cannot both hold"
                )
    return findings
