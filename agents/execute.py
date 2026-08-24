"""Deterministic Python over parquet. The model never reaches this with raw text."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from agents.resolve import issuer_matches, resolve_managers
from agents.validate import Plan

HR_FORMS = frozenset({"13F-HR", "13F-HR/A"})
NT_FORMS = frozenset({"13F-NT", "13F-NT/A"})
NULL_ANSWER = {"answer": None, "unit": "NONE", "sources": []}


@dataclass
class _Group:
    cik: str
    fund_name: str
    score: int | float
    accessions: list[str]
    extra: Any = None


def _norm_put_call(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip().upper()


def _is_hr(form_type: str) -> bool:
    return form_type in HR_FORMS


def _is_nt(form_type: str) -> bool:
    return form_type in NT_FORMS


def load_dataset(output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filings = pq.read_table(output_dir / "filings.parquet").to_pylist()
    holdings = pq.read_table(output_dir / "holdings.parquet").to_pylist()
    by_acc = {row["accession_number"]: row for row in filings}
    for row in holdings:
        filing = by_acc.get(row["accession_number"])
        if filing is None:
            continue
        row["fund_name"] = filing["fund_name"]
        row["form_type"] = filing["form_type"]
        row["table_value_total"] = filing["table_value_total"]
    return filings, holdings


def _roster(filings: list[dict[str, Any]]) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for row in filings:
        seen.setdefault((row["fund_name"], row["cik"]), None)
    return list(seen.keys())


def _manager_ciks(plan: Plan, filings: list[dict[str, Any]]) -> list[str] | None:
    roster = _roster(filings)
    if not plan.managers:
        return [cik for _, cik in roster]
    ciks = resolve_managers(list(plan.managers), roster)
    if not ciks:
        return None
    return ciks


def _holding_ok(row: dict[str, Any], plan: Plan, ciks: list[str]) -> bool:
    if row["cik"] not in ciks:
        return False
    if row["report_quarter"] not in plan.quarters:
        return False
    form = row.get("form_type") or ""
    if plan.form_type == "13F-HR" and not _is_hr(form):
        return False
    if plan.form_type == "13F-NT" and not _is_nt(form):
        return False
    if _is_nt(form):
        return False
    pc = _norm_put_call(row.get("put_call"))
    if plan.put_call == "COMMON" and pc is not None:
        return False
    if plan.put_call == "CALL" and pc != "CALL":
        return False
    if plan.put_call == "PUT" and pc != "PUT":
        return False
    if plan.put_call == "OPTION" and pc not in {"CALL", "PUT"}:
        return False
    ssh = row.get("ssh_prnamt_type") or ""
    if plan.ssh_prnamt_type in {"SH", "PRN"} and ssh != plan.ssh_prnamt_type:
        return False
    if plan.metric == "shares" and ssh != "SH":
        return False
    if plan.issuers and not any(issuer_matches(q, row["name_of_issuer"]) for q in plan.issuers):
        return False
    # Named-issuer questions: the filing manager's own lots, not otherManager
    # sequence rows (those belong to someone on the cover list). "Reported"
    # questions with no issuer still use the whole information table.
    if plan.issuers and plan.intent != "exists":
        om = row.get("other_manager")
        if om is not None and str(om).strip() not in {"", "0"}:
            return False
    return True


def _score(rows: list[dict[str, Any]], metric: str) -> int:
    if metric == "value":
        return int(sum(int(r["value"]) for r in rows))
    if metric == "shares":
        return int(sum(int(r["ssh_prnamt"]) for r in rows if r.get("ssh_prnamt_type") == "SH"))
    if metric == "count":
        return len(rows)
    if metric == "percent":
        return int(sum(int(r["value"]) for r in rows))
    return int(sum(int(r["value"]) for r in rows))


def _accessions(rows: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for row in sorted(rows, key=lambda r: (r["accession_number"], r["cik"])):
        seen.setdefault(row["accession_number"], None)
    return list(seen.keys())


def _sort_groups(groups: list[_Group], order: str) -> list[_Group]:
    # Tie-break cik then accession, always ascending. Only the metric flips.
    return sorted(
        groups,
        key=lambda g: (
            -g.score if order != "asc" else g.score,
            g.cik,
            g.accessions[0] if g.accessions else "",
        ),
    )


def _groups_by_manager(rows: list[dict[str, Any]], metric: str) -> list[_Group]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[row["cik"]].append(row)
    groups: list[_Group] = []
    for cik in sorted(buckets):
        chunk = buckets[cik]
        groups.append(
            _Group(
                cik=cik,
                fund_name=chunk[0]["fund_name"],
                score=_score(chunk, metric),
                accessions=_accessions(chunk),
            )
        )
    return groups


def _null() -> dict[str, Any]:
    return dict(NULL_ANSWER)


def _unit(metric: str) -> str:
    return {
        "value": "USD",
        "shares": "SHARES",
        "count": "COUNT",
        "name": "NAME",
        "percent": "PERCENT",
    }.get(metric, "NONE")


def execute(plan: Plan, output_dir: Path) -> dict[str, Any]:
    filings, holdings = load_dataset(output_dir)
    ciks = _manager_ciks(plan, filings)
    if ciks is None:
        print("no unique manager match", file=__import__("sys").stderr)
        return _null()

    if plan.intent == "exists":
        return _exec_exists(plan, filings, holdings, ciks)
    if plan.intent == "lookup":
        return _exec_lookup(plan, filings, holdings, ciks)
    if plan.intent == "aggregate":
        return _exec_aggregate(plan, filings, holdings, ciks)
    if plan.intent == "rank":
        return _exec_rank(plan, filings, holdings, ciks)
    if plan.intent == "delta":
        return _exec_delta(plan, filings, holdings, ciks)
    return _null()


def _filings_for(filings: list[dict[str, Any]], ciks: list[str], quarters: tuple[str, ...], form: str) -> list[dict[str, Any]]:
    out = []
    for row in filings:
        if row["cik"] not in ciks:
            continue
        if row["report_quarter"] not in quarters:
            continue
        if form == "13F-HR" and not _is_hr(row["form_type"]):
            continue
        if form == "13F-NT" and not _is_nt(row["form_type"]):
            continue
        out.append(row)
    return out


def _exec_exists(
    plan: Plan,
    filings: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    ciks: list[str],
) -> dict[str, Any]:
    # NT for the asked quarter ⇒ no, with that notice as the source.
    scoped = _filings_for(filings, ciks, plan.quarters, "ANY")
    nt = [f for f in scoped if _is_nt(f["form_type"])]
    hr = [f for f in scoped if _is_hr(f["form_type"])]
    if nt and not hr:
        return {
            "answer": "no",
            "unit": "NONE",
            "sources": _accessions(nt),
        }
    rows = [r for r in holdings if _holding_ok(r, plan, ciks)]
    sources = _accessions(rows) or _accessions(hr)
    return {
        "answer": "yes" if rows else "no",
        "unit": "NONE",
        "sources": sources,
    }


def _exec_lookup(
    plan: Plan,
    filings: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    ciks: list[str],
) -> dict[str, Any]:
    if plan.form_type == "13F-NT" or plan.metric == "name" and plan.form_type != "ANY":
        rows = _filings_for(filings, ciks, plan.quarters, plan.form_type)
        if plan.form_type == "13F-NT":
            rows = [r for r in rows if _is_nt(r["form_type"])]
        if not rows:
            return _null()
        names = sorted({r["fund_name"] for r in rows}, key=lambda n: n)
        return {
            "answer": names if len(names) != 1 else names[0],
            "unit": "NAME",
            "sources": _accessions(rows),
        }

    rows = [r for r in holdings if _holding_ok(r, plan, ciks)]
    if not rows:
        return _null()
    # Largest position: one issuer (sum common rows of that issuer) for the manager.
    if plan.managers and plan.metric in {"value", "name"}:
        by_issuer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_issuer[row["name_of_issuer"]].append(row)
        ranked = []
        for issuer, chunk in by_issuer.items():
            ranked.append(
                (
                    _score(chunk, "value"),
                    chunk[0]["cik"],
                    issuer,
                    _accessions(chunk),
                )
            )
        ranked.sort(key=lambda t: (-t[0], t[1], t[2]))
        top = ranked[0]
        return {
            "answer": [top[2], top[0]],
            "unit": "USD",
            "sources": top[3],
        }

    names = sorted({r["fund_name"] for r in rows})
    return {
        "answer": names if len(names) != 1 else names[0],
        "unit": "NAME",
        "sources": _accessions(rows),
    }


def _exec_aggregate(
    plan: Plan,
    filings: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    ciks: list[str],
) -> dict[str, Any]:
    # Cover totals: "reported value" is table_value_total, not a recomputed sum.
    # Named manager → that filer's declared total. No manager → average across HR.
    if plan.metric == "value" and not plan.issuers:
        scoped = [
            f
            for f in _filings_for(filings, ciks, plan.quarters, "13F-HR")
            if f.get("table_value_total") is not None
        ]
        if not scoped:
            return _null()
        total = int(sum(int(f["table_value_total"]) for f in scoped))
        if not plan.managers and len(scoped) > 1:
            avg = total / len(scoped)
            answer: int | float = int(avg) if avg == int(avg) else round(avg, 2)
            return {"answer": answer, "unit": "USD", "sources": _accessions(scoped)}
        return {"answer": total, "unit": "USD", "sources": _accessions(scoped)}

    rows = [r for r in holdings if _holding_ok(r, plan, ciks)]
    if plan.metric == "count" and not plan.issuers:
        # Distinct issuers as filed-normalized names, common positions already filtered.
        issuers = sorted({r["name_of_issuer"] for r in rows})
        return {
            "answer": len(issuers),
            "unit": "COUNT",
            "sources": _accessions(rows),
        }
    if not rows:
        return _null()
    return {
        "answer": _score(rows, plan.metric),
        "unit": _unit(plan.metric),
        "sources": _accessions(rows),
    }


def _exec_rank(
    plan: Plan,
    filings: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    ciks: list[str],
) -> dict[str, Any]:
    # Rankings are holdings. NT managers contribute no rows and do not win.
    rows = [r for r in holdings if _holding_ok(r, plan, ciks)]
    groups = _groups_by_manager(rows, plan.metric)
    groups = [g for g in groups if g.score != 0 or plan.metric == "count"]
    if not groups:
        return _null()
    ranked = _sort_groups(groups, plan.order)
    winners = ranked[: plan.limit]
    if plan.metric == "name":
        answer: Any = [g.fund_name for g in winners]
        if len(answer) == 1:
            answer = answer[0]
        unit = "NAME"
    else:
        if len(winners) == 1:
            answer = winners[0].score
        else:
            answer = [g.score for g in winners]
        unit = _unit(plan.metric)
    sources: list[str] = []
    seen: dict[str, None] = {}
    for g in winners:
        for acc in g.accessions:
            if acc not in seen:
                seen[acc] = None
                sources.append(acc)
    sources.sort()
    return {"answer": answer, "unit": unit, "sources": sources}


def _hr_ciks(filings: list[dict[str, Any]], quarter: str) -> set[str]:
    return {
        f["cik"]
        for f in filings
        if f["report_quarter"] == quarter and _is_hr(f["form_type"])
    }


def _exec_delta(
    plan: Plan,
    filings: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    ciks: list[str],
) -> dict[str, Any]:
    q_from, q_to = plan.compare_from, plan.compare_to
    hr_from = _hr_ciks(filings, q_from)
    hr_to = _hr_ciks(filings, q_to)

    def slice_q(quarter: str) -> list[dict[str, Any]]:
        qplan = Plan(
            intent=plan.intent,
            metric=plan.metric,
            managers=plan.managers,
            issuers=plan.issuers,
            quarters=(quarter,),
            put_call=plan.put_call,
            form_type="13F-HR",
            ssh_prnamt_type="SH" if plan.metric == "shares" else plan.ssh_prnamt_type,
            group_by=plan.group_by,
            order=plan.order,
            limit=plan.limit,
            compare_from=plan.compare_from,
            compare_to=plan.compare_to,
            require_both=plan.require_both,
        )
        return [r for r in holdings if _holding_ok(r, qplan, ciks)]

    from_rows = slice_q(q_from)
    to_rows = slice_q(q_to)
    from_g = {g.cik: g for g in _groups_by_manager(from_rows, plan.metric)}
    to_g = {g.cik: g for g in _groups_by_manager(to_rows, plan.metric)}

    deltas: list[_Group] = []
    candidates = sorted(set(from_g) | set(to_g) | (hr_from & set(ciks)) | (hr_to & set(ciks)))
    for cik in candidates:
        # NT in a quarter is not a holdings ranking participant for that book.
        if cik not in hr_to:
            continue
        if plan.require_both == "yes":
            if cik not in from_g or cik not in to_g:
                continue
            before = from_g[cik].score
            after = to_g[cik].score
        else:
            if cik not in hr_from:
                # Missing Q1 holding is 0 only if they filed 13F-HR for Q1.
                continue
            if cik not in from_g and cik not in to_g:
                continue
            before = from_g[cik].score if cik in from_g else 0
            after = to_g[cik].score if cik in to_g else 0
        acc = []
        if cik in from_g:
            acc.extend(from_g[cik].accessions)
        if cik in to_g:
            acc.extend(to_g[cik].accessions)
        named = to_g.get(cik) or from_g.get(cik)
        if named is None:
            continue
        fund = named.fund_name
        sources = _accessions([{"accession_number": a, "cik": cik} for a in acc])
        deltas.append(
            _Group(
                cik=cik,
                fund_name=fund,
                score=after - before,
                accessions=sources,
                extra=(before, after),
            )
        )

    if not deltas:
        return _null()

    if plan.require_both == "yes":
        deltas.sort(key=lambda g: (g.cik, g.fund_name))
        payload = []
        sources: list[str] = []
        seen: dict[str, None] = {}
        for g in deltas:
            before, after = g.extra
            if after > before:
                direction = "grew"
            elif after < before:
                direction = "shrunk"
            else:
                direction = "unchanged"
            payload.append([g.fund_name, direction, g.score])
            for acc in g.accessions:
                if acc not in seen:
                    seen[acc] = None
                    sources.append(acc)
        sources.sort()
        answer: Any = payload[0] if len(payload) == 1 else payload
        return {"answer": answer, "unit": "SHARES" if plan.metric == "shares" else _unit(plan.metric), "sources": sources}

    ranked = _sort_groups(deltas, plan.order)
    winner = ranked[0]
    return {
        "answer": winner.score if plan.metric != "name" else winner.fund_name,
        "unit": "NAME" if plan.metric == "name" else _unit(plan.metric),
        "sources": winner.accessions,
    }
