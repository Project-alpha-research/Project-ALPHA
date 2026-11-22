# Brief: toolbox family G, parameter and specification robustness (with engine re-runs)

Branch: `feat/m117-parameter-robustness`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main and
`docs/work/2026-11-22-toolbox-common/brief.md` on branch `work/m102-briefs` (read both first), and the earlier report
`docs/work/2026-11-22-toolbox-g-parameters/report.md` on main (why the first attempt built nothing).

Why: the owner asked for "permutation, parameter sensitivity" by name. The toolbox now has 101 checks, but none can re-run a rule with
other settings, so parameter robustness is missing. The earlier builder found the cause: the toolbox loader gives a check the stored
results only, not the bars, the idea spec or the run spec.

Build:
1. The loader (`apps/alpha-cli/src/alpha_cli/toolbox/inputs.py`, `contract.py`): a check may declare that it needs "a re-run". For
   such a check the loader also gives the bars and dividends the run used (loaded exactly as `alpha test` loads them, cut at the
   held-back boundary through `alpha_cli.spine.reserve`, and checked against the run's stored data fingerprint: on a mismatch the check
   refuses in plain words), the stored idea spec and run spec. `tests/unit/test_research_reads_are_cut.py` must pass unweakened, with
   one named entry for this read if the guard needs one. The cache key of such a check includes the data fingerprint.
2. One shared helper for re-runs that reuses the existing code (`spine/diagnose.py`: `variant_specs`, the full-sample engine run) and
   the worker pool; do not write a second engine path.
3. EVERY re-run is a try. Each parameter set a check evaluates is appended to the one trial ledger through the existing writer,
   exactly as the diagnostics variants are, BEFORE its result is shown, so the try count and the deflated Sharpe see it; an identical
   re-run of the same check on the same run adds nothing. State in each check's output how many tries it added.
4. The checks (build these from catalogue family G; each is a reading with a plain sentence, never pass/fail, never a "best" pick):
   - one-at-a-time sensitivity: each parameter at 0.5x, 0.8x, 1.2x, 1.5x (whole bars for windows), the Sharpe and return for each;
   - parameter plateau: a small grid around the chosen values (at most 25 runs), how much of the grid is within 20% of the chosen result;
   - neighbour stability: the share of nearest neighbours with the same sign of return;
   - worst neighbour: the weakest result among the nearest neighbours;
   - entry delay: enter 1, 2 and 3 bars later than the rule says;
   - exit delay: leave 1, 2 and 3 bars later;
   - skip trades at random: drop 10%, 20%, 30% of entries (seeded), the range of results;
   - cost ladder with re-fill: fees and slippage at 2x, 3x, 5x through the engine (not a rescale of stored costs);
   - start-date sensitivity through the engine: the test started 3, 6, 12 months later;
   - rule inversion: the opposite rule as a control (it should not also look good);
   - noise in prices: small seeded noise added to the bars (reuse `price_noise`), the spread of results.
   Leave out a check that cannot be made correct and say why. Target: at least 9.
5. Long checks print a progress line at least every 10 seconds and say in advance how many engine runs they will make and about how
   long that takes; a `--quick` style small setting is the default for the grid (9 runs) with the full grid on request.
6. Module `apps/alpha-cli/src/alpha_cli/toolbox/families/parameter_robustness.py` (split if over 300 lines), tests
   `tests/unit/test_toolbox_parameter_robustness.py` (for every check: a known-answer case on a small synthetic series, for example a
   rule whose result does not depend on the parameter gives a flat sensitivity; the too-little-data case; the repeat-is-identical
   case; the tries-are-counted-once case), one import line and `*CHECKS` entry in `registry.py`, the situations index
   (`situations.py` and `research/tools/toolbox-by-situation.md`) so `alpha tool find "parameter sensitivity"` reaches them, and a
   tool card `research/tools/toolbox-parameter-robustness.md` (at most 40 lines; cards say `alpha …`).
Done: pull request ready, green `ci-ok`, `report.md` in this folder (check id, what it re-runs, how many tries it adds).
