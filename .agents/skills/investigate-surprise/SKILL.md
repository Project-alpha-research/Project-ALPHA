---
name: investigate-surprise
description: Find out why an ALPHA result looks the way it does. Use when a diagnose flag fires, a result contradicts the owner's hunch, or the owner asks "why did it lose", "why does it only work in", "what caused this".
---

# Investigate a surprise

The middle of [the playbook](../../../research/PLAYBOOK.md): surprise, rivals, cheapest test.

1. State the surprise in one sentence, with its number and run id, or the flag and its `detail`.
2. List two to four rival explanations. Each names something measurable. Always consider:
   "it is the market", "it is a data or settings error", "it is chance" (few trades, many tries).
3. For each, say what you would expect to see if it were true.
4. Open [the tool cards](../../../research/tools/README.md) by symptom. Pick the cheapest test
   that separates the two leading explanations and say its cost ("free: already in diagnose",
   "one re-run, about a minute"). Much is already there: `drawdowns`, `by_year`,
   `concentration`, `sensitivity`, `delay` and `macro_window` in `alpha diagnose`.
5. Run it. A new `alpha test` is a counted trial: say so.
6. Say what changed: which explanation is now more or less likely, with the new number cited.
7. Decide: next test, stop, or ask the owner. Ask when a definition or a judgement call
   matters. After about three tests on one surprise, report what is known and what is not.
8. If something general was learned, use `record-lesson`.

Keep in mind:

- An explanation is a "Hypothesis:" until its test has run. Do not present it as a finding.
- Do not explain a loss with a market event you have not checked against the stored dates.
- The tool you want may not exist (regimes, beta, change points, capacity): say "not available
  yet", keep the explanation as a hypothesis, and move to the next cheapest test.
- A market-state or macro label that was not knowable on the day is look-ahead: say so.
- Disagree with the owner's hunch when the evidence does. Say what would change your mind.
