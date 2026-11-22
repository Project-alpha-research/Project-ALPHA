---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/confirm_cmds.py
  - apps/alpha-cli/src/alpha_cli/reserved_slots.py
  - apps/alpha-cli/src/alpha_cli/spine/confirm.py
  - apps/alpha-cli/src/alpha_cli/spine/confirm_run.py
verified: 0000000000000000
---
# Confirm one idea on the reserved period

**Reach for it when** the owner wants the final check: one tested idea, once, on the data from 2024-01-01 on, which no test has used.
**Command**
```text
uv run alpha confirm plan <run id>       # what would be tested and what it spends; writes nothing
uv run alpha confirm run <run id>        # prints the plan, then spends 1 slot and tests once
uv run alpha confirm list                # slots used and left
uv run alpha confirm show <run id>       # one finished confirmation
```
Run `run` only when the owner asks for the final check, by idea name, in chat. Show `plan` first. There is no
confirmation step and no Touch ID ([owner decision](../../docs/reference/project/owner-decisions-6.md)). A spent
slot cannot be given back. No nightly run, RD-Agent loop, MCP tool, web page or follow can start it.

Only a stored `alpha test` run made with the period held back can be confirmed, exactly as it ran: the same spec, costs,
asset, data and engine settings. The earlier period is computed again first; if it does not match the stored run, nothing
is spent. Then a slot receipt is written, and only then are the reserved bars read.

**How to read it**
- Ten slots for the life of the reserved period. A slot is spent once and cannot be undone.
- One rule on one asset can be confirmed once: after it, every test of that rule on that asset (tuned or not) carries
  `reserved-period-confirmed-in-family`, and cannot be confirmed again. The same idea on a similar asset (SPY, then VOO)
  or in another rule kind is not blocked: `plan` lists every earlier confirmation. No tuned neighbours are run.
- The output puts the earlier period and the reserved period side by side, as readings with the Sharpe. It is recorded
  whatever it is and cannot be discarded. The confirmation run carries `reserved-period-confirmation`; tools refuse it.
- A slot spent without a finished run (a crash) is listed as not finished; `alpha confirm run <run id>` resumes it with
  the same slot and the same bars. It spends no new slot.
- The confirmation is not a research trial: its ledger row has its own kind and changes no family count.

**What it cannot tell you** Whether the idea will make money. A reading on about two years of data is one more data point,
not a verdict and not advice. Setup Lab runs cannot be confirmed yet.
**Next** Record what the owner concludes on the idea card (`alpha idea file <id>`).
