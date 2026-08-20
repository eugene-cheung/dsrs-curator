"""Pipeline-level tests. Parser identity is in test_parse.py; dates in test_dates.py."""

from __future__ import annotations

import pytest

from curator.edgar import EdgarClient, EdgarError, pick_filing_documents


def test_user_agent_missing_email_fails_loud():
    with pytest.raises(EdgarError, match="User-Agent"):
        EdgarClient(user_agent="Eugene Cheung", cache_dir=__import__("pathlib").Path("/tmp"))


def test_index_json_picks_infotable_not_xsl():
    items = [
        {"name": "primary.xsl"},
        {"name": "primary_doc.xml"},
        {"name": "form13fInfoTable.xml"},
        {"name": "xslF345X01/primary_doc.xml"},
    ]
    cover, table = pick_filing_documents(items, primary_document="primary_doc.xml")
    assert cover == "primary_doc.xml"
    assert table == "form13fInfoTable.xml"
