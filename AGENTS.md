# Project ALPHA agent instructions

For any coding agent that is not Claude Code. Claude agents build and review this project; the Codex
hand-off is paused until the owner turns it back on ([roles](docs/reference/model-routing.md#roles)).

1. Read [CLAUDE.md](CLAUDE.md): what ALPHA is, the rules that must never break, the one check.
2. Then read the root [CONTEXT.md](CONTEXT.md) and follow its routing to one workspace's `CONTEXT.md`.
3. A change follows the [delivery pipeline](workflow/CONTEXT.md) and a [brief](docs/reference/model-routing.md#brief-template):
   read CLAUDE.md and the workspace rows the brief names, and only those. Stop when you have what you need.
4. A changed file makes its documents stale (`scripts/fs.py owners <path>`): correct them, then run
   `fs.py verify <document>` (a text change or `--reason "<why>"`); `gate.py check` fails until then.
Model or second-opinion output is advisory; checks and CI grant no research or owner authority.
