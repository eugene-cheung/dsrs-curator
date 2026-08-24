"""Allowlist the query plan. Never execute raw model text."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

ALLOWED_INTENTS = frozenset({"rank", "aggregate", "delta", "lookup", "exists", "unsupported"})
ALLOWED_METRICS = frozenset({"value", "shares", "count", "name", "percent"})
ALLOWED_QUARTERS = frozenset({"2026Q1", "2026Q2"})
ALLOWED_PUT_CALL = frozenset({"COMMON", "CALL", "PUT", "OPTION", "ANY"})
ALLOWED_FORM = frozenset({"ANY", "13F-HR", "13F-NT"})
ALLOWED_SSH = frozenset({"ANY", "SH", "PRN"})
ALLOWED_GROUP = frozenset({"manager", "issuer", "none"})
ALLOWED_ORDER = frozenset({"desc", "asc"})
ALLOWED_BOTH = frozenset({"yes", "no"})
FORBIDDEN_KEYS = frozenset(
    {
        "sql",
        "query",
        "code",
        "python",
        "path",
        "file",
        "eval",
        "exec",
        "cmd",
        "shell",
        "steps",
        "script",
    }
)
MAX_NAME_LEN = 120
MAX_LIST = 20


@dataclass(frozen=True)
class Plan:
    intent: str
    metric: str
    managers: tuple[str, ...]
    issuers: tuple[str, ...]
    quarters: tuple[str, ...]
    put_call: str
    form_type: str
    ssh_prnamt_type: str
    group_by: str
    order: str
    limit: int
    compare_from: str
    compare_to: str
    require_both: str


def _strings(value: Any, label: str) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        print(f"plan rejected: {label} must be a list", file=sys.stderr)
        return None
    if len(value) > MAX_LIST:
        print(f"plan rejected: {label} longer than {MAX_LIST}", file=sys.stderr)
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            print(f"plan rejected: {label} items must be strings", file=sys.stderr)
            return None
        if len(item) > MAX_NAME_LEN or "\x00" in item:
            print(f"plan rejected: {label} item looks hostile", file=sys.stderr)
            return None
        if ".." in item or "/" in item or "\\" in item:
            print(f"plan rejected: {label} must not contain a path", file=sys.stderr)
            return None
        cleaned = item.strip()
        if cleaned:
            out.append(cleaned)
    return tuple(out)


def validate_plan(raw: Any) -> Plan | None:
    """Return a Plan or None. None means the executor must not run."""
    if not isinstance(raw, dict):
        print("plan rejected: not an object", file=sys.stderr)
        return None
    bad = FORBIDDEN_KEYS & set(raw)
    if bad:
        print(f"plan rejected: forbidden key(s) {sorted(bad)}", file=sys.stderr)
        return None

    intent = raw.get("intent")
    if intent not in ALLOWED_INTENTS:
        print(f"plan rejected: intent {intent!r}", file=sys.stderr)
        return None
    if intent == "unsupported":
        print(
            f"plan unsupported: {raw.get('reason') or 'out of scope'}",
            file=sys.stderr,
        )
        return None

    metric = raw.get("metric", "value")
    if metric not in ALLOWED_METRICS:
        print(f"plan rejected: metric {metric!r}", file=sys.stderr)
        return None

    managers = _strings(raw.get("managers") or [], "managers")
    issuers = _strings(raw.get("issuers") or [], "issuers")
    if managers is None or issuers is None:
        return None

    quarters_raw = raw.get("quarters") or []
    quarters = _strings(quarters_raw, "quarters")
    if quarters is None:
        return None
    if any(q not in ALLOWED_QUARTERS for q in quarters):
        print(f"plan rejected: quarters {quarters}", file=sys.stderr)
        return None

    put_call = raw.get("put_call") or "COMMON"
    form_type = raw.get("form_type") or "ANY"
    ssh = raw.get("ssh_prnamt_type") or "ANY"
    group_by = raw.get("group_by") or "manager"
    order = raw.get("order") or "desc"
    require_both = raw.get("require_both") or "no"
    compare_from = raw.get("compare_from") or "none"
    compare_to = raw.get("compare_to") or "none"

    if put_call not in ALLOWED_PUT_CALL:
        print(f"plan rejected: put_call {put_call!r}", file=sys.stderr)
        return None
    if form_type not in ALLOWED_FORM:
        print(f"plan rejected: form_type {form_type!r}", file=sys.stderr)
        return None
    if ssh not in ALLOWED_SSH:
        print(f"plan rejected: ssh_prnamt_type {ssh!r}", file=sys.stderr)
        return None
    if group_by not in ALLOWED_GROUP:
        print(f"plan rejected: group_by {group_by!r}", file=sys.stderr)
        return None
    if order not in ALLOWED_ORDER:
        print(f"plan rejected: order {order!r}", file=sys.stderr)
        return None
    if require_both not in ALLOWED_BOTH:
        print(f"plan rejected: require_both {require_both!r}", file=sys.stderr)
        return None
    if compare_from not in ALLOWED_QUARTERS | {"none"}:
        print(f"plan rejected: compare_from {compare_from!r}", file=sys.stderr)
        return None
    if compare_to not in ALLOWED_QUARTERS | {"none"}:
        print(f"plan rejected: compare_to {compare_to!r}", file=sys.stderr)
        return None

    limit = raw.get("limit", 1)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        print(f"plan rejected: limit {limit!r}", file=sys.stderr)
        return None
    if limit > MAX_LIST:
        limit = MAX_LIST

    if intent == "delta":
        if compare_from == "none":
            compare_from = "2026Q1"
        if compare_to == "none":
            compare_to = "2026Q2"
        if compare_from not in ALLOWED_QUARTERS or compare_to not in ALLOWED_QUARTERS:
            print("plan rejected: delta needs in-scope compare quarters", file=sys.stderr)
            return None

    if not quarters:
        if intent == "delta":
            quarters = (compare_from, compare_to)
        else:
            print("plan rejected: quarters required", file=sys.stderr)
            return None

    return Plan(
        intent=intent,
        metric=metric,
        managers=managers,
        issuers=issuers,
        quarters=quarters,
        put_call=put_call,
        form_type=form_type,
        ssh_prnamt_type=ssh,
        group_by=group_by,
        order=order,
        limit=limit,
        compare_from=compare_from,
        compare_to=compare_to,
        require_both=require_both,
    )
