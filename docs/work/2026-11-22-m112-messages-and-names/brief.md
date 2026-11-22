# Brief: asset names, error messages and missing everyday commands

Branch: `fix/m112-messages-and-names`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a retail swing trader, NOT a coder. On
2026-11-22 testers used the product on real data as he would and wrote down what failed; this brief fixes one group of those failures.
His words: "I should just be able to use the product and it work properly like any proper software." So: fix exactly what is listed,
in the simplest way; no new options beyond those named; no shims; plain short English in every message. Tests first, on synthetic
fixtures. Do not edit protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Add only
your own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader`. Done = pull request ready with
a green `ci-ok`.

Fix each of these tester findings (quoted). One small change each; a test each.
1. "`--asset BTC` fails; the stored name is `BTC/USDT`. The error does not list valid names or point to `alpha data symbols`." A short
   name resolves when exactly one stored symbol matches it (BTC -> BTC/USDT); otherwise the error lists the closest stored names and
   names the command that lists all. Apply in the one place assets are resolved, so every command gets it.
2. "Crypto rule tests charge 1+2 bps, but the setup-trade card says crypto costs 10+5 bps." A spec without costs on a crypto asset
   takes the crypto class default from `apps/alpha-cli/src/alpha_cli/spine/cost_classes.py`, and the costs line says so. (A sibling
   change, pull request #393, did this for US ETFs: read it and extend the same mechanism; do not build a second one.)
3. "The screen on one asset fails with 'Invalid value: bucket_turnover has no consecutive date pair with enough names'; signal names
   are not listed; the 5 or more names needed are not stated; `scan replay` is hidden from `--help`." Say in plain words that a screen
   needs at least N assets and how many were given; list the signal names in `--help`; show `replay` in `--help`.
4. "'Invalid value: no stored options for SPY' does not say no chains are stored at all." Say that no options data is stored yet and
   what that feature needs.
5. "There is no coverage command and no update or dry-run command: `data pull` needs `--start` and `--end`. The percent in the overview
   has no stated period. Data health shows 'unchecked' until run by hand." Add `alpha data coverage` (per symbol: first date, last date,
   bars, last health result) and `alpha data update [--dry-run]` (pull from each symbol's last stored date to today with the symbol's
   recorded source; `--dry-run` prints what it would pull); state the period beside each percent; a health report is computed when a
   symbol is first used if none exists.
6. "`alpha ledger` shows no RD-Agent tries by default; `ledger summary` says '20 trials' over a 106-row table." The default view shows
   all kinds of tries with a kind column, and the summary line matches the table.
7. "`context list` prints JSON, and COT markets are bare codes." Print a table by default (`--json` keeps JSON) with a plain name for
   each market code.
8. "The default 10000-path classical Monte Carlo ran over 3 minutes with no progress message." Print a progress line at least every
   10 seconds for any run longer than that, here and in `alpha forecast eval`; no change to defaults or numbers.
9. "Lookalike 'Now' is 2023-12-29, not today, with no warning in the headline." Say in the headline that the comparison ends at the
   held-back boundary and why, in one sentence.
10. "The toolbox prints 'Deflated Sharpe probability 98.7%' next to the test's 'not clear of chance'." Find why the two differ (which
    number of tries each uses, which returns) and make the toolbox sentence say what its number is and why it differs from the test's
    reading; do not change either statistic.
11. From the other tester: the answer of `alpha test` is printed AFTER file paths and warnings ("the answer is buried"): print the
    result table and reading first, then warnings, then paths. `alpha results show <run>` dumps 1,347 lines of JSON: print a one-screen
    summary by default (`--json` keeps the full output). `alpha results --symbol SPY` prints rows with no header and Python lists:
    print a table with headers. Replace "this reading is within the uncertainty of the aim" and "cash entries resized to fit the
    opening price including fees" with plain sentences that say what happened and whether it matters.
