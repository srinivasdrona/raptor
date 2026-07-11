from scripts.audit_aavc_overlap import common_trim_key


def test_common_trim_equates_differently_anchored_deletion() -> None:
    raptor = common_trim_key("16-2048650-AGGAG-AG")
    aavc = common_trim_key("16-2048649-AAGG-A")

    assert raptor == ("16", 2048650, "AGG", "-")
    assert aavc == raptor


def test_common_trim_keeps_snv_identity() -> None:
    assert common_trim_key("9-132891409-T-G") == ("9", 132891409, "T", "G")
