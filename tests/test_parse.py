from __future__ import annotations

from datetime import date
from pathlib import Path

from curator.cik import pad_cik
from curator.edgar import FilingRef
from curator.parse import normalize_cusip, parse_filing
from curator.write import write_parquet

COVER_NS = "http://www.sec.gov/edgar/thirteenfilings"
TABLE_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

DEFAULT_NS_COVER = f'''<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="{COVER_NS}">
  <headerData>
    <filerInfo>
      <periodOfReport>03-31-2026</periodOfReport>
    </filerInfo>
  </headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2026</reportCalendarOrQuarter>
      <isAmendment>false</isAmendment>
      <filingManager>
        <name>TEST FUND LLC</name>
      </filingManager>
      <reportType>13F HOLDINGS REPORT</reportType>
      <form13FFileNumber>028-11111</form13FFileNumber>
      <crdNumber>001234</crdNumber>
      <secFileNumber>801-99999</secFileNumber>
      <otherIncludedManagersCount>0</otherIncludedManagersCount>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>2</tableEntryTotal>
      <tableValueTotal>1500</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>
'''

DEFAULT_NS_TABLE = f'''<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="{TABLE_NS}">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>1000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>10</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>10</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>FOREIGN ISSUER</nameOfIssuer>
    <titleOfClass>SHS</titleOfClass>
    <cusip>G11448100</cusip>
    <value>500</value>
    <shrsOrPrnAmt>
      <sshPrnamt>5</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <putCall>Call</putCall>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>0</Sole>
      <Shared>0</Shared>
      <None>5</None>
    </votingAuthority>
  </infoTable>
</informationTable>
'''

PREFIXED_COVER = f'''<?xml version="1.0" encoding="UTF-8"?>
<ns1:edgarSubmission xmlns:ns1="{COVER_NS}">
  <ns1:formData>
    <ns1:coverPage>
      <ns1:reportCalendarOrQuarter>03-31-2026</ns1:reportCalendarOrQuarter>
      <ns1:isAmendment>false</ns1:isAmendment>
      <ns1:filingManager>
        <ns1:name>TEST FUND LLC</ns1:name>
      </ns1:filingManager>
      <ns1:reportType>13F HOLDINGS REPORT</ns1:reportType>
      <ns1:otherIncludedManagersCount>0</ns1:otherIncludedManagersCount>
    </ns1:coverPage>
    <ns1:summaryPage>
      <ns1:tableEntryTotal>2</ns1:tableEntryTotal>
      <ns1:tableValueTotal>1500</ns1:tableValueTotal>
    </ns1:summaryPage>
  </ns1:formData>
</ns1:edgarSubmission>
'''

PREFIXED_TABLE = f'''<?xml version="1.0" encoding="UTF-8"?>
<ns1:informationTable xmlns:ns1="{TABLE_NS}">
  <ns1:infoTable>
    <ns1:nameOfIssuer>APPLE INC</ns1:nameOfIssuer>
    <ns1:titleOfClass>COM</ns1:titleOfClass>
    <ns1:cusip>037833100</ns1:cusip>
    <ns1:value>1000</ns1:value>
    <ns1:shrsOrPrnAmt>
      <ns1:sshPrnamt>10</ns1:sshPrnamt>
      <ns1:sshPrnamtType>SH</ns1:sshPrnamtType>
    </ns1:shrsOrPrnAmt>
    <ns1:investmentDiscretion>SOLE</ns1:investmentDiscretion>
    <ns1:votingAuthority>
      <ns1:Sole>10</ns1:Sole>
      <ns1:Shared>0</ns1:Shared>
      <ns1:None>0</ns1:None>
    </ns1:votingAuthority>
  </ns1:infoTable>
  <ns1:infoTable>
    <ns1:nameOfIssuer>FOREIGN ISSUER</ns1:nameOfIssuer>
    <ns1:titleOfClass>SHS</ns1:titleOfClass>
    <ns1:cusip>G11448100</ns1:cusip>
    <ns1:value>500</ns1:value>
    <ns1:shrsOrPrnAmt>
      <ns1:sshPrnamt>5</ns1:sshPrnamt>
      <ns1:sshPrnamtType>SH</ns1:sshPrnamtType>
    </ns1:shrsOrPrnAmt>
    <ns1:putCall>Call</ns1:putCall>
    <ns1:investmentDiscretion>SOLE</ns1:investmentDiscretion>
    <ns1:votingAuthority>
      <ns1:Sole>0</ns1:Sole>
      <ns1:Shared>0</ns1:Shared>
      <ns1:None>5</ns1:None>
    </ns1:votingAuthority>
  </ns1:infoTable>
</ns1:informationTable>
'''

NOTICE_COVER = f'''<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="{COVER_NS}">
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter>
      <filingManager>
        <name>NOTICE FILER LP</name>
      </filingManager>
      <reportType>13F NOTICE</reportType>
      <otherIncludedManagersCount>0</otherIncludedManagersCount>
    </coverPage>
  </formData>
</edgarSubmission>
'''

DUPLICATE_CUSIP_TABLE = f'''<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="{TABLE_NS}">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>100</value>
    <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>1</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>200</value>
    <shrsOrPrnAmt><sshPrnamt>2</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <otherManager>1</otherManager>
    <votingAuthority><Sole>0</Sole><Shared>2</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>
'''

LEADING_ZERO_CUSIP_TABLE = f'''<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="{TABLE_NS}">
  <infoTable>
    <nameOfIssuer>ZERO CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>000123456</cusip>
    <value>1</value>
    <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>1</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>
'''


def _ref(**kwargs) -> FilingRef:
    defaults = dict(
        fund_name="Test Fund LLC",
        cik="1423053",
        form_type="13F-HR",
        accession_dashed="0001423053-26-000001",
        report_date="2026-03-31",
        filing_date="2026-05-14",
    )
    defaults.update(kwargs)
    return FilingRef(**defaults)


def _combined(tmp: Path, cover: str, table: str | None, name: str = "filing.xml") -> Path:
    from curator.edgar import _write_combined_xml

    path = tmp / name
    _write_combined_xml(
        path,
        cover.encode("utf-8"),
        table.encode("utf-8") if table is not None else None,
    )
    return path


def test_cusip_leading_zeros_and_cins_never_int():
    assert normalize_cusip("000123456") == "000123456"
    assert normalize_cusip("G11448100") == "G11448100"
    assert normalize_cusip("37833100") == "037833100"  # 8-digit, pad
    assert isinstance(normalize_cusip("000123456"), str)
    assert not isinstance(normalize_cusip("000123456"), int)


def test_namespace_default_vs_prefixed_same_parse(tmp_path: Path):
    a = _combined(tmp_path, DEFAULT_NS_COVER, DEFAULT_NS_TABLE, "default.xml")
    b = _combined(tmp_path, PREFIXED_COVER, PREFIXED_TABLE, "prefixed.xml")
    ref = _ref()
    fa, ha = parse_filing(ref, a)
    fb, hb = parse_filing(ref, b)
    assert len(ha) == len(hb) == 2
    assert ha[0]["name_of_issuer"] == hb[0]["name_of_issuer"] == "APPLE INC"
    assert ha[0]["cusip"] == hb[0]["cusip"] == "037833100"
    assert ha[1]["put_call"] == hb[1]["put_call"] == "Call"
    assert ha[1]["voting_none"] == hb[1]["voting_none"] == 5
    assert fa["filing_manager"] == fb["filing_manager"] == "TEST FUND LLC"
    assert fa["table_entry_total"] == 2
    assert fa["is_amendment"] is False
    assert fa["amendment_no"] is None
    assert fa["amendment_type"] is None


def test_notice_filing_present_holdings_empty(tmp_path: Path):
    path = _combined(tmp_path, NOTICE_COVER, None)
    ref = _ref(form_type="13F-NT", accession_dashed="0001336528-26-000002",
               report_date="2026-06-30", filing_date="2026-08-14")
    filing, holdings = parse_filing(ref, path)
    assert filing["form_type"] == "13F-NT"
    assert filing["report_type"] == "13F NOTICE"
    assert filing["table_entry_total"] is None
    assert filing["table_value_total"] is None
    assert holdings == []


def test_no_cusip_collapse_order_preserved(tmp_path: Path):
    path = _combined(tmp_path, DEFAULT_NS_COVER, DUPLICATE_CUSIP_TABLE)
    _, holdings = parse_filing(_ref(), path)
    assert len(holdings) == 2
    assert holdings[0]["cusip"] == holdings[1]["cusip"] == "037833100"
    assert holdings[0]["value"] == 100
    assert holdings[1]["value"] == 200
    assert holdings[0]["investment_discretion"] == "SOLE"
    assert holdings[1]["investment_discretion"] == "DFND"


def test_leading_zero_cusip_survives_parquet(tmp_path: Path):
    xml = _combined(tmp_path, DEFAULT_NS_COVER, LEADING_ZERO_CUSIP_TABLE)
    filing, holdings = parse_filing(_ref(), xml)
    assert holdings[0]["cusip"] == "000123456"
    fpath, hpath = write_parquet(tmp_path / "out", [filing], holdings)
    import pyarrow.parquet as pq

    table = pq.read_table(hpath)
    assert table.schema.field("cusip").type.equals(__import__("pyarrow").string())
    assert table.column("cusip").to_pylist() == ["000123456"]
    assert table.schema.field("cik").type.equals(__import__("pyarrow").string())
    assert table.column("cik").to_pylist() == [pad_cik("1423053")]
    filings = pq.read_table(fpath)
    assert filings.schema.field("report_period").type.equals(__import__("pyarrow").date32())
    assert filings.column("report_period").to_pylist() == [date(2026, 3, 31)]


def test_amendment_fields_parsed_not_hardcoded(tmp_path: Path):
    cover = DEFAULT_NS_COVER.replace(
        "<isAmendment>false</isAmendment>",
        "<isAmendment>true</isAmendment><amendmentNo>1</amendmentNo>"
        "<amendmentType>RESTATEMENT</amendmentType>",
    )
    path = _combined(tmp_path, cover, DEFAULT_NS_TABLE)
    ref = _ref(form_type="13F-HR/A")
    filing, _ = parse_filing(ref, path)
    assert filing["is_amendment"] is True
    assert filing["amendment_no"] == 1
    assert filing["amendment_type"] == "RESTATEMENT"


def test_parquet_bytes_identical_across_writes(tmp_path: Path):
    xml = _combined(tmp_path, DEFAULT_NS_COVER, DEFAULT_NS_TABLE)
    filing, holdings = parse_filing(_ref(), xml)
    a = tmp_path / "a"
    b = tmp_path / "b"
    write_parquet(a, [filing], holdings)
    write_parquet(b, [filing], holdings)
    assert (a / "filings.parquet").read_bytes() == (b / "filings.parquet").read_bytes()
    assert (a / "holdings.parquet").read_bytes() == (b / "holdings.parquet").read_bytes()
