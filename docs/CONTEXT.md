---
owner: documentation
sources:
  - docs/README.md
  - scripts/roadmap_index.py
  - scripts/fs_stale.py
  - tests/unit/test_docs_links.py
verified: 116bd0583054770c
---

# docs workspace

## Purpose

The project's documentation: reference material, decision records, the architecture, runbooks, governance records and the roadmap.
Documents describe the code; they never grant authority. Every fact has one home and other files link to it.

## Read first

| Read | Section | When |
|---|---|---|
| [documentation invariants](reference/invariants/documentation.md) | Document lifecycle | always |
| [documentation invariants](reference/invariants/documentation.md) | Links | always |
| [documentation index](README.md) | Lifecycle | always |
| [documentation index](README.md) | Folders | deciding where a new document goes |
| [documentation invariants](reference/invariants/documentation.md) | — | an ADR, a plan, front matter, roadmap index or generators |
| [outside projects register](reference/project/outside-projects.md) | — | adding, upgrading or judging a library or outside project |
| [what this part is for](reference/project/components/delivery-and-agent-tooling.md) | — | why it exists; before you keep, shelve or remove it |
| [ideas and things considered](reference/project/ideas-and-considered.md) | — | before proposing an idea; one line each, with its status |

## How to change it

- Contract: `tests/unit/test_filesystem_contract.py`. When code changes, re-read the document and run
  `uv run python scripts/fs.py verify <document>`: [document lifecycle](reference/invariants/documentation.md#document-lifecycle).
- Check: `uv run pytest -q tests/unit/test_docs_links.py tests/unit/test_filesystem_contract.py`,
  then `uv run python scripts/gate.py check`.

## Outputs

- The owning document for these rules: `docs/reference/invariants/documentation.md`.
