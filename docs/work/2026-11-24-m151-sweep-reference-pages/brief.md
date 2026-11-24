# M151: sweep the stale reference pages

Goal: every stale page under `docs/reference/`, `apps/` and `workers/` matches its sources again.
The check is `uv run python scripts/fs.py stale`. Another change sweeps `research/` and `workflow/`.

Rules for each page:

1. Check each claim against the current code and `alpha <command> --help`.
2. Correct what is wrong. Cut text that only restates code or `--help`. Never weaken a rule.
3. Stamp the page with `fs.py verify`; give a reason when the text needed no change.
4. Where code and a rule disagree, leave the rule and list it in the pull-request report.

Documents only. Pages about research cases, `alpha research`, suites, projects and owner_auth are
being removed (owner decision 2026-11-23): fix plain errors only.
