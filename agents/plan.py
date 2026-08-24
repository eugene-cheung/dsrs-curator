"""LLM → flat query-plan JSON. Prompts live here; data does not."""

from __future__ import annotations

from typing import Any

from agents.llm import complete_json

# Flat on purpose. Nested guided schemas burn quality on Gemma.
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["rank", "aggregate", "delta", "lookup", "exists", "unsupported"],
        },
        "metric": {
            "type": "string",
            "enum": ["value", "shares", "count", "name", "percent"],
        },
        "managers": {"type": "array", "items": {"type": "string"}},
        "issuers": {"type": "array", "items": {"type": "string"}},
        "quarters": {
            "type": "array",
            "items": {"type": "string", "enum": ["2026Q1", "2026Q2"]},
        },
        "put_call": {
            "type": "string",
            "enum": ["COMMON", "CALL", "PUT", "OPTION", "ANY"],
        },
        "form_type": {"type": "string", "enum": ["ANY", "13F-HR", "13F-NT"]},
        "ssh_prnamt_type": {"type": "string", "enum": ["ANY", "SH", "PRN"]},
        "group_by": {"type": "string", "enum": ["manager", "issuer", "none"]},
        "order": {"type": "string", "enum": ["desc", "asc"]},
        "limit": {"type": "integer"},
        "compare_from": {"type": "string", "enum": ["2026Q1", "2026Q2", "none"]},
        "compare_to": {"type": "string", "enum": ["2026Q1", "2026Q2", "none"]},
        "require_both": {"type": "string", "enum": ["yes", "no"]},
        "reason": {"type": "string"},
    },
    "required": ["intent", "metric", "put_call"],
}

SYSTEM = """You translate a researcher's question about 13F holdings into a query plan.
You do not compute the answer. You do not write SQL or Python.

Dataset scope: only 2026Q1 and 2026Q2, twenty roster managers. Anything else → intent=unsupported.

intents:
- rank: who/which manager is first by a metric (largest position, most calls, added the most).
- aggregate: a single number over a filtered set (how many, total value, average).
- delta: Q1→Q2 change. Use compare_from/compare_to. "added the most" is rank-by-delta (require_both=no).
- lookup: identity list or "largest position and what was it" (issuer name + value).
- exists: yes/no (did X hold Y directly).
- unsupported: cannot be answered from this dataset.

Defaults a researcher would assume:
- "position" / "held" / "largest" → put_call=COMMON (ordinary positions, not options), unless the question says call/put/option.
- "shares" → ssh_prnamt_type=SH. Never add SH to PRN.
- "directly" → that manager's own information table. A 13F-NT is "no".
- "total reported value" of a manager → metric=value, aggregate, no issuer filter (cover total).
- "distinct issuers" → metric=count, aggregate.
- "call options" → put_call=CALL, metric=count unless they ask for value.
- "which managers filed a 13F-NT" → lookup, metric=name, form_type=13F-NT.
- "held in both quarters" / grow or shrink → delta, require_both=yes.
- Rank questions about size return a number (metric=value or shares), not the manager name.
- "largest position ... and what was it" → lookup, metric=value (executor returns [issuer, dollars]).

put_call: COMMON | CALL | PUT | OPTION (any option) | ANY.
quarters: only 2026Q1 and/or 2026Q2. If the question names any other period, unsupported.
managers / issuers: copy the names from the question (Apple, Nvidia, Renaissance). Do not invent CUSIPs.
limit: 1 for "the" winner, higher only when the question asks for a list.
"""


def propose_plan(question: str, roster: list[str]) -> dict[str, Any]:
    """One guided completion. The roster list is ours, not filing free text."""
    roster_line = ", ".join(roster)
    user = (
        f"Roster managers: {roster_line}\n\n"
        f"Question: {question}\n\n"
        "Return a query plan that matches the schema."
    )
    return complete_json(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        PLAN_SCHEMA,
        max_tokens=512,
    )
