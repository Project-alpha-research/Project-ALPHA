---
owner: delivery pipeline
sources:
  - scripts/handoff.py
  - scripts/handoff_sandbox.py
  - scripts/codex_bridge.py
  - .claude/agents/*.md
  - .codex/config.toml
  - AGENTS.md
verified: f6f028b7feb0cf36
---

# Model routing: who builds, who reviews, what happens at a limit

Claude plans, decides and reviews. Claude Sonnet builds every task class from a precise brief. Opus is kept for design
and for the reviews that need it. Codex is not in use since the owner's 2026-11-19 decision
([entry](project/owner-decisions-5.md#2026-11-19-claude-agents-build-until-the-codex-subscription-returns-the-file-system-comes-first));
its rules wait in [model-routing-codex.md](model-routing-codex.md) for the day the owner turns it back on. Apply the
tables below mechanically.

On this page: [Roles](#roles), [Brief template](#brief-template), [Task classes](#task-classes), [What stays with
Claude or the machine](#what-stays-with-claude-or-the-machine), [Review by risk tier](#review-by-risk-tier), [Economy
rules](#economy-rules-for-the-claude-side), [Records](#records).

## Roles

- **Orchestrating Claude session** — decides; writes briefs and plans; reads each builder's report and the diff stat (never build logs); commits;
  opens pull requests and lands them as [stage 05](../../workflow/stages/05-land/CONTEXT.md) says. Writes no code a builder could write.
- **Claude Sonnet sub-agents** — build every task class from a precise brief ([template](#brief-template)); chores
  (merges, regeneration, re-stamping, summarising logs); finding things (`navigator`); every ordinary review
  (`reviewer` called with `model: sonnet`).
- **Claude Opus sub-agents** — only design; reviews of honesty claims, tiers `quant`, `bias` and `protected`, and research-integrity work
  (`reviewer`, `quant-verifier`); investigation that needs design judgement.
- **Codex** — builder (`handoff.py build`) and second reviewer (`scripts/codex_bridge.py`), when the owner turns it
  back on. Not in use today; the rules are in [model-routing-codex.md](model-routing-codex.md).

The writer is never the only reviewer. Machine checks and CI run for everything and outrank every model. Briefs name the rows a builder reads;
they do not restate rules.

## Brief template

A builder reads only the brief and the routing rows it names. Write the brief in this shape:

```
Task: <one sentence: the outcome the owner sees>
Workspace: <path>/CONTEXT.md. Read its always rows, plus these rows: <row names>
Decision: <owner-decision link, or "none">
Change: <files>      Do not touch: <files or areas>
Done when: <named failing test passes>; `uv run python scripts/gate.py check` is green
Tier: <none|dag|bias|determinism|quant|protected>   Builder: Sonnet
Do NOT load: whole invariants files, CHANGE-NOTES, tmp/, docs/archive/
Stop when you have what you need, then open the code.
Report (≤ 15 lines): what changed; tests run and results; what is not done; the doc updated (path)
```

The reviewer brief is: the diff, the always rows of the touched workspace, the rows the diff touches, and the questions to answer. A reviewer has a
40k-token budget and never opens whole reference files.

## Task classes

The class is computed from the plan by `handoff.py` (`classify`); a plan's `**Build class:**` line or `--class` may
raise it, never lower it. The design is always already decided: an undecided task goes back to stage 02. Sonnet builds
every class. The Codex columns apply only when Codex is in use.

| Class | Objective criteria | Codex model, effort | Time cap (fix round) | Claude fallback |
|---|---|---|---|---|
| `small` | ≤ 3 files in scope, no tier other than `none` | `gpt-6.2-sol`, `medium` | 15 min (10) | Sonnet |
| `standard` | 4–8 files, or tier `dag`, `bias` or `determinism` | `gpt-6.2-sol`, `high` | 30 min (15) | Opus |
| `hard` | > 8 files, or tier `quant`, `risk` or `protected`, or a guarded path in scope | `gpt-6.2-astra`, `high` | 60 min (20) | Opus |

The reasons for the Codex models and the calibration builds are in [model-routing-codex.md](model-routing-codex.md#why-these-models).

## What stays with Claude or the machine

- Anything needing the network: `uv sync`, GitHub, CI, web research for a decision. `handoff.py` runs `uv sync --locked` before Codex starts.
- Commits, pushes, pull requests, merges. Codex's sandbox cannot write the git directory, and `handoff.py` refuses a build whose HEAD moved.
- Checks Codex's sandbox cannot run ([sandbox rules](model-routing-codex.md#what-the-build-sandbox-allows));
  `handoff.py` runs every check again outside it: pytest under `run_owned_test.py`, a private `TMPDIR`, the built web
  app linked or built.
- Decisions not written in the plan or brief; owner actions of any kind.
- Changes to the never paths (`tests/holdout/`, `scripts/codex_bridge.py`, `scripts/claude_hooks.py`,
  `.claude/settings*.json`, credential-shaped files) — refused whatever the plan says.
- Changes to guarded paths — hash-bound source bytes (`packages/alpha-research/src`, `packages/alpha-validation/src`,
  the four research CLI modules, `uv.lock`), the approval digest rules (`_structural_digest.py`), quant-named modules,
  `tests/oracles/`, `tests/bias_guards/`, `tests/acceptance/`, and the protected harness files (`CLAUDE.md`,
  `AGENTS.md`, `.claude/`, `.codex/`, `.github/`, `.agents/`, `scripts/gate*`, `scripts/harness_*`,
  `scripts/handoff.py`, the harness and file-system contract tests) — unless the plan lists the path in `files` AND
  declares the matching tier (`quant`, `bias`, `protected`), and the owner approved the plan. The list lives in
  `handoff.py` (`NEVER_PATHS`, `GUARDED`).

## Review by risk tier

`handoff.py review --base <ref> [--task <folder>]` prints the route for the current diff. Tiers come from the plan's `tier_impact` and from the paths
changed (quant tier: [engineering rules](invariants/engineering.md#quant-tier); protected and hash-bound: the list above).

| Diff | Built by Sonnet | Built by Codex (when back on) |
|---|---|---|
| ordinary | machine checks + `reviewer` with `model: sonnet` | machine checks + `reviewer` with `model: sonnet` |
| `risk`, `protected` or `bias`, or a claim of honesty | machine checks + `reviewer` (Opus) | machine checks + `reviewer` (Opus) |
| `quant` | machine checks + `quant-verifier` (Opus) + `reviewer` (Opus) | the same |

Review findings are advisory; each is disposed of (fix, or reject with a reason) in `04-verify.md` or the pull
request. `handoff.py review` still prints the older Codex table; this table is the one to follow while Codex is off.
Codex review through the bridge is optional and returns when Codex does.

## Economy rules for the Claude side

- Briefs name rows of a Read first table, never paste context or restate rules; `handoff.py` adds the touched workspaces' rows (≤ 24 KB).
- The orchestrator reads `handoff.py`'s summary (≤ 40 lines) and `git diff --stat`, not logs or event streams; it
  opens the diff only to review or when the summary says something failed.
- Fix rounds are driven by `handoff.py` (`codex exec resume` with the failing command and its output tail), never by a
  Claude turn. Budget: `--fix-rounds`, default 2.
- Sub-agent models are set in each agent's front matter (`model:`); override per call only as the review table says.
- One small route task per brief; batch unrelated small fixes into separate parallel builds.
- A brief says what to change and where; a style remark about a whole file reads as an order to rewrite it
  (calibration task A re-wrapped a whole reference file that way; see [calibration
  builds](model-routing-codex.md#calibration-builds)).

## Records

`handoff.py` writes a JSON build record for every run under its home (default `<parent of the main
checkout>/tmp/handoff/records/`, or `ALPHA_HANDOFF_HOME`); for a task folder it also writes
`docs/work/<task>/03-build.json`. A brief build leaves `brief.md` and the builder's `report.md` in
`docs/work/<date>-<slug>/` ([task folders](../work/CONTEXT.md)), merged with the work; the record stays outside the
tree and its numbers go into the pull request under "Who built and who reviewed". Worktrees are `<home>/wt/<name>` on
branch `build/<name>`; `handoff.py status` lists them and `handoff.py clean` removes merged ones (only those it
created). A later run on the same worktree (a fix by hand, or the Claude fallback through `handoff.py verify`) keeps
the earlier attempts under `previous_attempts`, so the fallback stays visible.
