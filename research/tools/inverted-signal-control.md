---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/controls.py
  - apps/alpha-cli/src/alpha_cli/spine/diagnose.py
verified: 1a8a89f6f3fdbea1
---

# Inverted-signal control

**Reach for it when** the question is "is this just the market going up?" or both directions seem profitable.

**Commands**
```text
uv run alpha diagnose <run_id>
uv run alpha results cite <run_id> inverted_sharpe
uv run alpha results cite <run_id> inverted_sharpe_se
```

**How to read it**

- The diagnostic pass shorts wherever the rule was long, on the same bars, costs and next-open fills; flat
  stays flat. The short is re-sized to 100% of equity (net of the dividends a short pays) every bar, as the
  long side is by construction; the book starts 1,000 times larger so whole-unit rounding cannot stop it.
  It adds no ledger trial and no sensitivity or family count.
- Label, in order: fewer than 30 closed trades either side, inconclusive; rule Sharpe zero or negative,
  inconclusive (the rule itself did not make money); opposite Sharpe positive and at
  least half the rule's positive Sharpe, control failed; opposite Sharpe below zero, control passed;
  anything else inconclusive. The IID-normal standard error is shown but never decides.
- A pass on a rising market adds "this check is weak here"; a nonpositive rule Sharpe says
  "cannot tell: the rule itself did not make money".

**What it cannot tell you**

- A pass is never proof of an edge: a long-only rule's opposite loses on any rising market. A failure
  points at data, costs or drift. No borrow or funding cost is charged; CASH shorts are hypothetical.
- Runs recorded before the entry-gap fix may enter late after a cash rejection; see
  [run rules](../../docs/reference/invariants/cli-runs.md#general-rule-trials). A ruined opposite book gets no label.

**Next** Compare the [benchmark](benchmark-and-drawdowns.md) and [out-of-sample results](walk-forward.md).
