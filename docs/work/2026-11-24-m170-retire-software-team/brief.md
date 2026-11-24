# Retire the Software Team

Outcome: the old Software Team and five-stage delivery pipeline are deleted, and every living page points to one page: [the build team](../../reference/project/components/delivery-and-agent-tooling.md).

- Owner approved, 2026-11-24, to retire the Software Team and point to the build team.
- Delete: `workflow/`, the stage slash commands, the Codex hand-off tool and bridge, the model-routing pages, `gate.py plan-check`.
- Keep: the gate, the map tools, `factory.toml`, the hooks, the reviewer agents, CI, `scripts/update.sh`.
- Not touched: the `ai-research-team` capability, RD-Agent, Qlib, Nautilus and the ML "handoff" code.
- Checks: `uv run python scripts/gate.py check`; the file-system, docs and harness unit tests.
