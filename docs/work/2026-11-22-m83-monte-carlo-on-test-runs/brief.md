# Brief: the four Monte Carlo families read an `alpha test` run

Branch: `feat/m83-monte-carlo-on-test-runs`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: the project retires the old commands `alpha backtest`, `alpha optim` and `alpha validate` later. The Monte Carlo commands
(`alpha monte-carlo classical` and the three other families; guide `docs/operations/monte-carlo/README.md`) must first be proven on runs
written by the new pipeline, `alpha test <spec.toml>` (code under `apps/alpha-cli/src/alpha_cli/spine/`). The Monte Carlos are a named
feature: never remove or weaken them.

Build:
1. Find out, with tests on a synthetic store, whether each of the four families accepts the run id of an `alpha test` run (a rule test,
   and an owner-rule test) and reads its out-of-sample returns or trades correctly. Where one does not, make it work through the one
   shared run reader; do not add a second reader.
2. The numbers must come from the stored run only: no bar is re-read at or after the held-back boundary, and the seed and settings are
   stored so the result repeats byte for byte (add a repeat test).
3. Output is a reading: percentile bands and the original path, in plain words; no pass/fail word. Say on the output which run and which
   period (out-of-sample only) the paths were built from, and how many trades or days; refuse with a clear message when there are too few.
4. Port the cases of `tests/unit/test_monte_carlo_cli.py` (and the integration twin if there is one) that start from `alpha backtest` so
   they start from `alpha test`; keep each assertion at least as strong. Do not delete the old command in this pull request.
5. Add the tool cards / `research/tools/` text so an agent knows it can run each family on an `alpha test` run id.

Done: pull request ready with `ci-ok` green, and `report.md` in this folder with a table: family, worked before, works now, test name.
