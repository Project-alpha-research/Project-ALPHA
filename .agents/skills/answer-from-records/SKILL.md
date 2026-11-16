---
name: answer-from-records
description: Answer questions about past ALPHA work from the stored records only. Use when the owner asks "what was the Sharpe", "did we test", "what did we find", "how many times", or refers to an earlier result.
---

# Answer from the records

Your memory of earlier chats is not a source. The records are.

1. Find the run: `uv run alpha results --json`, narrowed with `--symbol <SYMBOL>` or
   `--name <test name>` (there is no search by words yet).
2. Quote the number: `uv run alpha results cite <run_id> <metric>`
   ([metric names](../../../research/tools/results-and-cite.md)).
3. Answer with the number, its tag, its labels in plain words, and the date in `recorded_at`.
   Save the draft and run `uv run alpha results check <file>` before sending; fix every problem.

What to say when:

- No run matches: "That was not tested." Offer the exact `alpha test` command that would.
- The ledger is empty (`EMPTY_LEDGER`): "Nothing has been recorded yet."
- The run exists but the value is `null`: "That was not computed for this run", with the
  `reason` from the fact.
- The metric name is unknown (`UNKNOWN_METRIC`): pick from `error.known`; do not guess a value.
- The owner quotes a number that differs from the record: say so plainly, give the recorded
  number with its tag, and do not agree to be polite.
- Two runs could match: list both with their dates and labels, and ask which.
- The question is about a lesson: read `research/lessons/` and cite the lesson's run ids.

A figure is never estimated, recalled or given "roughly". "I don't know; here is how to find
out" is a correct answer.
