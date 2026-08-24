#!/usr/bin/env python3
"""Run the whole pipeline: fetch from EDGAR, parse, write the dataset.

    python main.py --user-agent "FirstName LastName netid@illinois.edu"

This is how we run your submission, so it must work from a clean checkout with nothing
in output/. Everything below is yours to rewrite — add modules, packages, classes,
whatever fits. Only two things are fixed:

  - this file is the entry point, and it accepts --user-agent
  - it writes output/filings.parquet and output/holdings.parquet

Start with docs/01-source.md. Check your output with `python verify.py`.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from curator.cik import LookupIndex, reconcile_filers, unpad_cik, write_filers_csv
from curator.constants import FILING_DATE_CUTOFF, REPORT_PERIODS
from curator.edgar import (
    EdgarClient,
    discover_filings,
    download_all_filings,
    download_lookup,
    has_inscope_13f,
)
from curator.bonus_cusip import run_cusip_validation
from curator.bonus_notice import run_notice_attribution
from curator.parse import parse_all
from curator.write import write_parquet

ROOT = Path(__file__).resolve().parent
FILERS = ROOT / "filers.csv"
OUTPUT = ROOT / "output"
CACHE = ROOT / ".cache"

UA_PATTERN = re.compile(r"^\S.*\s+[^@\s]+@[^@\s]+\.[a-z]{2,}\s*$", re.I)


def load_filers() -> list[dict[str, str]]:
    """The roster the researcher supplied. At least one CIK in here is wrong."""
    with FILERS.open(newline="") as fh:
        return list(csv.DictReader(fh))


def run(user_agent: str, output: Path) -> None:
    """Build the dataset: verify CIKs, fetch 13F XML, parse, write Parquet."""
    cache_dir = CACHE
    client = EdgarClient(user_agent=user_agent, cache_dir=cache_dir)
    try:
        print("Reconciling roster CIKs against SEC lookup...", file=sys.stderr)
        pairs = download_lookup(client)
        index = LookupIndex(pairs)
        probe_cache: dict[str, bool] = {}

        def probe(cik: str) -> bool:
            if cik not in probe_cache:
                probe_cache[cik] = has_inscope_13f(client, cik)
            return probe_cache[cik]

        reconciled = reconcile_filers(load_filers(), index, filings_probe=probe)
        write_filers_csv(output / "filers.csv", reconciled)
        n_corr = sum(1 for f in reconciled if f.cik_source == "corrected")
        print(
            f"Wrote {output / 'filers.csv'} ({n_corr} CIK(s) corrected)",
            file=sys.stderr,
        )

        print("Discovering in-scope 13F filings...", file=sys.stderr)
        refs = discover_filings(client, reconciled)
        print(f"Discovered {len(refs)} filings (expect 40)", file=sys.stderr)
        if len(refs) != 40:
            print(
                f"WARNING: expected 40 filings (20 managers x 2 quarters); got {len(refs)}. "
                f"Check CIKs and filingDate <= {FILING_DATE_CUTOFF}, "
                f"reportDate in {sorted(REPORT_PERIODS)}.",
                file=sys.stderr,
            )

        print("Downloading filing documents...", file=sys.stderr)
        expected_dirs = {unpad_cik(f.cik) for f in reconciled}
        filings_root = output / "filings"
        if filings_root.exists():
            import shutil

            for child in sorted(filings_root.iterdir(), key=lambda p: p.name):
                if child.is_dir() and child.name not in expected_dirs:
                    shutil.rmtree(child)
                    print(f"removed leftover filings dir {child.name}", file=sys.stderr)
        refs = download_all_filings(client, refs, output / "filings")

        print("Parsing XML → rows...", file=sys.stderr)
        filings_rows, holdings_rows = parse_all(refs)
        write_parquet(output, filings_rows, holdings_rows)
        print(
            f"Wrote {len(filings_rows)} filings, {len(holdings_rows)} holdings → {output}",
            file=sys.stderr,
        )
        run_notice_attribution(client, refs, output)
        run_cusip_validation(client, output)
        client.manifest.print_summary()
        client.manifest.write_jsonl(cache_dir / "manifest.jsonl")
    finally:
        client.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-agent", required=True,
                    help='required by SEC: "FirstName LastName netid@illinois.edu"')
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()

    if not UA_PATTERN.match(args.user_agent):
        sys.exit(
            "invalid --user-agent.\n"
            "SEC requires a contact address and rejects requests without one.\n"
            '  python main.py --user-agent "Jane Doe jdoe@illinois.edu"'
        )

    args.output.mkdir(parents=True, exist_ok=True)
    run(args.user_agent, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
