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
verified: ceb51c1ae476edc9
---

# Documentation invariants

What must hold when adding or changing documents under `docs/`: decision records, feature plans and their
delivery states, the generated roadmap index, append-only records, and relative links.

## Document lifecycle

- Living documents (`ARCHITECTURE.md`, `context/`, `governance/` hand-written files, `operations/`) are
  updated in place when behaviour changes (`docs/README.md`).
- The June 2026 research reports (`archive/2026-06-research-notes/`) and dated specs and plans are rationale
  and intent: neither a recommendation nor a `Completed` plan proves current behaviour. Read the accepted ADR, the code and a
  fresh check result. A `verified` commit or resolving links show a document was checked, not that it is right.
- Private research material (such as the owner's October 2026 research archive, kept outside the repository)
  enters only as an owner-authorised, sanitised derivative with its own provenance, after checks for
  credentials, identifiers, private conversations, owner data, licences and redistribution rights. A right
  to keep material privately is not a right to publish it, and private verification grants no authority.
- One home per fact: when behaviour changes, update the one document that owns the fact (see the table in
  `docs/README.md`) and link to it from elsewhere; never copy a fact into a second file. There is no
  manual to update and no delivery log to append to — history is git log and pull requests.
- Retrospectives stay true as of their date: left as-is, with path-only link fix-ups allowed. Older plans,
  records and archives were removed on 2026-11-14; read them at git tag `pre-thin-2026-11-14`. The
  owner's research notes stay in `docs/archive/research-notes/`, never edited (links inside are not checked,
  nor in a build's `brief.md` and `report.md`: [task folders](../../work/CONTEXT.md)).
- Retrospectives are `docs/operations/retrospectives/YYYY-MM-DD-<slug>.md` with a `## Watch-outs` section.
- When the code a document describes changes, re-read the document, fix it and run
  `uv run python scripts/fs.py verify <document>` (with `--reason "<why>"` when it needed no fix);
  `fs.py stale` lists the documents to re-check and `fs.py owners <path>` names the ones that
  describe a file. A stale document is listed, not blocked; one sweep pull request stamps them, not each feature pull request.
- When work lands, any page that listed it as queued, open or not built is updated in the same pull request (search for the feature's name).
- Caps are split triggers, not targets. Near a cap, split by heading into a sibling file, or summarise and link. Never drop words
  to fit. CONTEXT files hold routing only, so they have nothing to cram. A test fails a reference file when more than 20% of its
  prose lines are 150 to 160 characters long (a sign of text squeezed under the line cap).

The project's documentation: the file system's reference material (`docs/reference/`), decision
records (`docs/adr/`), the architecture reference, operations runbooks, governance records and the
roadmap. History is git log and pull requests. Documents describe the code; they never grant authority. Every fact has one home and
other files link to it.

## Front matter

- Every `CONTEXT.md` and hand-written `docs/reference/` file starts with `owner` (a role, never a person),
  `sources` and `verified` (a fingerprint of the content of those sources when the document was last checked
  against them); `tests/unit/test_filesystem_contract.py` enforces the shape.
- A document is stale when any source was edited, added or removed since: its fingerprint no longer matches.
  Another document counts as a source only when `sources` names its exact path, and then by its text below
  the front matter (its own re-stamp does not cascade); one a glob merely covers never counts. A document left
  with nothing to fingerprint is listed by `fs.py stale` as "cannot be checked": give it a real source.
  `fs.py stale` also fails on a document with unreadable front matter or merge conflict markers.
  `uv run python scripts/fs.py stale` lists stale documents; `gate.py check` and the CI `static` job print the list
  and do not fail on it (owner decision 2026-11-21: stamping in every pull request made all open ones conflict).
  A feature pull request fixes wrong TEXT and leaves the stamps; a sweep pull request re-reads and stamps.
- `uv run python scripts/fs.py owners <path>...` names the documents that describe a file. Claude Code is told
  them after every edit by the `post-edit-documents` hook; any other agent learns them from the failing check.
- `sources` lists only files whose change can make the document wrong: the code, scripts, templates,
  schemas and configuration whose behaviour it states. It never lists data the document tells the reader to
  open or edit (`docs/roadmap/capabilities.toml`, backlog items, plans,
  generated pages): those change with routine work, and a document that names their fields is covered by
  the script that reads them (`scripts/capabilities.py`, `scripts/status.py`, `scripts/roadmap_index.py`).
- Never copy a value from a data file (a count, a cap, a list of names) into a document; name the field
  and link the file or the generated page that shows it.
- After re-reading a stale document against its changed sources, fix it, then run
  `uv run python scripts/fs.py verify <document>...`; it prints which sources changed by how many lines. When
  nothing needed fixing, add `--reason "<why it is still correct>"`: `verify` refuses a document whose text
  is unchanged since its last stamp without one, and keeps the latest reason per document in
  `docs/verified-reasons.txt`. Never type a fingerprint by hand, and never verify a document you have not
  re-read: the stamp is your statement that it is true of the sources as they are now.
- Two branches that change sources of one document both rewrite its `verified` line, so the second to merge
  gets a git conflict there: take either side, re-read the document against the merged sources, verify again.
- Reference documents (`docs/reference/**`) and every `CONTEXT.md` follow the contract in
  `tests/unit/test_filesystem_contract.py`: front matter `owner`, `sources`, `verified`; at most 40 lines and 2,560 bytes for a
  workspace `CONTEXT.md` (60 lines for a stage file) and 200 lines for a reference file; no line over 160 characters; no paragraph
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

## Feature plans

- A plan is `docs/work/YYYY-MM-DD-<slug>/02-plan.md` (the task folder of the
  [delivery pipeline](../../../workflow/CONTEXT.md), on the task branch only) with a `FeaturePlan` object in the first
  fenced `json` code block. It must validate against `scripts/harness_models.py::FeaturePlan`
  (`schema_version` 1, at least one alternative, at least two pre-mortem items, at least two slices each
  with `verify`, `expected`, `rollback`, and a closed `tier_impact` list). Check with
  `uv run python scripts/gate.py plan-check docs/work/<task>/02-plan.md`; `scripts/handoff.py build --task`
  runs the same check.
- Every plan has exactly one `**Delivery state:** <state>` line within its first 12 lines.
  States: `Completed`, `Implemented – qualification pending` (en dash), `In progress`, `Blocked`, `Planned`,
  `Superseded by <relative path>`. Text may follow after ` — `, `(`, `.`, `;`, `,` or a date.
- A plan written from 2026-11-14 also states `**Build class:** small|standard|hard — <reason>` in its first
  12 lines and lists every file in scope in the front block's `files`
  ([model routing](../model-routing.md#task-classes)); `scripts/handoff.py` builds and checks from them.
- By convention the state line sits under the title, or on line 1 when a JSON block leads the file, and
  reads `**Delivery state:** <state> — <evidence>` (the test checks only the first 12 lines).
- The task folder is removed before its pull request merges; the pull request is the record.

1. `# <title>`, then within the first 12 lines one `**Delivery state:** Planned — <note>` line
   (vocabulary in the Feature plans rules; `In progress` once stage 03 starts), and one `**Build class:** small|standard|hard — <reason>` line.
2. `## For the owner` — at most 10 plain-English lines: what will change for them, how they will
   see it, what it will not do, anything they must decide.
3. The first fenced `json` block: a `FeaturePlan` (`scripts/harness_models.py`).
4. `## Read first` — a table `| Read | Section | When |` naming the exact files and sections the
   builder must read for this task (workspace files, invariants, the code it changes).
5. `## Slices`, `## Test plan`, `## Look-ahead, determinism and import impact` — short prose.

## Roadmap index

- `docs/roadmap/README.md` is generated: never edit it by hand. Run `uv run python scripts/roadmap_index.py`
  after adding, moving or changing any backlog item or refactor; `--check` reports a stale index, and
  `tests/unit/test_roadmap_index.py` fails on one.
- A wanted feature with no plan is `docs/roadmap/backlog/<slug>.md` with `**Status:**` `Idea` or `Scoped` and
  `**Rough size:**` `S`, `M`, `L` or `XL` within its first 8 lines. Remove it when the work lands.
- A backlog note also has `## Problem / why`, `## What "done" looks like` and `## Dependencies`.
  Every capability id is traced to its checklist row in `docs/roadmap/capability-trace.md`, every
  `alpha` command is named by a capability, and every component page has a `- **Plan:**` line
  linking the roadmap; `tests/unit/test_filesystem_completeness.py` enforces all four.
- Health-plan items not yet done are listed once, in `docs/roadmap/health-plan.md`.
- A staged refactor is `docs/roadmap/refactors/<slug>.md` with `**Risk:**` `L`, `M` or `H` within its first
  8 lines. Copy an existing file's template.

## Generated files

- Regenerate, never hand-edit. The generated files (`STATUS.md`, `docs/reference/commands.md`,
  `docs/roadmap/README.md`, the capability matrix and the OpenAPI classification) and their commands are
  listed once, in [docs/README.md § Generated files](../../README.md#generated-files).
- Status comes from `docs/roadmap/capabilities.toml` via `STATUS.md`; work in progress is the open pull
  requests.

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
