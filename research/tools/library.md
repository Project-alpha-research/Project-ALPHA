---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/library_cmds.py
  - apps/alpha-cli/src/alpha_cli/library_papers_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/papers.py
  - apps/alpha-cli/src/alpha_cli/spine/library.py
  - apps/alpha-cli/src/alpha_cli/spine/library_import.py
verified: 445857b6fb8af7f7
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
uv run alpha library search "momentum" --unpaywall-email <contact>
uv run alpha library import-pdf <file.pdf> --title "..." --author "..." --year 2001
uv run alpha library papers
uv run alpha idea new --claim "..." --paper <paper-id>
```

A record points to a paper in our own words: the idea, why it is said to work (the record says whose reading it is), the data needed, how
long a trade is held, what later research says about decay, and whether ALPHA can test it today.

**How to read it**
- `list` shows `checked` records. `--market` takes us-equities, crypto, futures or multi. "private" rows are the owner's
  notes in `<home>/library/private/`, never in git. `--tier imported|all` adds 212 facts-only records (id `osap-<name>`):
  authors, year, category, sign, sample years. The header counts each tier. Read the paper for the idea.
- `show` also lists idea cards already made from the record, and how many tests are linked to each.
- `card` writes an idea card with the idea, the mechanism and the holding time. What would disprove it and the
  baseline stay "not stated": the owner fills them. The card keeps a `source` line,
  "from library record <id>, published <year>". For an imported record it says "from imported library record <id>; not
  hand-checked", and the idea is a neutral label: edit it. It is not part of the card id, so the idea text stays the owner's.
- `search` asks the literature worker (the same sources as before) and keeps each hit as a paper under
  `<home>/library/papers/`. `import-pdf` keeps one local PDF: title, authors, year, source, file hash and the place of
  the extracted text. The same file twice gives one paper. A value not given is "not stated", never zero. No project or case.
- `idea new --paper <id>` links a paper to a card; `alpha idea file` lists the papers. A paper is a source for ideas
  only: it is not evidence, a test or an approval. The old `alpha research` literature commands still run and name these.
- Nothing is tested and no ledger row is written. Their published returns: `alpha context show-osap-portfolios`.
- To give an idea to RD-Agent, pass it in discussion with `alpha ledger reply --idea`. There is no other channel.

**What it cannot tell you** Whether an idea works today. Published results often shrink after publication.
"Can test today" names the ALPHA data that is missing; "citation to check" in a record's notes means verify first.

**Next** Fill the card, then test it ([rule test](rule-test.md)); the card id goes in the spec ([idea card](idea-card.md)).
