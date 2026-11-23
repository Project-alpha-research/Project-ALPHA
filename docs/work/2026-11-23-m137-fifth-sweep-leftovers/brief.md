# Brief: the leftovers of the fifth acceptance sweep (small, last round)

Branch: `fix/m137-fifth-sweep-leftovers`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The
owner is a retail swing trader, NOT a coder. A tester re-ran what changed: no feature fails and no number is wrong; these few
items are left. Fix exactly these, each with a test first (synthetic fixtures, stubbed models), in the simplest way; plain short
English. Do not change what a rule test STORES (`alpha test --recheck` compares it). Do not edit protected paths (`workers/**`,
`.claude/`, `.agents/`, `scripts/`, `tests/bias_guards/`, `.github/`). Do not regenerate `STATUS.md`, `docs/roadmap/README.md`,
`docs/reference/commands.md`. Put this brief in the task folder on your branch. Write no number from a real run anywhere.
Before the pull request also run: `uv run pytest -q tests/unit/test_code_size.py tests/unit/test_filesystem_contract.py
tests/unit/test_research_playbook.py tests/unit/test_reserved_date_one_home.py tests/unit/test_spine_spec.py tests/smoke` (tests
that parse a command's JSON read standard output only; a function over its size ceiling is split, never the ceiling raised).
Done = pull request ready (not draft), green `ci-ok`; then stop, push nothing more.

MEDIUM
1. `alpha results` (the list) shows an ML run as "recorded without a reading" with empty Sharpe columns, while `alpha report` on
   the same run gives its Sharpe, the basket's Sharpe and a reading word. The list must show for an ML run the same reading word
   and out-of-sample Sharpe that `alpha report` shows (one source for both), and likewise a short reading for forecast and Monte
   Carlo runs (what `alpha results show` says in its first sentence). Add a test that an ML, a forecast, a forecast-eval and a
   Monte Carlo run each appear in the default list with a reading.
2. `alpha monte-carlo kronos` with few paths still prints "100% of paths end with a loss" (and the like). With fewer than 20
   paths never print a percentage of paths: say "all 8 simulated paths ended with a loss; 8 paths is too few to rank" (or "5 of
   8"). Apply this to every line of that output and to the stored reading of NEW Monte Carlo runs.
3. `alpha monte-carlo kronos` needs `--from-run` and `--forecast-eval-run`, and the help does not say where the second id comes
   from. Help and the missing-option message say: "run `alpha forecast eval <SYMBOL>` first (a few minutes); it prints the id".
   If exactly one stored forecast-eval run fits the source run (same symbol, same bars), use it by default and say so.
4. `alpha test --recheck` prints no estimate and no progress for minutes: use the same progress helper as a normal test.
5. `alpha ml run` progress never says which fold it is on. The worker that trains is under a protected path and reports nothing
   until it ends: do NOT edit it. Instead say honestly what is known: "Model training: fold count N; this stage reports when it
   ends", then the closing stage. If the worker already writes per-fold files as it goes that the CLI may read without touching
   the worker, count them for "fold k of N"; if not, leave it at the honest sentence and say so in the report.
6. `cost_realism.cost_sweep` on an ML run: its values print as fractions beside a sentence in percent, and its no-cost figure
   differs slightly from "Return before costs" in `alpha report` with no reason given in ITS output. Print percents, and add the
   half sentence the report already has about the basis ("from the account's fills with costs added back; `alpha report` uses the
   planned weights").

LOW (a line or two each)
7. ML, forecast and Monte Carlo readings get a "What decided it" line like rule tests (from the stored reading's own fields; if a
   run kind has nothing that decides it, say "Nothing decides a reading for this kind of run: it is a description").
8. `alpha diagnose`: "Price noise" and "Opposite rule" show a Sharpe that differs in the second decimal from the headline; say
   why in half a sentence (a re-run on the full sample against the out-of-sample figure, or whatever is true) or show the same.
9. `alpha forecast run` prints picture files named `<figure>.<hash>.png`: export them as `<figure>.png` like the other figures.
   The fan's y-axis label "Kronos synthetic OHLCV equity (x)" becomes plain ("Account value on simulated prices (1 = start)").
10. The tries paragraph ends "plus these: N.": make it a sentence that says what N counts. `alpha tool run` never prints
    scientific notation.
11. `alpha data update --dry-run` repeats the same note once per symbol: print it once.
12. `alpha ledger summary` "By kind" includes the ML tries.
13. `alpha ml run` missing-symbol lines print `<date>` placeholders: fill in the spec's own start date and today's date.
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why. No real-run numbers.
