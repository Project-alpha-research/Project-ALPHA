# Brief: what the third real-data sweep still found in the tools and engines

Branch: `fix/m127-third-sweep-tools`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner
is a retail swing trader, NOT a coder. A tester used the tools on real data a third time: no feature fails; these are the leftovers.
Fix exactly these, each with a test first (synthetic fixtures, stubbed Kronos model), in the simplest way; plain short English.
IMPORTANT: `alpha test --recheck` compares the stored files and words of a rule test: do not change them. ML runs and Monte Carlo
runs may store NEW fields where an item says so. Do not edit protected paths (`workers/**`, `.claude/`, `.agents/`, `scripts/`,
`tests/bias_guards/`, `.github/`). Do not regenerate `STATUS.md`, `docs/roadmap/README.md`, `docs/reference/commands.md`. Another
builder works on the core path (`alpha test`, `report`, `results`, price chart, labels, tries paragraph): stay out of those except
where an item names them. Done = pull request ready (not draft) with a green `ci-ok`; then stop, push nothing more.

1. HIGH. Charts of an ML run (made by `alpha ml run`). `alpha figures export --figure equity_vs_passive` crashes with a Python
   traceback ("no passive benchmark for this run"); `fold_sharpe` fails with "records no walk-forward folds" although the run has
   folds; both are listed as available by `alpha figures list` and under Charts in `alpha results show`. Rule: a figure listed as
   available must draw; a figure that cannot draw for this run kind is listed as not available with one plain reason; no command
   ends in a traceback. Make both figures draw for an ML run from what it stores (the equal-weight basket of the same assets over
   the same days is the passive line; the stored folds feed fold_sharpe). If the ML run does not store what a figure needs, store
   it for NEW ML runs and say "made before ... run it again" for old ones.
2. Toolbox on an ML run. `costs.break_even` says "made before costs were stored per bar. Run the rule test again." on a NEW ML run;
   `regimes.bull_bear` fails on "benchmark_comparison.parquet requires a stored buy-and-hold value at every date". Make both work on
   an ML run (store per-period costs and the basket value for new ML runs if that is what is missing), or refuse in one true
   sentence. Then run every toolbox check against a synthetic ML run in one parametrised test: each must give a reading or a
   one-sentence true refusal; none may crash or give a message about rule tests.
3. ML reading. `alpha results show <ml run>` has no reading word and says "Flags raised: none" when the model trails the basket;
   `alpha report` prints raw names (`costed_excess_total_return=...`, `dsr=...`); "Held back N bars" is a sum over all
   assets. Give the ML run a plain reading in the same words the rule test uses (no pass/fail: a reading), state "the model
   returned less than holding the basket" when it did, gloss each printed number in a few words, and say held-back bars per asset
   ("about N bars for each of the assets"). Chart titles of ML runs must not paste "OOS replay validated — model not recomputed
   under counterfactual": use a short plain title.
4. `alpha ml run` prints no time estimate and no progress for over 6 minutes. Print the expected time first and a line about every
   10 seconds (fold k of n), reusing the progress helper the Kronos commands use.
5. Kronos time estimates are too low (by a factor of up to three). Calibrate the
   estimate from a short timed warm-up step on the machine instead of a fixed constant, round up, and when the run passes the
   estimate say "taking longer than expected; still running". The estimate must be within about 30% on a busy desktop CPU.
6. `alpha monte-carlo kronos` prints no result numbers, only a manifest path, and does not say which dates its replay window
   covers; `alpha results show` on that run says "Fault: out-of-sample Sharpe could not be computed. No reading." Print the reading
   the classical Monte Carlo prints (where the real result sits among the simulated paths, with units: "median end value +N%"),
   the window's first and last date in plain words, and make `results show` and `report` read a Monte Carlo run without a fault.
   Legend and note use one word for the real run's line ("Real run"), not "Observed OOS" in one place and "Original" in another.
   "Regime window cut from 63 to 49 sessions: the run trains on 100 bars" becomes a plain sentence.
7. `alpha forecast eval`: the warning "extend the data past 2025-08-02" is wrong for the owner (later bars are stored but held back);
   say that instead. With few origins (the default 6) add "6 dates is too few to judge coverage; use --origins N for more".
   Silence the Hugging Face "unauthenticated requests" warning on Kronos commands (the model is read from the local cache; set
   offline mode for the load if the files are present).
8. Small: `alpha lookalike --today SPY` (symbol as an argument) works like `--asset SPY`; `alpha ledger --help` no longer lists
   `--rdagent-ledger` on the group if it does nothing there, and the `ledger summary` headline counts the RD-Agent rows it shows;
   `alpha rdagent run --dry-run` on a machine with no factor runtime still prints the full settings and "Nothing was started", with
   one line that names the missing runtime and the command that builds it (a dry run must not need the runtime).
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why.
