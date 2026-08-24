"""Bonus 2: check 2026 Q2 holdings CUSIPs against SEC's official 13F list.

The list is fixed-width 80-character lines. CUSIPs are nine characters at the
start of the line; a `*` in column 10 is a marker, not part of the identifier.
Older publications insert spaces (`037833 10 0`); we compact both sides before
comparing so a formatting mismatch is not reported as a filer error.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

from curator.constants import OFFICIAL_13F_LIST_Q2_2026
from curator.edgar import EdgarClient
from curator.parse import normalize_cusip

CUSIP_CHARS = re.compile(r"[^0-9A-Za-z]")
# 80-col layout: CUSIP(9) marker(1) issuer(30) description(32) status/tail(8)
OFFICIAL_LINE = re.compile(r"^([0-9A-Z]{9})([ *])(.{30})(.{32})")


def compact_cusip(raw: str | None) -> str:
    """Same 9-character identifier whether the list wrote `037833100` or `037833 10 0`."""
    if raw is None:
        return ""
    return normalize_cusip(CUSIP_CHARS.sub("", raw))


def parse_official_list_line(line: str) -> tuple[str, str, bool] | None:
    """Return (cusip, issuer, starred) or None if the line is not a security row."""
    line = line.rstrip("\n")
    if len(line) < 10:
        return None
    m = OFFICIAL_LINE.match(line)
    if m:
        return m.group(1), m.group(3).rstrip(), m.group(2) == "*"
    # Spaced historical layout: CUSIP pieces then issuer.
    compact = compact_cusip(line[:12])
    if len(compact) != 9:
        return None
    rest = line[12:].lstrip() if len(line) > 12 else ""
    issuer = rest[:30].rstrip() if rest else ""
    return compact, issuer, False


def parse_official_list(text: str) -> dict[str, str]:
    """Map CUSIP → issuer name. Prefer the starred (primary) row when several exist."""
    issuers: dict[str, str] = {}
    starred: set[str] = set()
    for line in text.splitlines():
        parsed = parse_official_list_line(line)
        if parsed is None:
            continue
        cusip, issuer, is_star = parsed
        if cusip not in issuers or (is_star and cusip not in starred):
            issuers[cusip] = issuer
        if is_star:
            starred.add(cusip)
    return issuers


def assess_unmatched(cusip: str) -> str:
    if not cusip or len(cusip) != 9:
        return "LIKELY_FILER_ERROR"
    if cusip[0].isalpha():
        return "CINS_FOREIGN"
    return "UNRESOLVED"


def run_cusip_validation(client: EdgarClient, output: Path) -> Path:
    dest = output / "bonus_cusip_validation.csv"
    text, hit = client.get_text(OFFICIAL_13F_LIST_Q2_2026)
    print(
        f"Bonus 2: official list ({'cache' if hit else 'download'}) {len(text)} bytes",
        file=sys.stderr,
    )
    official = parse_official_list(text)
    print(f"Bonus 2: {len(official)} CUSIPs on the Q2 2026 list", file=sys.stderr)

    holdings = pq.read_table(output / "holdings.parquet")
    filings = pq.read_table(output / "filings.parquet")
    filing_meta = {
        acc: {"cik": cik, "fund_name": name}
        for acc, cik, name in zip(
            filings.column("accession_number").to_pylist(),
            filings.column("cik").to_pylist(),
            filings.column("fund_name").to_pylist(),
        )
    }

    # (accession, cusip) → running tally. Dict insertion order is first-seen;
    # we sort before write.
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    quarters = holdings.column("report_quarter").to_pylist()
    accessions = holdings.column("accession_number").to_pylist()
    cusips = holdings.column("cusip").to_pylist()
    issuers = holdings.column("name_of_issuer").to_pylist()
    for i, quarter in enumerate(quarters):
        if quarter != "2026Q2":
            continue
        acc = accessions[i]
        cusip = compact_cusip(cusips[i])
        key = (acc, cusip)
        if key not in grouped:
            meta = filing_meta.get(acc, {"cik": "", "fund_name": ""})
            listed = official.get(cusip)
            on_list = listed is not None
            grouped[key] = {
                "accession_number": acc,
                "cik": meta["cik"],
                "fund_name": meta["fund_name"],
                "cusip": cusip,
                "on_official_list": on_list,
                "issuer_from_filing": issuers[i],
                "issuer_from_list": listed if on_list else None,
                "rows": 0,
                "assessment": None if on_list else assess_unmatched(cusip),
            }
        grouped[key]["rows"] = int(grouped[key]["rows"]) + 1

    rows = [grouped[k] for k in sorted(grouped)]
    matched = sum(1 for r in rows if r["on_official_list"])
    print(
        f"Bonus 2: {matched}/{len(rows)} (accession, CUSIP) pairs on the official list",
        file=sys.stderr,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "accession_number",
        "cik",
        "fund_name",
        "cusip",
        "on_official_list",
        "issuer_from_filing",
        "issuer_from_list",
        "rows",
        "assessment",
    ]
    with dest.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "accession_number": row["accession_number"],
                    "cik": row["cik"],
                    "fund_name": row["fund_name"],
                    "cusip": row["cusip"],
                    "on_official_list": "true" if row["on_official_list"] else "false",
                    "issuer_from_filing": row["issuer_from_filing"],
                    "issuer_from_list": row["issuer_from_list"] or "",
                    "rows": row["rows"],
                    "assessment": row["assessment"] or "",
                }
            )
    print(f"Bonus 2: wrote {len(rows)} rows → {dest}", file=sys.stderr)
    return dest
