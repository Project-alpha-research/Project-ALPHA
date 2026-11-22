# Brief: review and land the eight toolbox pull requests

You are the independent QUANT reviewer. Eight builders each added 10 to 14 toolbox checks in one family. Their pull requests are the ones
whose branch starts with `feat/toolbox-` (list them: `gh pr list --state open --json number,headRefName,isDraft`). Their rules:
`docs/work/2026-11-22-toolbox-common/brief.md` on branch `work/m102-briefs` (read it first), and each family brief beside it.

The owner is a retail swing trader, not a coder. He wants the toolbox finished: about 100 checks that give correct numbers in plain
words. ONE review round per pull request; fix real defects only; no new features, no extra layers.

Work through them ONE AT A TIME, smallest first. A builder may still be working: skip a pull request that is still a draft or whose last
push is under 20 minutes old, and come back to it.

For each pull request:
1. Check out its branch. Merge `origin/main` into it (`git merge origin/main`, message `chore(merge): bring main into <branch>`). The
   only expected conflict is `apps/alpha-cli/src/alpha_cli/toolbox/registry.py`: keep BOTH sides' import lines and `*CHECKS` entries.
   For `STATUS.md`, `docs/roadmap/README.md`, `docs/reference/commands.md` take main's side.
2. Review every check:
   - The NUMBER is right: recompute at least the known-answer case by hand or with scipy/statsmodels in a scratch script and compare.
     Check the formula against the cited source (annualisation, sample vs population variance, sign conventions, log vs simple
     returns, what happens with zero variance, one observation, all-equal values, NaN).
   - Inputs come only from the shared loader, cut at the held-back boundary; no check reads bars or data itself;
     `tests/unit/test_research_reads_are_cut.py` passes unweakened.
   - It gives a reading in plain words with what it cannot tell; no pass/fail, grade or advice; too little data gives a clear
     "too little to read" result, never a confident number.
   - Deterministic: seeded draws only; a repeat gives identical output.
   - It is not a duplicate of an existing check under another name (`uv run alpha tool list`); drop true duplicates.
   - The check id and its one-line question are clear to a trader.
   Fix real defects with a failing test first. Remove a check you cannot make right, and say so.
3. Checks: `uv run ruff check . && uv run ruff format --check . && uv run lint-imports`; `uv run mypy apps/alpha-cli/src`; the new test
   file; `uv run pytest -q tests/unit -k "toolbox"`; `uv run pytest -q tests/bias_guards -x`; then run two of the new checks for real
   through the command on a synthetic stored run (make one with `uv run alpha test --rule ma_cross --param fast=5 --param slow=20
   --asset <fixture symbol> --quick` in a temp data home built from the repo's test fixtures) and read the output as a trader would.
4. Push; mark ready if it is a draft (`gh pr ready <n>`); wait for the required check `ci-ok` on the head commit
   (`gh api repos/tradingsystem1880-eng/Project-ALPHA/commits/<sha>/check-runs`, every 90 seconds). Fix what CI finds.
5. When `ci-ok` is green and no real defect is open: `gh pr merge <n> --merge`. If merging is refused for lack of permission, leave the
   pull request ready and green and continue with the next one.

Protected paths, not to be edited: `packages/alpha-research/src`, `packages/alpha-validation/src`, `workers/**`, `apps/alpha-mcp/**`,
`tests/bias_guards`, `tests/oracles`, `tests/acceptance`, `tests/unit/test_claude_harness_*.py`, `.semgrep/`, `.github/`, `.claude/`,
`.agents/`, top-level `scripts/`, `uv.lock`, `CLAUDE.md`, `AGENTS.md`. If a pull request's own diff touches one, do not merge it.
Commits end with the exact line `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`; merge commits only (never amend, rebase,
squash or force-push).

After the last one: on a new branch `feat/toolbox-index` from main, update `apps/alpha-cli/src/alpha_cli/toolbox/situations.py` and the
tool card `research/tools/toolbox-by-situation.md` so that `alpha tool find "<words>"` and the situation list reach the new checks
(group them by the trader's question, not by family code), with a test; open that pull request and land it the same way.

Write `docs/work/2026-11-22-toolbox-review/report.md` on that last branch: per pull request merged or not and why; each defect (one
line) and its fix; checks removed; the final count of checks (`uv run alpha tool list | wc -l`).
