---
name: test-idea
description: Run a trading idea through ALPHA's one pipeline and record it. Use when the owner states an idea, a rule or a setup, or asks "does X work", "test this", "try this on".
---

# Test an idea

Nothing is refused. Integrity shows as labels on the result. The method is
[the playbook](../../../research/PLAYBOOK.md); this is its first half.

1. Look first: `uv run alpha results --json` (add `--symbol` or `--name` to narrow) and
   [the lessons](../../../research/lessons/README.md). Tell the owner what was already tried.
2. Write the spec in the owner's words: quote their sentence in `idea`. Say what result would
   disprove it. If a definition is unclear (which average, which bar, which assets), ask one
   question, then go on. Format: [rule test card](../../../research/tools/rule-test.md).
3. Run it: `uv run alpha test <spec.toml> --json`. Use `--quick` only for a first look, and
   call it a quick look.
4. The rule does not fit `ma_cross`, `breakout` or `tsmom`, or needs shorts or sizing: say so,
   offer the nearest rule that can run today, and label the answer as that nearer rule.
5. A command fails: read `error.next` and `error.known`, and do what `next` says. An asset that
   fails is "not tested"; never swap in another asset silently.
6. For each `run_id`: `uv run alpha diagnose <run_id> --json`. Read `labels`, `trials_total`,
   `flags` and `audit` before saying anything.
7. Go on to `review-result`, then `report-to-owner`. A flag or a surprise: `investigate-surprise`.

Keep in mind:

- Each change of a number after seeing a result is a new counted trial; say you changed it.
- A result exists only for a run that finished. Numbers come from the run, with its run id.
- A spec expresses the rule; do not write strategy code for it.
- This is also a system test: note every command that failed or confused you, for the report.

Checklist:

- [ ] ledger and lessons looked at
- [ ] owner's sentence quoted in the spec; what would disprove it stated
- [ ] run finished; run ids and `test_id` noted
- [ ] diagnose read; labels, flags, audit and trial count noted
