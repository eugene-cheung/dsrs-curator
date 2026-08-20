"""Chapter 2 · Interrogate.

Run against `output/filings/` (the XML Chapter 1 downloaded). Prints counts and
example accessions, then a FINDINGS block.

Schema map (every required column → source or derived)
======================================================

filings.parquet
  accession_number              submissions API (dashed). Never constructed.
  cik                           roster CIK, zero-padded to 10. String.
  fund_name                     roster CSV, exactly as given.
  filing_manager                coverPage/filingManager/name
  form_type                     submissions API `form`
  report_period                 coverPage/reportCalendarOrQuarter (MM-DD-YYYY)
  report_quarter                DERIVED from report_period
  filing_date                   submissions API `filingDate` (accepted date)
  is_amendment                  form_type ends in /A; also read cover isAmendment
  amendment_no, amendment_type  coverPage (null on originals)
  report_type                   coverPage/reportType
  form_13f_file_number          coverPage/form13FFileNumber
  crd_number                    coverPage/crdNumber (string — leading zeros)
  sec_file_number               coverPage/secFileNumber
  other_included_managers_count coverPage (summaryPage repeats it)
  table_entry_total             summaryPage/tableEntryTotal; null on notices
  table_value_total             summaryPage/tableValueTotal; null on notices

holdings.parquet
  accession_number, cik, report_quarter   denormalized from the filing
  name_of_issuer, title_of_class          infoTable; XML entities decoded by lxml
  cusip                                   infoTable; 9-char string (CINS allowed)
  figi                                    infoTable; usually absent
  value                                   infoTable; whole dollars
  ssh_prnamt, ssh_prnamt_type             shrsOrPrnAmt (SH vs PRN — do not add)
  put_call                                infoTable/putCall; absent ⇒ null
  investment_discretion                   infoTable
  other_manager                           infoTable; a sequence, not a name
  voting_sole, voting_shared, voting_none votingAuthority/{Sole,Shared,None}

The cover namespace in this slice is `http://www.sec.gov/edgar/thirteenffiler`
(not the older `thirteenfilings` URI). Match on local name.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
FILINGS_DIR = ROOT / "output" / "filings"
FILERS_CSV = ROOT / "output" / "filers.csv"


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    value = "".join(el.itertext()).strip()
    return value or None


def _load_roster() -> dict[str, str]:
    with FILERS_CSV.open(newline="") as fh:
        return {row["cik"]: row["fund_name"] for row in csv.DictReader(fh)}


def main() -> int:
    if not FILINGS_DIR.exists():
        print(f"missing {FILINGS_DIR}", file=sys.stderr)
        return 1
    paths = sorted(FILINGS_DIR.glob("*/*.xml"))
    print(f"files: {len(paths)} under {FILINGS_DIR}")
    roster = _load_roster()
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False)

    n_info_total = 0
    form_types: Counter[str] = Counter()
    report_types: Counter[str] = Counter()
    put_call: Counter[str] = Counter()
    ssh_type: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    ns_uris: Counter[str] = Counter()
    cusip_len: Counter[int] = Counter()
    cins_n = 0
    cins_eg: list[str] = []
    figi_rows = 0
    files_without_figi = 0
    entry_mismatch: list[tuple] = []
    value_mismatch: list[tuple] = []
    zero_tables: list[tuple] = []
    cover_vs_roster: list[tuple[str, str, str]] = []
    multi: list[tuple] = []
    other_mgr: Counter[str] = Counter()
    amend_true: list[str] = []
    voting_none_nz = 0
    sizes: list[tuple] = []
    custom_table_names: list[str] = []

    for path in paths:
        root = etree.parse(str(path), parser).getroot()
        cik = path.parent.name
        acc = path.stem
        infos = root.findall(".//{*}infoTable")
        n = len(infos)
        n_info_total += n
        report_type = _text(root.find(".//{*}reportType"))
        submission = _text(root.find(".//{*}submissionType"))
        form_types[submission or "?"] += 1
        report_types[report_type or "?"] += 1
        is_amendment = _text(root.find(".//{*}isAmendment"))
        if is_amendment and is_amendment.lower() == "true":
            amend_true.append(acc)

        cover = root.find(".//{*}coverPage")
        filing_manager = None
        if cover is not None:
            fm = cover.find(".//{*}filingManager")
            if fm is not None:
                filing_manager = _text(fm.find(".//{*}name"))
        roster_name = roster.get(cik, "")
        if roster_name and filing_manager and roster_name.upper() != filing_manager.upper():
            cover_vs_roster.append((cik, roster_name, filing_manager))

        entry_decl = _text(root.find(".//{*}tableEntryTotal"))
        value_decl = _text(root.find(".//{*}tableValueTotal"))
        other_count = _text(root.find(".//{*}otherIncludedManagersCount"))
        if n == 0:
            zero_tables.append((cik, acc, submission, report_type, entry_decl))
        if other_count and other_count not in {"0", "00"}:
            multi.append((cik, acc, other_count, n, filing_manager))

        uris: set[str] = set()
        prefs: set[str] = set()
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            q = etree.QName(el)
            uris.add(q.namespace or "")
            if el.prefix:
                prefs.add(el.prefix)
        for u in uris:
            ns_uris[u or "(none)"] += 1
        for p in prefs:
            prefixes[p] += 1

        computed = 0
        saw_figi = False
        for inf in infos:
            pc = _text(inf.find(".//{*}putCall"))
            put_call[pc if pc is not None else "<absent>"] += 1
            ssh_type[_text(inf.find(".//{*}sshPrnamtType")) or "?"] += 1
            cusip = _text(inf.find(".//{*}cusip")) or ""
            cusip_len[len(cusip)] += 1
            if cusip[:1].isalpha():
                cins_n += 1
                if len(cins_eg) < 3:
                    issuer = _text(inf.find(".//{*}nameOfIssuer"))
                    cins_eg.append(f"{cusip} {issuer} {acc}")
            if _text(inf.find(".//{*}figi")):
                figi_rows += 1
                saw_figi = True
            om = _text(inf.find(".//{*}otherManager"))
            if om is not None:
                other_mgr[om] += 1
            val = _text(inf.find(".//{*}value"))
            if val:
                computed += int(val.replace(",", ""))
            none_v = _text(inf.find(".//{*}None"))
            if none_v and none_v not in {"0"}:
                voting_none_nz += 1

        if infos and not saw_figi:
            files_without_figi += 1
        if entry_decl is not None and entry_decl.replace(",", "") != str(n):
            entry_mismatch.append((acc, entry_decl, n, report_type))
        if value_decl is not None and infos:
            declared = int(value_decl.replace(",", ""))
            if declared != computed:
                value_mismatch.append((acc, declared, computed, declared - computed))
        sizes.append((n, cik, acc, roster_name, report_type, submission))

    print("\n--- grain ---")
    print(f"submissionType: {dict(form_types)}")
    print(f"reportType:     {dict(report_types)}")
    print(f"infoTable rows: {n_info_total}")
    print("zero infoTable (notices or missing table):")
    for row in zero_tables:
        print(f"  cik={row[0]} acc={row[1]} form={row[2]} reportType={row[3]!r} declared_entries={row[4]!r}")

    print("\n--- size ---")
    for row in sorted(sizes, reverse=True)[:3]:
        print(f"  largest  {row[0]:6d}  {row[3]}  {row[2]}  {row[4]}")
    nonzero = [s for s in sizes if s[0] > 0]
    for row in sorted(nonzero)[:3]:
        print(f"  smallest {row[0]:6d}  {row[3]}  {row[2]}  {row[4]}")

    print("\n--- namespaces (file counts) ---")
    print(f"  prefixes: {dict(prefixes)}")
    for uri, n in ns_uris.most_common():
        print(f"  {n:3d}  {uri}")

    print("\n--- declared vs computed ---")
    print(f"  tableEntryTotal ≠ infoTable count: {len(entry_mismatch)}")
    for row in entry_mismatch[:5]:
        print(f"    {row}")
    print(f"  tableValueTotal ≠ sum(value):      {len(value_mismatch)}")
    for row in value_mismatch[:5]:
        print(f"    {row}")

    print("\n--- putCall / SH vs PRN / CUSIP ---")
    print(f"  putCall: {dict(put_call)}")
    print(f"  sshPrnamtType: {dict(ssh_type)}")
    print(f"  cusip lengths: {dict(cusip_len)}")
    print(f"  CINS (letter prefix): {cins_n}  e.g. {cins_eg}")
    print(f"  figi present on {figi_rows} rows; {files_without_figi} holdings filings have none")
    print(f"  voting None nonzero rows: {voting_none_nz}")
    print(f"  isAmendment=true: {amend_true or 'none in this slice'}")

    print("\n--- cover name vs roster ---")
    seen: set[tuple[str, str, str]] = set()
    for cik, roster_name, filing_manager in cover_vs_roster:
        key = (cik, roster_name, filing_manager)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {cik}  roster={roster_name!r}  cover={filing_manager!r}")

    print("\n--- other managers ---")
    print(f"  filings with otherIncludedManagersCount>0: {len(multi)}")
    for row in multi:
        print(f"    cik={row[0]} acc={row[1]} count={row[2]} infoTable={row[3]} manager={row[4]!r}")
    print(f"  otherManager on infoTable rows: {sum(other_mgr.values())}  top={other_mgr.most_common(8)}")

    print("\n" + "=" * 72)
    print("FINDINGS")
    print("=" * 72)
    print(
        """
1. Notices are a different grain, not a missing download. The only 13F-NT in
   this roster is Pershing Square, accession 0001172661-26-003777 (Q2). Cover
   reportType is "13F NOTICE", tableEntryTotal is absent, infoTable count is 0.
   additionalInformation says holdings are now in the public parent's report;
   otherManagersInfo names PERSHING SQUARE INC. CIK 0002026053 — not on the
   roster. Flattening filings+holdings would make Pershing look like they
   filed nothing in Q2. They filed a pointer. (Bonus 1.)

2. The information table is not always called infotable.xml. RenTec ships
   renaissance13Fq12026_holding.xml; Baupost BGLLCQ12026.xml; Millennium
   MLP_FIling_20260331.xml. Matching only the string "infotable" downloads a
   cover page, declares thousands of rows, and parses zero. Pick the other
   XML in the accession directory (the large one). After that, tableEntryTotal
   equals infoTable count on every holdings filing in this slice — 0 mismatches
   — so the declared count is a useful check, not an override.

3. Namespaces: every cover uses xmlns="http://www.sec.gov/edgar/thirteenffiler"
   (not thirteenfilings). Information tables use the informationtable URI.
   Prefixes observed: ns1 (most tables), n1 (2 files), default/no prefix
   (Citadel), plus com/common on addresses. Matching ns1:infoTable as a string
   silently drops Citadel. Match local name.

4. putCall is absent on 103,603 ordinary rows. When present it is title case
   Call/Put in this slice, not CALL/PUT. Treating "" and missing the same is
   fine; treating "Call" and "CALL" as different is not. Do not mix option
   rows into a "largest Apple position" unless the question asks for options.

5. sshPrnamtType is SH on 133,509 rows and PRN on 1,126. Summing ssh_prnamt
   across types adds shares to principal dollars.

6. Every cusip in this slice is already 9 characters. 11,137 start with a
   letter (CINS), e.g. G1151C101 Accenture on D. E. Shaw 0001104659-26-062472.
   Coercing cusip to int drops leading zeros *and* rejects CINS.

7. votingAuthority/None is a real element (local name None). 13,625 rows have
   a nonzero value. A parser that turns the tag into Python None loses the
   number.

8. fund_name ≠ filing_manager on several funds: Baupost cover is
   "BAUPOST GROUP LLC/MA"; Tudor is "TUDOR INVESTMENT CORP ET AL"; DME drops
   the "(Greenlight)" nickname. Keep both columns. other_manager is a
   sequence number into the cover list (and sometimes "2,1"), never a name.

9. AQR Q2 0001167557-26-000226 is the huge multi-manager filing: 21,077
   infoTable rows, otherIncludedManagersCount=13, reportType 13F COMBINATION
   REPORT. Pershing Q1 0001172661-26-002336 is the small concentrated book:
   11 rows, SOLE, no other managers. Same schema, different shape.

10. figi is optional and mostly missing (present on 54,487 rows; 32 of 39
    holdings filings have zero FIGIs). Amendments: isAmendment is false on
    every cover in this window — still parse the fields; do not hardcode.
    tableValueTotal matched sum(value) on every holdings filing here; still
    store the declared total separately from the computed one.
""".strip(
        "\n"
    )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
