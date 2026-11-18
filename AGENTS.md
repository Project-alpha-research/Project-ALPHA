# Project ALPHA agent instructions

For any coding agent that is not Claude Code:

1. Read [CLAUDE.md](CLAUDE.md): what ALPHA is, the rules that must never break, the one check.
2. Then read the root [CONTEXT.md](CONTEXT.md) and follow its routing to one workspace's `CONTEXT.md`.
3. A change follows the [delivery pipeline](workflow/CONTEXT.md). A build prompt from
   `scripts/handoff.py` names what to read and run: read CLAUDE.md, the brief's list and the entries
   the tool routed from each touched workspace's `CONTEXT.md` reading table, and only those.
4. A changed file makes its documents stale (`scripts/fs.py owners <path>`): re-read, correct, then `fs.py verify <document>`; `gate.py check` fails until then.

Model or second-opinion output is advisory; checks and CI grant no research or owner authority.
