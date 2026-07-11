"""
AC-A1: Predictor aggregation defect oracle.
Independent synthetic multi-predictor oracle for max/tie/order behavior.
"""
import pytest
from typing import Mapping

def intended_strength(per_tool_scores: Mapping[str, int], cap: int) -> int:
    """
    Independent pure spec of the intended max-plus-consensus-with-cap aggregation.
    """
    if not per_tool_scores:
        return 0
    max_score = max(per_tool_scores.values())
    tied_count = sum(1 for v in per_tool_scores.values() if v == max_score)
    score = max_score
    if tied_count > 1:
        score += 1
    return min(score, cap)

def simulated_bias_emitted_pp3(per_tool_scores: Mapping[str, int]) -> int:
    """
    Simulates actual BIAS 3.0.0 emitted behavior for PP3, based on L944-954 of pathogenic_classifiers.py.
    Anchor evidence: `best_score = 0` (L944) is never reassigned. Loop `if a_score >= best_score` (L948)
    is always true. Result is order-dependent (last tool).
    Bump occurs if any >= 2 tools fire: `if len(best_algs) > 1: score += 1` (L952-953).
    """
    pp3_tools = ['phylop', 'revel', 'absplice', 'alphamissense']
    best_score = 0
    best_algs = []
    score = 0
    for alg in pp3_tools:
        if alg in per_tool_scores:
            a_score = per_tool_scores[alg]
            if a_score >= best_score:
                best_algs.append(alg)
                score = a_score
    if len(best_algs) > 1:
        score += 1
    return min(score, 3)

def simulated_bias_emitted_bp4(per_tool_scores: Mapping[str, int]) -> int:
    """
    Simulates actual BIAS 3.0.0 emitted behavior for BP4, based on L491-503 of benign_classifiers.py.
    Anchor evidence: `best_score = 0` (L491) is never reassigned. Loop `if a_score >= best_score`
    is always true. Result is order-dependent (last tool).
    Consensus bump `if len(best_algs) > 1 and best_score > 1` (L499-500) is permanently dead.
    """
    bp4_tools = ['phylop', 'revel', 'dann', 'gerp', 'absplice', 'alphamissense']
    best_score = 0
    best_algs = []
    score = 0
    for alg in bp4_tools:
        if alg in per_tool_scores:
            a_score = per_tool_scores[alg]
            if a_score >= best_score:
                best_algs.append(alg)
                score = a_score
    if len(best_algs) > 1 and best_score > 1:
        score += 1
        
    if len(per_tool_scores) < 2 and score == 1:
        return 0
    if score == 2:
        return 3
    return min(score, 4)

def test_aca1_defect_oracle():
    """
    AC-A1: Probe 1 reproduces emitted != intended deterministically.
    Defecthood is asserted from those two blocks' own code and comments: the dead `best_score` sentinel.
    `get_pm1` L405-433 is only corroborating context for the correct `if score > best_score` idiom.
    """
    # 1. PP3: Last iterated tool order dependency and over-bump.
    # {phylop: 2, revel: 3} -> last is revel (3). best_algs length is 2. score=3+1=4, capped to 3.
    # Intended: max is 3, tie count 1 -> score=3.
    scores_1 = {'phylop': 2, 'revel': 3}
    assert intended_strength(scores_1, 3) == 3
    assert simulated_bias_emitted_pp3(scores_1) == 3 # Wait, 3+1 = 4, capped to 3. So it equals. Let's find one that diverges.
    
    # Let's try {phylop: 3, revel: 1} -> last is revel (1). best_algs is 2. score=1+1=2. Capped to 3.
    # Intended: max is 3, tie 1 -> score 3.
    scores_2 = {'phylop': 3, 'revel': 1}
    assert intended_strength(scores_2, 3) == 3
    assert simulated_bias_emitted_pp3(scores_2) == 2
    
    # 2. BP4: Never bumps
    # {revel: 3, dann: 3} -> last is dann (3). best_algs is 2. best_score=0 so best_score > 1 is false. score=3.
    # Intended: max is 3, tie count 2 -> score=4.
    scores_3 = {'revel': 3, 'dann': 3}
    assert intended_strength(scores_3, 4) == 4
    assert simulated_bias_emitted_bp4(scores_3) == 3

    # BP4: Single supporting floor logic logic remap
    # Let's just prove defecthood: order dependent
    scores_4 = {'phylop': 3, 'revel': 1} # last is revel (1), no bump -> score=1 -> single supporting floor -> 0? Wait, len=2.
    assert intended_strength(scores_4, 4) == 3
    assert simulated_bias_emitted_bp4(scores_4) == 1

def test_aca1_no_agpl_import():
    import sys
    assert 'bias_2015' not in sys.modules
