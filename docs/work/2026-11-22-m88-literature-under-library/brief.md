# Brief: literature search and PDF import move under `alpha library`

Branch: `feat/m88-literature-under-library`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: the owner decided on 2026-11-21 to KEEP literature search and PDF import, and to retire the old "projects / cases / evidence"
machinery they hang from. So these two functions need a home that does not need a project or a case. `alpha library` is the idea and
seed library of the new pipeline. Read `apps/alpha-cli/CONTEXT.md`, the present literature commands (find them with
`uv run alpha info commands --json`; code around `research_literature*` / `literature*` in `apps/alpha-cli/src/alpha_cli/`), the worker
`workers/literature/` (protected: call it as it is called today, do not edit it), and the `alpha library` commands.

Build:
1. `alpha library search "<words>"`: literature search with the same sources and the same worker call as today, with no project or case
   id. Results are stored under the data home in the library area and listed with `alpha library papers`.
2. `alpha library import-pdf <file>`: PDF import with the same extraction as today, stored in the same area; a paper record keeps
   title, authors, year, source, file hash and where the text is. The same file imported twice gives one record.
3. A paper can be linked to an idea card (`alpha idea …`): add `--paper <id>` where an idea is created or edited, and show linked papers
   in `alpha idea file --json`. A paper is a source for ideas only: nothing in it counts as evidence, a test or an approval.
4. The old commands keep working in this pull request and print one line that names the new command. Do not delete them here.
5. Tests use recorded offline responses and a small synthetic PDF only; no network in tests. No key is read or printed.
6. Docs: commands reference (generated), the library tool card under `research/tools/`, the component page that owns literature.

Done: pull request ready with `ci-ok` green, and `report.md` in this folder (include what the old commands needed from projects/cases
and how the new home replaces each need).
