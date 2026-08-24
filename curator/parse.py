"""Namespace-safe 13F XML → filing and holding row dicts.

Match on namespace URI + local name (lxml `{*}`), never on a prefix string.
Do not dedupe or reorder information-table entries.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from lxml import etree

from curator.cik import pad_cik, unpad_cik
from curator.edgar import FilingRef

# Documented 13F namespaces. Empty namespace is also accepted — some filers
# omit it. Matching is by local name; these URIs are what we *expect*, not a
# prefix we search for.
NS_COVER = "http://www.sec.gov/edgar/thirteenfilings"
NS_TABLE = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

NOTICE_FORMS = frozenset({"13F-NT", "13F-NT/A"})


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def _findall(el: etree._Element, local: str) -> list[etree._Element]:
    return el.findall(f".//{{*}}{local}")


def _first(el: etree._Element | None, local: str) -> etree._Element | None:
    if el is None:
        return None
    found = el.find(f".//{{*}}{local}")
    return found


def _text(el: etree._Element | None) -> str | None:
    if el is None:
        return None
    # lxml decodes XML entities. Strip whitespace; empty means missing.
    value = "".join(el.itertext()).strip()
    return value if value else None


def _child_text(el: etree._Element | None, local: str) -> str | None:
    return _text(_first(el, local))


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "").replace("+", "")
    if cleaned == "":
        return None
    return int(float(cleaned)) if "." in cleaned else int(cleaned)


def parse_int_required(value: str | None, default: int = 0) -> int:
    n = parse_int(value)
    return default if n is None else n


def parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"true", "1", "y", "yes"}


def parse_cover_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def report_quarter_from_period(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}"


def normalize_cusip(raw: str | None) -> str:
    """Keep as a 9-character string. Leading zeros and letter-prefix CINS stay."""
    if raw is None:
        return ""
    s = re.sub(r"\s+", "", raw.strip().upper())
    if len(s) < 9 and s.isalnum():
        s = s.zfill(9)
    return s


def _load_tree(path: Path) -> etree._Element:
    parser = etree.XMLParser(recover=False, huge_tree=True, resolve_entities=False)
    return etree.parse(str(path), parser=parser).getroot()


def parse_filing(ref: FilingRef, xml_path: Path | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = xml_path or ref.output_xml
    if path is None:
        raise ValueError(f"no XML path for {ref.accession_dashed}")
    root = _load_tree(path)

    cover = _first(root, "coverPage")
    summary = _first(root, "summaryPage")
    header = _first(root, "headerData")

    filing_manager = _child_text(_first(cover, "filingManager"), "name")
    if not filing_manager:
        filing_manager = _child_text(_first(header, "filer"), "name") or ref.fund_name

    period = parse_cover_date(_child_text(cover, "reportCalendarOrQuarter"))
    if period is None:
        period = parse_cover_date(_child_text(header, "periodOfReport"))
    if period is None:
        period = datetime.strptime(ref.report_date, "%Y-%m-%d").date()

    filing_date = datetime.strptime(ref.filing_date, "%Y-%m-%d").date()

    is_amendment = ref.form_type.endswith("/A")
    cover_amendment = parse_bool(_child_text(cover, "isAmendment"))
    if cover_amendment is True:
        is_amendment = True

    amendment_no = parse_int(_child_text(cover, "amendmentNo"))
    amendment_type = _child_text(cover, "amendmentType")
    if not is_amendment:
        amendment_no = None
        amendment_type = None

    report_type = _child_text(cover, "reportType") or _report_type_fallback(ref.form_type)

    form_13f = _child_text(cover, "form13FFileNumber")
    crd = _child_text(cover, "crdNumber")
    sec_file = _child_text(cover, "secFileNumber")

    other_count = parse_int(_child_text(cover, "otherIncludedManagersCount"))
    if other_count is None and summary is not None:
        other_count = parse_int(_child_text(summary, "otherIncludedManagersCount"))

    is_notice = ref.form_type in NOTICE_FORMS or (
        report_type is not None and "NOTICE" in report_type.upper() and "HOLDINGS" not in report_type.upper()
    )

    entry_total = parse_int(_child_text(summary, "tableEntryTotal") if summary is not None else None)
    if entry_total is None:
        entry_total = parse_int(_child_text(cover, "tableEntryTotal"))
    value_total = parse_int(_child_text(summary, "tableValueTotal") if summary is not None else None)
    if value_total is None:
        value_total = parse_int(_child_text(cover, "tableValueTotal"))
    if is_notice:
        entry_total = None
        value_total = None

    filing_row: dict[str, Any] = {
        "accession_number": ref.accession_dashed,
        "cik": pad_cik(ref.cik),
        "fund_name": ref.fund_name,
        "filing_manager": filing_manager,
        "form_type": ref.form_type,
        "report_period": period,
        "report_quarter": report_quarter_from_period(period),
        "filing_date": filing_date,
        "is_amendment": bool(is_amendment),
        "amendment_no": amendment_no,
        "amendment_type": amendment_type,
        "report_type": report_type,
        "form_13f_file_number": form_13f,
        "crd_number": crd,
        "sec_file_number": sec_file,
        "other_included_managers_count": other_count,
        "table_entry_total": entry_total,
        "table_value_total": value_total,
    }

    holdings: list[dict[str, Any]] = []
    if is_notice:
        return filing_row, holdings

    for entry in _findall(root, "infoTable"):
        holdings.append(_parse_info_table(entry, ref, filing_row["report_quarter"]))
    return filing_row, holdings


def _report_type_fallback(form_type: str) -> str:
    if form_type.startswith("13F-NT"):
        return "13F NOTICE"
    if form_type.startswith("13F-HR"):
        return "13F HOLDINGS REPORT"
    return form_type


def _parse_info_table(entry: etree._Element, ref: FilingRef, report_quarter: str) -> dict[str, Any]:
    shrs = _first(entry, "shrsOrPrnAmt")
    voting = _first(entry, "votingAuthority")
    put_call = _child_text(entry, "putCall")
    # Absent element → null. Empty string → null. Do not invent "N/A".
    if put_call is not None:
        put_call = put_call.strip() or None

    other_manager = _child_text(entry, "otherManager")

    return {
        "accession_number": ref.accession_dashed,
        "cik": pad_cik(ref.cik),
        "report_quarter": report_quarter,
        "name_of_issuer": _child_text(entry, "nameOfIssuer") or "",
        "title_of_class": _child_text(entry, "titleOfClass") or "",
        "cusip": normalize_cusip(_child_text(entry, "cusip")),
        "figi": _child_text(entry, "figi"),
        "value": parse_int_required(_child_text(entry, "value")),
        "ssh_prnamt": parse_int_required(_child_text(shrs, "sshPrnamt") if shrs is not None else None),
        "ssh_prnamt_type": (_child_text(shrs, "sshPrnamtType") if shrs is not None else None) or "SH",
        "put_call": put_call,
        "investment_discretion": _child_text(entry, "investmentDiscretion") or "SOLE",
        "other_manager": other_manager,
        "voting_sole": parse_int_required(_child_text(voting, "Sole") if voting is not None else None),
        "voting_shared": parse_int_required(_child_text(voting, "Shared") if voting is not None else None),
        # Local name is `None` — a reserved word in Python. Match by local name.
        "voting_none": parse_int_required(_child_text(voting, "None") if voting is not None else None),
    }


def parse_all(
    refs: list[FilingRef],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filings: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    # Stable order: CIK then accession. Holdings follow information-table order
    # within each filing and are concatenated in that filing order.
    for ref in sorted(refs, key=lambda r: (int(unpad_cik(r.cik)), r.accession_dashed)):
        filing_row, holding_rows = parse_filing(ref)
        filings.append(filing_row)
        holdings.extend(holding_rows)
    return filings, holdings


def other_managers_from_cover(xml_path: Path) -> list[dict[str, str | None]]:
    """Cover-page other-manager list: sequence number, name, CIK.

    Used by Bonus 1. Sequence is what `other_manager` on an infoTable row points at.
    """
    root = _load_tree(xml_path)
    out: list[dict[str, str | None]] = []
    # Filers use otherManager, otherManager2, otherManagersInfo, ...
    for el in list(_findall(root, "otherManager")) + list(_findall(root, "otherManager2")):
        seq = _child_text(el, "sequenceNumber") or _child_text(el, "otherManagerSeq")
        name = _child_text(el, "name")
        cik = _child_text(el, "cik")
        file_no = _child_text(el, "form13FFileNumber")
        if name is None and cik is None and seq is None:
            continue
        # Skip nested filingManager-style name-only noise if it has no sequence
        # and lives under filingManager (the filer's own name).
        parent_locals = {_local(p) for p in el.iterancestors()}
        if "filingManager" in parent_locals and seq is None:
            continue
        out.append(
            {
                "sequence": seq,
                "name": name,
                "cik": unpad_cik(cik) if cik and re.search(r"\d", cik) else None,
                "form_13f_file_number": file_no,
            }
        )
    # Deterministic: by sequence then name.
    def _key(row: dict[str, str | None]) -> tuple[int, str]:
        try:
            seq_n = int(row["sequence"] or 10**9)
        except (TypeError, ValueError):
            seq_n = 10**9
        return (seq_n, row["name"] or "")

    out.sort(key=_key)
    # De-dupe identical (seq, cik, name) while preserving first occurrence.
    seen: set[tuple[str | None, str | None, str | None]] = set()
    unique: list[dict[str, str | None]] = []
    for row in out:
        key = (row["sequence"], row["cik"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def other_manager_tokens(raw: str | None) -> list[str]:
    """`other_manager` is a sequence reference; some filers list several, comma-separated."""
    if raw is None:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def token_matches_sequence(token: str, sequence: str) -> bool:
    a = token.strip()
    b = sequence.strip()
    if a == b:
        return True
    try:
        return int(a) == int(b)
    except ValueError:
        return False


def holding_includes_sequence(other_manager: str | None, sequence: str) -> bool:
    return any(token_matches_sequence(tok, sequence) for tok in other_manager_tokens(other_manager))


def sequenced_other_managers(xml_path: Path) -> list[dict[str, str | None]]:
    """summaryPage/otherManagers2Info entries that carry a sequence number.

    That sequence is what an information-table `other_manager` value points at.
    Cover-page otherManagersInfo (no sequence) is a name list, not the join key.
    """
    root = _load_tree(xml_path)
    out: list[dict[str, str | None]] = []
    for el in _findall(root, "otherManager2"):
        seq = _child_text(el, "sequenceNumber") or _child_text(el, "otherManagerSeq")
        if seq is None:
            continue
        inner = _first(el, "otherManager")
        name = _child_text(inner, "name") if inner is not None else _child_text(el, "name")
        cik = _child_text(inner, "cik") if inner is not None else _child_text(el, "cik")
        file_no = (
            _child_text(inner, "form13FFileNumber")
            if inner is not None
            else _child_text(el, "form13FFileNumber")
        )
        out.append(
            {
                "sequence": seq.strip(),
                "name": name,
                "cik": unpad_cik(cik) if cik and re.search(r"\d", cik) else None,
                "form_13f_file_number": file_no,
            }
        )
    out.sort(key=lambda row: (int(row["sequence"] or 10**9), row["name"] or ""))
    return out


def notice_parent_from_cover(xml_path: Path) -> dict[str, str | None] | None:
    """CIK named on a 13F-NT cover as the manager whose report includes these holdings.

    Nested under coverPage/otherManagersInfo — not the sequenced otherManager2 list.
    """
    root = _load_tree(xml_path)
    for el in _findall(root, "otherManager"):
        ancestors = {_local(p) for p in el.iterancestors()}
        if "filingManager" in ancestors or "otherManager2" in ancestors:
            continue
        cik = _child_text(el, "cik")
        if not cik or not re.search(r"\d", cik):
            continue
        return {
            "cik": unpad_cik(cik),
            "name": _child_text(el, "name"),
            "form_13f_file_number": _child_text(el, "form13FFileNumber"),
        }
    return None
