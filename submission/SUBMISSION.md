# Submission

Fill this in and commit it. A submission missing the video link is incomplete.

## Who

- **Name:** Eugene Cheung
- **NetID:** eugene10

## Video

Under 3 minutes, narrated, showing a cold-start pipeline run and your agent answering
a question.

Upload to Illinois MediaSpace: https://mediaspace.illinois.edu/upload/media
Set visibility to **Unlisted**.

- **Link:** https://mediaspace.illinois.edu/media/t/1_lquedb58

## Chapters attempted

Mark what you completed. Partial work still gets read.

- [x] 1 · Source
- [x] 2 · Interrogate
- [x] 3 · Structure
- [x] 4 · Serve
- [x] 5 · Show
- [x] Bonus 1 — Notice attribution
- [x] Bonus 2 — CUSIP validation

## Checklist

- [x] `python check_submission.py` passes
- [x] Repo is **private** and `dsrsBOT` is a collaborator with Read access
- [x] Video uploaded to MediaSpace, visibility **Unlisted**, link tested
- [ ] Repository URL submitted at <https://ikompete.dsrs.illinois.edu/competition/16>
- [x] `python verify.py` passes
- [x] Pipeline run twice; output is byte-identical
- [x] `output/filings.parquet`, `output/holdings.parquet` committed
- [x] `output/filers.csv`, `output/filings/`, `submission/eda.py` committed
- [x] `DEPENDENCIES.md`, `AI_USAGE.md`, and `ASSUMPTIONS.md` filled in
- [x] No API keys, tokens, or credentials committed
- [x] Frozen files unmodified

## Anything we should know

The video is a cold start of `output/` with the EDGAR cache already on disk, so you see
reconciliation and writes rather than a live SEC crawl. Local `.env` is `LLM_MODE=mock`
(no Gemma on this laptop). The working-agent clip is the validated plan run through the
executor — same path graders use after Gemma emits the plan — and the Q3 clip is
`python -m agents.answer`, which returns `null` before the model. I did not restore
`output/` on camera; that run's parquet matches the committed SHA-1s.

Two spreadsheet CIKs were real filers but the wrong firms (Tudor → Wisconsin; Situational
Awareness → ARK). Baupost's given CIK stayed. Pershing Q2 is a 13F-NT; Bonus 1 pulls
fourteen rows from `PERSHING SQUARE INC.` accession `0001172661-26-003790` and drops the
one lot that does not list sequence 1. Bonus 2: after compacting CUSIPs to nine characters
against the 80-column official list, every Q2 `(accession, CUSIP)` pair is on the list.
I would not treat that as "filers never mistype" outside this slice.

## Video sharing

We may share your video publicly to show what candidates built. If you would rather we
did not, write "do not share" here:

- **Preference:** do not share
