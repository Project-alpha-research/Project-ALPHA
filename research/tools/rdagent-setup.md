---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/rdagent_init.py
  - apps/alpha-cli/src/alpha_cli/rdagent_defaults.py
---
# RD-Agent setup: `alpha rdagent init`

**Reach for it when** you want RD-Agent to propose ideas and `alpha rdagent run --dry-run` fails.

**Commands**
```text
alpha rdagent init               # writes rdagent.toml with every path filled in
alpha rdagent run --dry-run      # checks the setup; starts no loop
bash scripts/setup_rdagent.sh --with-factor-runtime   # installs the worker and the factor runtime
```
`init` never replaces a file. For each part it cannot find, it prints the command that installs it.

**How to read it**
- `Found:` lines are parts that exist. `Not found:` lines name the fix.
- One rule for each setting: an environment variable wins, then `rdagent.toml`, then the default.
- The dry run names the setting it used and where it came from.

**What it cannot tell you**
- A passing dry run does not prove a loop will produce an idea worth testing.

**Next** Read [one idea's journey](rdagent-journey.md), or compare models with the [model bench](rdagent-model-bench.md).
