"""Bonus 1: recover a notice-filer's holdings from the parent's information table.

A 13F-NT does not link to the parent accession. The cover names the parent CIK;
we then take that CIK's in-scope 13F-HR for the same report period.

Rows whose `other_manager` list includes the notice filer's sequence belong to
that manager (possibly jointly). Rows with no sequence, or a list that omits
them, are the parent's book or another affiliate — not what the researcher asked
for.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from curator.cik import pad_cik, unpad_cik
from curator.edgar import EdgarClient, FilingRef, discover_cik_filings, download_filing_documents
from curator.parse import (
    NOTICE_FORMS,
    holding_includes_sequence,
    notice_parent_from_cover,
    parse_filing,
    sequenced_other_managers,
)
from curator.write import write_attributed_parquet


def _notice_refs(refs: list[FilingRef]) -> list[FilingRef]:
    return [r for r in refs if r.form_type in NOTICE_FORMS]


def _match_sequence(
    managers: list[dict[str, str | None]],
    notice_cik: str,
    notice_file_no: str | None,
) -> str | None:
    want = unpad_cik(notice_cik)
    file_no = (notice_file_no or "").strip() or None
    for row in managers:
        if row.get("cik") and unpad_cik(row["cik"]) == want:
            return row.get("sequence")
    if file_no:
        for row in managers:
            theirs = (row.get("form_13f_file_number") or "").strip()
            if theirs and theirs == file_no:
                return row.get("sequence")
    return None


def _pick_parent_hr(candidates: list[FilingRef], report_date: str) -> FilingRef | None:
    hrs = [
        r
        for r in candidates
        if r.report_date == report_date and r.form_type.startswith("13F-HR")
    ]
    if not hrs:
        return None
    hrs.sort(key=lambda r: (r.filing_date, r.accession_dashed))
    return hrs[-1]


def attribute_rows(
    holdings: list[dict[str, Any]],
    sequence: str,
    attributed_to_cik: str,
) -> list[dict[str, Any]]:
    """Keep information-table order. Do not include the parent's untagged book."""
    out: list[dict[str, Any]] = []
    for row in holdings:
        if not holding_includes_sequence(row.get("other_manager"), sequence):
            continue
        copied = dict(row)
        copied["attributed_to_cik"] = attributed_to_cik
        out.append(copied)
    return out


def run_notice_attribution(
    client: EdgarClient,
    refs: list[FilingRef],
    output: Path,
) -> Path:
    dest = output / "bonus_attributed.parquet"
    parent_root = output / "bonus_parent"
    attributed: list[dict[str, Any]] = []
    notices = _notice_refs(refs)
    if not notices:
        print("Bonus 1: no 13F-NT on the roster; writing empty attributed parquet", file=sys.stderr)
        return write_attributed_parquet(dest, attributed)

    for notice in sorted(notices, key=lambda r: (r.report_date, r.accession_dashed)):
        if notice.output_xml is None or not notice.output_xml.exists():
            print(f"Bonus 1: notice XML missing for {notice.accession_dashed}", file=sys.stderr)
            continue
        parent_id = notice_parent_from_cover(notice.output_xml)
        if parent_id is None or not parent_id.get("cik"):
            print(
                f"Bonus 1: {notice.accession_dashed} names no parent CIK on the cover; "
                "not guessing",
                file=sys.stderr,
            )
            continue
        parent_cik = parent_id["cik"]
        parent_name = parent_id.get("name") or parent_cik
        print(
            f"Bonus 1: notice {notice.accession_dashed} → parent {parent_name} CIK {parent_cik}",
            file=sys.stderr,
        )
        candidates = discover_cik_filings(client, parent_cik, parent_name)
        parent_ref = _pick_parent_hr(candidates, notice.report_date)
        if parent_ref is None:
            print(
                f"Bonus 1: no in-scope 13F-HR for parent {parent_cik} "
                f"reportDate={notice.report_date}",
                file=sys.stderr,
            )
            continue
        parent_ref = download_filing_documents(client, parent_ref, parent_root)
        _, holdings = parse_filing(parent_ref)
        managers = sequenced_other_managers(parent_ref.output_xml)
        notice_filing, _ = parse_filing(notice)
        sequence = _match_sequence(
            managers,
            notice.cik,
            notice_file_no=notice_filing.get("form_13f_file_number"),
        )
        if sequence is None:
            print(
                f"Bonus 1: parent {parent_ref.accession_dashed} has no sequenced manager "
                f"matching notice CIK {notice.cik}; writing no rows for this notice",
                file=sys.stderr,
            )
            continue
        rows = attribute_rows(holdings, sequence, pad_cik(notice.cik))
        print(
            f"Bonus 1: sequence {sequence} → {len(rows)} of {len(holdings)} parent rows "
            f"from {parent_ref.accession_dashed}",
            file=sys.stderr,
        )
        attributed.extend(rows)

    write_attributed_parquet(dest, attributed)
    print(f"Bonus 1: wrote {len(attributed)} rows → {dest}", file=sys.stderr)
    return dest
