---
name: review-result
description: Audit a finished ALPHA run for the defects that most often make a backtest wrong. Use before reporting any result, and when the owner asks "is this real", "review this", "audit this", "can I trust this".
---

# Review a result

Assume the result is wrong and look for where. You are a partner, not a cheerleader.

1. `uv run alpha diagnose <run_id> --json`. Read `audit`, `flags` and `trials`
   ([card](../../../research/tools/diagnose-and-audit.md)).
2. Go through every audit line; each is `PASS`, `FLAG` or `NOT-CHECKED`:
   `fills-after-decisions`, `fills-inside-bar-range`, `costs-charged`, `enough-trades`,
   `benchmark-present`, `history-length`, `artifacts-intact`, `quick-run`, `variants-counted`.
3. For each `FLAG`, quote its `detail` and say in one sentence what it means for the result.
   A `FLAG` on `fills-after-decisions` or `artifacts-intact` makes the result unusable: say so.
4. For each `NOT-CHECKED`, say it was not checked. If a tool card can check it, run that.
5. Trials: read `trials_total` or `total_trials`, `variants_evaluated` and `trial_dsr`. List the
   other ledger rows for this rule and asset (`uv run alpha results --symbol <SYMBOL> --json`).
   A best-of-many result is reported as best-of-many.
6. Benchmark: compare `full_sample_sharpe` with `benchmark_sharpe`, both cited. If the rule does
   not beat holding the asset (`below-benchmark`), that comes first.
7. Read the gauntlet lines in `uv run alpha report <run_id>`: the random-price null, the
   bootstrap range, the deflated Sharpe. The stored `verdict` is a grade, not "it works".
8. Say what the audit cannot see ([planned tools](../../../research/tools/README.md#not-available-yet))
   and what evidence would change your view.

Give the review in this order:

- Fatal: what makes the result unusable (the check and its detail).
- Material: what weakens it.
- Not checked, and not available yet.
- What would settle it: one command each, with its cost.

Do not soften a flag, do not add a grade of your own, and do not write "validated" while any
line is `FLAG` or `NOT-CHECKED`. The owner decides what is good enough.
