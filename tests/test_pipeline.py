"""Pipeline-level tests. Parser identity is in test_parse.py; dates in test_dates.py."""

from __future__ import annotations

import pytest

from curator.edgar import EdgarClient, EdgarError, pick_filing_documents


def test_user_agent_missing_email_fails_loud():
    with pytest.raises(EdgarError, match="User-Agent"):
        EdgarClient(user_agent="Eugene Cheung", cache_dir=__import__("pathlib").Path("/tmp"))


def test_index_json_picks_infotable_not_xsl():
    items = [
        {"name": "primary.xsl", "size": "10"},
        {"name": "primary_doc.xml", "size": "2000"},
        {"name": "form13fInfoTable.xml", "size": "800000"},
        {"name": "xslF345X01/primary_doc.xml", "size": "10"},
    ]
    cover, table = pick_filing_documents(items, primary_document="primary_doc.xml")
    assert cover == "primary_doc.xml"
    assert table == "form13fInfoTable.xml"


def test_index_json_picks_custom_holdings_filename():
    items = [
        {"name": "primary_doc.xml", "size": "2015"},
        {"name": "renaissance13Fq12026_holding.xml", "size": "1836709"},
        {"name": "0001037389-26-000033.txt", "size": "1839000"},
    ]
    cover, table = pick_filing_documents(items, primary_document="primary_doc.xml")
    assert cover == "primary_doc.xml"
    assert table == "renaissance13Fq12026_holding.xml"


def test_notice_has_cover_only():
    items = [
        {"name": "primary_doc.xml", "size": "1800"},
        {"name": "0001172661-26-003777.txt", "size": "2000"},
    ]
    cover, table = pick_filing_documents(items, primary_document="primary_doc.xml")
    assert cover == "primary_doc.xml"
    assert table is None
