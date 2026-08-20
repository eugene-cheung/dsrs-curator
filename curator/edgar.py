"""EDGAR client: User-Agent, rate limit, cache, submissions, archive download."""

from __future__ import annotations

import json
import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from curator.constants import (
    ARCHIVE_FILE_URL,
    ARCHIVE_INDEX_URL,
    EDGAR_RPS,
    FILING_DATE_CUTOFF,
    IN_SCOPE_FORMS,
    LOOKUP_URL,
    REPORT_PERIODS,
    SUBMISSIONS_URL,
)
from curator.cik import ReconciledFiler, pad_cik, unpad_cik
from curator.manifest import Manifest


class EdgarError(RuntimeError):
    pass


def in_scope_filing(form: str, report_date: str, filing_date: str) -> bool:
    """Quarter membership is reportDate. filingDate is only a cutoff."""
    if form not in IN_SCOPE_FORMS:
        return False
    if report_date not in REPORT_PERIODS:
        return False
    if not filing_date or filing_date > FILING_DATE_CUTOFF:
        return False
    return True


def _parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


class RateLimiter:
    def __init__(self, rps: float = EDGAR_RPS) -> None:
        self.min_interval = 1.0 / rps
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


@dataclass
class FilingRef:
    fund_name: str
    cik: str  # unpadded
    form_type: str
    accession_dashed: str
    report_date: str  # YYYY-MM-DD from the submissions API
    filing_date: str  # YYYY-MM-DD accepted date
    primary_document: str = ""
    cover_cache: Path | None = None
    table_cache: Path | None = None
    output_xml: Path | None = None

    @property
    def cik_padded(self) -> str:
        return pad_cik(self.cik)

    @property
    def accession_nodash(self) -> str:
        return self.accession_dashed.replace("-", "")


@dataclass
class EdgarClient:
    user_agent: str
    cache_dir: Path
    rps: float = EDGAR_RPS
    timeout: float = 60.0
    _limiter: RateLimiter = field(init=False)
    manifest: Manifest = field(init=False)
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.user_agent or not re.search(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", self.user_agent, re.I):
            raise EdgarError(
                "User-Agent must include a contact email. SEC rejects requests without one."
            )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._limiter = RateLimiter(self.rps)
        self.manifest = Manifest()
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=self.timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def cache_path_for(self, url: str) -> Path:
        parsed = urlparse(url)
        rel = parsed.netloc + parsed.path
        if parsed.query:
            rel = rel.rstrip("/") + "_" + parsed.query.replace("=", "_").replace("&", "_")
        return self.cache_dir / rel.lstrip("/")

    def get_bytes(self, url: str, *, force: bool = False) -> tuple[bytes, bool, int]:
        """Return (body, cache_hit, status). Writes a cache file on success."""
        dest = self.cache_path_for(url)
        if dest.exists() and dest.stat().st_size > 0 and not force:
            body = dest.read_bytes()
            self.manifest.record(url, dest, status=200, cache_hit=True, n_bytes=len(body))
            return body, True, 200

        dest.parent.mkdir(parents=True, exist_ok=True)
        status = 0
        body = b""
        backoff = 1.0
        last_exc: Exception | None = None
        for attempt in range(6):
            self._limiter.wait()
            try:
                resp = self._client.get(url)
                status = resp.status_code
                if status == 429:
                    retry_after = resp.headers.get("Retry-After")
                    sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                    sleep_s += random.uniform(0, 0.3)
                    print(f"EDGAR 429 on {url}; backing off {sleep_s:.1f}s", file=sys.stderr)
                    time.sleep(sleep_s)
                    backoff = min(backoff * 2, 60)
                    continue
                if status >= 500:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                if status >= 400:
                    self.manifest.record(url, dest, status=status, cache_hit=False, n_bytes=0)
                    raise EdgarError(f"GET {url} failed: HTTP {status}")
                body = resp.content
                dest.write_bytes(body)
                self.manifest.record(url, dest, status=status, cache_hit=False, n_bytes=len(body))
                return body, False, status
            except EdgarError:
                raise
            except Exception as exc:
                last_exc = exc
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self.manifest.record(url, dest, status=status or 0, cache_hit=False, n_bytes=0)
        raise EdgarError(f"GET {url} failed after retries: {last_exc}")

    def get_text(self, url: str) -> tuple[str, bool]:
        body, hit, _ = self.get_bytes(url)
        return body.decode("utf-8", errors="replace"), hit

    def get_json(self, url: str) -> tuple[Any, bool]:
        text, hit = self.get_text(url)
        return json.loads(text), hit


def download_lookup(client: EdgarClient) -> list[tuple[str, str]]:
    from curator.cik import lookup_to_csv, parse_lookup_text

    csv_path = client.cache_dir / "cik-lookup.csv"
    raw_url = LOOKUP_URL
    # Always prefer the converted local table if present so we do not re-parse 10MB.
    if csv_path.exists() and csv_path.stat().st_size > 0:
        from curator.cik import load_lookup_csv

        # Still record a cache hit against the source URL if the raw file is on disk.
        raw_path = client.cache_path_for(raw_url)
        if raw_path.exists():
            client.manifest.record(
                raw_url, raw_path, status=200, cache_hit=True, n_bytes=raw_path.stat().st_size
            )
        return load_lookup_csv(csv_path)

    text, _ = client.get_text(raw_url)
    pairs = parse_lookup_text(text)
    lookup_to_csv(pairs, csv_path)
    return pairs


def _recent_filings(payload: dict[str, Any]) -> list[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    n = len(forms)
    rows = []
    for i in range(n):
        rows.append(
            {
                "form": forms[i],
                "accession": recent["accessionNumber"][i],
                "filingDate": recent["filingDate"][i],
                "reportDate": recent.get("reportDate", [""] * n)[i],
                "primaryDocument": recent.get("primaryDocument", [""] * n)[i],
            }
        )
    return rows


def has_inscope_13f(client: EdgarClient, cik: str) -> bool:
    """True if this CIK has at least one in-scope 13F. Used to break namesake ties."""
    url = SUBMISSIONS_URL.format(cik10=pad_cik(cik))
    payload, _ = client.get_json(url)
    return any(
        in_scope_filing(row["form"], row["reportDate"], row["filingDate"])
        for row in _recent_filings(payload)
    )


def discover_filings(
    client: EdgarClient,
    filers: list[ReconciledFiler],
) -> list[FilingRef]:
    refs: list[FilingRef] = []
    # Iterate filers in CIK order so discovery itself is deterministic.
    for filer in sorted(filers, key=lambda f: int(f.cik)):
        url = SUBMISSIONS_URL.format(cik10=pad_cik(filer.cik))
        payload, _ = client.get_json(url)
        for row in _recent_filings(payload):
            if not in_scope_filing(row["form"], row["reportDate"], row["filingDate"]):
                continue
            refs.append(
                FilingRef(
                    fund_name=filer.fund_name,
                    cik=filer.cik,
                    form_type=row["form"],
                    accession_dashed=row["accession"],
                    report_date=row["reportDate"],
                    filing_date=row["filingDate"],
                    primary_document=row.get("primaryDocument") or "",
                )
            )
    refs.sort(key=lambda r: (int(r.cik), r.accession_dashed))
    return refs


def _as_item_list(index_json: dict[str, Any]) -> list[dict[str, Any]]:
    directory = index_json.get("directory", index_json)
    items = directory.get("item", [])
    if isinstance(items, dict):
        return [items]
    return list(items)


def pick_filing_documents(
    items: list[dict[str, Any]],
    primary_document: str = "",
) -> tuple[str | None, str | None]:
    """Return (cover_filename, infotable_filename). Table may be None for notices."""
    names = [item.get("name", "") for item in items if item.get("name")]
    xml_like = [
        n
        for n in names
        if n.lower().endswith((".xml", ".html", ".htm")) and "xsl" not in n.lower()
    ]
    table = None
    cover = None
    for n in xml_like:
        ln = n.lower()
        if any(tok in ln for tok in ("infotable", "informationtable", "form13finfo")):
            table = n
            continue
        if "primary" in ln or n == primary_document:
            cover = n
    if cover is None and primary_document in names:
        cover = primary_document
    if cover is None:
        for n in xml_like:
            ln = n.lower()
            if n != table and not any(tok in ln for tok in ("infotable", "informationtable")):
                cover = n
                break
    if cover is None and xml_like:
        cover = xml_like[0]
    return cover, table


def download_filing_documents(
    client: EdgarClient,
    ref: FilingRef,
    output_filings: Path,
) -> FilingRef:
    index_url = ARCHIVE_INDEX_URL.format(
        cik_nolead=unpad_cik(ref.cik),
        accession_nodash=ref.accession_nodash,
    )
    index_json, _ = client.get_json(index_url)
    cover_name, table_name = pick_filing_documents(
        _as_item_list(index_json), ref.primary_document
    )
    if cover_name is None:
        raise EdgarError(
            f"no XML/HTML document in {index_url} for {ref.accession_dashed}"
        )

    def _file_url(name: str) -> str:
        return ARCHIVE_FILE_URL.format(
            cik_nolead=unpad_cik(ref.cik),
            accession_nodash=ref.accession_nodash,
            name=name,
        )

    cover_bytes, _, _ = client.get_bytes(_file_url(cover_name))
    ref.cover_cache = client.cache_path_for(_file_url(cover_name))
    table_bytes = None
    if table_name and table_name != cover_name:
        table_bytes, _, _ = client.get_bytes(_file_url(table_name))
        ref.table_cache = client.cache_path_for(_file_url(table_name))

    dest_dir = output_filings / unpad_cik(ref.cik)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{ref.accession_nodash}.xml"
    _write_combined_xml(dest, cover_bytes, table_bytes)
    ref.output_xml = dest
    return ref


def _write_combined_xml(
    dest: Path, cover_bytes: bytes, table_bytes: bytes | None
) -> None:
    """One file per filing so eda.py can see cover + information table together.

    Original namespaces are preserved. The wrapper element has no SEC namespace
    and is ignored by local-name matching.
    """
    from lxml import etree

    parser = etree.XMLParser(recover=False, huge_tree=True, resolve_entities=False)
    root = etree.Element("curatorFiling")
    cover_holder = etree.SubElement(root, "primaryDoc")
    try:
        cover_el = etree.fromstring(cover_bytes, parser=parser)
        cover_holder.append(cover_el)
    except etree.XMLSyntaxError:
        # Some primary documents are HTML. Keep the raw bytes as text so EDA
        # still has evidence, and parsing can fall back to the submissions API.
        cover_holder.set("non_xml", "true")
        cover_holder.text = cover_bytes.decode("utf-8", errors="replace")
    if table_bytes:
        table_holder = etree.SubElement(root, "infoTableDoc")
        table_el = etree.fromstring(table_bytes, parser=parser)
        table_holder.append(table_el)
    dest.write_bytes(
        etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=False)
    )


def download_all_filings(
    client: EdgarClient,
    refs: list[FilingRef],
    output_filings: Path,
) -> list[FilingRef]:
    output_filings.mkdir(parents=True, exist_ok=True)
    out: list[FilingRef] = []
    for ref in refs:
        out.append(download_filing_documents(client, ref, output_filings))
        print(
            f"saved {ref.form_type} {ref.accession_dashed} -> {ref.output_xml}",
            file=sys.stderr,
        )
    return out
