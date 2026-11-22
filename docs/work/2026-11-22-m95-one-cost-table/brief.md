# Brief: one cost table for the whole project

Branch: `fix/m95-one-cost-table`. Rules: `docs/work/_common-rules-2026-11-21.md`. The owner wants the project SIMPLER: no new option,
no shim. Do not copy other briefs into your branch; add only your own `report.md` in this task folder.

Why: `alpha test` takes its default trading costs from one table (`apps/alpha-cli/src/alpha_cli/spine/cost_classes.py`, with
`spine/setup_costs.py`). Three other places carry their own numbers: the RD-Agent judge `apps/alpha-cli/src/alpha_cli/_rdagent_judge.py`
(about line 54: fee 10, slippage 6 basis points, while the table says 10 and 5 for crypto spot), `_native_daily_rule_study.py` (about
line 286) and `research_cmds.py` (about line 3135: 1 and 2). The owner decided on 2026-11-22: one cost table.

Build:
1. The RD-Agent judge and the native daily rule study read their costs from the one table, by the asset class of the asset they score.
   Delete their own constants. Leave `research_cmds.py` alone if it belongs to the old research-case lane (it is scheduled for
   deletion): say so in the report.
2. Stored results are never rewritten. A stored RD-Agent score keeps the costs it was made with; a new score records the costs used and
   their source (`class-default` and the class), exactly as `alpha test` does. Where the judge compares a new score with an old one made
   under other costs, the output says so in one plain sentence; it does not silently mix them.
3. Do not change `workers/rdagent/**` (protected) or anything about RD-Agent's prompts, reflections, feedback, memory or context. If the
   costs reach the worker through a parameter that the CLI side sets, change only the CLI side.
4. Tests first: the judge uses the table value for a crypto asset and for a US ETF; a table change reaches the judge; an old stored
   score is not altered; golden pins of `alpha test` do not change.
5. Docs: fix the text of the page that states the judge's costs.

Done: pull request ready with `ci-ok` green, and `report.md` in this folder with each call site, old numbers and new source.
