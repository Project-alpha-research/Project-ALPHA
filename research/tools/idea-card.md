---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/idea_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_card.py
verified: df354f77e1993d98
---
# Idea card

**Reach for it when** the owner states an idea and no test has run yet. Write the card first.

**Command**
```text
uv run alpha idea new --claim "<owner's words>" --disproved-by "<what would kill it>" --json
uv run alpha idea new --from research/examples/idea-card.example.toml
uv run alpha idea show <id>
uv run alpha idea list --json
```

A card holds nine short fields: the idea (the owner's own sentence), why it could work, who is on the other side
of the trade, what result would disprove it, the simplest baseline it must beat, and four clocks (how long a
signal takes to form, how long a trade is held, how often it happens, how long the edge should last).

**How to read it**
- Any field may be empty. `show` lists the fields that are "not stated". There is no score and no pass mark.
- The id is a short hash of the card's text. The same words give the same id. A card never changes: a changed
  card is a new card (`--supersedes <old id>`) and the old one stays.
- Link a test: add `idea_card = "<id>"` to a rule-test spec (or `--idea-card <id>` on `alpha test`) or to a
  setup spec. The link is not part of the test identity, so no id, result or trial count changes.
- A run first stored with the link names the card in `manifest.json` (`spine.idea_card` for a rule test,
  `idea_card` for a setup find). A card reads "linked to a test" only after a run stored its result.
  An unknown id stops the test, and the error names it.
- `alpha next` counts the cards and those with no test yet.

A card can start from a published idea: `alpha library card <id>` ([library](library.md)).

**What it cannot tell you** Whether the idea is good. A card is a note written before the data was seen.

**Next** `uv run alpha test <spec.toml> --json` with the card id in the spec ([rule test](rule-test.md)).
