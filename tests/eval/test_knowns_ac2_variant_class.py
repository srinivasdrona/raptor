import pytest
from raptor.eval.knowns import classify_variant

def test_ac2_variant_class():
    assert classify_variant("NM_000548.5(TSC2):c.1832G>A (p.Arg611Gln)") == "missense"
    assert classify_variant("NM_000548.5(TSC2):c.1832G>A (p.Arg611Ter)") == "truncating"
    assert classify_variant("NM_000548.5(TSC2):c.1832G>A (p.Gln1503*)") == "truncating"
    assert classify_variant("NM_000548.5(TSC2):c.1832G>A (p.Ser1043fs)") == "truncating"
    
    # synonymous, splice, no-p -> other
    assert classify_variant("NM_000548.5(TSC2):c.1832G>A (p.=)") == "other"
    assert classify_variant("NM_000548.5(TSC2):c.1832+1G>A") == "other"
    assert classify_variant("unparseable string p.????") == "other"
