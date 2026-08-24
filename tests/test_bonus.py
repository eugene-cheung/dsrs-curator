"""Bonus 1 and 2. No live EDGAR — fixtures only."""

from __future__ import annotations

from pathlib import Path

from curator.bonus_cusip import (
    assess_unmatched,
    compact_cusip,
    parse_official_list,
    parse_official_list_line,
)
from curator.bonus_notice import attribute_rows, _match_sequence
from curator.parse import (
    holding_includes_sequence,
    notice_parent_from_cover,
    other_manager_tokens,
    sequenced_other_managers,
)
from curator.write import ATTRIBUTED_SCHEMA, write_attributed_parquet

COVER_NS = "http://www.sec.gov/edgar/thirteenfilings"


def _pad80(s: str) -> str:
    return s.ljust(80)[:80]


def test_official_list_star_is_not_part_of_cusip():
    line = "037833100*APPLE INC                     COM                                    E"
    assert len(line) == 80
    parsed = parse_official_list_line(line)
    assert parsed is not None
    cusip, issuer, starred = parsed
    assert cusip == "037833100"
    assert starred is True
    assert issuer == "APPLE INC"
    assert "COM" not in issuer


def test_official_list_compacts_spaced_cusip():
    assert compact_cusip("037833 10 0") == "037833100"
    assert compact_cusip("037833100") == "037833100"
    assert compact_cusip("G11448100") == "G11448100"
    line = _pad80("037833 10 0 APPLE INC")
    parsed = parse_official_list_line(line)
    assert parsed is not None
    assert parsed[0] == "037833100"


def test_official_list_prefers_starred_issuer():
    text = "\n".join(
        [
            _pad80("037833100 APPLE INC                     CALL"),
            _pad80("037833100*APPLE INC                     COM"),
        ]
    )
    table = parse_official_list(text)
    assert table["037833100"] == "APPLE INC"


def test_unmatched_assessment_does_not_guess():
    assert assess_unmatched("G11448100") == "CINS_FOREIGN"
    assert assess_unmatched("037833100") == "UNRESOLVED"
    assert assess_unmatched("123") == "LIKELY_FILER_ERROR"


def test_comma_list_includes_notice_sequence_only():
    assert other_manager_tokens("1, 2, 3, 4") == ["1", "2", "3", "4"]
    assert holding_includes_sequence("1, 2, 3, 4", "1") is True
    assert holding_includes_sequence("1, 2, 3, 4, 6", "1") is True
    assert holding_includes_sequence("3, 4, 5", "1") is False
    assert holding_includes_sequence(None, "1") is False
    assert holding_includes_sequence("11", "1") is False


def test_attribute_rows_drops_parent_book_and_other_affiliates():
    holdings = [
        {"name_of_issuer": "A", "other_manager": "1, 2, 3, 4", "value": 1},
        {"name_of_issuer": "B", "other_manager": None, "value": 2},
        {"name_of_issuer": "C", "other_manager": "3, 4, 5", "value": 3},
        {"name_of_issuer": "D", "other_manager": "1, 2, 3, 4, 6", "value": 4},
    ]
    rows = attribute_rows(holdings, "1", "0001336528")
    assert [r["name_of_issuer"] for r in rows] == ["A", "D"]
    assert all(r["attributed_to_cik"] == "0001336528" for r in rows)
    assert rows[0]["other_manager"] == "1, 2, 3, 4"


def test_match_sequence_by_cik():
    managers = [
        {"sequence": "1", "cik": "1336528", "name": "PSCM", "form_13f_file_number": "028-11694"},
        {"sequence": "2", "cik": "1336477", "name": "GP", "form_13f_file_number": None},
    ]
    assert _match_sequence(managers, "0001336528", "028-11694") == "1"
    assert _match_sequence(managers, "9999999", None) is None


def test_notice_parent_and_sequenced_managers(tmp_path: Path):
    from curator.edgar import _write_combined_xml

    cover = f'''<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="{COVER_NS}">
  <formData>
    <coverPage>
      <reportType>13F NOTICE</reportType>
      <form13FFileNumber>028-11694</form13FFileNumber>
      <otherManagersInfo>
        <otherManager>
          <cik>0002026053</cik>
          <form13FFileNumber>028-25746</form13FFileNumber>
          <name>PERSHING SQUARE INC.</name>
        </otherManager>
      </otherManagersInfo>
    </coverPage>
  </formData>
</edgarSubmission>
'''
    path = tmp_path / "nt.xml"
    _write_combined_xml(path, cover.encode(), None)
    parent = notice_parent_from_cover(path)
    assert parent is not None
    assert parent["cik"] == "2026053"
    assert parent["name"] == "PERSHING SQUARE INC."

    parent_cover = f'''<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="{COVER_NS}">
  <formData>
    <coverPage>
      <reportType>13F HOLDINGS REPORT</reportType>
    </coverPage>
    <summaryPage>
      <otherIncludedManagersCount>2</otherIncludedManagersCount>
      <otherManagers2Info>
        <otherManager2>
          <sequenceNumber>1</sequenceNumber>
          <otherManager>
            <cik>0001336528</cik>
            <form13FFileNumber>028-11694</form13FFileNumber>
            <name>Pershing Square Capital Management, L.P.</name>
          </otherManager>
        </otherManager2>
        <otherManager2>
          <sequenceNumber>2</sequenceNumber>
          <otherManager>
            <cik>0001336477</cik>
            <name>PSCM GP, LLC</name>
          </otherManager>
        </otherManager2>
      </otherManagers2Info>
    </summaryPage>
  </formData>
</edgarSubmission>
'''
    parent_path = tmp_path / "parent.xml"
    _write_combined_xml(parent_path, parent_cover.encode(), None)
    seq = sequenced_other_managers(parent_path)
    assert [s["sequence"] for s in seq] == ["1", "2"]
    assert seq[0]["cik"] == "1336528"


def test_attributed_parquet_schema(tmp_path: Path):
    path = write_attributed_parquet(
        tmp_path / "bonus_attributed.parquet",
        [],
    )
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    assert table.schema.equals(ATTRIBUTED_SCHEMA)
    assert table.num_rows == 0
    assert "attributed_to_cik" in table.schema.names
