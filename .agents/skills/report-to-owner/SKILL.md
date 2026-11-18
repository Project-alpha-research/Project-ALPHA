---
name: report-to-owner
description: Write the plain-English answer the owner reads after a test, review or investigation. Use for any owner-facing reply that contains a result, a number or a recommendation from ALPHA.
---

# Report to the owner

The owner is a swing trader, not a coder. Short sentences. No jargon without a gloss. Never
promise or imply a profit.

1. Get the facts: `uv run alpha results show <run_id> --json` (a `test_id` works too). Copy
   numbers from it; do not retype from memory.
2. Tag each number: `uv run alpha results cite <run_id> <metric>` prints
   `<value> [<run_id>:<metric>]`. A number from `alpha diagnose` or `alpha report` that `cite`
   does not cover is quoted with the run id and the field or line it came from.
3. Write in this order:
   - What this run showed about the system: failed commands, missing tools, confusing output,
     anything `NOT-CHECKED`. Until ALPHA is production grade this comes first.
   - Answer: one paragraph. Lead with the comparison against holding the asset.
   - What was tested: the owner's sentence, the rule and its numbers, assets, dates, costs.
   - Labels, in plain words, before the numbers
     ([wording](../../../research/PLAYBOOK.md#labels-flags-and-trial-counts)).
   - Numbers, each with its tag.
   - Charts, by the names in `charts`, rendered ([card](../../../research/tools/charts.md)).
   - Flags and audit: every flag, every `FLAG`, every `NOT-CHECKED`.
   - Tried so far: "trial N of M recorded", the re-runs, and any runs the ledger does not count.
   - Next: one to three steps, each with a reason, what it would tell us, and its cost.
4. Mark every sentence that is not a recorded fact "My reading:" or "Hypothesis:".
5. Save the draft to a file and run `uv run alpha results check <file>`; fix every problem and
   re-run until it says OK; never send a draft that fails. Asked how numbers were checked, say
   so and offer `uv run alpha partner selftest`.

Writing style (Simplified Technical English, about 80% of the way):

- Answer first. Write less, not only simpler.
- Short sentences, one idea in each. Active voice. Steps as numbered lists.
- One name for one thing: never vary the name of a test, stage or metric in a report. Use the
  name in the [glossary](../../../docs/reference/glossary.md).
- Every number carries its unit.
- No wording that implies profit or a recommendation.

Keep in mind:

- A number that was not computed is written "not computed", with the command that would.
- Do no arithmetic of your own; quote both numbers, or the recorded `strategy_minus_benchmark`.
- Say what was measured, not "validated", "proven", "works" or "profitable".
- A label stays on the result even when the result looks good.
- Say plainly when the evidence goes against the owner's view, and what would change yours.
