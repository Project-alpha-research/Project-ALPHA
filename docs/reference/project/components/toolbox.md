---
owner: project layer
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - tests/unit/test_toolbox_*.py
  - apps/alpha-cli/src/alpha_cli/_rdagent_checks.py
verified: de553e6a7d10b2c0
---

# Toolbox

The toolbox is one catalogue of tests and analyses that can be run on a stored result. Each has a plain
question, declared inputs and settings, a plain reading and caveats, and every attempt to run one is
recorded. The owner's AI assistant uses the catalogue. ALPHA also runs two fixed checks on judged RD-Agent ideas.

Two rule sets: the [runner rules](../../invariants/cli-investigation-tools.md) for every `alpha tool` run (attempts logged,
stored answers reused), and the five [honesty rules](../../invariants/cli-toolbox.md#honesty-rules) for RD-Agent's post-verdict checks only.

## Why it exists

The owner wants "all possible test and system availability like permutation, parameter sensitivity, etc.":
hundreds of tests, if not thousands, not a small fixed set
([owner, 2026-11-18](../owner-decisions-5.md#2026-11-18-the-toolbox-is-an-open-catalogue-meant-to-grow-to-hundreds-of-tests)).
One way to describe, find and run a test makes a new one cost one entry.
Running many tests and quoting the favourable ones is itself overfitting, so the record of what was run is part of the design.

## Its job in the research loop

Step 6, judging, and the "look before testing" step: after a rule test the assistant asks which tests
suit the result and runs them. Later, RD-Agent proposes ideas and may pick tests from the same catalogue;
it would not write them (a recommendation the owner has not yet confirmed,
[log](../owner-decisions-5.md#2026-11-18-rd-agent-may-choose-tests-but-not-write-them-recommendation-not-yet-confirmed)).
Kronos, the four [Monte Carlo](monte-carlo.md) methods, lookalike search and the pattern tools are
meant to become entries too, and are never slimming targets
([log](../owner-decisions-5.md#2026-11-18-kronos-the-four-monte-carlos-lookalike-and-pattern-tools-are-rd-agents-toolbox)).
The Workstation report shows a rule test's stored checks.

## Intended design

- One explicit list of entries in `toolbox/registry.py`; no automatic discovery, so the list is readable.
- Each entry declares an id (`family.name`), a version, a question, a kind (diagnostic, test, control or
  gate), required input, settings with defaults, labelled outputs with units, a reading template filled only
  from those outputs, caveats, a cost class, whether it uses a seed, whether it is safe about time order,
  and the reference test that checks its numbers. An entry holds no statistics: it calls a function in
  `alpha_validation` or an installed library.
- The runner owns everything honest: it writes a ledger row before computing and another with the outcome,
  including errors, so a failed or unflattering attempt cannot hide. A result is stored by a key of input
  hashes, settings, seed and version, so asking again reads the stored answer and is not a new look.
- A "look" class separates describing a result (adds no trial), testing it (counted per result) and
  searching variants (would add the number of variants to the many-tries correction).
- Gates come from a frozen list that is empty today; a tool never changes a grade or a promotion.
- A tool row has a null verdict and adds no deflation trial by itself
  ([rule](../../invariants/cli-investigation-tools.md)). The four settings checks that re-run the engine are the exception:
  each re-run is one `screen_trial` row in the trial ledger ([rule](../../invariants/cli-toolbox.md#checks-that-re-run-the-engine)).
- A single run is labelled `ad-hoc`, a non-default setting `non-default-params`, and a result whose run
  already used 2024 onward `reserved-period-seen`.
- Growth rule: moving an old tool in deletes its old command and card in the same pull request, and a test
  without a known answer (a reference value or a planted effect) does not go in.

## What is real today

The catalogue holds 112 entries in 15 families (`alpha tool list`). The [toolbox rules](../../invariants/cli-toolbox.md#registered-checks)
list what they constrain. `alpha tool` lists, finds, describes and runs them, and records the owner's plan before a look
(`declare`). Every attempt is logged and stored answers are reused. Two predeclared sets exist (`sets.py`): `market-context`
and `rdagent-post-judge`, which runs two fixed checks after each judged RD-Agent idea and never changes the verdict. Not built:
agent-chosen checks and the rest of the 480-candidate catalogue ([STATUS.md](../../../../STATUS.md)).
To add a check, see [Adding a check](../../invariants/cli-toolbox.md#adding-a-check).

## Where it lives

- **Workspaces:** none (inside the command-line workspace `apps/alpha-cli`, owned by [command line](command-line.md)).
- **Capabilities:** `investigation-tools`
- Code: `apps/alpha-cli/src/alpha_cli/toolbox/` (contract, inputs, runner, store, registry,
  sets, reference, families) and `tool_cmds.py`.
- Tests: `tests/unit/test_toolbox_*.py`, `tests/smoke/test_rule_tools_smoke.py`.
- How to change it: [apps/alpha-cli/CONTEXT.md](../../../../apps/alpha-cli/CONTEXT.md); rules in [toolbox rules](../../invariants/cli-toolbox.md)
  and [investigation tools](../../invariants/cli-investigation-tools.md). Tool cards: `research/tools/`.
- **Plan:** the toolbox rows of the [AI partner stage](../../../roadmap/production-scope-2.md#8-ai-partner) of the checklist.

## Decisions and open questions

- Decided 2026-11-18: open catalogue, hundreds of tests (linked above; [decisions log](../owner-decisions.md), volume 5).
- Recommended, not confirmed: RD-Agent chooses tests but does not write them.
- Open, for the owner: the reserve policy (one date for everything, a tail per idea, or labels only; who
  may reveal it) in [ideas and things considered](../ideas-and-considered.md#open-questions); when sweep
  variants enter the deflation count; which stored gauntlet results join the frozen gate list; RD-Agent's
  budget; whether a declared plan is needed before citing evidence toward promotion; who reviews new statistics.

## Never

- Never let a tool change a grade, verdict or promotion; only the owner decides.
- Never let RD-Agent set test settings, write to the gate list or read the reserved period.
- Never hide an attempt, an error or an unfavourable result from the history.
- Never add statistics inside the toolbox; call `alpha_validation` or a library.
- The rules: [investigation tools](../../invariants/cli-investigation-tools.md).
