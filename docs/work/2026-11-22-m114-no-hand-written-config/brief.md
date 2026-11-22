# Brief: no hand-written config files for Setup Lab and RD-Agent

Branch: `feat/m114-no-hand-config`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a retail swing trader, NOT a coder. On
2026-11-22 testers used the product on real data as he would and wrote down what failed; this brief fixes one group of those failures.
His words: "I should just be able to use the product and it work properly like any proper software." So: fix exactly what is listed,
in the simplest way; no new options beyond those named; no shims; plain short English in every message. Tests first, on synthetic
fixtures. Do not edit protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Add only
your own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader`. Done = pull request ready with
a green `ci-ok`.

What failed: "Hand-written files are required: the setup TOML with its undocumented `[exit]`, and rdagent.toml with 8 absolute paths.
`alpha rdagent … --dry-run` needs 8 hand-edited absolute paths." A product does not ask its user to write config files by hand.

Build:
1. `alpha setup new <name>`: writes a complete, valid, commented Setup Lab spec file from options (`--asset`, `--when "<condition>"`,
   `--horizon`, `--stop`, `--target`, each with a sensible default) into the data home's specs folder, prints its path and the exact
   command to run it. `alpha setup find|study|trade` also accept the same options directly, so a first run needs no file at all.
2. RD-Agent: every path in its config has a default derived from the data home and the installed worker location (find how the worker
   and its assets are located today: environment variables, `stores.toml`, the setup script); `alpha rdagent init` writes a config with
   those defaults and says which of them it could not find and what to run to install them; `--dry-run` works with no config file when
   the defaults resolve. `workers/**` is protected: change only the CLI side that builds the worker's arguments.
3. A missing or wrong path gives one plain sentence naming the setting and the fix, never a traceback.
Report: each setting, its default rule, and what a fresh machine still needs.
