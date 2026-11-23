# Brief: the last rough edges from the fourth acceptance sweep

Branch: `fix/m134-fourth-sweep-polish`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The
owner is a retail swing trader, NOT a coder. Two testers used every feature a fourth time: no feature fails and no number is
wrong. These are the leftovers. Fix exactly these, each with a test first (synthetic fixtures, stubbed models), in the simplest
way; plain short English. Do not change what a rule test STORES (`alpha test --recheck` compares it); ML and Monte Carlo runs may
store new fields. Do not edit protected paths (`workers/**`, `.claude/`, `.agents/`, `scripts/`, `tests/bias_guards/`,
`.github/`). Do not touch `apps/alpha-web/frontend` (another builder is deleting windows there). Do not regenerate `STATUS.md`,
`docs/roadmap/README.md`, `docs/reference/commands.md`. Put this brief in the task folder on your branch. Before the pull request
also run: `uv run pytest -q tests/unit/test_code_size.py tests/unit/test_filesystem_contract.py
tests/unit/test_research_playbook.py tests/unit/test_reserved_date_one_home.py tests/unit/test_spine_spec.py` (a function over its
size ceiling is split, never the ceiling raised). Done = pull request ready (not draft), green `ci-ok`; then stop, push nothing more.

MEDIUM
1. Time estimates are off by a factor of two to four, in both directions. One helper, used by `alpha test`, `alpha ml run`,
   `alpha monte-carlo kronos`, `alpha forecast run|eval`: the estimate must come from something measured on this machine in this
   run, not a constant. `alpha test`: a spec file with two assets and several variants takes far longer than a built-in rule but
   gets the same estimate: estimate from the count of assets x variants x folds and a timed first unit of work. `alpha ml run`
   over-estimates: use the first fold's measured time x folds left, and re-state it once after fold 2. `alpha monte-carlo kronos`
   over-estimates because it ignores batching: use the batched warm-up timing the forecast commands already use; the
   "--paths 32 takes about N" tip must come from the same formula. Target: within about 30% on a busy desktop CPU. A
   stubbed-clock test for each.
2. `alpha ml run` progress stops counting folds about two thirds of the way through although the run goes on for minutes: the
   line must keep counting to the last fold and then name the closing stage ("scoring", "writing the run").
3. On an ML run three outputs give different figures for what costs did, with no explanation: the return before costs in
   `alpha report`, the no-cost return in `cost_realism.cost_sweep`, and the cost share in `costs.break_even` (which does not
   equal the gap between the gross and net returns that `alpha report` prints). Find out which is which (compounded against
   summed returns? a different cost basis?). If one is wrong, fix it. If all are right, each output says in a few words what it
   measures ("share of summed per-period gross profit", "compounded return"), so the three can be read side by side. Add a test
   on a tiny fixture with a hand computation.
4. `alpha results` (the list) fills with toolbox rows: each check appears twice, labelled "fault", and hides the real tests.
   The default list shows tests, ML, forecast and Monte Carlo runs only; a tool reading belongs to its run (`results show <run>`
   lists them) and is in the list only with `--tools`. No tool reading is labelled "fault" unless it is one.
5. `alpha-web --help` starts the server. It must print help (what it is, `ALPHA_WEB_PORT`, `ALPHA_DATA_DIR`, the address it
   serves) and exit; add the same facts to the Workstation card or README a user reads. This file is under `apps/alpha-web/src`.
6. `alpha ml run` stops at the first symbol that is not stored and names one at a time: name ALL missing symbols at once with the
   exact `alpha data pull <SYMBOL> --start <date> --end <date>` line for each, and say the alternative (edit the list in the spec).
   The ML card says the same in two lines.
7. `alpha test --json`: the data-health hint field still says `uv run alpha data health`: say `alpha data health`. Grep every
   user-facing string for `uv run alpha` and fix the rest the same way (stored text of existing runs stays as stored).

LOW (one or two lines each)
8. Tries paragraph: split the one long sentence into two or three short ones. One heading for the deciding sentence
   ("What decided it") whatever the reading is.
9. Results list: dates as `YYYY-MM-DD HH:MM`, no microseconds; the flags column has a header.
10. `alpha diagnose` can show a Sharpe that differs in the second decimal from the one `alpha test` shows for the same run: say
    why in half a sentence or show the same number.
11. `alpha tool run`: round floats to a sensible number of digits; money values carry a unit; the "ad-hoc" and "exploratory"
    labels print with their meaning; a check on a model run says "the model", not "the rule".
12. `alpha figures list <run>` works with the run as an argument. Figure file names: `<figure>.png` in the run's figure folder
    when exported for the owner (the hash may stay in a cache name, not in the name the user sees).
13. ML fold picture numbers folds 1 to n, like the text. Cone and fan titles use plain names, not `forecast_run` /
    `ma_crossover`; the fan's x axis is dates when the window's dates are known.
14. Kronos Monte Carlo with few paths: do not print "above 100% of paths" from 8 paths; say "above all 8 simulated paths, which
    is too few to rank" and state the window's dates beside it.
15. `alpha options derived` wrong-input message is not headed "Invalid value"; `alpha crypto-data coverage` error is one plain
    sentence; `alpha data coverage` says why a symbol is "out of date" (newest stored bar against the newest closed session);
    `alpha data update --dry-run` says it would pull only the days after the newest stored bar, if that is what a real update
    does (if a real update re-pulls everything, say so and why).
16. `alpha ledger summary` headline counts the ML tries and RD-Agent tries it lists below.
17. Propfirm: a negative money value prints with the minus sign before the currency sign; when a futures preset is used on a
    stock or ETF run, say so in one sentence.
18. `trade_pnl` figure axis label says the account size it assumes.
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why. No real-data numbers.
