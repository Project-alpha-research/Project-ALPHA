---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/library_cmds.py
  - apps/alpha-cli/src/alpha_cli/library_papers_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/papers.py
  - apps/alpha-cli/src/alpha_cli/spine/library.py
  - apps/alpha-cli/src/alpha_cli/spine/library_import.py
verified: 563e9cc54e1c1da5
---
# Library of published ideas

**Reach for it when** the owner asks "what has been published on this?". It is a starting map, not a claim: no idea is said to make money.

**Command**
```text
uv run alpha library list --market crypto --json   # also: show <id>, card <id>
uv run alpha library search "momentum" --unpaywall-email <contact>
uv run alpha library import-pdf <file.pdf> --title "..." --author "..." --year 2001
uv run alpha library papers
```

A record is a paper in our own words: idea, why it is said to work, data needed, holding time, decay evidence, can test today.

**How to read it**
- `list` shows `checked` records. `--market` takes us-equities, crypto, futures or multi. `--tier imported|all` adds 212 facts-only
  records (id `osap-<name>`). "private" rows are the owner's notes in `<home>/library/private/`. `show` lists idea cards made from a record.
- `card` writes an idea card with the idea, the mechanism and the holding time. What would disprove it and the
  baseline stay "not stated": the owner fills them. The `source` line names the record (an imported one says "not
  hand-checked"; its idea is a neutral label: edit it). The line is not in the card id.
- `search` keeps each hit as a paper under `<home>/library/papers/`. `import-pdf` keeps one local PDF: title, authors,
  year, source, file hash, text place. The same file twice gives one paper. A value not given reads "not stated".
- `idea new --paper <id>` links a paper to a card; `alpha idea file` lists them. A paper is a source for ideas only:
  not evidence, a test or an approval. The old `alpha research` literature commands still run and name these.
- Nothing is tested; no ledger row is written. Returns: `alpha context show-osap-portfolios`. To RD-Agent: `alpha ledger reply --idea` only.

**What it cannot tell you** Whether an idea works today; published results often shrink.
"Can test today" names missing data; "citation to check" means verify first.

**Next** Fill the card, then test it ([rule test](rule-test.md)); the card id goes in the spec ([idea card](idea-card.md)).
