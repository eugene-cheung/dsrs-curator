"""Resolve roster managers and free-text issuers.

Filers type issuer names. The question says 'Apple'. Those are not the same
string. Matching is conservative: mega-cap aliases plus token overlap with a
residue whitelist so APPLE HOSPITALITY does not count as Apple.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from curator.cik import normalize_name

# Question-side aliases. Values are the first-token family we accept on a filing.
ISSUER_ALIASES: dict[str, frozenset[str]] = {
    "APPLE": frozenset({"APPLE", "AAPL"}),
    "AAPL": frozenset({"APPLE", "AAPL"}),
    "NVIDIA": frozenset({"NVIDIA", "NVDA"}),
    "NVDA": frozenset({"NVIDIA", "NVDA"}),
    "MICROSOFT": frozenset({"MICROSOFT", "MSFT"}),
    "MSFT": frozenset({"MICROSOFT", "MSFT"}),
    "TESLA": frozenset({"TESLA", "TSLA"}),
    "TSLA": frozenset({"TESLA", "TSLA"}),
    "AMAZON": frozenset({"AMAZON", "AMZN"}),
    "AMZN": frozenset({"AMAZON", "AMZN"}),
    "ALPHABET": frozenset({"ALPHABET", "GOOGLE", "GOOGL", "GOOG"}),
    "GOOGLE": frozenset({"ALPHABET", "GOOGLE", "GOOGL", "GOOG"}),
    "META": frozenset({"META", "FACEBOOK"}),
    "FACEBOOK": frozenset({"META", "FACEBOOK"}),
    "NETFLIX": frozenset({"NETFLIX", "NFLX"}),
    "BERKSHIRE": frozenset({"BERKSHIRE", "BRK"}),
}

# After the issuer's first token matches an alias, leftover tokens must be
# share-class residue. HOSPITALITY / REIT / BANK fail this and do not match.
_RESIDUE_OK = frozenset(
    {
        "COM",
        "CLASS",
        "CL",
        "A",
        "B",
        "C",
        "CAP",
        "STK",
        "STOCK",
        "SHS",
        "ADS",
        "SPONSORED",
        "NOTE",
        "ORD",
        "NEW",
        "WTS",
        "WARRANT",
        "PAR",
        "ORDINARY",
        "COMMON",
        "PREFERRED",
        "PFD",
        "ADR",
        "ADRS",
    }
)

_ISSUER_SUFFIXES = frozenset(
    {
        "CORP",
        "CORPORATION",
        "INC",
        "INCORPORATED",
        "LLC",
        "PLC",
        "LTD",
        "LIMITED",
        "CO",
        "COMPANY",
        "CLASS",
        "COM",
    }
)


def normalize_issuer(name: str) -> str:
    s = name.upper()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\bCL\s+[A-Z]\b", " ", s)
    s = re.sub(r"\bCLASS\s+[A-Z]\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    while tokens and tokens[-1] in _ISSUER_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _alias_family(query: str) -> frozenset[str] | None:
    key = normalize_issuer(query)
    if not key:
        return None
    if key in ISSUER_ALIASES:
        return ISSUER_ALIASES[key]
    first = key.split()[0]
    return ISSUER_ALIASES.get(first)


def issuer_matches(query: str, name_of_issuer: str) -> bool:
    """True if this information-table name is the issuer the question named."""
    q = normalize_issuer(query)
    n = normalize_issuer(name_of_issuer)
    if not q or not n:
        return False
    if q == n:
        return True
    family = _alias_family(query)
    n_tokens = n.split()
    if family and n_tokens[0] in family:
        return all(tok in _RESIDUE_OK or tok in family for tok in n_tokens[1:])
    q_tokens = set(q.split())
    n_set = set(n_tokens)
    if q_tokens <= n_set and n_tokens[0] == q.split()[0]:
        extra = n_set - q_tokens
        return extra <= _RESIDUE_OK
    return False


def resolve_issuers(queries: list[str], names: list[str]) -> list[str]:
    """Return the filing `name_of_issuer` values that match any query.

    Used only to build a mask. The model never sees these strings.
    """
    if not queries:
        return list(names)
    hit: dict[str, None] = {}
    for name in names:
        for q in queries:
            if issuer_matches(q, name):
                hit.setdefault(name, None)
                break
    return list(hit.keys())


@lru_cache(maxsize=4)
def roster_from_filings(filings_path: str) -> tuple[tuple[str, str], ...]:
    """(fund_name, padded_cik) pairs, stable order."""
    import pyarrow.parquet as pq

    table = pq.read_table(filings_path, columns=["fund_name", "cik"])
    seen: dict[tuple[str, str], None] = {}
    for name, cik in zip(table.column("fund_name").to_pylist(), table.column("cik").to_pylist()):
        seen.setdefault((name, cik), None)
    return tuple(sorted(seen, key=lambda pair: pair[1]))


def resolve_managers(queries: list[str], roster: list[tuple[str, str]]) -> list[str]:
    """Return padded CIKs for managers named in the question. Empty if none unique."""
    if not queries:
        return [cik for _, cik in roster]
    found: dict[str, None] = {}
    for raw in queries:
        q = raw.strip()
        if not q:
            continue
        q_norm = normalize_name(q)
        exact = [(name, cik) for name, cik in roster if name.lower() == q.lower()]
        if len(exact) == 1:
            found.setdefault(exact[0][1], None)
            continue
        norm_hits = [(name, cik) for name, cik in roster if normalize_name(name) == q_norm]
        if len(norm_hits) == 1:
            found.setdefault(norm_hits[0][1], None)
            continue
        # Unique containment: "Citadel" → Citadel Advisors LLC; "Pershing Square" too.
        contains = [
            (name, cik)
            for name, cik in roster
            if q.lower() in name.lower() or q_norm in normalize_name(name)
        ]
        if len(contains) == 1:
            found.setdefault(contains[0][1], None)
            continue
        token = set(q_norm.split())
        token_hits = [
            (name, cik)
            for name, cik in roster
            if token and token <= set(normalize_name(name).split())
        ]
        if len(token_hits) == 1:
            found.setdefault(token_hits[0][1], None)
    return list(found.keys())


def roster_names(output_dir: Path) -> list[str]:
    pairs = roster_from_filings(str(output_dir / "filings.parquet"))
    return [name for name, _ in pairs]
