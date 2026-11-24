# Sweep of the stale research and workflow pages (2026-11-24)

Task: re-read every stale page under `research/` and `workflow/` against the current code and `--help`. Correct what is wrong.
Cut text that only repeats the command's own help. Keep every research-integrity statement. Stamp each page with `fs.py verify`.

Scope: documents only. Not `docs/reference`, `apps/` or `workers/` (another sweeper). No code, tests, CLAUDE.md, AGENTS.md, `.claude/`, `.agents/` or `scripts/`.

Limits: lines at most 160 characters; tool cards at most 40 lines; no real-run numbers; no claim that the code or `--help` cannot confirm.

Done when: `fs.py stale` lists no page under `research/` or `workflow/`; the gate and the research and file-system tests pass.
