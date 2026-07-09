import pytest
from raptor.eval.knowns import LabeledVariantReader
from raptor.ingest.contract import SourceContractError
from raptor.ingest.reader import SourceChecksumMismatchError
from conftest import make_eval_config
from _knowns_fixtures import FakeNormalizer

def test_ac6_contract_and_checksum(tmp_path):
    config = make_eval_config(clinvar_snapshot_file_checksum="a" * 64)
    file_path = tmp_path / "bad.txt"
    file_path.write_text("Wrong\tHeader\n", encoding="utf-8")
    
    with pytest.raises(SourceChecksumMismatchError):
        list(LabeledVariantReader(file_path, config, FakeNormalizer({}), snapshot_id="s", snapshot_date="d"))
    
    # Fix checksum to pass checksum check, then fail on contract check
    config2 = make_eval_config(clinvar_snapshot_file_checksum="")
    with pytest.raises(SourceContractError):
        list(LabeledVariantReader(file_path, config2, FakeNormalizer({}), snapshot_id="s", snapshot_date="d"))
