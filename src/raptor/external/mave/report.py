"""Identity-free, label-free, deterministic aggregate for the label-blind
MAVE endpoint (`endpoint.run_label_blind_validation`).

`LabelBlindReport.aggregate()` never contains a `variant_id`, a clinical
label, or any gate/authorization key -- `report.content_hash()` lets callers
prove two independently-built reports (e.g. built from rows in a different
order) are byte-identical.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ._stats import bootstrap_ci, spearman_kendall

_FUNCTIONAL_BLB_BELOW = 0.242
_FUNCTIONAL_PLP_ABOVE = 0.477
_FUNCTIONAL_CLASSES = ("functional_BLB", "ambiguous", "functional_PLP")


def _classify(score: float) -> str:
    # Mirrors `endpoint.classify_functional_score` exactly (duplicated as
    # plain constants, not an import, to avoid a report.py<->endpoint.py
    # import cycle -- endpoint.py already imports this module).
    if score < _FUNCTIONAL_BLB_BELOW:
        return "functional_BLB"
    if score > _FUNCTIONAL_PLP_ABOVE:
        return "functional_PLP"
    return "ambiguous"


@dataclass(frozen=True)
class LabelBlindReport:
    _payload: dict

    @staticmethod
    def build(
        observations: list[tuple[str, float, float]],
        *,
        bootstrap_resamples: int,
        random_seed: int,
    ) -> "LabelBlindReport":
        """`observations` is `[(variant_id, raptor_score, mave_score), ...]`.
        Sorted by `variant_id` before any statistic is computed so the
        result is independent of the caller's original row order."""
        ordered = sorted(observations, key=lambda item: item[0])
        raptor_scores = [item[1] for item in ordered]
        mave_scores = [item[2] for item in ordered]

        spearman_stat, kendall_stat = spearman_kendall(raptor_scores, mave_scores)
        spearman_ci = bootstrap_ci(
            raptor_scores,
            mave_scores,
            lambda xs, ys: spearman_kendall(xs, ys)[0],
            resamples=bootstrap_resamples,
            seed=random_seed,
        )
        kendall_ci = bootstrap_ci(
            raptor_scores,
            mave_scores,
            lambda xs, ys: spearman_kendall(xs, ys)[1],
            resamples=bootstrap_resamples,
            seed=random_seed + 1,
        )

        raptor_classes = [_classify(score) for score in raptor_scores]
        mave_classes = [_classify(score) for score in mave_scores]

        functional_class_counts = {name: mave_classes.count(name) for name in _FUNCTIONAL_CLASSES}
        agreement_matrix = {
            row_name: {
                col_name: sum(
                    1
                    for raptor_class, mave_class in zip(raptor_classes, mave_classes)
                    if raptor_class == row_name and mave_class == col_name
                )
                for col_name in _FUNCTIONAL_CLASSES
            }
            for row_name in _FUNCTIONAL_CLASSES
        }

        payload = {
            "validation_mode": "NON_GATING",
            "n_variants": len(ordered),
            "spearman": {
                "n": len(ordered),
                "statistic": spearman_stat,
                "bootstrap_ci": list(spearman_ci),
            },
            "kendall": {
                "n": len(ordered),
                "statistic": kendall_stat,
                "bootstrap_ci": list(kendall_ci),
            },
            "functional_class_counts": functional_class_counts,
            "agreement_matrix": agreement_matrix,
        }
        return LabelBlindReport(_payload=payload)

    def aggregate(self) -> dict:
        """Return the identity-free, label-free aggregate dict. A fresh
        (deep) copy is returned each call so callers cannot mutate internal
        state through the returned dict."""
        return json.loads(json.dumps(self._payload, sort_keys=True))

    def content_hash(self) -> str:
        """sha256 of the canonical (sorted-key) JSON aggregate -- lets
        callers prove two independently-built reports are byte-identical."""
        blob = json.dumps(self.aggregate(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


__all__ = ["LabelBlindReport"]
