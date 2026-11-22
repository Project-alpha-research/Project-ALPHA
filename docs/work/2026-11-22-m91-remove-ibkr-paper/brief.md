# Brief: remove IBKR paper trading

Branch: `chore/m91-remove-ibkr-paper`. Rules: `docs/work/_common-rules-2026-11-21.md` (deletion-only build). Extra rules for this build: the owner wants the project SMALLER
and SIMPLER: add no shim, no "moved" notice, no alias, no new option, no new guard. Do not copy other briefs or the common rules into your
branch; add only your own `report.md` in this task folder. NEVER delete anything that comes from neurotrader888: before deleting a file,
run `grep -il neurotrader <file>`; a hit means keep it and say so in the report (his material: `packages/alpha-patterns`,
`alpha_research/pip_miner.py`, `retracements.py`, `rolling_pca.py`, `alpha_validation/mcpt.py`, `bar_permutation.py`,
`trade_dependence.py`, `tests/fixtures/neurotrader/`, `alpha_data/crypto/features.py`). Report lines removed and added, and commands removed.

The owner decided on 2026-11-22 to remove the IBKR paper-trading code (about 4.1k source and 4.3k test lines, 14 commands). `alpha follow`
already does forward paper tracking with no broker, and it stays untouched.

Delete: the `alpha paper` command group and every module only it reaches (find them from `apps/alpha-cli/src/alpha_cli/main.py` and
`uv run alpha info commands --json`); the web routes, models and the Paper screen/pane in the Workstation with its menu entry, tests and
Playwright lanes; MCP tools for paper if any exist under `apps/alpha-mcp` (protected: do not edit; list them in the report instead);
docs pages and tool cards that describe paper trading (`docs/reference/invariants/cli-paper.md` and links to it); the capability rows
in `docs/roadmap/capabilities.toml`; any IBKR dependency ONLY if nothing else imports it (do not change `uv.lock`: report it instead).
Keep: `alpha follow`, propfirm, the no-live-capital rules and their tests (a test that proves no route reaches a broker must stay and
still pass; if it tested through the paper code, rewrite it to assert the code is absent).

Done: pull request ready, `ci-ok` green except possibly the code-size test, `report.md` with the no-caller proof per deleted file.
