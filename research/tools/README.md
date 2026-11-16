---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
verified: 8c4ddc9b3d4e9532
---

# Research tools, by symptom

One card per tool that exists and runs today. Start from what you see, not from the tool you
already know. Every card says when to reach for it, the exact command, how to read the output,
what it cannot tell you and what to try next. The method is in [the playbook](../PLAYBOOK.md).

| What you see or need | Open |
|---|---|
| An idea to test | [rule test](rule-test.md) |
| "Did we test this?", "what was the number?" | [results and cite](results-and-cite.md) |
| The result looks too good | [diagnose and audit](diagnose-and-audit.md), then [random-price null](random-price-null.md) |
| The result looks too good after many tries | [deflated Sharpe and trials](deflated-sharpe-and-trials.md) |
| Big drawdown in a short period | [benchmark and drawdowns](benchmark-and-drawdowns.md), then the macro row below |
| Works in some years only | [benchmark and drawdowns](benchmark-and-drawdowns.md) (`by_year`), [walk-forward](walk-forward.md) |
| Few trades | [diagnose and audit](diagnose-and-audit.md) (`enough-trades`), [rule test](rule-test.md) on more assets |
| Profit from a handful of trades | [diagnose and audit](diagnose-and-audit.md) (`concentrated-profit`), [charts](charts.md) (`trade_pnl`) |
| Fragile to costs, to a one-bar delay or to nearby settings | [sensitivity](sensitivity.md) |
| "Is it just the market?" | [benchmark and drawdowns](benchmark-and-drawdowns.md) |
| "How bad could it get?" | [path risk](path-risk.md) |
| A picture for the owner | [charts](charts.md) |
| Need the macro picture | [macro context](macro-context.md); `macro_window` in [diagnose and audit](diagnose-and-audit.md) |

## Not available yet

Say "not available yet" and name the gap; never invent the output. Planned, not built:

- regime detection and change-point detection;
- factor and beta attribution (market, size, momentum, Bitcoin);
- capacity and size-aware costs (costs are flat basis points today);
- an event calendar (scheduled releases and earnings dates);
- an event study and random-date controls as plain commands (they exist only inside the older
  staged lane);
- a lessons search and counted variants;
- short selling, position sizing and intraday bars in the rule test (long or flat, all-in, daily bars);
- the planned plain verbs that would wrap these tools (get, idea, tool, vary, learn, promote): none is a
  command yet, so never type one; use the cards above.

## How to change it

A card is at most 40 lines and names only commands that exist: `tests/unit/test_research_playbook.py`
checks every command, option, metric, flag and audit name against the program. Add a card when a
tool starts to work; move a line out of "Not available yet" in the same change.
