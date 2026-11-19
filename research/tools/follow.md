---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/follow_cmds.py
  - apps/alpha-cli/src/alpha_cli/follow_store.py
  - apps/alpha-cli/src/alpha_cli/follow_journal.py
  - apps/alpha-cli/src/alpha_cli/follow_chain.py
  - apps/alpha-cli/src/alpha_cli/follow_update.py
  - apps/alpha-cli/src/alpha_cli/follow_show.py
verified: 8a78979f3151cd2f
---
# Follow a tested idea on paper

**Reach for it when** a rule test or setup find is done and the owner wants to see it work on new bars, on paper.

**Command**
```text
uv run alpha follow start --test <run id> --size-pct 10
uv run alpha follow start --find <find id>
uv run alpha follow list
uv run alpha follow update <follow id>
uv run alpha follow show <follow id>
uv run alpha follow verify <follow id>
```

The follow is frozen when it starts: the source, the spec hash, the assets, the paper size (a percent of a paper account) and the
start time. A journal in `forward/` records each new session of a followed rule test. `update` reads the stored bars. It downloads nothing. It decides on each close and books a paper fill at the next open. A setup or factor cannot be updated yet.

**How to read it**
- `list` shows one state per follow. `show` says "waiting for its first new bar" until a session is recorded.
- Changing a followed idea is a new version. The old follow stops and stays. The forward clock restarts. Without an [idea card](idea-card.md) only restarts of the same test are versions.
- `update` writes one entry per session: the rule's numbers, a plain decision ("would buy at the next open", "holding"), the paper book. A session with no stored bar is `late`. One written after the next open is `missed`: it shows what the rule would have signalled.
- Bars before the start only warm the indicators. The follow starts flat, even if the rule is already long. - Each update replays the rule. `agrees = false` names the sessions that differ, because stored bars or the engine changed.
- `verify` recomputes the hash chain and names the first broken entry. Exit 1 means do not trust the journal.
- A follow is not a test: no trial, no research record changed. Research never reads it.

**What it cannot tell you** Whether the idea works. It is paper only, with no order and no advice. A factor cannot be followed yet.

**Next** Store new bars, run `alpha follow update <follow id>`, then `alpha follow show <follow id>`.
