# Project ALPHA

One retail swing trader's private quant-research platform: it tells luck from edge before money is
at risk, with point-in-time data, costs, out-of-sample statistics and an honest count of every try.
Python 3.12 with uv; no hosting, no distribution, no live trading. The owner is not a coder: they
prompt an AI, the AI runs the pipeline, the Workstation shows the result. Three golden paths must
always work end to end on real data:

1. Test an idea: `alpha test` gives a reading, the try count and charts.
2. Study a chart setup: `alpha setup find|study|trade` (Setup Lab).
3. Run RD-Agent on a theme: `alpha rdagent run`; every try is counted.

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

- One check: `uv run python scripts/gate.py check`. Loop: branch → check → commit
  (`type(scope): summary`) → pull request → CI green → merge commit. `ci-ok` is the one required
  check ([ADR-0039](docs/adr/0039-ci-is-the-merge-gate.md)).
- Text the owner reads follows Simplified Technical English about 80% of the way: answer first;
  short sentences; one idea per sentence; one name for one thing; active voice; numbered steps.

## What to load

Start at [`CONTEXT.md`](CONTEXT.md): it routes the task to one workspace `CONTEXT.md`. Read that
file's always rows, then only the rows your task matches; then open the code. Stop when you have
what you need. Each fact has one home ([list](docs/README.md#one-home-per-fact)): update it, never copy it.

- Find a module: `uv run python scripts/fs.py map <workspace> --find WORDS`. Find a document:
  `fs.py search "words"`. Areas: `fs.py orient`. Out-of-date documents: `fs.py stale`.
- Do not load: other workspaces; whole rule pages when a row names a section; `docs/archive/`;
  `docs/work/` of other tasks; `workers/rdagent/CHANGE-NOTES.md`; backend rule pages for a
  display-only change.
- What a part is for and what the owner decided: [project layer](docs/reference/project/overview.md).
  Testing a trading idea: `research/CONTEXT.md`. Building and landing a change: `workflow/CONTEXT.md`.
