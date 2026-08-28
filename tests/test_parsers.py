"""Offline tests. No network. These lock the parsers that every finding rests on."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))
from enrich import parse_code, parse_locator, clean_name

def test_citation_code_variants_seen_in_the_operative_tariff():
    assert parse_code("S.I. 2020/1430") == (2020, 1430)
    assert parse_code("2022 No. 748") == (2022, 748)
    assert parse_code("2022 No.998") == (2022, 998)
    assert parse_code("Statutory Instruments  2019 No. 450") == (2019, 450)
    assert parse_code("Taxation Notice: 2023/014") == (2023, 14)
    assert parse_code("2025 NO.13") == (2025, 13)

def test_codes_that_name_no_instrument_return_none():
    assert parse_code("Ukraine FTA amendment 2022") is None
    assert parse_code("") is None
    assert parse_code(None) is None

def test_locator_parsing():
    assert parse_locator("https://www.legislation.gov.uk/uksi/2022/689/contents") == (2022, 689)
    assert parse_locator("https://www.gov.uk/government/publications/x") is None

def test_known_answer_disagreement_case():
    """X2209980 is the one internal contradiction in the set. It must stay detected."""
    assert parse_code("2022 No.998") != parse_locator(
        "https://www.legislation.gov.uk/uksi/2022/689/contents")

def test_clean_name_undoes_the_publication_layers_own_damage():
    assert clean_name("Rizhao Baohua New Material Co., Ltd<br>") == "Rizhao Baohua New Material Co., Ltd"
    assert clean_name("Handan Iron &amp; Steel Group Han-Bao Co., Ltd") == "Handan Iron & Steel Group Han-Bao Co., Ltd"
    assert "'" in clean_name("Beijing Shougang Co. Ltd., Qian’an Iron & Steel branch")

def test_clean_name_is_idempotent():
    once = clean_name("Handan Iron &amp; Steel<br>")
    assert clean_name(once) == once
