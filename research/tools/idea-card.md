---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/idea_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_card.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_file.py
verified: e76c78af62ceb95d
---
# Idea card

**Reach for it when** the owner states an idea and no test has run yet. Write the card first.

**Command**
```text
alpha idea new --claim "<owner's words>" --disproved-by "<what would kill it>" --json
alpha idea new --from research/examples/idea-card.example.toml
alpha idea show <id>
alpha idea list --json
alpha idea file <id>
alpha idea new --from-rdagent <run>/<idea>
alpha idea link <id> --rdagent <run>/<idea>
alpha idea note <id> "<text>"
```

A card holds nine short fields: the idea, why it could work, the other side, what disproves it, the baseline, four clocks.

**How to read it**
- A field may be empty ("not stated"). No score. The id is a hash of the text. A changed card is a new card
  (`--supersedes <old id>`); the old one stays.
- Link a test: add `idea_card = "<id>"` to a rule-test spec (or `--idea-card <id>` on `alpha test`) or to a
  setup spec. The link is not part of the test identity, so no id, result or trial count changes.
- A run first stored with the link names the card in `manifest.json` (`spine.idea_card` for a rule test,
  `idea_card` for a setup find). "Linked to a test" needs a stored result. An unknown id stops the test.
- RD-Agent: `idea link --rdagent` links a stored journey (`--unlink` adds a later line). `note` is append-only.
- `alpha next` counts the cards. `alpha idea file <id> [--json]` is one read-only page (card, map, readings, paper follows, counts).
  From a published idea: `alpha library card <id>`.

**What it cannot tell you** Whether the idea is good. A card is a note made before the data.

**Next** `alpha test <spec.toml> --json` with the card id in the spec ([rule test](rule-test.md)).
