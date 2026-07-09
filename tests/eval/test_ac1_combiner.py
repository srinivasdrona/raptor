"""AC1 — implied-direction combiner, validated against the INDEPENDENT Tavtigian-2018
point oracle (not the implementation). Asserts the computed points + implied
direction; `variant_id` is assigned by the caller, so it is not compared here.
"""
from raptor.eval.combine import implied_direction


def _call(calls, config):
    return implied_direction(calls, config)


def test_ac1_tavtigian_points_and_direction(valid_eval_config):
    cfg = valid_eval_config

    # PVS1(+8) + PM2(+1) = +9 -> LP
    r = _call([("PVS1", "very_strong", "pathogenic"), ("PM2", "supporting", "pathogenic")], cfg)
    assert (r.points, r.implied) == (9, "LP")

    # PM2(+2) + PP3(+1) = +3 -> no_call (VUS 0..5)
    r = _call([("PM2", "moderate", "pathogenic"), ("PP3", "supporting", "pathogenic")], cfg)
    assert (r.points, r.implied) == (3, "no_call")

    # BA1(stand_alone = -8) -> LB (Benign)
    r = _call([("BA1", "stand_alone", "benign")], cfg)
    assert (r.points, r.implied) == (-8, "LB")

    # BS1(-4) + BP4(-1) = -5 -> LB (Likely Benign)
    r = _call([("BS1", "strong", "benign"), ("BP4", "supporting", "benign")], cfg)
    assert (r.points, r.implied) == (-5, "LB")

    # PS4(+4) + PM1(+2) + PM2(+2) + PP3(+1) = +9 -> LP
    r = _call([("PS4", "strong", "pathogenic"), ("PM1", "moderate", "pathogenic"),
               ("PM2", "moderate", "pathogenic"), ("PP3", "supporting", "pathogenic")], cfg)
    assert (r.points, r.implied) == (9, "LP")

    # PVS1(+8) + PS4(+4) = +12 (Pathogenic >=10) -> LP
    r = _call([("PVS1", "very_strong", "pathogenic"), ("PS4", "strong", "pathogenic")], cfg)
    assert (r.points, r.implied) == (12, "LP")


def test_ac1_no_fired_criteria_is_no_call(valid_eval_config):
    """Zero criteria -> 0 points -> no_call (abstain is first-class, never forced)."""
    r = _call([], valid_eval_config)
    assert (r.points, r.implied) == (0, "no_call")
