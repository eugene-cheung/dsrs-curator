# Dependencies

Every library you added to `requirements-extra.txt`, with a one-line reason.

We are not counting libraries — a well-chosen dependency is better engineering than a
hand-rolled version of the same thing. What we are reading is whether you added each
one deliberately.

| Library | Version | Why |
|---|---|---|
| pytest | 9.1.1 | Runner for parser/CIK/agent tests (`LLM_MODE=mock`). Not imported by `main.py`. |

## Anything you considered and rejected

- **edgartools / sec-edgar-downloader / 13F parser packages.** They wrap retrieval and parsing end to end. The grade is the schema and the edge cases (namespaces, notices, CUSIP-as-string). `httpx` + `lxml` + `pyarrow` from the frozen set are enough.
- **pandas.** Easy to leak an index column and to coerce CUSIP/CIK to numbers. Rows go to Arrow directly.
- **rapidfuzz / jellyfish** for CIK names. A Jaccard on normalised tokens plus an "names agree?" check was enough; a fuzzy library would hide the threshold.

## Note

Libraries that wrap 13F retrieval and parsing end to end will not, on their own,
satisfy the schema or the quality report, and we will ask you to explain the edge cases
in your output regardless of how you produced it. If you can explain it, you own it.
