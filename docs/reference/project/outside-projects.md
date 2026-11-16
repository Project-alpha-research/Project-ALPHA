---
owner: project layer
sources:
  - pyproject.toml
  - packages/*/pyproject.toml
  - apps/*/pyproject.toml
  - workers/*/pyproject.toml
  - workers/rdagent/source_pin.py
  - apps/alpha-web/frontend/package.json
  - docs/adr/0051-glue-rules-for-outside-projects.md
verified: 4be27286a617a963
---

# Outside projects: the register

Every open-source project ALPHA uses or has judged, in one table. An *outside project* is any
library, engine or tool ALPHA did not write. How one is chosen and joined is decided in
[ADR-0051](../../adr/0051-glue-rules-for-outside-projects.md) (the glue rules); what a proposal
must record is in [ADR-0011](../../adr/0011-evidence-gated-external-integrations.md).

## How to read it

- **How it is glued.** *Imported in X*: the main install, used by package X. *Own worker*: a
  separate program with its own install and lock file. *Vendored*: a copy of the project's
  files kept inside ALPHA. A dash means it is not in ALPHA.
- **State.** *In use*: installed and called today. *Approved, not yet added*: the owner approved
  it on 2026-11-15; it arrives in its own pull request. *Later*: fits a row that is not being
  built yet. *Reference only*: worth reading, never installed. *Refused*: judged and turned
  down; ask again only with new facts.
- Judgements of projects not in ALPHA were made on 2026-11-15 from their public package pages.
  None of those projects was installed or run against ALPHA.

## The register

| Project | What it does for ALPHA | How it is glued | State | Reason |
|---|---|---|---|---|
| RD-Agent | The AI research loop: proposes, codes and repeats ideas | Own worker; one pinned commit | In use | Core engine; ALPHA judges its output |
| RD-Agent's own libraries (LiteLLM, others) | Let RD-Agent run | Its runtimes, checksum-locked | In use | Come with the engine; ALPHA never imports them |
| Ollama | Text embeddings for RD-Agent, on this machine | Separate program, behind ALPHA's model gateway | In use | Keeps that step local and free |
| Qlib (`pyqlib`) | Trains models that rank stocks; standard features | Own worker, exact pins | In use | Mature toolkit; ALPHA replays its predictions |
| LightGBM, CatBoost, XGBoost | The model types Qlib trains | Qlib worker | In use | Qlib's standard models |
| Plotly, Graphviz | Drawing libraries Qlib needs | Qlib worker | In use | Required by Qlib, not used by ALPHA itself |
| MLflow | Qlib's own experiment notebook | Qlib worker only, brought by Qlib | In use | Fine inside the worker; refused in the main install |
| NautilusTrader | Simulates orders, fees; paper sessions | Imported in `alpha-backtest`, `alpha-strategies`, `alpha-cli` | In use | The one backtest engine |
| Kronos | Draws possible future price paths | Vendored in `alpha_forecast/_vendor` | In use | Upstream publishes no package |
| PyTorch and its helpers | Run the Kronos model | Imported in `alpha-forecast` | In use | Kronos needs them |
| Polars | Tables of data in every calculation | Imported across packages | In use | ALPHA's one dataframe library |
| pandas | Tables at three named edges only | Imported in `alpha-data`, `alpha-validation`, `alpha-forecast` | In use | Some libraries speak only pandas |
| numpy, SciPy | The arithmetic under the statistics | Imported in the numeric packages | In use | Standard, well tested |
| PyArrow | Reads and writes Parquet data files | Imported in `alpha-cli` | In use | The file format of the store |
| Matplotlib | Fixed, repeatable charts | Imported in `alpha-research`, `alpha-validation`, `alpha-cli`; AFML worker | In use | Same picture every run |
| quantstats-lumi | Draws one HTML performance report | Imported in `alpha-validation` (one file) | In use | Pictures only; never a judged number |
| exchange_calendars | Knows each market's trading days | Imported in `alpha-data`, `alpha-cli` | In use | Use more: year length from the calendar |
| yfinance | Free daily stock prices from Yahoo | Imported in `alpha-data` | In use | Free source for the Dell phase |
| ccxt | Prices from crypto exchanges | Imported in `alpha-data` | In use | One client for many exchanges |
| pydantic, pydantic-settings | Checked settings and records | Imported in `alpha-core` and above | In use | Catches malformed data early |
| Typer | Builds the `alpha` command | Imported in `alpha-cli` | In use | Small and standard |
| webauthn | Checks the owner is present (fingerprint) | Imported in `alpha-cli` | In use | Standard for that check |
| FastAPI, Uvicorn, Starlette, sse-starlette, AnyIO | The web server behind the Workstation | Imported in `alpha-web` | In use | Standard web stack |
| MCP SDK (`mcp`) | Lets AI clients call ALPHA's tools | Imported in `alpha-mcp` | In use | The standard for that link |
| React, TanStack Table and Virtual, cmdk | The Workstation's screens | Browser code in `alpha-web/frontend` | In use | Standard building blocks |
| lightweight-charts | Price charts in the Workstation | Browser code in `alpha-web/frontend` | In use | Use more: mark every setup match on the chart |
| BokehJS | Other charts in the Workstation | Browser code in `alpha-web/frontend` | In use | A second chart library; one per chart kind is the aim |
| pypdf | Reads the text of research papers | Literature worker | In use | The worker's one dependency |
| RiskLabAI 3.2.0 | Textbook label and weight methods | Own worker, `workers/afml` | In use | Primary; must agree with quantowl |
| quantowl 0.1.6 | A second writing of the same methods | AFML worker, commit `37a17de` | In use | Not on PyPI; young, never trusted alone |
| statsmodels 0.14.6, numba 0.68.1, scikit-learn | Libraries the two above need | AFML worker only | In use | RiskLabAI needs statsmodels below 0.15 |
| pytest, Hypothesis, mypy, ruff, import-linter | Tests and code checks | Development tools only | In use | Never part of a result |
| statsmodels | Regression, factor exposure, regimes | For `alpha-validation` | Approved, not yet added | Closes missing rows; replaces hand-written code |
| arch | Block bootstraps and best-of-many checks | For `alpha-validation` | Approved, not yet added | Proven maths; replaces two ALPHA files |
| ruptures | Finds dates where behaviour changed | For `alpha-validation` | Approved, not yet added | New ability; needs only numpy and SciPy |
| DuckDB | Asks one question across many stored files | For `alpha-cli`, in memory only | Approved, not yet added | A query tool, never the store |
| pandas-datareader | Downloads the Fama-French factor series | For `alpha-data` | Approved, not yet added | That one reader only; lightly maintained |
| STUMPY | Finds chart stretches that look like an example | To be chosen | Approved, not yet added | Fixed, declared threshold only; see notes |
| skfolio | Sizes a basket of positions | — | Later | When baskets need real sizing; heavy |
| alphalens-reloaded | Report pages for mined factors | — (a worker, if adopted) | Later | Leans on pandas; not for the main install |
| edgartools | Company figures from official filings | — | Later | Needs the owner's contact email; filing dates to check |
| alpaca-py | Talks to a broker practice account | — | Later | At the paper phase; could shrink ALPHA's adapter |
| pandera | Checks the shape of stored tables | — | Later | Only for the generic checks |
| TA-Lib | Standard indicators | — (tests first) | Later | As a comparison for ALPHA's own indicators |
| linearmodels | Factor regressions across many assets | — | Later | Same author as arch; one later row |
| QuantLib | Options pricing | — | Later | Large; only when options work starts |
| Vollib, FinancePy | Options maths | — | Later | Possible comparison or worker (ADR-0011) |
| inspect-ai | Scripted checks of an AI's whole journey | — | Later | Not yet studied in depth |
| apprise | Sends alerts | — | Later | Trading-phase work; not yet studied in depth |
| Machine Learning for Trading (book code) | A map of the ideas on ALPHA's checklist | — | Reference only | Notebooks for a book, not a library |
| open-code-review (Alibaba) | A second reader of code changes | — | Reference only | Trial found nothing ALPHA's reviewers missed; see notes |
| OpenBB | Ideas for a data-provider layer | — | Reference only | Dozens of packages; ADR-0011 decided this |
| TradingAgents, FinGPT, FinRobot, TensorTrade | Examples of AI trading agents | — | Reference only | Promise results; short tests; no trading authority |
| TimesFM, Chronos | General forecasting models | — | Reference only | A possible comparison for Kronos, later |
| PyBroker, mlfinpy | Ideas ALPHA already has with tests | — | Reference only | Too small, or mlfinpy needs numpy 1 |
| FinRL | Trains trial-and-error trading agents | — | Refused | A teaching framework; heavy; closes no row |
| vectorbt | A fast backtest engine | — | Refused | Conflicts with ALPHA's pandas pin; a second engine |
| bt, backtesting.py, zipline-reloaded, backtrader, Lean | Backtest engines | — | Refused | ALPHA has one engine and must judge with it |
| Freqtrade, Jesse, Hummingbot | Whole crypto trading bots | — | Refused | A second system with its own store and rules |
| pyfolio-reloaded, empyrical-reloaded | Performance reports and measures | — | Refused | Repeat what ALPHA already computes and draws |
| quantstats (the original) | The report library the fork came from | — | Refused for now | Recent corrections to its numbers; revisit after a quiet spell |
| MLflow in the main install | A second record of experiments | — | Refused | ALPHA is the record |
| Optuna | Automatic search for the best settings | — | Refused | Multiplies trials that must each be counted |
| hmmlearn | Regime models | — | Refused | In limited maintenance; statsmodels covers it |
| tsfresh | Makes hundreds of features automatically | — | Refused | Works against counting trials; Qlib supplies features |
| pandas-ta | Indicators | — | Refused | No maintained release found; re-check before any reuse |
| pandas_market_calendars | Trading calendars | — | Refused | Wraps what exchange_calendars already gives |
| Great Expectations | Data quality checks | — | Refused | Heavy; pandera would do the job |
| fredapi | Downloads macro series | — | Refused | Stale; ALPHA keeps its own dated store |
| ib_async | Talks to Interactive Brokers | — | Refused | Nautilus already carries that link |
| lightweight-charts-python, getFamaFrenchFactors, sec-edgar-downloader | Wrappers, downloaders | — | Refused | Stale, or do less |
| mlfinlab 0.12.3 (public archive) | The textbook methods, older code | — | Reference only | Answer key when the two disagree; needs pandas 1 |

## Notes on single rows

- **STUMPY** is a matrix-profile library: it compares every stretch of a price series with an
  example and scores how alike they are. Its default cut-off for a match is worked out from the
  whole series, so it uses later data. The adapter must take a fixed threshold stated before the
  search and must never fall back to the default.
- **open-code-review** was tried on two ALPHA branches. In the only mode that does not send code
  to a model provider it mostly filters the list of changed files and attaches a checklist per
  folder. Against the same branches it found 2 of the 10 and 2 of the 7 defects ALPHA's own
  reviewers found, and nothing they missed. Its launcher updates itself silently unless that is
  switched off, which breaks rule 4. Worth borrowing as ideas: checklists aimed at a path, and a
  required list showing every file was covered. Revisit when its higher-recall mode ships.

## Changing this file

- Add or change a row in the same pull request that adds, upgrades, removes or judges a project.
- A project moves to *In use* only with its adapter, its contract test and its smoke test
  (rule 6 of the glue rules), and to *Refused* with a reason a later session can check.
- Versions are not repeated here: the exact ones are in each `pyproject.toml` and lock file.
- Licences of what is installed are in the
  [dependency and licence matrix](../../governance/2026-07-19-dependency-license-matrix.md);
  the Qlib worker also keeps a [notices file](../../../workers/qlib/THIRD_PARTY_NOTICES.md).
