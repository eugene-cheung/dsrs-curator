from __future__ import annotations

from pathlib import Path

from curator.cik import (
    LookupIndex,
    normalize_name,
    pad_cik,
    parse_lookup_text,
    reconcile_filers,
    unpad_cik,
    write_filers_csv,
)

LOOKUP_TXT = """\
RENAISSANCE TECHNOLOGIES LLC:1037389:
THIRD POINT LLC:1040273:
APPLE INC:320193:
SOME OTHER SHOP LLC:9991111:
D. E. SHAW & CO., INC.:1009207:
SITUATIONAL AWARENESS LP:1999999:
WRONG ENTITY INC:1697748:
"""


def test_unpad_and_pad_are_string_not_int():
    assert unpad_cik("0001423053") == "1423053"
    assert pad_cik("1423053") == "0001423053"
    assert pad_cik(1037389) == "0001037389"
    assert isinstance(pad_cik("1037389"), str)


def test_normalize_strips_suffixes_and_parentheticals():
    assert normalize_name("DME Capital Management LP (Greenlight)") == (
        "DME CAPITAL MANAGEMENT"
    )
    assert normalize_name("D. E. Shaw & Co. Inc.") == "D E SHAW"
    assert normalize_name("The Baupost Group LLC") == "BAUPOST GROUP"
    assert normalize_name("Man Group plc") == "MAN GROUP"


def test_parse_lookup_splits_from_the_right():
    pairs = parse_lookup_text(LOOKUP_TXT)
    assert ("THIRD POINT LLC", "1040273") in pairs
    assert ("RENAISSANCE TECHNOLOGIES LLC", "1037389") in pairs


def test_given_cik_matches_name():
    index = LookupIndex(parse_lookup_text(LOOKUP_TXT))
    rows = reconcile_filers(
        [{"fund_name": "Renaissance Technologies LLC", "cik": "0001037389"}],
        index,
    )
    assert rows[0].cik == "1037389"
    assert rows[0].cik_source == "given"
    assert rows[0].fund_name == "Renaissance Technologies LLC"


def test_wrong_cik_is_corrected_name_is_not_renamed():
    """Planted bug: name is right, CIK is a real but different company."""
    index = LookupIndex(parse_lookup_text(LOOKUP_TXT))
    rows = reconcile_filers(
        [{"fund_name": "Third Point LLC", "cik": "0001697748"}],
        index,
    )
    assert rows[0].cik == "1040273"
    assert rows[0].cik_source == "corrected"
    assert rows[0].fund_name == "Third Point LLC"


def test_ambiguous_name_is_not_guessed():
    txt = LOOKUP_TXT + "ACME FUND LLC:1:\nACME FUND LLC:2:\n"
    index = LookupIndex(parse_lookup_text(txt))
    rows = reconcile_filers(
        [{"fund_name": "Acme Fund LLC", "cik": "9"}],
        index,
    )
    assert rows[0].cik == "9"
    assert rows[0].cik_source == "given"
    assert "no unique" in rows[0].note.lower() or "candidates" in rows[0].note.lower()


def test_given_cik_kept_when_lookup_name_is_same_firm_with_suffix():
    """BAUPOST GROUP LLC/MA is the roster fund, not BAUPOST GROUP INC."""
    txt = """\
BAUPOST GROUP INC:842322:
BAUPOST GROUP LLC/MA:1061768:
"""
    index = LookupIndex(parse_lookup_text(txt))
    rows = reconcile_filers(
        [{"fund_name": "The Baupost Group LLC", "cik": "0001061768"}],
        index,
    )
    assert rows[0].cik == "1061768"
    assert rows[0].cik_source == "given"
    assert rows[0].fund_name == "The Baupost Group LLC"


def test_namesake_disambiguated_by_who_filed_13f():
    """TUDOR INVESTMENT CORP and TUDOR INVESTMENT CORP ET AL share a name."""
    txt = """\
STATE OF WISCONSIN INVESTMENT BOARD:854157:
TUDOR INVESTMENT CORP:1080384:
TUDOR INVESTMENT CORP ET AL:923093:
"""
    index = LookupIndex(parse_lookup_text(txt))
    probe = lambda cik: cik == "923093"
    rows = reconcile_filers(
        [{"fund_name": "Tudor Investment Corp", "cik": "0000854157"}],
        index,
        filings_probe=probe,
    )
    assert rows[0].cik == "923093"
    assert rows[0].cik_source == "corrected"
    assert rows[0].fund_name == "Tudor Investment Corp"


def test_filers_csv_sorted_by_cik_unpadded(tmp_path: Path):
    index = LookupIndex(parse_lookup_text(LOOKUP_TXT))
    rows = reconcile_filers(
        [
            {"fund_name": "Third Point LLC", "cik": "0001040273"},
            {"fund_name": "Renaissance Technologies LLC", "cik": "0001037389"},
        ],
        index,
    )
    dest = tmp_path / "filers.csv"
    write_filers_csv(dest, rows)
    text = dest.read_text()
    lines = text.strip().splitlines()
    assert lines[0] == "fund_name,cik,cik_source"
    assert lines[1].startswith("Renaissance Technologies LLC,1037389,")
    assert lines[2].startswith("Third Point LLC,1040273,")
    assert "0001037389" not in text
