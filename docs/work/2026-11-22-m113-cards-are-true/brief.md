# Brief: the help cards match the product

Branch: `fix/m113-cards-are-true`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a retail swing trader, NOT a coder. On
2026-11-22 testers used the product on real data as he would and wrote down what failed; this brief fixes one group of those failures.
His words: "I should just be able to use the product and it work properly like any proper software." So: fix exactly what is listed,
in the simplest way; no new options beyond those named; no shims; plain short English in every message. Tests first, on synthetic
fixtures. Do not edit protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Add only
your own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader`. Done = pull request ready with
a green `ci-ok`.

What failed: "The research/tools cards have no entries for lookalike, forecast, ml or chart overlays. Cards say `uv run alpha` while the
program is `alpha`. The `[exit]` syntax of a setup spec is documented nowhere; I had to read spec.py to learn `stop = \"5 %\"`. A
documented command no longer exists" (several old commands were removed this week). `alpha --help` still lists a Touch ID owner
credential (`owner-auth`), which the owner removed from the product.

Build:
1. A test that reads every tool card and skill file the product ships to its users (`research/tools/*.md`, `.claude/skills/*/SKILL.md`
   or wherever the user-facing skills live; `.agents/` is protected: READ it in the test, do not edit it; list any wrong command you
   find there in your report) and fails when a card names an `alpha` command, sub-command or option that does not exist (build the
   list from the program: `alpha info commands --json`). Then fix every card the test catches.
2. New cards (at most 40 lines each, same form as the others: when to use it, the command, how to read it, what it cannot tell you):
   `lookalike.md`, `forecast.md` (Kronos: run, eval, the context length rule, how long it takes), `data.md` (symbols, health, coverage,
   pull). Add them to `research/tools/README.md`.
3. The Setup Lab card documents the complete spec file: every section and key with one example each, including `[exit]` (read
   `spec` code for the truth); add a complete commented example under `research/examples/`.
4. Cards say `alpha …` (the installed program), and say once how to run it from a checkout.
5. Hide the `owner-auth` group from `alpha --help` (it stays callable until its code is removed with the old research machinery) and
   remove Touch ID wording from the cards and from `alpha next` / `alpha home` texts if present.
Report: every wrong command found and what replaced it.
