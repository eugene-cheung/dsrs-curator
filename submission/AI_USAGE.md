# AI Usage

Declare what you used and how. We are not scoring the amount — we are checking that
you can account for your own work.

## Tools used

Cursor (agent) under Eugene Cheung's direction. Architecture, traps, and review
decisions are Eugene's. Nothing is kept that he cannot explain in the walkthrough.

## Where you used them

Roughly, by chapter. A sentence each is enough.

| Chapter | How you used AI |
|---|---|
| 1 · Source | Implemented `curator/cik.py` / `edgar.py` from the spec: lookup parse, name-agree-before-correct, ET AL namesake + 13F probe, cache, 5 rps. AI did not choose CIKs — those are lookup evidence (Tudor 923093, Situational Awareness 2045724). |
| 2 · Interrogate | |
| 3 · Structure | |
| 4 · Serve | |

## What you would change

The 13F-probe disambiguation for Tudor is a judgment call (two legal names, one filer). I can defend it from the submissions JSON. I would not silently take `BAUPOST GROUP INC`.
