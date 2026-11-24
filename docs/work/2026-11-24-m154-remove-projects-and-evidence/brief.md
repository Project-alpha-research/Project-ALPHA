# Brief: remove projects and evidence commands (plan step 6)

Branch: `chore/m154-remove-projects-and-evidence`. Full brief: `docs/work/2026-11-24-m154-remove-projects-and-evidence/brief.md`
on branch `work/m102-briefs`. Common rules: `docs/work/2026-11-21-common-build-rules/brief.md`.

- Deletes `alpha evidence` and every `alpha project` command except `job-*` (owner decision 2026-11-23).
- `project_cmds.py` becomes `jobs_cmds.py`; `main.py` still mounts it as `alpha project`.
- Deletes `project_workspace.py`, `evidence_cmds.py` and the tests of the removed commands.
- Does NOT delete `tests/bias_guards/test_agent_brief_future_poison.py`: the orchestrator adds that commit.
