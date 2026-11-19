# Project ALPHA

ALPHA is one person's private, non-commercial quant-research platform: it tests whether a market
idea survives point-in-time data, costs and out-of-sample statistics, and records the owner's
decisions. Python 3.12 with uv; there is no hosting, no distribution and no live trading.

## Never break these

- Every data and strategy read is point-in-time at an aware-UTC `as_of`.
  [Rule](docs/reference/invariants/research-integrity.md#point-in-time-reads)
- Decide on the close of bar t, fill at the open of bar t+1.
  [Rule](docs/reference/invariants/research-integrity.md#decide-at-close-fill-at-next-open)
- Invalid, non-finite or disordered data and degenerate statistics fail loud; never swallow errors.
  [Rule](docs/reference/invariants/research-integrity.md#invalid-data-fails-loud)
- Runs, snapshots, receipts and admitted evidence are immutable and hash-bound.
  [Rule](docs/reference/invariants/research-integrity.md#immutable-hash-bound-artefacts)
- Seeds and execution fingerprints are deterministic; D0/D1 seeds are frozen.
  [Rule](docs/reference/invariants/research-integrity.md#deterministic-seeds-and-identity)
- Research before strategy; only the owner promotes, on verified evidence.
  [Rule](docs/reference/invariants/research-integrity.md#research-before-strategy)
- Owner acts need explicit local owner confirmation; no route reaches live capital.
  [Owner](docs/reference/invariants/research-integrity.md#owner-authority),
  [capital](docs/reference/invariants/research-integrity.md#no-live-capital)
- UI, MCP, model output, account state and passing checks confer no authority; infer no approvals.
  [Rule](docs/reference/invariants/research-integrity.md#owner-authority)
- Obey the layered import DAG (`uv run lint-imports`); web and MCP call `alpha_cli` as a subprocess,
  except bounded read-only reads of stored files ([Setup Lab](docs/reference/invariants/web-api-reads.md#reads-and-writes)).
  [DAG](docs/reference/invariants/engineering.md#import-layers),
  [subprocess](docs/reference/invariants/engineering.md#subprocess-boundary)
- Never weaken bias guards, oracles or the guarded `tests/holdout/` path to make a change pass.
  [Rule](docs/reference/invariants/research-integrity.md#protected-and-hidden-tests)
- Bytes under `packages/alpha-research/src` and `packages/alpha-validation/src` feed approval
  hashes and the quant tier: no cosmetic edits.
  [Bytes](docs/reference/invariants/engineering.md#hash-bound-source-bytes),
  [tier](docs/reference/invariants/engineering.md#quant-tier)

## Check and land

- One check: `uv run python scripts/gate.py check`.
- Loop: branch → check → commit (`type(scope): summary`) → pull request → CI green → merge commit.
  CI on the pull request is the merge gate; `ci-ok` is the one required check
  ([ADR-0039](docs/adr/0039-ci-is-the-merge-gate.md)).
- Text the owner reads (replies, reports, screen labels, pull-request summaries) follows Simplified
  Technical English (ASD-STE100) about 80% of the way: answer first; short sentences; one idea per
  sentence; one name for one thing; active voice; steps as numbered lists.

## What to load

Start at [`CONTEXT.md`](CONTEXT.md). It routes the task to one workspace `CONTEXT.md`. Read that
file's always rows, then only the rows your task matches. Stop when you have what you need; then
open the code. Each fact has one home ([list](docs/README.md#one-home-per-fact)): update it, never copy it.

| Task | Start at | Do NOT load |
|---|---|---|
| Change package, worker or app code | that workspace's `CONTEXT.md` | other workspaces; whole rule pages |
| RD-Agent loop or judge | `workers/rdagent/CONTEXT.md` | `CHANGE-NOTES.md`; other workers |
| An `alpha` command or toolbox check | `apps/alpha-cli/CONTEXT.md` | `cli-*` pages your rows do not name |
| A Workstation screen | `apps/alpha-web/CONTEXT.md` | backend rule pages for a display-only change |
| Tests or guards | `tests/CONTEXT.md` | — |
| Docs or this file system | `docs/CONTEXT.md` | `docs/archive/`; `docs/work/` of other tasks |
| What a part is for; what the owner decided | [project layer](docs/reference/project/overview.md) | rule pages; code |
| Test a trading idea | `research/CONTEXT.md` | code |
| Build, review or land a change | `workflow/CONTEXT.md` | stages you are not in |

Tools: `uv run python scripts/fs.py orient` lists the areas, `fs.py search "words"` finds documents,
`fs.py stale` lists documents whose sources changed since they were verified.
