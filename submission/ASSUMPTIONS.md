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

## Bonus 1 — Notice attribution

The only roster 13F-NT is Pershing Square Capital Management L.P. (`1336528`), accession
`0001172661-26-003777`, report period 2026-06-30. `additionalInformation` says holdings
are in the public parent's report. Cover `otherManagersInfo` names **PERSHING SQUARE INC.**
CIK `0002026053`, 13F file number `028-25746`. The notice does not give an accession.

That CIK's in-scope 13F-HR for the same `reportDate` is `0001172661-26-003790` (filed
2026-08-14). Cover report type is `13F HOLDINGS REPORT` even though
`otherIncludedManagersCount` is 6. The join key is `summaryPage/otherManagers2Info`:

| seq | CIK | name |
|---|---|---|
| 1 | 1336528 | Pershing Square Capital Management, L.P. (`028-11694`, matches the notice) |
| 2 | 1336477 | PSCM GP, LLC |
| 3 | 2129159 | Pershing Square Partner Group LLC |
| 4 | 2027456 | Pershing Square Management, LLC |
| 5 | 2129160 | Pershing Square PSUS Holdings, LLC |
| 6 | 2131683 | Pershing Square HHH Holdings, LLC |

Fifteen information-table rows. None are untagged (the parent's own book). Fourteen list
sequence `1` (`1, 2, 3, 4` or `1, 2, 3, 4, 6`) — shared discretion, not sole PSCM lots.
One row, **PERSHING SQUARE USA LTD** (`149,520,000`, `other_manager=3, 4, 5`), does not
include sequence 1 and is excluded. `output/bonus_attributed.parquet` is those 14 rows;
`accession_number` is the parent's; `attributed_to_cik` is `0001336528`. Sum of value
`$19,316,172,772` vs parent `tableValueTotal` `$19,465,692,772` (the excluded lot).

Taking every parent row, or only rows with `other_manager` exactly `1` (zero rows), would
be wrong. Q1 is not attributed: PSCM filed its own 13F-HR that quarter.

## Bonus 2 — CUSIP validation

SEC list: `https://www.sec.gov/files/investment/13flist2026q2-txt.txt` (25,333 lines × 80
columns). CUSIP = columns 1–9; column 10 is `*` or space (not part of the identifier);
issuer = columns 11–40. Spaced historical CUSIPs (`037833 10 0`) are compacted the same
way as `holdings.parquet` (`normalize_cusip`) so a formatting mismatch cannot look like a
filer error.

2026 Q2 holdings: **32,176** distinct `(accession_number, cusip)` pairs, **8,613** distinct
CUSIPs, **68,070** rows. After that normalisation, **32,176 / 32,176** are on the official
list (`assessment` empty). No `LIKELY_FILER_ERROR` in this slice. I did not invent misses.

Residual risk I would still tell the researcher:

- Option lots often carry the **underlying** CUSIP plus `putCall=Call`/`Put`, not the
  list's separate option CUSIPs (`037833900` / `037833950` for Apple). The identifier is
  on the list; the class is in `put_call`.
- Issuer names are free text (`A O Smith Corp - US` vs list `SMITH A O CORP`). First-token
  disagreements here were inverted names and ETF series vs fund names, not swapped CUSIPs.
- CINS (letter-prefix) CUSIPs in this slice are on the list; they are reportable foreign
  identifiers, not errors.
- The list is a quarter snapshot. A later quarter can add or drop a CUSIP (`TIMING`) even
  if this one is clean.

**What I would tell the researcher:** in this Q1/Q2 2026 roster extract, you can treat
reported CUSIPs as members of the Q2 official 13F list. You cannot treat issuer spelling
as standardised, and you must not assume an option row's CUSIP identifies a listed option
contract.

## Questions you sent us

If you emailed dsrs@business.illinois.edu and proceeded before hearing back, note it
here so we can see what you were working around.

| Question | Date sent | What you did in the meantime |
|---|---|---|
| | | |
