---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/follow_cmds.py
  - apps/alpha-cli/src/alpha_cli/follow_store.py
  - apps/alpha-cli/src/alpha_cli/follow_journal.py
  - apps/alpha-cli/src/alpha_cli/follow_chain.py
verified: ca184e1177f7193e
---
# Follow a tested idea on paper

**Reach for it when** a rule test or setup find is done and the owner wants to see it work on new bars, on paper.

**Command**
```text
uv run alpha follow start --test <run id> --size-pct 10
uv run alpha follow start --find <find id>
uv run alpha follow list
uv run alpha follow show <follow id>
uv run alpha follow verify <follow id>
```

The follow is frozen when it starts: the source, the spec hash, the assets, the paper size (a percent of a paper account) and the
start time. A journal in `forward/` records each new session. Today it only holds the start. No signal and no trade is computed yet.

**How to read it**
- `list` shows one row per follow. `show` says "waiting for its first new bar" until a session is recorded.
- Changing a followed idea is a new version. The old follow stops and stays. The forward clock restarts.
- `verify` recomputes the hash chain and names the first broken entry. Exit 1 means do not trust the journal.
- A follow is not a test. It writes no trial and changes no research record. Research never reads it.

**What it cannot tell you** Whether the idea works. It is paper only, with no order and no advice. A factor cannot be followed yet.

**Next** Wait for new bars, then `alpha follow show <follow id>`. Without an [idea card](idea-card.md), only restarts of the same test are versions; write the card first to link different tests.
