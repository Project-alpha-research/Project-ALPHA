---
owner: documentation set
sources:
  - docs/README.md
  - scripts/roadmap_index.py
  - scripts/harness_awareness.py
  - scripts/harness_models.py
  - tests/unit/test_docs_links.py
  - tests/unit/test_repo_awareness_drift.py
  - tests/unit/test_roadmap_index.py
---

# Documentation invariants

What must hold when adding or changing documents under `docs/`: decision records, the roadmap index,
append-only records, and relative links.

## Document lifecycle

- Living documents (`ARCHITECTURE.md`, `context/`, `governance/` hand-written files, `operations/`) are
  updated in place when behaviour changes (`docs/README.md`).
- The June 2026 research reports (`archive/2026-06-research-notes/`) and dated specs and plans are rationale
  and intent: neither a recommendation nor a `Completed` plan proves current behaviour. Read the accepted ADR, the code and a
  fresh check result. Resolving links show a document is connected, not that it is right.
- Private research material (such as the owner's October 2026 research archive, kept outside the repository)
  enters only as an owner-authorised, sanitised derivative with its own provenance, after checks for
  credentials, identifiers, private conversations, owner data, licences and redistribution rights. A right
  to keep material privately is not a right to publish it, and private verification grants no authority.
- One home per fact: when behaviour changes, update the one document that owns the fact (see the table in
  `docs/README.md`) and link to it from elsewhere; never copy a fact into a second file. There is no
  manual to update and no delivery log to append to — history is git log and pull requests.
- Retrospectives stay true as of their date: left as-is, with path-only link fix-ups allowed. Older plans,
  records and archives were removed on 2026-11-14; read them at git tag `pre-thin-2026-11-14`. The
  owner's research notes stay in `docs/archive/research-notes/`, never edited (links inside are not checked).
- Retrospectives are `docs/operations/retrospectives/YYYY-MM-DD-<slug>.md` with a `## Watch-outs` section.
- Pages are kept true by structure, not by stamps. Anything code can derive is generated on demand and
  never stored (the command list, the status page, the roadmap index: see
  [docs/README.md § Generated files](../../README.md#generated-files)). A prose page holds only purpose,
  reasoning and limits. A weekly sweep re-reads the pages against the code and fixes drift; a feature pull
  request fixes text it knows is wrong, and nothing else.
- When work lands, any page that listed it as queued, open or not built is updated in the same pull request (search for the feature's name).
- Caps are split triggers, not targets. Near a cap, split by heading into a sibling file, or summarise and link. Never drop words
  to fit. CONTEXT files hold routing only, so they have nothing to cram. A test fails a reference file when more than 20% of its
  prose lines are 150 to 160 characters long (a sign of text squeezed under the line cap).

The project's documentation: the file system's reference material (`docs/reference/`), decision
records (`docs/adr/`), the architecture reference, operations runbooks, governance records and the
roadmap. History is git log and pull requests. Documents describe the code; they never grant authority. Every fact has one home and
other files link to it.

## Front matter

- Every `CONTEXT.md` and `docs/reference/` file starts with `owner` (a role, never a person) and `sources`
  (the code, scripts and configuration the page describes); `tests/unit/test_filesystem_contract.py`
  enforces the shape and that each source glob still matches a tracked file. There is no stamp and no
  stale alarm: the weekly sweep uses `owner` and `sources` to know what to re-read.
- `sources` lists only files whose change can make the document wrong. It never lists data the document
  tells the reader to open or edit (`docs/roadmap/capabilities.toml`, backlog items, plans).
- Never copy a value from a data file (a count, a cap, a list of names) into a document; name the field
  and link the file, or name the command that prints it.
- Reference documents (`docs/reference/**`) and every `CONTEXT.md` follow the contract in
  `tests/unit/test_filesystem_contract.py`: front matter `owner`, `sources`; at most 40 lines and 2,560 bytes for a
  workspace `CONTEXT.md` and 200 lines for a reference file; no line over 160 characters; no paragraph
  repeated across files.

## Decision records

- ADRs are `docs/adr/NNNN-<slug>.md`, zero-padded and sequential; a number is never reused. Add the new
  record to the index table in `docs/adr/README.md`. If another branch merges first and takes the number, renumber
  yours before it merges (ADR-0045 was 0044 until then) and fix every reference.
- Decision text is not rewritten. A superseded ADR keeps its number; add a dated status note and a forward
  link to its replacement.
- Status is one of `Proposed`, `Accepted`, `Superseded`. Keep the Status/Date/Deciders header and the
  `Context`, `Decision` and `Consequences` sections, and cite precise `file:symbol` or test anchors.
- Every ADR file is linked from the index table in `docs/adr/README.md`, its one listing. Enforced by
  `tests/unit/test_repo_awareness_drift.py` through `scripts/harness_awareness.py::adr_drift`.
- When the owner says something directional, a decision entry (date, decision, reason, what it changes) lands
  in [the newest decisions volume](../project/owner-decisions-6.md) in the same pull request as the work it
  changes, or in a documentation pull request the same day; an idea considered but not decided goes in
  [ideas and things considered](../project/ideas-and-considered.md).

## Roadmap index

- `docs/roadmap/README.md` is three lines of routing, written by hand. The index of backlog items and
  refactors is not stored: print it with `uv run python scripts/roadmap_index.py`
  (`tests/unit/test_roadmap_index.py` checks the generator and the item templates).
- A wanted feature with no plan is `docs/roadmap/backlog/<slug>.md` with `**Status:**` `Idea` or `Scoped` and
  `**Rough size:**` `S`, `M`, `L` or `XL` within its first 8 lines. Remove it when the work lands.
- A backlog note also has `## Problem / why`, `## What "done" looks like` and `## Dependencies`.
  Every `alpha` command is named by a capability, and every component page has a `- **Plan:**` line
  linking the roadmap; `tests/unit/test_filesystem_completeness.py` enforces both.
- Health-plan items not yet done are listed once, in `docs/roadmap/health-plan.md`.
- A staged refactor is `docs/roadmap/refactors/<slug>.md` with `**Risk:**` `L`, `M` or `H` within its first
  8 lines. Copy an existing file's template.

## Generated files

- Regenerate, never hand-edit. The stored generated files (the capability matrix and the OpenAPI
  classification) and their commands are listed once, in
  [docs/README.md § Generated files](../../README.md#generated-files).
- Not stored, printed on demand: `uv run python scripts/status.py` (what works today, from
  `docs/roadmap/capabilities.toml`), `scripts/commands_reference.py`, `scripts/roadmap_index.py`. Work in
  progress is the open pull requests.

## Links

- Relative Markdown links must resolve, including `#fragment` anchors on Markdown targets (GitHub heading
  slugs or explicit `<a id>`). Scope: tracked `docs/**/*.md`, root `*.md`, `.claude/**/*.md`,
  `.agents/**/*.md`, and READMEs under `apps/`, `packages/`, `workers/`. Fenced code, inline
  code, external URLs and `mailto:` are skipped. Enforced by `tests/unit/test_docs_links.py`.
- Its `ALLOWLIST` is only for links in dated records whose target was removed or moved; each entry needs a
  reason and the test fails if an entry is no longer needed. A link to removed history points at git tag
  `pre-thin-2026-11-14` on GitHub.
- Find documents with `uv run python scripts/fs.py search "QUERY"`; heading matches rank first.

## Research playbook and tool cards

- The playbook is one page (at most 120 lines); a tool card and a skill are at most 40 lines. Every command,
  option, metric, flag and audit name in them is checked against the program by
  `tests/unit/test_research_playbook.py`. Change the tool first, then the page that describes it.
- A skill's text lives in `.agents/skills/<name>/SKILL.md`; `.claude/skills/<name>/SKILL.md` is a pointer.
