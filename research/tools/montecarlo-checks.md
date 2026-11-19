---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/montecarlo.py
  - tests/unit/test_toolbox_montecarlo_checks.py
verified: a37a1ca2d940a3ab
---

# Calm-and-stormy and fat-tail histories

**Reach for these checks when** the owner asks how bad a rule's path could get if bad spells cluster, or if rare large moves are likelier than the history shows.

| Question | Command |
|---|---|
| What do histories give that keep calm and stormy periods apart? | `alpha tool run resampling.regime_paths <run_id>` |
| What do fat-tailed histories give, with rare large moves? | `alpha tool run resampling.student_t_paths <run_id>` |

**How to read it**

- Both give the 5th, 50th and 95th percentile final return and the one-in-20 worst drop. Compare them with the
  [resampling checks](resampling-checks.md) and with `alpha monte-carlo classical --from-run <run_id>`.
- The regime check draws 2,000 histories. It labels each bar calm or stormy from the swing of the run's own last 63
  returns. The classical command uses the market's closes, so its numbers can differ. A state with too few bars gives
  "unavailable" and a reason. Settings: `n_paths`, `regime_window`, `min_state_observations`, `min_state_transitions`.
- The Student-t check draws 10,000 histories. Tail weight comes from the run's own returns.
- Given the same returns, states and seed, each gives the numbers of the matching classical family.
- They also run on an RD-Agent factor replay. They are not in the fixed set `rdagent-post-judge`.

**What these checks cannot tell you** Every history assumes the future looks like this one. A scenario is not proof of an edge.

**Next** Check [trade clustering](run-level-checks.md) or [cite](results-and-cite.md) the stored output.
