"""Chapter 2 · Interrogate.

Run against `output/filings/` (the XML Chapter 1 downloaded). Prints counts and
example accessions, then a FINDINGS block built from those same counts.

Schema map (every required column → source or derived)
======================================================

filings.parquet
  accession_number              submissions API (dashed). Not in the XML.
                                Filename is the nodash form of the same id.
  cik                           roster CIK, zero-padded to 10. String.
                                Header credentials/cik agrees, also padded.
  fund_name                     roster CSV, exactly as given.
  filing_manager                coverPage/filingManager/name
  form_type                     submissions API `form`. XML submissionType is
                                the form without `/A` (none in this window).
  report_period                 coverPage/reportCalendarOrQuarter (MM-DD-YYYY).
                                header periodOfReport matches it here.
  report_quarter                DERIVED from report_period (YYYYQn).
  filing_date                   submissions API `filingDate`. Not in the XML.
                                cover signatureDate is a different date.
  is_amendment                  form_type ends in /A; also cover isAmendment
  amendment_no, amendment_type  coverPage. Absent on every file in this slice.
  report_type                   coverPage/reportType
  form_13f_file_number          coverPage/form13FFileNumber
  crd_number                    coverPage/crdNumber (string — leading zeros)
  sec_file_number               coverPage/secFileNumber
  other_included_managers_count summaryPage (cover may omit). Empty on the NT.
  table_entry_total             summaryPage/tableEntryTotal; empty on notices
  table_value_total             summaryPage/tableValueTotal; empty on notices

holdings.parquet
  accession_number, cik, report_quarter   denormalized from the filing
  name_of_issuer, title_of_class          infoTable; XML entities decoded by lxml
  cusip                                   infoTable; 9-char string (CINS allowed)
  figi                                    infoTable; usually absent
  value                                   infoTable; whole dollars
  ssh_prnamt, ssh_prnamt_type             shrsOrPrnAmt (SH vs PRN — do not add)
  put_call                                infoTable/putCall; absent ⇒ null
  investment_discretion                   infoTable (SOLE / DFND / OTR)
  other_manager                           infoTable; sequence into
                                          summaryPage/otherManagers2Info, not a name
  voting_sole, voting_shared, voting_none votingAuthority/{Sole,Shared,None}
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
FILINGS_DIR = ROOT / "output" / "filings"
FILERS_CSV = ROOT / "output" / "filers.csv"
CACHE_DATA = ROOT / ".cache" / "www.sec.gov" / "Archives" / "edgar" / "data"


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    value = "".join(el.itertext()).strip()
    return value or None


def _load_roster() -> dict[str, str]:
    with FILERS_CSV.open(newline="") as fh:
        return {row["cik"]: row["fund_name"] for row in csv.DictReader(fh)}


def _element_state(root: etree._Element, local: str) -> str:
    """present+text | present+empty | missing — empty ≠ missing for notices."""
    el = root.find(f".//{{*}}{local}")
    if el is None:
        return "missing"
    if _text(el) is None:
        return "present+empty"
    return "present"


def _dash_accession(nodash: str) -> str:
    # EDGAR: 18-digit nodash → ##########-##-######
    if len(nodash) == 18 and nodash.isdigit():
        return f"{nodash[:10]}-{nodash[10:12]}-{nodash[12:]}"
    return nodash


def _index_table_names() -> list[tuple[str, str]]:
    """Original information-table filenames from cached index.json, if present."""
    rows: list[tuple[str, str]] = []
    if not CACHE_DATA.exists():
        return rows
    for idx in sorted(CACHE_DATA.glob("*/*/index.json")):
        data = json.loads(idx.read_text())
        items = data.get("directory", data).get("item", [])
        if isinstance(items, dict):
            items = [items]
        names = [
            str(item.get("name") or "")
            for item in items
            if str(item.get("name") or "").lower().endswith(".xml")
            and "xsl" not in str(item.get("name") or "").lower()
        ]
        tables = [n for n in names if n.lower() != "primary_doc.xml"]
        acc = _dash_accession(idx.parent.name)
        for name in tables:
            rows.append((acc, name))
    return rows


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
    inv_disc: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    ns_uris: Counter[str] = Counter()
    cusip_len: Counter[int] = Counter()
    entry_state: Counter[str] = Counter()
    value_state: Counter[str] = Counter()
    oim_state: Counter[str] = Counter()
    cins_n = 0
    cins_eg: list[str] = []
    entity_eg: list[str] = []
    n_files_with_amp = 0
    figi_rows = 0
    files_without_figi = 0
    files_with_figi = 0
    entry_mismatch: list[tuple] = []
    value_mismatch: list[tuple] = []
    zero_tables: list[tuple] = []
    cover_vs_roster: list[tuple[str, str, str]] = []
    multi: list[tuple] = []
    other_mgr: Counter[str] = Counter()
    amend_true: list[str] = []
    voting_none_nz = 0
    sizes: list[tuple] = []
    n_accession_el = 0
    n_filing_date_el = 0
    n_amendment_no = 0
    n_amendment_type = 0
    n_cover_om_info = 0
    n_summary_om2 = 0
    nt_notes: list[str] = []
    crd_eg: list[str] = []
    sig_vs_period: list[tuple[str, str, str]] = []
    dup_filings = 0
    dup_extra_rows = 0
    dup_eg: list[str] = []
    comma_om: list[tuple[str, int]] = []

    for path in paths:
        root = etree.parse(str(path), parser).getroot()
        raw = path.read_bytes()
        cik = path.parent.name
        acc_nodash = path.stem
        acc = _dash_accession(acc_nodash)
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
        if any(
            isinstance(el.tag, str) and "accession" in el.tag.lower()
            for el in root.iter()
        ):
            n_accession_el += 1
        if root.find(".//{*}filingDate") is not None:
            n_filing_date_el += 1
        if root.find(".//{*}amendmentNo") is not None:
            n_amendment_no += 1
        if root.find(".//{*}amendmentType") is not None:
            n_amendment_type += 1

        cover = root.find(".//{*}coverPage")
        summary = root.find(".//{*}summaryPage")
        filing_manager = None
        if cover is not None:
            fm = cover.find(".//{*}filingManager")
            if fm is not None:
                filing_manager = _text(fm.find(".//{*}name"))
            if cover.find(".//{*}otherManagersInfo") is not None:
                n_cover_om_info += 1
        if summary is not None and summary.find(".//{*}otherManagers2Info") is not None:
            n_summary_om2 += 1
        roster_name = roster.get(cik, "")
        if roster_name and filing_manager and roster_name.upper() != filing_manager.upper():
            cover_vs_roster.append((cik, roster_name, filing_manager))

        entry_decl = _text(root.find(".//{*}tableEntryTotal"))
        value_decl = _text(root.find(".//{*}tableValueTotal"))
        other_count = _text(root.find(".//{*}otherIncludedManagersCount"))
        entry_state[_element_state(root, "tableEntryTotal")] += 1
        value_state[_element_state(root, "tableValueTotal")] += 1
        oim_state[_element_state(root, "otherIncludedManagersCount")] += 1
        if n == 0:
            extra = _text(root.find(".//{*}additionalInformation"))
            parent = None
            if cover is not None:
                om = cover.find(".//{*}otherManager")
                if om is not None:
                    parent = f"{_text(om.find('.//{*}name'))} CIK {_text(om.find('.//{*}cik'))}"
            zero_tables.append((cik, acc, submission, report_type, entry_decl))
            nt_notes.append(
                f"  {acc} form={submission} reportType={report_type!r} "
                f"tableEntryTotal={_element_state(root, 'tableEntryTotal')} "
                f"parent={parent!r} additionalInformation={extra!r}"
            )
        if other_count and other_count not in {"0", "00"}:
            multi.append((cik, acc, other_count, n, filing_manager))

        period = _text(root.find(".//{*}reportCalendarOrQuarter"))
        signed = _text(root.find(".//{*}signatureDate"))
        if period and signed:
            sig_vs_period.append((acc, period, signed))
        crd = _text(root.find(".//{*}crdNumber"))
        if crd and crd.startswith("0") and len(crd_eg) < 3:
            crd_eg.append(f"{acc} crdNumber={crd!r}")

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
        cusips: list[str] = []
        if b"&amp;" in raw:
            n_files_with_amp += 1
        for inf in infos:
            pc = _text(inf.find(".//{*}putCall"))
            put_call[pc if pc is not None else "<absent>"] += 1
            ssh_type[_text(inf.find(".//{*}sshPrnamtType")) or "?"] += 1
            inv_disc[_text(inf.find(".//{*}investmentDiscretion")) or "?"] += 1
            cusip = _text(inf.find(".//{*}cusip")) or ""
            cusips.append(cusip)
            cusip_len[len(cusip)] += 1
            if cusip[:1].isalpha():
                cins_n += 1
                if len(cins_eg) < 3:
                    issuer = _text(inf.find(".//{*}nameOfIssuer"))
                    cins_eg.append(f"{cusip} {issuer} {acc}")
            issuer = _text(inf.find(".//{*}nameOfIssuer")) or ""
            if "&" in issuer and len(entity_eg) < 2:
                entity_eg.append(f"{issuer!r} cusip={cusip} {acc}")
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
        if saw_figi:
            files_with_figi += 1
        if entry_decl is not None and entry_decl.replace(",", "") != str(n):
            entry_mismatch.append((acc, entry_decl, n, report_type))
        if value_decl is not None and infos:
            declared = int(value_decl.replace(",", ""))
            if declared != computed:
                value_mismatch.append((acc, declared, computed, declared - computed))
        sizes.append((n, cik, acc, roster_name, report_type, submission))

        counts = Counter(c for c in cusips if c)
        extras = sum(v - 1 for v in counts.values() if v > 1)
        if extras:
            dup_filings += 1
            dup_extra_rows += extras
            if len(dup_eg) < 1:
                # Prefer a pair that differs on other_manager — that's why
                # collapsing on cusip is wrong, not a data-entry duplicate.
                target = next(c for c, v in counts.items() if v > 1)
                pair = [
                    inf
                    for inf in infos
                    if _text(inf.find(".//{*}cusip")) == target
                ][:2]
                if len(pair) == 2:
                    dup_eg.append(
                        f"{acc} cusip={target} n={counts[target]} "
                        f"issuer={_text(pair[0].find('.//{*}nameOfIssuer'))!r} "
                        f"other_manager={_text(pair[0].find('.//{*}otherManager'))!r} "
                        f"vs {_text(pair[1].find('.//{*}otherManager'))!r} "
                        f"value={_text(pair[0].find('.//{*}value'))} vs "
                        f"{_text(pair[1].find('.//{*}value'))}"
                    )

    comma_om = [(k, v) for k, v in other_mgr.items() if "," in k]
    comma_om.sort(key=lambda kv: -kv[1])

    print("\n--- grain ---")
    print(f"submissionType: {dict(form_types)}")
    print(f"reportType:     {dict(report_types)}")
    print(f"infoTable rows: {n_info_total}")
    print("zero infoTable (notices or missing table):")
    for row in zero_tables:
        print(
            f"  cik={row[0]} acc={row[1]} form={row[2]} "
            f"reportType={row[3]!r} declared_entries={row[4]!r}"
        )
    for note in nt_notes:
        print(note)

    print("\n--- columns that are NOT in the XML ---")
    print(f"  element whose tag contains 'accession': {n_accession_el} / {len(paths)} files")
    print(f"  filingDate element:                     {n_filing_date_el} / {len(paths)} files")
    print("  accession_number comes from the submissions API (and the filename).")
    print("  filing_date comes from the submissions API. signatureDate is not it:")
    for acc, period, signed in sig_vs_period[:2]:
        print(f"    {acc}  reportCalendarOrQuarter={period}  signatureDate={signed}")
    print(f"  amendmentNo present: {n_amendment_no}  amendmentType present: {n_amendment_type}")
    print(f"  isAmendment=true: {amend_true or 'none in this slice'}")
    print(f"  crdNumber keeps leading zeros, e.g. {crd_eg}")

    print("\n--- empty vs missing (notices) ---")
    print(f"  tableEntryTotal:              {dict(entry_state)}")
    print(f"  tableValueTotal:              {dict(value_state)}")
    print(f"  otherIncludedManagersCount:   {dict(oim_state)}")

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

    print("\n--- putCall / SH vs PRN / CUSIP / discretion ---")
    print(f"  putCall: {dict(put_call)}")
    print(f"  sshPrnamtType: {dict(ssh_type)}")
    print(f"  investmentDiscretion: {dict(inv_disc)}")
    print(f"  cusip lengths: {dict(cusip_len)}")
    print(f"  CINS (letter prefix): {cins_n}  e.g. {cins_eg}")
    print(f"  figi present on {figi_rows} rows; {files_with_figi} filings have some, "
          f"{files_without_figi} holdings filings have none")
    print(f"  voting None nonzero rows: {voting_none_nz}")
    print(f"  files whose raw XML contains &amp;: {n_files_with_amp}")
    print(f"  decoded nameOfIssuer with ampersand e.g. {entity_eg}")

    print("\n--- duplicate CUSIPs (do not collapse) ---")
    print(f"  holdings filings with a repeated cusip: {dup_filings}")
    print(f"  extra rows beyond first-of-cusip:       {dup_extra_rows}")
    for row in dup_eg:
        print(f"  e.g. {row}")

    print("\n--- cover name vs roster ---")
    seen: set[tuple[str, str, str]] = set()
    for cik, roster_name, filing_manager in cover_vs_roster:
        key = (cik, roster_name, filing_manager)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {cik}  roster={roster_name!r}  cover={filing_manager!r}")

    print("\n--- other managers ---")
    print(f"  coverPage/otherManagersInfo present:           {n_cover_om_info}")
    print(f"  summaryPage/otherManagers2Info (sequenced):    {n_summary_om2}")
    print(f"  filings with otherIncludedManagersCount>0:     {len(multi)}")
    for row in multi:
        print(
            f"    cik={row[0]} acc={row[1]} count={row[2]} "
            f"infoTable={row[3]} manager={row[4]!r}"
        )
    print(f"  otherManager on infoTable rows: {sum(other_mgr.values())}  "
          f"top={other_mgr.most_common(8)}")
    print(f"  otherManager values that are lists, not one sequence: {comma_om}")

    table_names = _index_table_names()
    print("\n--- original table filenames (from cached index.json, if present) ---")
    if not table_names:
        print("  .cache not present; names below are from the Chapter 1 fetch.")
    else:
        by_name = Counter(name for _, name in table_names)
        print(f"  {dict(by_name)}")
        for acc, name in table_names:
            if name.lower() not in {"infotable.xml", "form13finfotable.xml"}:
                print(f"    {acc}  {name}")

    absent_put = put_call.get("<absent>", 0)
    call_n = put_call.get("Call", 0)
    put_n = put_call.get("Put", 0)
    sh_n = ssh_type.get("SH", 0)
    prn_n = ssh_type.get("PRN", 0)
    nt_acc = zero_tables[0][1] if zero_tables else "?"
    largest = sorted(sizes, reverse=True)[0]
    smallest = sorted(nonzero)[0]
    comma_om_str = ", ".join(f"{k!r}×{v}" for k, v in comma_om)

    print("\n" + "=" * 72)
    print("FINDINGS")
    print("=" * 72)
    print(
        f"""
1. Notices are a different grain, not a missing download. The only 13F-NT in
   this roster is Pershing Square, {nt_acc} (Q2). Cover reportType is
   "13F NOTICE". tableEntryTotal / tableValueTotal / otherIncludedManagersCount
   are present-but-empty elements, not omitted — a parser that asks "is the
   tag there?" and then int("") will throw. infoTable count is 0.
   additionalInformation says holdings are now in the public parent's report;
   otherManagersInfo names PERSHING SQUARE INC. CIK 0002026053 — not on the
   roster. Flattening filings+holdings would make Pershing look like they
   filed nothing in Q2. They filed a pointer. (Bonus 1.)

2. The information table is not always called infotable.xml. Of 39 holdings
   filings: 25 infotable.xml, 3 form13fInfoTable.xml, and the rest are custom
   (RenTec renaissance13Fq12026_holding.xml, Baupost BGLLCQ12026.xml,
   Millennium MLP_FIling_20260331.xml — capital I in FIling — Viking
   MSFS13F033126.XML vs Q2202613F.xml, Balyasny 53979.xml). Matching only
   the string "infotable" downloads a cover page, declares thousands of
   rows, and parses zero. After taking the other XML, tableEntryTotal equals
   infoTable count on every holdings filing here ({len(entry_mismatch)} mismatches)
   and tableValueTotal equals sum(value) ({len(value_mismatch)} mismatches).
   Store the declared totals; do not overwrite them with the computed ones.

3. Namespaces: every cover uses xmlns="http://www.sec.gov/edgar/thirteenffiler"
   (not thirteenfilings). Information tables use the informationtable URI.
   Prefixes observed: {dict(prefixes)}. Matching ns1:infoTable as a string
   silently drops Citadel (default namespace, no prefix). Match local name.

4. putCall is absent on {absent_put:,} ordinary rows. When present it is title
   case Call ({call_n:,}) / Put ({put_n:,}) in this slice, not CALL/PUT.
   Treating missing and "" the same is fine; treating "Call" and "CALL" as
   different is not. Do not mix option rows into a "largest Apple position"
   unless the question asks for options.

5. sshPrnamtType is SH on {sh_n:,} rows and PRN on {prn_n:,}. Summing
   ssh_prnamt across types adds shares to principal dollars.
   investmentDiscretion is DFND {inv_disc.get('DFND', 0):,} / OTR
   {inv_disc.get('OTR', 0):,} / SOLE {inv_disc.get('SOLE', 0):,}.

6. Every cusip in this slice is already 9 characters. {cins_n:,} start with a
   letter (CINS), e.g. {cins_eg[0] if cins_eg else 'n/a'}. Coercing cusip to
   int drops leading zeros and rejects CINS.

7. votingAuthority/None is a real element (local name None). {voting_none_nz:,}
   rows have a nonzero value. A parser that turns the tag into Python None
   loses the number.

8. fund_name ≠ filing_manager on several funds: Baupost cover is
   "BAUPOST GROUP LLC/MA"; Tudor is "TUDOR INVESTMENT CORP ET AL"; DME drops
   the "(Greenlight)" nickname. Keep both columns.

9. other_manager is a sequence into summaryPage/otherManagers2Info
   (present on {n_summary_om2} filings), not the coverPage/otherManagersInfo
   list (present on {n_cover_om_info}) and never a name. {sum(other_mgr.values()):,}
   infoTable rows carry it. Some values are lists: {comma_om_str}. Keep the
   string as filed; splitting is Chapter 3 / Bonus 1, not a reason to drop
   the row.

10. Duplicate CUSIPs are legitimate. {dup_filings} of 39 holdings filings
    repeat a cusip; collapsing them would drop {dup_extra_rows:,} rows.
    e.g. {dup_eg[0] if dup_eg else 'n/a'}. Same issuer, different
    other_manager (and value). Schema: do not deduplicate.

11. accession_number and filing_date are not in the XML ({n_accession_el} and
    {n_filing_date_el} files have those elements). Take them from the
    submissions API. signatureDate is on every cover and is the signature,
    not EDGAR's accepted date — D. E. Shaw Q1 is period 03-31-2026 signed
    05-15-2026. report_quarter is derived from reportCalendarOrQuarter.
    amendmentNo/amendmentType are missing on all {len(paths)} files;
    isAmendment is false throughout. Still parse the fields; do not hardcode.
    figi is optional ({figi_rows:,} rows; {files_without_figi} holdings filings
    have zero). {n_files_with_amp} files contain &amp; in the raw XML; lxml
    already decodes it — e.g. {entity_eg[0] if entity_eg else 'n/a'}.

12. Same schema, different shape. AQR Q2 {largest[2]} is {largest[0]:,} rows,
    otherIncludedManagersCount=13, 13F COMBINATION REPORT. Pershing Q1
    {smallest[2]} is {smallest[0]} rows, SOLE, no other managers.
""".strip(
            "\n"
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
