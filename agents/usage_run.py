"""Run the example questions and write output/agent_usage.json."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agents.answer import main
from agents.llm import usage

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
QUESTIONS_DOC = ROOT / "docs" / "questions-examples.md"


def example_questions() -> list[str]:
    text = QUESTIONS_DOC.read_text()
    start = text.find("```")
    end = text.find("```", start + 3)
    block = text[start + 3 : end]
    return [line.strip() for line in block.splitlines() if line.strip() and not line.startswith("```")]


def run() -> Path:
    questions = example_questions()
    rows = []
    before = usage()
    for question in questions:
        t0 = time.perf_counter()
        result = main(question)
        elapsed = time.perf_counter() - t0
        after = usage()
        rows.append(
            {
                "question": question,
                "calls": after["calls"] - before["calls"],
                "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
                "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
                "elapsed_seconds": round(elapsed, 3),
                "answer_unit": result.get("unit"),
                "null": result.get("answer") is None,
            }
        )
        before = after
        print(json.dumps(result), file=sys.stderr)
    totals = {
        "calls": sum(r["calls"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
    }
    payload = {
        "questions": [
            {
                "question": r["question"],
                "calls": r["calls"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "elapsed_seconds": r["elapsed_seconds"],
            }
            for r in rows
        ],
        "totals": totals,
    }
    dest = OUTPUT / "agent_usage.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {dest} totals={totals}", file=sys.stderr)
    return dest


if __name__ == "__main__":
    run()
