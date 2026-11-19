---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/nightly_cmds.py
  - apps/alpha-cli/src/alpha_cli/nightly_run.py
  - apps/alpha-cli/src/alpha_cli/nightly_status.py
verified: 677912418279ec8f
---

# Nightly run

**Reach for it when** you want proof that the whole pipeline still works on the data stored here. It judges the system. It never judges whether an idea is good.

**Command**
```text
uv run alpha nightly run --config nightly.toml [--only N1,N2] [--json]
uv run alpha nightly status [--json]
```
Start from [the example](../examples/nightly.example.toml).

**What it runs.** Each step is the real command in a child process, with a time limit.
- N1 rule path: `alpha next`, `data health` per asset, `alpha test` on the fixed spec, `diagnose`, `results check`, then any `post_tools`.
- N2 setup path: `setup find`, `study`, `trade`, then the stored result read back.
- N3 RD-Agent path: not run until `rdagent_config` is set. Then it calls `alpha rdagent run --config <file>` unchanged, then `rdagent status`. It adds no cap.

**How to read it**
- A step passes, has a minor defect (a warning, data health warn) or was not run.
- A blocking defect is a non-zero exit, a time out, bad JSON, a missing field, a `results check` disagreement or data health fail.
- A verdict such as "not supported" is not a defect.
- A record is `<home>/nightly/<date>-<n>/record.json` and `summary.txt`. A new run never edits an old one.
- Ready means two full runs in a row with no blocking defect. A partial `--only` run does not count.
- Nightly tests are counted trials. A fixed spec and an unchanged saved health report give the same test id. A repeat adds a ledger row labelled `repeat`.
- The run reads the saved health report first. A new report changes the test id, so it computes one only when none is saved or it is out of date.

**What it cannot tell you** Whether any idea has an edge. A clean night says the system works, nothing more.
**Schedule** The command installs nothing. `alpha nightly status` prints one crontab line you can paste.
**Next** `uv run alpha nightly status`.
