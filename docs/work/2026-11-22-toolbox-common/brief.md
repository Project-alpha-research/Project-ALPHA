# Common rules for the toolbox build-out (2026-11-22)

Read first: `docs/work/2026-11-21-common-build-rules/brief.md` (the general build rules) and `apps/alpha-cli/CONTEXT.md`.

Why: the owner's plan was a toolbox of about 100 checks that he, his AI and RD-Agent can run on any tested idea. Sixteen exist
(`uv run alpha tool list`). Each brief in this batch adds 10 to 14 more in ONE family. The owner is a retail swing trader on daily bars,
not a coder. He wants the product finished and working, not more process.

How a check is built (copy the existing pattern exactly; read two existing family files first, for example
`apps/alpha-cli/src/alpha_cli/toolbox/families/costs.py` and `trades.py`, plus `contract.py`, `inputs.py`, `registry.py`, `runner.py`):
- One `ToolSpec` per check in YOUR new module `apps/alpha-cli/src/alpha_cli/toolbox/families/<module>.py` (the module name is in your
  brief; split into `<module>_a.py`, `<module>_b.py` if a file would pass 300 lines). Export them as one tuple `CHECKS`.
- Register by adding exactly ONE import line and ONE `*CHECKS` entry in `registry.py`. Seven other builders add their own line at the same
  time, so keep that edit minimal. Do not edit `situations.py`, `sets.py`, the existing family files or the existing tool cards.
- Inputs come only from the shared loader (`Inputs`): the stored run's scored out-of-sample returns, trades, equity, bars already cut at
  the held-back boundary (2024-01-01). Never read bars or data yourself; `tests/unit/test_research_reads_are_cut.py` must pass unweakened.
  If a check needs an input the loader does not give (for example re-running the engine with another parameter), check whether an
  existing check already does it and reuse that path; if nothing does, leave that check out and list it in your report.
- A check gives a READING: numbers with a plain sentence that says what they mean and what they cannot tell. Never pass/fail, never a
  grade, never advice. Catalogue rows marked G (pass/fail test) are built as readings: report the statistic, its p-value or interval,
  and the reference level in words.
- Too little data (few trades, short history) gives a clear "too little to read" result with the count, never a number that looks sure.
- Deterministic: any random draw uses the seeded generator the contract passes in; the same run gives the same bytes.
- Where `packages/alpha-validation` or `packages/alpha-research` already has the statistic (catalogue status "have.code" or "partial"),
  CALL it; those packages are protected and must not be edited. New statistics are written in your module with numpy/scipy only.
- Each check counts as a toolbox run in the existing run record (the runner does this); do not add a second ledger.
- Tests first, one test file per module under `tests/unit/`: for EVERY check (a) a known-answer test on a small synthetic series whose
  answer you can state by hand or from scipy/statsmodels (floats with `pytest.approx(rel=1e-9, abs=1e-12)` or a stated tolerance for a
  random method), (b) the too-little-data case, (c) the repeat-is-identical case. A statistic with a published formula cites the paper
  or textbook in the docstring (author, year, equation).
- Words: each check has a one-line question as its description, like the existing ones ("How much after-cost profit remains without the
  best trades?"). Standard trading terms; no internal codes.
- Docs: one new tool card `research/tools/toolbox-<module>.md` (at most 40 lines) listing your checks with one line each. Do not touch
  `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`.
- Build the checks marked * (the ones that matter most for a daily-bar swing trader) first, then the rest of your family that run on a
  finished run (needs RUN, T, R or B), until you have at least 10. Skip rows that need a factor panel (F), several strategies (MS), a
  model (ML), an event list (E) or extra data (X); skip rows that an existing check already covers (see `uv run alpha tool list`).
- Done: pull request ready with a green `ci-ok`, and `report.md` in your task folder: a table check id -> catalogue row -> known-answer
  source; rows you skipped and why.
