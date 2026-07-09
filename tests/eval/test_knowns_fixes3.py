"""PRD-07 checker round-3 finding (planner-authored, spec-correct invariant).

1 MAJOR: the protein parser still admits NON-substitutions into `missense` because it
accepts any 3-letter (or 1-letter) `rest` as an amino acid:
  * `p.Arg611del` / `p.Arg611dup` (deletion/duplication) -> false-missense (`del`/`dup`
    are 3 letters);
  * `p.Xaa123Gln` / `p.X123Q` (unknown/placeholder aa) -> false-missense;
  * lowercase `p.Arg611ter` (nonsense) / `p.met1val` (start-loss) -> false-missense
    because the Ter/Met logic is case-sensitive.
Fix: classify `missense` ONLY when BOTH ref and alt are CANONICAL amino-acid codes
(same 3- or 1-letter system) and differ; case-fold the Ter/*/Met/fs/ext logic. A
false-missense corrupts the R-A2c-gated missense stratum -- the worst class of error here.
"""
from __future__ import annotations

from raptor.eval.knowns import classify_variant


def _n(p: str) -> str:
    return f"NM_1(TSC1):c.1A>G (p.{p})"


# --------------------------------------------------------------------------
# del/dup are not substitutions -> never missense
# --------------------------------------------------------------------------
def test_del_dup_not_missense():
    assert classify_variant(_n("Arg611del")) == "other"
    assert classify_variant(_n("Arg611dup")) == "other"
    assert classify_variant(_n("R611del")) == "other"


# --------------------------------------------------------------------------
# unknown / placeholder amino-acid codes -> never missense
# --------------------------------------------------------------------------
def test_unknown_aa_not_missense():
    assert classify_variant(_n("Xaa123Gln")) == "other"
    assert classify_variant(_n("X123Q")) == "other"
    assert classify_variant(_n("Arg611Zzz")) == "other"


# --------------------------------------------------------------------------
# case-folded marker/AA logic
# --------------------------------------------------------------------------
def test_case_insensitive_markers():
    assert classify_variant(_n("Arg611ter")) == "truncating"   # lowercase nonsense (aa -> ter)
    assert classify_variant(_n("met1val")) == "other"          # lowercase start-loss (initiator Met)
    assert classify_variant(_n("ter1808arg")) == "other"       # lowercase stop-loss (Ter is REF)


# --------------------------------------------------------------------------
# regression: genuine substitutions (any case) still missense
# --------------------------------------------------------------------------
def test_valid_substitutions_still_missense():
    assert classify_variant(_n("Arg611Gln")) == "missense"
    assert classify_variant(_n("R611Q")) == "missense"
    assert classify_variant(_n("arg611gln")) == "missense"     # case-folded valid substitution
