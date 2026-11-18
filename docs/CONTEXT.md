---
owner: documentation
sources:
  - docs/README.md
  - scripts/roadmap_index.py
  - scripts/fs_stale.py
  - tests/unit/test_docs_links.py
verified: 9fa7d28629ce6172
---

# docs workspace

## Purpose

The project's documentation: the file system's reference material (`docs/reference/`), decision
records (`docs/adr/`), the architecture reference, operations runbooks, governance records and the
roadmap. History is git log and pull requests. Documents describe the code; they never grant authority. Every fact has one home and
other files link to it.

## Read first

| Read | Section | When |
|---|---|---|
| [documentation invariants](reference/invariants/documentation.md) | — | always |
| [documentation index](README.md) | Lifecycle | always |
| [documentation index](README.md) | Folders | deciding where a new document goes |
| [documentation invariants](reference/invariants/documentation.md) | Decision records | writing or superseding an ADR |
| [documentation invariants](reference/invariants/documentation.md) | Feature plans | writing or closing a plan |
| [outside projects register](reference/project/outside-projects.md) | — | adding, upgrading or judging a library or outside project |
| [command reference](reference/commands.md) | — | documenting a command (link here; never copy it) |
| [what this part is for](reference/project/components/delivery-and-agent-tooling.md) | — | why it exists; before you keep, shelve or remove it |
| [ideas and things considered](reference/project/ideas-and-considered.md) | — | before proposing an idea; one line each, with its status |

## How to change it

- Reference documents (`docs/reference/**`) and every `CONTEXT.md` follow the contract in
  `tests/unit/test_filesystem_contract.py`: front matter `owner`, `sources`, `verified`; at most 80
  lines for a CONTEXT file and 200 for a reference file; no line over 160 characters; no paragraph
  repeated across files.
- When the code a document describes changes, re-read the document, fix it and run
  `uv run python scripts/fs.py verify <document>`; `fs.py stale` lists the documents to re-check
  and `fs.py owners <path>` names the ones that describe a file. The check fails while one is stale.
- When the owner says something directional, a decision entry (date, decision, reason, what it changes) lands
  in [the newest decisions volume](reference/project/owner-decisions-5.md) in the same pull request as the work it
  changes, or in a documentation pull request the same day; an idea considered but not decided goes in
  [ideas and things considered](reference/project/ideas-and-considered.md).
- Generated pages are never edited by hand; their commands are listed in
  [docs/README.md § Generated files](README.md#generated-files).
- Check: `uv run pytest -q tests/unit/test_docs_links.py tests/unit/test_filesystem_contract.py`,
  then `uv run python scripts/gate.py check`.

## Outputs

- The one owning document updated, links resolving, generated pages regenerated.
- The owning document for these rules: `docs/reference/invariants/documentation.md`.
