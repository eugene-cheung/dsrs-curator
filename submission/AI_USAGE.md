# AI Usage

Declare what you used and how. We are not scoring the amount — we are checking that
you can account for your own work.

## Tools used

Cursor (agent) as a coding assistant, directed by Eugene Cheung. I set the architecture,
the CIK keep/correct rules, what “honest null” means, how to attribute a 13F-NT, and how
to parse the official list. Generated code was read, tested, and discarded when it did
not match those rules. Nothing is in the repo that I cannot walk through without the
tool.

## Where you used them

Roughly, by chapter. A sentence each is enough.

| Chapter | How you used AI |
|---|---|
| 1 · Source | Implemented `curator/cik.py` / `edgar.py` from the spec: lookup parse, name-agree-before-correct, ET AL namesake + 13F probe, cache, 5 rps. AI did not choose CIKs — those are lookup evidence (Tudor 923093, Situational Awareness 2045724). |
| 2 · Interrogate | Wrote `submission/eda.py` to scan every XML. Findings are from that run: Pershing NT empty totals, custom infotable filenames, `thirteenffiler` namespace, Call/Put title case, duplicate CUSIPs, `otherManagers2Info` sequences. |
| 3 · Structure | Parser matches local names (`{*}`), writes explicit Arrow schema, no pandas. `verify.py` 8/8; second run byte-identical parquet, 142/142 cache hits. |
| 4 · Serve | Implemented plan / validate / execute / resolve. The model only emits a flat query plan. Numbers come from PyArrow/Python. Tests are `LLM_MODE=mock`. |
| 5 · Show | Screen recording + narration. Local mock cannot answer Apple through `agents.answer`; the clip shows the executor on a validated plan and Q3 `null` on the real entry point. |
| Bonus 1 | Parent CIK from the NT cover, not a hardcoded guess. Sequence 1 = PSCM; comma-lists that include 1 are in; `3, 4, 5` (Pershing Square USA Ltd) is out. |
| Bonus 2 | Parsed the 80-column list (9-char CUSIP, `*` is not a tenth digit, issuer is 30 columns). Compared Q2 `(accession, CUSIP)` pairs. Reported a clean match rather than forcing an error story. |

## What you would change

The 13F-probe disambiguation for Tudor is a judgment call (two legal names, one filer). I
can defend it from the submissions JSON. I would not silently take `BAUPOST GROUP INC`.

I would put `other_manager` on the holdings schema as own-book vs included-manager instead
of filtering it only in the agent and in Bonus 1. Combination reports will otherwise look
like the platform owns every client lot.
