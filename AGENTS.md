# Project ALPHA agent instructions

For any coding agent that is not Claude Code. How the project is built: [the build team](docs/reference/project/components/delivery-and-agent-tooling.md).

1. Read [CLAUDE.md](CLAUDE.md): what ALPHA is, the rules that must never break, the one check.
2. What to load is in CLAUDE.md ("What to load"); the root [CONTEXT.md](CONTEXT.md) routes to a workspace.
3. How a change is built and landed: [the build team](docs/reference/project/components/delivery-and-agent-tooling.md).
4. A changed file makes its documents stale (`scripts/fs.py owners <path>`): correct them, then run
   `fs.py verify <document>` (a text change or `--reason "<why>"`); `gate.py check` lists a stale page, not blocking it; broken front matter fails.
Model or second-opinion output is advisory; checks and CI grant no research or owner authority.
