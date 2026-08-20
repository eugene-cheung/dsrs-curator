"""CIK lookup download, name normalisation, and roster reconciliation.

The roster CIK is not trusted. The fund *name* is. A bad CIK still resolves to a
real EDGAR entity, so a match on the identifier alone is not evidence.
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Iterable

# Legal suffixes only. Stripping MANAGEMENT / CAPITAL / ADVISORS would collide
# distinct funds onto the same key.
_SUFFIXES = frozenset(
    {
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "LLC",
        "LLP",
        "LP",
        "PLC",
        "LTD",
        "LIMITED",
        "CO",
        "COMPANY",
        "PC",
        "NA",
        "PLLC",
        "THE",
    }
)

# Leftover tokens after expanding "&" → "AND" and stripping "CO".
_TRAILING_NOISE = frozenset({"AND", "THE"})


def unpad_cik(cik: str | int) -> str:
    """CIK with leading zeros stripped. Never empty — CIK 0 does not exist."""
    s = re.sub(r"[^0-9]", "", str(cik))
    stripped = s.lstrip("0")
    if not stripped:
        raise ValueError(f"invalid CIK: {cik!r}")
    return stripped


def pad_cik(cik: str | int) -> str:
    return unpad_cik(cik).zfill(10)


def normalize_name(name: str) -> str:
    """Uppercase, strip parentheticals, punctuation, and legal suffixes."""
    s = name.upper()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("&", " AND ")
    # 13F filers often append "ET AL" to the legal name. That is the same firm.
    s = re.sub(r"\bET\s+AL\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    while tokens and tokens[0] == "THE":
        tokens.pop(0)
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    while tokens and tokens[-1] in _TRAILING_NOISE:
        tokens.pop()
    return " ".join(tokens)


def names_agree(roster_name: str, lookup_names: Iterable[str]) -> bool:
    """Does this CIK's SEC name refer to the same entity as the roster name?

    Used to keep a given CIK when it is already right, even if another namesake
    (INC vs LLC, a state suffix) also exists. First token must match so
    'Tudor Investment' does not agree with 'State of Wisconsin Investment Board'.
    """
    roster_norm = normalize_name(roster_name)
    roster_tok = set(roster_norm.split())
    if not roster_tok:
        return False
    roster_first = roster_norm.split()[0]
    for raw in lookup_names:
        other = normalize_name(raw)
        if not other:
            continue
        other_tok = set(other.split())
        other_first = other.split()[0]
        if other_first != roster_first:
            continue
        if roster_norm == other:
            return True
        if roster_tok <= other_tok or other_tok <= roster_tok:
            return True
        if _jaccard(roster_norm, other) >= 0.7:
            return True
    return False


def parse_lookup_text(text: str) -> list[tuple[str, str]]:
    """Parse SEC cik-lookup-data.txt into (name, unpadded_cik) pairs.

    Lines are `NAME:CIK:` with the CIK as the last numeric field. Names can
    contain colons, so we split from the right.
    """
    rows: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Inactive markers sometimes trail the closing colon.
        line = line.rstrip("*").strip()
        match = re.match(r"^(.*):(\d{1,10}):?$", line)
        if not match:
            continue
        name = match.group(1).strip()
        cik = unpad_cik(match.group(2))
        if name:
            rows.append((name, cik))
    return rows


def lookup_to_csv(pairs: Iterable[tuple[str, str]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "cik"])
        for name, cik in pairs:
            w.writerow([name, cik])


def load_lookup_csv(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="") as fh:
        return [(row["name"], row["cik"]) for row in csv.DictReader(fh)]


@dataclass(frozen=True)
class ReconciledFiler:
    fund_name: str
    cik: str  # unpadded
    cik_source: str  # "given" | "corrected"
    note: str = ""


class LookupIndex:
    def __init__(self, pairs: Iterable[tuple[str, str]]) -> None:
        by_cik: dict[str, list[str]] = {}
        by_norm: dict[str, list[str]] = {}
        by_exact_upper: dict[str, list[str]] = {}
        for name, cik in pairs:
            cik = unpad_cik(cik)
            by_cik.setdefault(cik, []).append(name)
            by_exact_upper.setdefault(name.upper().strip(), []).append(cik)
            key = normalize_name(name)
            if key:
                by_norm.setdefault(key, []).append(cik)
        self.by_cik = {k: _unique_stable(v) for k, v in by_cik.items()}
        self.by_norm = {k: _unique_stable(v) for k, v in by_norm.items()}
        self.by_exact_upper = {k: _unique_stable(v) for k, v in by_exact_upper.items()}
        # Precompute unique (norm_name, cik) for fuzzy scan. Sorted for stability.
        self._norm_pairs = tuple(
            sorted(
                {(normalize_name(n), unpad_cik(c)) for n, c in pairs if normalize_name(n)}
            )
        )

    def names_for_cik(self, cik: str) -> list[str]:
        return self.by_cik.get(unpad_cik(cik), [])


def _unique_stable(items: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen.keys())


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _fuzzy_ciks(norm: str, index: LookupIndex) -> list[str]:
    """Conservative unique fuzzy match. Empty if ambiguous or weak."""
    if not norm:
        return []
    scored: dict[str, float] = {}
    for other, cik in index._norm_pairs:
        score = _jaccard(norm, other)
        if score < 0.85:
            continue
        prev = scored.get(cik, 0.0)
        if score > prev:
            scored[cik] = score
    if not scored:
        return []
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    best_cik, best = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= best - 0.05:
        return []  # no unique winner
    if best < 0.9 and len(norm.split()) < 3:
        return []  # short names need a near-exact hit
    return [best_cik]


def _candidates_for_name(fund_name: str, index: LookupIndex) -> list[str]:
    norm = normalize_name(fund_name)
    exact_upper = fund_name.upper().strip()
    found: dict[str, None] = {}
    for cik in index.by_norm.get(norm, []):
        found.setdefault(cik, None)
    for cik in index.by_exact_upper.get(exact_upper, []):
        found.setdefault(cik, None)
    if not found:
        for cik in _fuzzy_ciks(norm, index):
            found.setdefault(cik, None)
    return list(found.keys())


def reconcile_filers(
    roster: list[dict[str, str]],
    index: LookupIndex,
    filings_probe: Callable[[str], bool] | None = None,
) -> list[ReconciledFiler]:
    """Name is right; CIK may be wrong. Do not rename the fund to fit a bad CIK.

    `filings_probe(cik) -> bool` is optional. When two namesakes remain, it
    picks the one that actually filed an in-scope 13F — evidence, not a guess.
    """
    out: list[ReconciledFiler] = []
    for row in roster:
        fund_name = row["fund_name"]
        given = unpad_cik(row["cik"])
        given_names = index.names_for_cik(given)
        name_ciks = _candidates_for_name(fund_name, index)

        if names_agree(fund_name, given_names):
            out.append(ReconciledFiler(fund_name, given, "given"))
            continue

        chosen: str | None = None
        note = ""
        if len(name_ciks) == 1:
            chosen = name_ciks[0]
        elif len(name_ciks) > 1 and filings_probe is not None:
            live = [cik for cik in sorted(name_ciks, key=int) if filings_probe(cik)]
            if len(live) == 1:
                chosen = live[0]
                note = (
                    f"name {fund_name!r} matched {name_ciks}; "
                    f"only {chosen} filed an in-scope 13F"
                )

        if chosen is None:
            note = (
                f"no unique CIK for {fund_name!r} (given {given}, "
                f"candidates={name_ciks or 'none'}). Keeping given; not a guess."
            )
            print(f"CIK unresolved: {note}", file=sys.stderr)
            out.append(ReconciledFiler(fund_name, given, "given", note))
            continue

        source = "given" if chosen == given else "corrected"
        if source == "corrected":
            pointed_at = given_names[0] if given_names else "(unknown)"
            note = note or (
                f"roster CIK {given} points at {pointed_at!r}; "
                f"name {fund_name!r} maps to {chosen}"
            )
            print(f"CIK corrected: {note}", file=sys.stderr)
        out.append(ReconciledFiler(fund_name, chosen, source, note))
    return out


def write_filers_csv(path: Path, filers: list[ReconciledFiler]) -> None:
    """Names exactly as given. CIKs unpadded. Sorted by CIK ascending."""
    ordered = sorted(filers, key=lambda f: int(f.cik))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fund_name", "cik", "cik_source"])
        for f in ordered:
            w.writerow([f.fund_name, f.cik, f.cik_source])
