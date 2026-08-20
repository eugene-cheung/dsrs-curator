from __future__ import annotations

from curator.edgar import in_scope_filing


def test_2025_q4_filed_in_2026_is_dropped():
    assert not in_scope_filing("13F-HR", "2025-12-31", "2026-02-14")


def test_filing_date_after_cutoff_is_dropped():
    assert not in_scope_filing("13F-HR", "2026-06-30", "2026-08-19")


def test_filing_date_on_cutoff_is_kept():
    assert in_scope_filing("13F-HR", "2026-06-30", "2026-08-18")


def test_report_date_not_filing_date_for_quarter():
    # Filed in May, reports on Q1 — in scope.
    assert in_scope_filing("13F-HR", "2026-03-31", "2026-05-15")
    # Filed on a Q2 calendar day, but reports Q4 2025 — out of scope.
    assert not in_scope_filing("13F-HR", "2025-12-31", "2026-06-30")


def test_notice_forms_are_in_scope():
    assert in_scope_filing("13F-NT", "2026-03-31", "2026-05-01")
    assert in_scope_filing("13F-NT/A", "2026-06-30", "2026-08-14")


def test_unrelated_forms_dropped():
    assert not in_scope_filing("10-K", "2026-03-31", "2026-05-01")
    assert not in_scope_filing("13F-HR", "2026-09-30", "2026-08-01")
