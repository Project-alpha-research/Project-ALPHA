# Report: no hand-written config for Setup Lab and RD-Agent

## Answer first
A first run needs no file now. Both gaps are closed on the CLI side only. `workers/**` is unchanged.

## Setup Lab
1. `alpha setup new <name>` writes a complete, commented spec to `<data folder>/specs/<name>.toml`. It prints the path and
   `alpha setup find <path>`. It never overwrites a file.
2. Options and defaults: `--asset SPY`, `--when "crosses_above(close, sma(close, 20))"`, `--horizon 10`, `--stop "5 %"`,
   `--target "10 %"`. The file always has `[setup]`, `[exit]` (long, stop, target, `time_bars = horizon`) and `[study]`
   (horizons 1, 5, 10, 20 plus the horizon; primary = horizon).
3. `alpha setup find` takes the same options with no file. `alpha setup study` and `alpha setup trade` also take them: with no
   find id they run a find first, then the study or trade. The file is `specs/quick-<hash>.toml`: same options, same file, same
   find id. A spec file or find id together with options is refused. `find <file> --asset` still filters the file's assets.
4. A bad option gives one sentence that names it (`--when`, `--stop`, `--target`, `--horizon`, the name).

## RD-Agent: setting, default rule
| Setting | Default |
|---|---|
| `data_dir` | the data home (`ALPHA_DATA_DIR`) |
| `gateway_data_dir` | `<home>/rdagent/gateway-state` |
| `trial_ledger` | `<home>/rdagent/trial-ledger/rdagent-factor-trials.jsonl` |
| `working_directory` | the nearest parent of the installed code that holds `workers/rdagent/factor_loop_launch.py` |
| `rdagent_source` | `ALPHA_RDAGENT_SOURCE`, else `<checkout>/.alpha/state/runtime/rdagent-source` (the setup script's path) |
| `factor_python` | `ALPHA_FACTOR_PYTHON`, else `<checkout>/.alpha/state/runtime/rdagent-factor-py311/venv/bin/python` |
| `universe`, `funding_dir`, `memory_dir`, `key_file` | none: the launcher's own default applies |

- `alpha rdagent init` writes `<home>/rdagent.toml` with the six paths and lists each one it could not find, with the fix.
  It refuses to overwrite.
- `run` and `status` read `--config`, else `<home>/rdagent.toml` if it exists, else use the defaults. `--dry-run` works with no file
  and writes nothing. A file may hold only the keys the owner wants to change.
- The ledger and gateway folders inside the data home are made when a real run starts, so they are not a missing-path error.
- Every path problem is one sentence: `The path for <setting> does not exist: <path>. Fix: <what to do>`. No traceback.

## What a fresh machine still needs
1. `bash scripts/setup_rdagent.sh --with-factor-runtime` (the pinned RD-Agent source and factor runtime). Only the owner can run it.
2. The repo `.venv` (`uv sync`), because the launcher runs under `.venv/bin/python`.
3. A key file and model route if the owner wants a real (not `fake`) model route; `key_file` and `chat_route` stay optional keys.

## Decisions
- Done in `rdagent_defaults.py` and `rdagent_init.py`; `rdagent_run_config.py` and `rdagent_cmds.py` changed. Setup code is in
  `_setup_spec_build.py` so `setup_cmds.py` grows only by command wiring (it was already over 300 lines).
- The brief says not to regenerate `docs/reference/commands.md`, so it is stale for `setup new` and `rdagent init`.
- `workers/rdagent/README.md` is under protected `workers/**`: its "copy the example file" line is now out of date; the default
  rules are in `docs/reference/invariants/cli-native.md`. It needs an owner edit.
- The brief's commit trailer names another model than the one that built this. The trailer from this session's attribution
  rule was used.
- `research/tools/setup-find.md` is 41 lines (limit 40 for tool cards); the living-documents check passes.

## Fail-first evidence
Both new test files failed at collection before the code existed (`No module named alpha_cli._setup_spec_build`, then
`alpha_cli.rdagent_defaults`). After the code: `test_setup_new.py` 14 passed, `test_rdagent_defaults.py` 12 passed;
the existing setup and RD-Agent run tests still pass.

## Review round 1 (three findings, all fixed)
1. An edited `specs/quick-<hash>.toml` is refused, not used, and not overwritten.
2. `--accept-bad-data` now reaches the find that `study` and `trade` run first.
3. `--recheck` with direct options is refused before any file is written.
Each has a test in `test_setup_new.py`; two of them failed before the fix.
