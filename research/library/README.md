---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/library.py
verified: 6ca504cc9457bc0d
---
# Library of published ideas

A starting map, not a claim. One small TOML file per published idea in `published/<id>.toml`.
Read them with `uv run alpha library list`. The tool card is [library](../tools/library.md).

## What a record is
A pointer to a paper, in our own words. Fields: `id`, `name`, `source` (authors, year, title, venue, public URL
or DOI), `year_published`, `market`, `idea` (one sentence), `mechanism_claimed` (why the authors say it works),
`data_needed`, `direction`, `holding_clock`, `decay_evidence`, `can_test_today`, `notes`.
`tests/unit/test_library.py` checks every record. An unknown key fails.

## The own-words rule
- Write every sentence yourself. Do not copy an abstract or a line from a paper. No quotes longer than a few words.
- Do not put third-party data or code in this folder.
- Never write that an idea makes money. Say what the authors report and what later work found.
- Add a record only when you are sure of the citation. If not, say "citation to check" in `notes`.

## How to add one
1. Copy a record. The file name must equal its `id`.
2. Check the citation (authors, year, venue, DOI) against the publisher or Crossref.
3. Run `uv run pytest -q tests/unit/test_library.py`.

## Private notes
The owner's own records go in `<home>/library/private/*.toml`, with the same fields. They are never in git.
