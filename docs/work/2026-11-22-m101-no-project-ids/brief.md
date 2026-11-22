# Brief: ML, forecast and crypto-data commands no longer need a project or a case

Branch: `chore/m101-no-project-ids`. Rules: `docs/work/_common-rules-2026-11-21.md`. The owner wants the project SMALLER and SIMPLER:
no shim, no alias, no "moved" notice, no new option beyond what is named here. Do not copy other briefs into your branch; add only your
own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader` (case-insensitive).

Why: the old "projects / research cases / evidence" machinery is being deleted (owner decision 2026-11-21). Three kept features still
reach into it, which blocks that deletion:
1. `alpha ml export-input` (and any other `alpha ml` command) that takes `--project-id` or reads `project show`: give it `--spec FILE`
   (the ML spec file it needs) and remove the project path. The ML lab web screen must stop calling `project show`.
2. `alpha forecast eval` (Kronos skill): remove `--project-id`; it writes its run like any other stored run.
3. `alpha crypto-data` commands that take `--case-id`: remove the option and the case lookup; they work on the data home directly.

For each: find every reader of the project/case id (CLI, web routes in `apps/alpha-web`, tests, docs, tool cards), make the command
work without it, delete the dead branch, and update tests to the new call. Kept features must behave the same otherwise: Qlib/ML,
Kronos, crypto download/backfill/coverage/quality. `workers/**` and `apps/alpha-mcp/**` are protected: if a worker or an MCP tool passes a
project or case id to one of these commands, keep that one path working and list it in the report as "blocked by a protected file".
Reads stay cut at the held-back boundary (`tests/unit/test_research_reads_are_cut.py` unweakened). Golden pins change only with a
one-line reason.

Done: pull request ready with `ci-ok` green (a pull request now runs `quick`, `static` and, for web changes, `frontend`), and `report.md`
here listing each command, what it needed from projects or cases, and how it works now; plus anything still tied to projects or cases.
