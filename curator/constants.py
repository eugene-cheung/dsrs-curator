"""Scope constants shared by discovery, parsing, and the agent."""

from __future__ import annotations

REPORT_PERIODS = frozenset({"2026-03-31", "2026-06-30"})
FILING_DATE_CUTOFF = "2026-08-18"  # inclusive; see docs/01-source.md
IN_SCOPE_FORMS = frozenset({"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"})
IN_SCOPE_QUARTERS = frozenset({"2026Q1", "2026Q2"})

LOOKUP_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVE_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accession_nodash}/index.json"
)
ARCHIVE_FILE_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_nolead}/{accession_nodash}/{name}"
)
OFFICIAL_13F_LIST_Q2_2026 = (
    "https://www.sec.gov/files/investment/13flist2026q2-txt.txt"
)

# Stay well under SEC's 10 req/s fair-access limit.
EDGAR_RPS = 5.0
