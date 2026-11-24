---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/library.py
  - apps/alpha-cli/src/alpha_cli/spine/library_import.py
---
# Library of published ideas

A starting map, not a claim. One small TOML file per published idea in `published/<id>.toml`.
Read them with `uv run alpha library list`. The tool card is [library](../tools/library.md).

## What a record is
A pointer to a paper, in our own words. Fields: `id`, `name`, `source` (authors, year, title, venue, public URL
or DOI), `year_published`, `market`, `idea` (one sentence), `mechanism_claimed` (why it is said to work; the text says if the reading is the authors' or a common later one),
`data_needed`, `direction`, `holding_clock`, `decay_evidence`, `can_test_today`, `notes`, `tier`.
`can_test_today` starts with yes, partly, no or unknown.
`tests/unit/test_library.py` checks every record. An unknown key fails.

## Tiers
- `checked` (default): the hand-checked records in `published/`. Each has `tier = "checked"`.
- `imported`: facts-only records made by a script from a published catalogue, in `imported/<source>/`. Each has
  `tier = "imported"` and an `[imported]` table (source id, release, category, sign, sample years). A record must sit in
  the folder of its tier.
- `alpha library list` shows checked records only and prints the count of each tier. `--tier imported` or `--tier all`
  shows more. `show` works for both. `card` works for an imported record too.
  The idea is a neutral label; edit it. The card's source says "from imported library record <id>; not hand-checked".

## Importing a catalogue
Source: the Open Source Asset Pricing signal table (Chen and Zimmermann, CC BY 4.0). Attribution is in
[imported/osap/README.md](imported/osap/README.md).
```text
curl -sL -A "Project-ALPHA/1.0" -o /tmp/SignalDoc.csv \
  "https://huggingface.co/datasets/OpenSourceAP/CrossSection/resolve/Data-Release-2026.10/SignalDoc.csv"
uv run alpha library import-catalogue osap --from /tmp/SignalDoc.csv --release 2026.10 --into repo
```
`--into home` (the default) writes to `<home>/library/imported/` instead, outside git. The importer keeps the
predictor rows, drops placebo and dropped rows, and fails loud if a needed column is missing.
The 212 records of release 2026.10 are committed: they are facts only and the terms allow redistribution.
The own-words rule below does not apply to them, because no sentence is taken from a paper or from the source's text.

## The own-words rule
- Write every sentence yourself. Do not copy an abstract or a line from a paper. No quotes longer than a few words.
- Do not put third-party data or code in this folder. (Facts-only imported records live in `imported/`, not here.)
- Never write that an idea makes money. Say what the authors report and what later work found.
- Add a record only when you are sure of the citation. If not, say "citation to check" in `notes`.

## How to add one
1. Copy a record. The file name must equal its `id`.
2. Check the citation (authors, year, venue, DOI) against the publisher or Crossref.
3. Run `uv run pytest -q tests/unit/test_library.py`.

## Private notes
The owner's own records go in `<home>/library/private/*.toml`, with the same fields. They are never in git.
