---
name: record-lesson
description: Write down something general that was learned so later work reuses it. Use when an investigation ends, an idea is closed, a test contradicts a held lesson, or the owner says "remember this" or "note that".
---

# Record a lesson

A lesson is a claim that should change what is tried next. A single result is not a lesson.
Lessons are suggestions for the next researcher, never rules.

1. Look first: read the files in `research/lessons/` ([format](../../../research/lessons/README.md)).
   Update an existing lesson rather than adding a near copy.
2. Write `research/lessons/<slug>.md`, about ten lines:
   - Claim: one sentence.
   - Scope: assets, bar size, period. No wider than what was tested.
   - Evidence: run ids, each with a cited number such as `[<run_id>:oos_sharpe]`. At least one.
   - Status: open, held or contradicted.
   - Date. Times used: 0.
3. When you rely on a lesson in later work, add one to "Times used" and say in your answer which
   lessons you checked.
4. New evidence contradicts a lesson: set it to contradicted and add the run id. Keep the file.
5. Tell the owner the lesson in one sentence and where it is saved. A lesson file is committed
   through an ordinary pull request.

Keep in mind:

- A lesson needs a run id. No run, no lesson.
- The owner's view is not a finding: write it as "Owner hypothesis:" until a run supports it.
- Stay inside the scope tested: "on BTC daily bars, 2017 to 2024", not "in crypto".
- A lesson about the system itself ("this command fails on short histories") is welcome: mark
  its scope "system".
