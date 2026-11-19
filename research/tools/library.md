---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/library_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/library.py
  - apps/alpha-cli/src/alpha_cli/spine/library_import.py
verified: 8c26b75e9ac84bfa
---
# Library of published ideas

**Reach for it when** the owner asks "what has been published on this?" or wants an idea to start from.
The library is a starting map, not a claim. It does not say any idea makes money.

**Command**
```text
uv run alpha library list --market crypto --json
uv run alpha library list --tier all
uv run alpha library show <id>
uv run alpha library card <id> --json
```

A record points to a paper in our own words: the idea, why it is said to work (the record says whose reading it is), the data needed, how
long a trade is held, what later research says about decay, and whether ALPHA can test it today.

**How to read it**
- `list` shows every record. `--market` takes us-equities, crypto, futures or multi. Rows marked
  "private" come from the owner's own notes in `<home>/library/private/`; they are never in git.
- `list` shows `checked` records (hand-verified). `--tier imported|all` adds the 212 facts-only records of a published
  signal catalogue (id `osap-<name>`); the header counts each tier. Imported records give authors, year, category,
  predicted sign and sample years only. Read the paper for the idea.
- `show` also lists idea cards already made from the record, and how many tests are linked to each.
- `card` writes an idea card with the idea, the mechanism and the holding time. What would disprove it and the
  baseline stay "not stated": the owner fills them. The card keeps a `source` line,
  "from library record <id>, published <year>". It is not part of the card id, so the idea text stays the owner's.
- Nothing is tested and no ledger row is written.
- Return series of those signals are in `alpha context show-osap-portfolios` (reference only; name the release).
- To give an idea to RD-Agent, pass it in discussion with `alpha ledger reply --idea`. There is no other channel.

**What it cannot tell you** Whether an idea works today. Published results often shrink after publication.
"Can test today" names the ALPHA data that is missing; "citation to check" in a record's notes means verify first.

**Next** Fill the card, then test it ([rule test](rule-test.md)); the card id goes in the spec ([idea card](idea-card.md)).
