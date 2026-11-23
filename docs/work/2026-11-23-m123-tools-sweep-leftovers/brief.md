# Brief: what the second real-data sweep still found in the tools and engines

Branch: `fix/m123-tools-sweep-leftovers`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner
is a retail swing trader, NOT a coder. A tester used the tools and engines on real data a second time: 9 of 14 features pass, none
fails outright; these are the leftovers (Kronos is handled elsewhere: do not touch `alpha forecast` or `alpha monte-carlo kronos`).
Fix exactly these, each with a test first (synthetic fixtures), in the simplest way; plain short English in every message.
IMPORTANT: stored run files and stored reading words are compared by `alpha test --recheck`: do NOT change any stored text or file
content of an existing run kind; change what is PRINTED, and what NEW ML runs store only where an item says so. Do not edit protected
paths (`workers/**`, `.claude/`, `.agents/`, `scripts/`, …): if a fix needs one, leave that part and say so in `report.md`. Do not
regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Done = pull request ready with a green `ci-ok`.

1. ML runs (made by `alpha ml run <spec>`) cannot be read back. `alpha results show <run>` says "Fault: the out-of-sample Sharpe could
   not be computed. Fix this first. No reading." although the run printed a Sharpe; `alpha report <run>` shows `[?]`; every toolbox
   check refuses with "Run … was not made by alpha test"; the run's own output is raw dict lines (26 folds). Make an ML run a
   first-class stored run: `alpha results show` and `alpha report` give its reading in plain words (the split sentence, assets,
   model, costs, out-of-sample Sharpe against buy-and-hold of the same basket over the same days, the try count); the fold table is
   printed as a table; and every toolbox check that needs only the stored equity, returns or trades of a run accepts an ML run (a
   check that needs a single rule's bars or settings says in one sentence why it does not apply). Find the one place where "was made
   by alpha test" is decided and widen it by what the check needs, not by run kind.
2. `alpha rdagent run --dry-run` fails on a machine with no factor runtime; its message says to set `ALPHA_FACTOR_PYTHON`, but that
   variable is ignored once an `rdagent.toml` exists. One rule: an explicit environment variable wins over the file, the file wins over
   the default; the message names the setting that was used and its source. `alpha rdagent init` prints, for each missing part, the
   exact command that installs it.
3. RD-Agent tries: `alpha ledger summary --rdagent-ledger <path>` works only with the flag before the subcommand, and the default path
   works only on the real home. Accept the flag after the subcommand too, and resolve the default RD-Agent ledger with the same rule
   the Workstation uses (`apps/alpha-web/src/alpha_web/api/rdagent.py`), so `alpha ledger` shows RD-Agent tries by default wherever
   the Workstation shows them.
4. Stale guidance: `alpha next` still says to hand-write a spec and to copy `rdagent.example.toml`; `research/tools/data.md` lacks
   `coverage` and `update`; there is no card for `alpha rdagent init`. Fix `alpha next`'s text; fix the data card; add
   `research/tools/rdagent-setup.md` (at most 40 lines) and link it. The start-here skill file may live under a protected folder: if
   so, write the corrected text into your report and leave the file.
5. `alpha context show` prints JSON: print a table by default (`--json` keeps JSON), like `context list` now does.
6. A Setup Lab context condition still needs a hand-written TOML: `alpha setup find|study|trade` and `alpha setup new` accept
   `--context "<condition>"` (the same expression language the spec's `[context]` section uses) and write it into the spec.
7. `alpha monte-carlo classical` at its default 10,000 paths takes about 7 minutes. Make 2,000 the default, say in the output that
   10,000 is available and about how long it takes, and print the time estimate before it starts.
8. Lookalike cannot be run on today's chart (it stops at the held-back boundary, which is right for research). Add a clearly separate
   forward-use mode, `alpha lookalike today <SYMBOL>` (or `--today`), that compares the most recent bars with the history BEFORE the
   boundary only, is labelled "forward use: a look at today, not a test", writes no research run and no try, and lives beside the
   other forward-use code (follow, today, market view) so `tests/unit/test_follow_separation.py` and
   `tests/unit/test_research_reads_are_cut.py` pass unweakened. If those guards make this impossible without weakening them, leave
   it out and say so.
9. The toolbox prints "Deflated Sharpe probability 99.9%" beside the test's "not clear of chance". State under the number, in one
   sentence, which tries it counts and why the test's reading can still be "not clear of chance" (the test also weighs the random
   price tests and the trade count). Do not change either statistic.
Report: per item the cause in one sentence, the change, the test; anything you could not fix and why.
