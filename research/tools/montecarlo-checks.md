---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/montecarlo.py
  - tests/unit/test_toolbox_montecarlo_checks.py
verified: 649c96b27d241394
---

# Fat-tail histories

**Reach for this check when** the owner asks how bad a rule's path could get if rare large moves are likelier than a bell curve allows.

| Question | Command |
|---|---|
| What do fat-tailed histories give, with rare large moves? | `alpha tool run resampling.student_t_paths <run_id>` |

**How to read it**

- It re-draws the run's past returns 10,000 times; it is not a forecast. Each bar is drawn on its own from a
  Student-t curve fitted to the run's returns. It gives the 5th, 50th and 95th percentile final return and the
  one-in-20 worst drop. Compare them with the [resampling checks](resampling-checks.md).
- Given the same returns and seed, it gives the numbers of the Student-t family of
  `alpha monte-carlo classical`. The command reads a validation run; this check reads a rule test's stored equity.
- Between seeds, on 7,500 bars, the low end and the worst drop moved under 1% of their value and the high end about 3%.
- It also runs on an RD-Agent factor replay. It is not in the fixed set `rdagent-post-judge`.
- The calm-and-stormy family is not a check yet: it needs the market's closes, which a check on stored equity lacks.

**What this check cannot tell you** Every history assumes the future looks like this one. It draws bars independently,
so it cannot show losing streaks. A scenario is not proof of an edge.

**Next** Check [trade clustering](run-level-checks.md) or [cite](results-and-cite.md) the stored output.
