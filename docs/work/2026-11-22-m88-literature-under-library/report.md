# Report: literature search and PDF import under `alpha library`

## Result
Three new commands work with no project or case: `alpha library search "<words>" --unpaywall-email <contact>`,
`alpha library import-pdf <file>` and `alpha library papers`. `alpha idea new --paper <id>` links a paper to a card;
`alpha idea file --json` lists linked papers (key `papers`). The old commands still run.

## What the old commands needed from projects and cases, and the new home
1. `sources discover <project_id>` stored the search in the control store under a project. Now: each hit is one paper file
   under `<home>/library/papers/<id>.json`; the id comes from the worker's candidate id, so a repeat search adds nothing.
2. `sources acquire <project> <discovery> <candidate>` checked a per-discovery full-text budget kept in the project. Now:
   search does no full-text fetch (`--max-full-texts 0`). The owner imports a PDF by hand; the budget is not needed.
3. `import-pdf <project_id>` checked project ownership, bound the source to a project and a contract, and kept the original
   bytes in the control store. Now: the paper keeps the file hash and the place of the extracted text
   (`library/papers/text/<extraction_id>.json`). The same file gives the same id, so one record. Original bytes are not kept
   (the brief asks for hash and text place only; the owner keeps the file).
4. Claims (`sources claim ...`) need a contract. Not moved: a paper is a source for ideas only, not a claim or evidence.
5. A paper links to an idea card by `library/paper-links.jsonl`. The card id does not change with its papers.

## Decisions
- Extraction uses the same worker call and the same validator (`_validated_extraction`, `_read_owner_pdf`) as today.
- Search needs `--unpaywall-email` (the worker requires a contact; it is not a key). No key is read or printed.
- A value not known is stored as null and named in `not_stated`; text shows "not stated". Never zero.
- `--paper` exists on `idea new` only: cards are immutable, and the same card with a new `--paper` adds the link (card id unchanged).
  An unknown paper id stops the command before any card is written.
- The old-command notice goes to stderr (a wrapper in `moved_notice.py`, set up in `main.py`) so `--json` output stays valid.
  Commands covered: `research import-pdf`, `research sources discover`, `research sources acquire`. I added the wrapper outside
  `research_cmds.py` because that file is at its size baseline (3539 lines) and I may not edit the baseline.
- Two existing tests read `result.output` as JSON; the notice on stderr broke them. They now read `result.stdout`
  (`tests/fixtures/research_cli.py`, `test_research_local_pdf_validation.py`). `test_idea_file.py` lists the key `papers`.
- Protected paths untouched (worker, packages, `.claude`, `scripts`).

## Tests
`tests/unit/test_library_papers.py`: 7 tests, recorded offline worker responses and a tiny synthetic PDF; no network.
Fail-first: before the source change, with only the new modules present, 3 of 7 failed (idea link, unknown paper, old-command notice);
the other 4 test the new modules themselves, which were written together with their tests.
Local gate: `gate.py check --base origin/main` passes; `lint-imports` 13 kept; code-size test green.

## Lines
Source: about +330 added (two new modules, small edits), 0 removed. No baseline entry needs lowering.
