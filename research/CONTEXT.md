---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/research_cmds.py
verified: f53929b25ec79459
---

# Research: how any idea is tested

## Purpose

Any idea goes through one route: read [the playbook](PLAYBOOK.md), then run `uv run alpha test`. No idea is stopped
for being of an unknown kind, and no research run needs an approval; integrity shows as labels and flags. The only
approval gate is before paper or live trading. Changing the research code is a delivery task ([`workflow/`](../workflow/CONTEXT.md)).

| The owner says | Skill (`.agents/skills/<name>/SKILL.md`) |
|---|---|
| an idea, a rule, "does X work" | `test-idea` |
| "is this real", or a result is about to be reported | `review-result` |
| "why did it...", or a flag fires | `investigate-surprise` |
| anything answered with a result | `report-to-owner` |
| "what was...", "did we test..." | `answer-from-records` |
| "remember this", or an idea is closed | `record-lesson` |

## Read first

| Read | Section | When |
|---|---|---|
| [research playbook](PLAYBOOK.md) | — | always |
| [tool cards](tools/README.md) | — | choosing the next test, by symptom |
| [lessons](lessons/README.md) | — | before proposing a test |
| [research integrity](../docs/reference/invariants/research-integrity.md) | Owner authority | before paper or live trading, or any owner act |
| [what this part is for](../docs/reference/project/components/research-cases-and-approval.md) | — | why it exists; before you keep, shelve or remove it |
| [research method](../docs/reference/research-method.md) | — | working a case in the older staged lane |
| [command line research](../docs/reference/invariants/cli-research.md) | — | a staged-lane command refuses and you need the rule behind it |
| [command reference](../docs/reference/commands.md) | alpha research | finding a staged-lane command; full options are `--help` |

## The older staged lane

The governed Research Case lane (`alpha research ...`, the control store, its Workstation screens) still
works and is kept until the playbook route covers what it does. New ideas do not start there. It accepts only
its registered operators; when it reports `RESEARCH_OPERATOR_UNAVAILABLE`, take the idea through the playbook.

| Phase (`uv run alpha research status <case> --json`) | Main commands | Owner act |
|---|---|---|
| `captured`, `triage` | `research capture`, `proposal-options`, `sources add`, `sources freeze` | answers the questions |
| `triage`, `exploration_review` | `research data register`, `research data audit`, `draft`, `export`, `verify` | approves the contract |
| `pilot`, `deep_research` | `research run pilot`, `research run deep` | none, or an early decision |
| `confirmation_review`, `sealed_confirmation` | `research draft-confirmation`, `research run confirm` | approves the one-shot run |
| `research_decision` | `research report`, `evidence-hub`, `decision-view` | `research decide` |

Its stage-by-stage walk-through was removed on 2026-11-15 (readable at commit `0c8b0535`, `research/stages/`).
Its method library, `.agents/skills/alpha-research-protocols/`, stays: the program and the tool server load it.

## Where records live

Nothing a test or a case produces is committed to git. Everything is under the data directory
(`ALPHA_DATA_DIR`, default `data/`, git-ignored; [layout](../docs/ARCHITECTURE.md#runtime-data-directory-layout)):
`runs/<run_id>/` (immutable runs; a rule test adds `diagnostics.json`), `ledger/trials.jsonl` (every rule trial,
failed ones included, append-only), and the staged lane's `control/workstation.sqlite3` and `research/projects/<case>/`.

## Authority

Research needs no approval. Owner acts stay the owner's alone: anything toward paper or live trading, and in the
staged lane approve, reject, decide, revise and authorise ([ADR-0038](../docs/adr/0038-local-confirmation-and-terminal-archive-charts.md)).
An agent never runs an owner command, and never treats a green check or silence as approval.

## How to change it

- The playbook is one page (at most 120 lines); a tool card and a skill are at most 40 lines. Every command,
  option, metric, flag and audit name in them is checked against the program by
  `tests/unit/test_research_playbook.py`. Change the tool first, then the page that describes it.
- A skill's text lives in `.agents/skills/<name>/SKILL.md`; `.claude/skills/<name>/SKILL.md` is a pointer.

## Outputs

- Per idea: run folders and ledger rows under the data directory, and a plain-English report to the owner.
