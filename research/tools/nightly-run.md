---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/nightly_cmds.py
  - apps/alpha-cli/src/alpha_cli/nightly_run.py
  - apps/alpha-cli/src/alpha_cli/nightly_status.py
verified: ed3c4f941cd296bc
---

# Nightly run

**Reach for it when** you want proof that the whole pipeline still works on the data stored here. It judges the system. It never judges whether an idea is good.

**Command**
```text
uv run alpha nightly run --config nightly.toml [--only N1,N2,N3,N4,N0] [--json]
uv run alpha nightly status [--json]
```
Start from [the example](../examples/nightly.example.toml).

**What it runs.** Each step is the real command in a child process, with a time limit.
- N1 rule path: `alpha next`, `data health` per asset, `alpha test` on the fixed spec, `diagnose`, `results check`, then any `post_tools`.
- N2 setup path: `setup find`, `study`, `trade`, then the stored result read back.
- N3 RD-Agent path: not run until `rdagent_config` is set. Then it calls `alpha rdagent run --config <file>` unchanged, then `rdagent status`. It adds no cap.
- N4 (only if an idea is followed): `follow update --all`, `today`, `verify`; a changed journal history is blocking.
  N0 (opt-in, `refresh_followed = true`): `data pull` per followed asset, before N4. The pull freezes the old series first (0.3 MB, reused when identical). A failed freeze blocks it.

**How to read it**
- A step passes, has a minor defect (a warning) or was not run. A reading such as `not clear of chance` is not a defect.
- A blocking defect is a non-zero exit, a time out, bad JSON, a missing field, a `results check` disagreement or data health fail.
- A record is `<home>/nightly/<date>-<n>/record.json` and `summary.txt`. A new run never edits an old one.
- Each step says `computed`, `reused` (the command printed the `repeat` label) or `unknown`. A run is `full` only when N1, N2 and N3 all ran.
- Ready needs the two latest runs on two different dates, each with no blocking defect, all three paths run, and a computed rule test and setup step.
- With no new bar the rule test is `reused`: "reused only", and it does not count. N4 counts only if a follow exists.
- Nightly tests are counted trials. A fixed spec and an unchanged saved health report give the same test id. A repeat adds a ledger row labelled `repeat`.
- The run reads the saved health report first. A new report changes the test id, so it computes one only when none is saved or it is out of date.

**What it cannot tell you** Whether any idea has an edge. A clean night says the system works, nothing more.
**Schedule** Installs nothing; `status` prints one crontab line. Run after the close and the provider's bar, before the next open: check the time.
**Next** `uv run alpha nightly status` lists 5 runs and names the missing item, (a) to (d). `--only` runs are ignored.
