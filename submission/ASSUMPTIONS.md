# Assumptions

Where the specification was ambiguous, or where you asked a question and kept working
rather than waiting on an answer, record the call you made and why.

This is not a penalty. A documented assumption is a normal part of data work — the
alternative is a stalled pipeline or a silent guess nobody can audit later. We read
this alongside your output, and a well-reasoned assumption that differs from ours costs
you nothing.

| # | What was unclear | What you assumed | Why |
|---|---|---|---|
| 1 | Roster CIK vs SEC lookup name | The **name** is the identity. A given CIK is kept only when its lookup name is the same firm (first token matches and token sets nest / Jaccard ≥ 0.7). Otherwise the CIK is replaced. The fund is never renamed to match a bad CIK. | A wrong CIK still resolves to a real filer. `0001697748` is ARK Investment Management, not Situational Awareness. |
| 2 | `The Baupost Group LLC` vs `BAUPOST GROUP INC` (842322) vs `BAUPOST GROUP LLC/MA` (1061768) | Keep **1061768** (`given`). `/MA` is a jurisdiction tag on the same LLC, not a disagreement. | Exact normalised-name match would have uniquely selected `BAUPOST GROUP INC`, which files no 13F in this window. Names agreed; we did not "correct" a working CIK. |
| 3 | `Tudor Investment Corp` vs `TUDOR INVESTMENT CORP` (1080384) vs `TUDOR INVESTMENT CORP ET AL` (923093) | Treat trailing `ET AL` as the same legal name. When both namesakes remain, pick the one that filed an in-scope 13F. That is **923093** (`corrected`). | 1080384 matches the roster string exactly but has no 13F-HR/NT in 2026 Q1/Q2. 923093 is the 13F filer (Q2 accession `0000902664-26-003485`). Given CIK `854157` is the State of Wisconsin Investment Board. |
| 4 | `Situational Awareness LP` given CIK `1697748` | Correct to **2045724**. | Lookup maps `1697748` to ARK Investment Management LLC. `2045724` is the unique name match and files 13F-HR for both quarters. |
| 5 | Ambiguous names with no unique 13F filer | Do not guess; keep the given CIK and log it. | Spec: if ambiguous, do not guess. |
| 6 | Information table filename | If `index.json` has no `*infotable*` XML, take the other (largest) `.xml` besides `primary_doc.xml`. | RenTec/Baupost/Millennium/Balyasny use custom names. Matching only `infotable` leaves a 13F-HR with a declared table and zero parsed rows. |

## Chapter 1 — CIK verification

Two corrections, eighteen `given`:

| fund_name | given | used | cik_source | evidence |
|---|---|---|---|---|
| Tudor Investment Corp | 854157 | 923093 | corrected | given → Wisconsin Investment Board; 13F filer is TUDOR INVESTMENT CORP ET AL |
| Situational Awareness LP | 1697748 | 2045724 | corrected | given → ARK Investment Management LLC |

`output/filers.csv` is 20 rows, CIKs unpadded, sorted by CIK ascending, names exactly as rostered. Discovery then found **40** filings (`reportDate` ∈ {2026-03-31, 2026-06-30}, `filingDate` ≤ 2026-08-18). Pershing Square filed `13F-HR` for Q1 and `13F-NT` for Q2.

Cover namespace in this slice is `http://www.sec.gov/edgar/thirteenffiler`. Combined XML in `output/filings/` wraps `primary_doc` + the information-table document so `eda.py` can see both. Pipeline run twice: parquet SHA-1 `51c3086a…` / `0586c230…` unchanged; second run 142/142 cache hits.

## Chapter 4 — Agent semantics

| # | What was unclear | What you assumed | Why |
|---|---|---|---|
| 7 | What “largest Apple position” returns | The **dollar value** of the winning manager’s own common-stock Apple lots (`put_call` null), not the manager’s name. | The contract example is a USD number. Sources name the filing. |
| 8 | Options vs common | “Position” / “held” / “largest” uses `put_call` null. Calls/puts only when the question says so. | Filers leave the element off for ordinary stock and type `Call`/`Put` when it is an option. |
| 9 | Shares | `ssh_prnamt_type == SH` only. PRN is never added in. | Shares and principal dollars are different units. |
| 10 | Combination reports | When the question names an **issuer**, ignore `other_manager` lots (except `0` / null). Those rows belong to someone on the cover list. “Total reported value” and “most call options” use the whole information table / cover total. | AQR’s Apple book is $5.0B including sequence 1–13 and $4.75B on its own lots. Mixing them in a “who held Apple” ranking credits the platform for its clients. |
| 11 | Q1→Q2 “added” | Delta = Q2 − Q1. Missing Q1 = 0 only if that manager filed a **13F-HR** for Q1. 13F-NT managers are not ranked. | They did not report positions in their own table. |
| 12 | “Directly” | Exists against that manager’s own information table. Pershing Q2 is 13F-NT → `"no"` plus the notice accession. | Spec: NT is not a guess from a parent filing. |
| 13 | 2026 Q3 / hostile input | `null` before the model runs. Guided JSON cannot emit `2026Q3`, so a plan-only check would answer from Q1/Q2. | Honest null beats a confident wrong number. |
| 14 | Distinct issuers | Count distinct `name_of_issuer` as filed (after common-stock filter), not CUSIPs. | The question asked for issuers, not securities. |
| 15 | Total reported value | Cover `table_value_total`, not a recomputed sum of holdings. | “Reported” is what they declared. |
| 16 | `agent_usage.json` | Written under `LLM_MODE=mock` (0 tokens). Re-run `python -m agents.usage_run` against a live endpoint before the video if one is available. | Frozen `llm.py` does not charge the budget in mock. |

Issuer aliases (question → first token on the filing): Apple/AAPL, Nvidia/NVDA, Microsoft/MSFT, Tesla/TSLA, plus Amazon, Alphabet/Google, Meta/Facebook, Netflix, Berkshire. `APPLE HOSPITALITY REIT` does not match Apple.

## Questions you sent us

If you emailed dsrs@business.illinois.edu and proceeded before hearing back, note it
here so we can see what you were working around.

| Question | Date sent | What you did in the meantime |
|---|---|---|
| | | |
