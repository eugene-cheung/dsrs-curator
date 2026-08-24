"""Question in, {answer, unit, sources} out. Orchestration only."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from agents.execute import execute
from agents.plan import propose_plan
from agents.resolve import roster_names
from agents.validate import validate_plan

OUTPUT = Path(__file__).resolve().parents[1] / "output"
FILINGS = OUTPUT / "filings.parquet"
HOLDINGS = OUTPUT / "holdings.parquet"

VALID_UNITS = {"USD", "SHARES", "COUNT", "PERCENT", "NAME", "DATE", "NONE"}
NULL = {"answer": None, "unit": "NONE", "sources": []}

# Guided schema cannot emit 2026Q3. Catch it on the question or the model
# will pick Q1/Q2 and invent an in-scope number.
_OUT_OF_SCOPE = re.compile(
    r"(?:2026\s*Q\s*[34]|Q\s*[34]\s*2026|2026Q[34]|"
    r"third\s+quarter(?:\s+of)?\s+2026|2026.{0,24}third\s+quarter|"
    r"fourth\s+quarter(?:\s+of)?\s+2026|"
    r"20(?:2[0-57-9]|1\d)\b)",
    re.I,
)

_HOSTILE = re.compile(
    r"(?:\bdrop\s+table\b|\bdelete\s+from\b|\binsert\s+into\b|"
    r"\bupdate\s+\w+\s+set\b|\beval\s*\(|\bexec\s*\(|__import__|"
    r"\bos\.system\b|subprocess|\.\./|/etc/passwd|\brm\s+-rf\b)",
    re.I,
)


def _null(reason: str) -> dict[str, Any]:
    print(reason, file=sys.stderr)
    return dict(NULL)


def main(question: str, output_dir: Path | None = None) -> dict[str, Any]:
    """Answer `question` against the dataset. Do not rename this function."""
    try:
        return _answer(question, output_dir or OUTPUT)
    except Exception as exc:
        return _null(f"agent error: {type(exc).__name__}: {exc}")


def _answer(question: str, output_dir: Path) -> dict[str, Any]:
    if not isinstance(question, str) or not question.strip():
        return _null("empty question")
    if _HOSTILE.search(question):
        return _null("refused: question looks like an attack, not a holdings query")
    if _OUT_OF_SCOPE.search(question):
        return _null("out of scope: this dataset is 2026 Q1 and 2026 Q2 only")

    filings_path = output_dir / "filings.parquet"
    holdings_path = output_dir / "holdings.parquet"
    if not filings_path.exists() or not holdings_path.exists():
        return _null("dataset missing: run main.py first")

    roster = roster_names(output_dir)
    raw = propose_plan(question, roster)
    plan = validate_plan(raw)
    if plan is None:
        return _null("no executable plan")

    result = execute(plan, output_dir)
    if not isinstance(result, dict) or set(result) < {"answer", "unit", "sources"}:
        return _null("executor returned a bad shape")
    if result["unit"] not in VALID_UNITS:
        return _null(f"bad unit {result['unit']!r}")
    if not isinstance(result["sources"], list):
        return _null("sources must be a list")
    # Sources must be dashed accessions. Drop anything else rather than crash.
    dashed = []
    for src in result["sources"]:
        if isinstance(src, str) and re.fullmatch(r"\d{10}-\d{2}-\d{6}", src):
            dashed.append(src)
    result["sources"] = dashed
    return result


def _cli() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m agents.answer "your question"', file=sys.stderr)
        return 2

    result = main(sys.argv[1])

    if not isinstance(result, dict):
        print(f"main() must return a dict, got {type(result).__name__}", file=sys.stderr)
        return 1
    missing = {"answer", "unit", "sources"} - set(result)
    if missing:
        print(f"result missing key(s): {sorted(missing)}", file=sys.stderr)
        return 1
    if result["unit"] not in VALID_UNITS:
        print(f"unit must be one of {sorted(VALID_UNITS)}, got {result['unit']!r}",
              file=sys.stderr)
        return 1
    if not isinstance(result["sources"], list):
        print("sources must be a list of accession numbers", file=sys.stderr)
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
