# Brief: a rule test's numbers agree with each other

**Build class:** hard

## Task

The rule-test Summary (PR #267) now shows the strategy, but a real run exposed numbers that
disagree on one page. A reader cannot trust a result whose own figures conflict. Find the cause
of each disagreement below and fix it at the source (the run's stored numbers and figures), not
by hiding it on the screen. No strategy logic, cost rule or statistic definition changes.

Observed on one real 50/200-day moving-average run on a US index fund (do not copy numbers into
the repository; build synthetic runs that reproduce each fault):

1. **Two periods on one page.** The tiles (total return, return per year, worst drop,
   buy-and-hold) cover the full history; the charts and their captions cover only the scored
   walk-forward test period. Worst drop read −27.5% in a tile and −25.9% in the chart below it;
   buy-and-hold read 1616.9% in a tile and 16.56× in the chart.
2. **The comparison chart contradicts itself.** Its caption said the strategy "finished at
   16.38x against 16.56x for the passive price index — behind it by 1.1%", while the excess
   panel beneath ended labelled −43.3%. Find what each number is (difference of cumulative
   returns? ratio? peak-relative?) and why they differ; one of the labels or series is wrong or
   misnamed.
3. **Buy-and-hold leaves out dividends.** The passive line is an open-to-open price index, so
   for a dividend-paying fund it understates holding. The strategy's own returns: do they
   include dividends while it is in the market? If the strategy gets dividends and the
   benchmark does not (or the reverse), the comparison is biased.
4. **The headline dates are the data range**, not the period the rule could first trade
   (indicators need a warm-up), and not the scored period.
5. **Stored figures are drawn dark** although the Workstation default is light.

## Read first

| Read | Section | When |
|---|---|---|
| `apps/alpha-cli/CONTEXT.md`, `research/tools/rule-test.md`, `research/tools/benchmark-and-drawdowns.md` | whole | always |
| `apps/alpha-cli/src/alpha_cli/spine/` (`run.py`, `facts.py`, `diagnostics.py`, `diagnose.py`) | which period each stored fact covers; how buy-and-hold is computed | always |
| `apps/alpha-cli/src/alpha_cli/validate_cmds.py`, `_artifacts.py` | what the run stores: equity, benchmark comparison, figures | always |
| the figure code that draws "Strategy versus passive" and "Equity and drawdown" (search those titles) | captions, the excess panel, theme | items 2, 5 |
| `packages/alpha-data/src/alpha_data/corporate.py`, the source/PIT reader | how dividends reach prices and returns | item 3 |
| `apps/alpha-web/frontend/src/rundetail/RuleTestReport.tsx`, `ruleTestModel.ts` | what the Summary reads | screen |

## Decision already made

1. **One declared period per number.** Every stored headline fact carries the period it covers
   (`full_history`, `tradable` = after indicator warm-up, or `scored` = the walk-forward test
   periods), with start and end dates. The Summary's tiles and the charts beneath them use the
   SAME period: the tradable period for the headline row (what the rule did over all the time
   it could trade), with the scored-period figures shown as a clearly titled second row
   ("Scored test periods only"), each row with its dates. If a needed figure for a period is
   not stored, store it for new runs; old runs show "not recorded" for it.
2. **The comparison chart is consistent.** The caption, the end labels and the excess panel use
   one definition, named in plain words on the chart (recommended: "ahead of / behind buy and
   hold" = strategy growth ÷ buy-and-hold growth − 1, as a percent). Add a test that the last
   point of the excess series equals the figure in the caption on synthetic data.
3. **Like-for-like benchmark.** Establish and document in the tool card whether prices are
   adjusted for dividends in the strategy's returns. Then make buy-and-hold use the same price
   basis as the strategy (both total-return when adjusted data is used; both price-only
   otherwise), and label the basis on the tile and the chart ("with dividends" / "price only,
   no dividends"). Where the data cannot support a total-return benchmark, keep the price-only
   one, label BOTH lines' basis, and add the run label `benchmark-price-only`. Prove with a
   synthetic dividend-paying series that an always-invested rule equals buy-and-hold to 1e-9
   under the like-for-like basis (minus costs).
4. **Headline dates** state the tradable period ("could trade from … to …"); the data range is
   shown smaller as "data from … to …".
5. **Figures are stored light by default** for new runs (use the existing light figure theme
   the journey figures use); a dark variant remains available by option. Old runs keep their
   stored figures.
6. Old runs stay readable: missing new fields show "not recorded", never a guess.
7. Tests fail first for each item, on synthetic runs. Update the tool cards so they say which
   period and price basis each number uses. Delete code this replaces (for example a second
   buy-and-hold computation) and name it in the report.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/spine/facts.py`
- `apps/alpha-cli/src/alpha_cli/spine/diagnostics.py`
- `apps/alpha-cli/src/alpha_cli/spine/run.py`
- `apps/alpha-cli/src/alpha_cli/validate_cmds.py`
- `apps/alpha-cli/src/alpha_cli/_artifacts.py`
- `apps/alpha-web/frontend/src/rundetail/RuleTestReport.tsx`
- `apps/alpha-web/frontend/src/rundetail/ruleTestModel.ts`
- `research/tools/rule-test.md`
- `research/tools/benchmark-and-drawdowns.md`
- `apps/alpha-cli/CONTEXT.md`

This decision overrides the standing rule for: other modules under
`apps/alpha-cli/src/alpha_cli/` that compute or draw these facts and figures (the figure
painters for the two charts, result/“results show” readers); `apps/alpha-web/` backend reader
and frontend test/style files for the rule-test report, plus generated API files if a response
model changes (follow the route-change steps in `apps/alpha-web/CONTEXT.md`); test files under
`tests/unit/` and `tests/smoke/` for rule tests, facts, figures and the report; generated pages
the capability/command tests require (regenerate with the scripts); any living document
`scripts/fs.py stale` reports because of your edits (verify with a real text change or
`--reason`). If a named file does not exist, use the real one. List each in the report; do not
stop to ask. Where a fault's cause lies under `packages/` (for example the engine's dividend
handling), do not edit `packages/`: report the cause precisely and apply the labelled fallback.

## Do not touch

`packages/**` (read only), `workers/**`, `tests/bias_guards`, `tests/oracles`, golden files and
browser baselines, `.semgrep/`, `.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`. Cost
rules, the walk-forward split, statistic definitions, grade rules. No `nosemgrep`, `noqa`,
`type: ignore`, `eslint-disable`, `vars(`, `__doc__`, `inspect`, `.__dict__`. Functions ≤ 150
lines, files ≤ 1,500 lines; tests fully type-annotated; no test file named `*fixups*` or ending
`_<N>.py`. No negative shifts.

## Checks

- `uv run pytest -q tests/unit -k "spine or facts or rule or benchmark or figure or artifacts or code_size or filesystem or docs_links"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

Also the frontend lint, type-check and unit tests named in `apps/alpha-web/CONTEXT.md`.

## Report

Per item: the cause in one or two sentences with file and function; the fix; the test. For
item 2: what −43.3% and −1.1% each were. For item 3: exactly how dividends enter strategy
returns and the benchmark today, and what basis each uses after the fix. Fields added to stored
runs. Code deleted. Every file outside the list. What old runs show. What is unverified.
