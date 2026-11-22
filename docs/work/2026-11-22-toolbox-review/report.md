# Report: review of the eight toolbox pull requests (2026-11-22)

Result: all eight pull requests are merged. The toolbox has 101 checks (`uv run alpha tool list | wc -l`).
16 existed before. 85 are new. Two checks were removed in review.

## Pull requests

| PR | Family | Result | Checks added |
|---|---|---|---|
| #394 | G, parameter robustness | Merged. A report only: no check can be built from the shared loader. | 0 |
| #399 | C, performance statistics | Merged. No defect found by this review. | 12 |
| #400 | K and L, risk and sizing | Merged after two fixes. | 13 (1 removed) |
| #396 | E, resampling | Merged after one removal. | 11 (1 removed) |
| #395 | D, overfitting controls | Merged. Builders fixed three edge cases while it was open. | 11 |
| #398 | J, time series | Merged. Builders fixed three edge cases while it was open. | 12 |
| #397 | I, regimes | Merged after one fix. | 14 |
| #401 | H, cost realism | Merged after one fix. | 12 |
| #412 | Docs guards (new) | Merged. Main failed three research-playbook tests after #399. | 0 |

Family G needs the bars and the rule spec in the loader. The owner decides that change. Options are in its report.

## What was checked

1. I read every formula against its source. I merged `origin/main` into each branch.
2. I ran ruff, ruff format, `lint-imports`, mypy, the toolbox tests, `test_research_reads_are_cut.py` and the bias guards. All passed before each push.
3. I ran several checks of each family through `alpha tool run` on a synthetic stored run (`ma_cross`, fast 5, slow 20, 2020 to 2023 fixture bars) and read the sentences as a trader would.
4. I did not recompute every number with scipy again. The builders' known-answer tests do that; I checked that those tests use independent code.

## Defects and fixes

- I, `regimes.break_count`: with no break, the reading said "was unavailable per bar". The largest step is now 0 and the reading says so. Test first.
- K and L, `risk.parametric_var`: a run flat on 37% of bars (normal for a swing rule) collapsed the Student-t fit onto zero. It reported a 0.00% loss.
  The fit is now refused when its tail weight is 2 or less, or its scale is near zero, and the reason names flat bars. Test first.
- H, `cost_realism.financing_cost`, `capacity_curve`, `share_rounding`: they compared the stored equity (it starts at 1.0) with currency amounts.
  The values were wrong on every real run. The tests had hidden it by storing equity in currency. Equity is now scaled by `starting_cash`, and the tests store equity as the engine does.
- Main: after #399, three tests in `test_research_playbook.py` failed (the index did not link the new cards, the situation card passed 40 lines, the card guard wanted every metric in a card).
  CI did not run them. #412 links the cards, allows the generated situation card 200 lines, and accepts a metric when a card names its check.
- Builders still pushed to D, I, J, H, C and K and L during the review (for example haircut at a large t-statistic, non-finite trade profits, flat-market beta bars, constant series).
  I reviewed those changes and merged them.
- CI: a push to a pull request that is still a draft runs only the quick job, and `ci-ok` fails by design. I marked each pull request ready after the push, and where that gave no full run I converted it to draft and back.

## Checks removed

- `risk.worst_windows`: a duplicate of `performance.worst_windows`.
- `resampling.circular_block_paths`: it differs from `resampling.moving_block_paths` only at the ends of the history.

## Final index

The new branch `feat/toolbox-index` adds seven questions in `situations.py` (`QUESTIONS`): bet size, tail loss, enough history, return patterns, weekday and month, real fills, trade size.
Each lists its checks by question, not by family. The registry adds these tags to the checks' own. `alpha tool find "<words>"` reaches them (new synonyms in `find.py`).
The card `research/tools/toolbox-by-situation.md` is regenerated. Test: `tests/unit/test_toolbox_questions.py`.

## Open points for the owner

- Family G (parameter robustness) needs a loader change. See #394.
- 77 living documents are stale in `fs.py stale`. That was true before this work.
- `performance.holding_period` carries the tag `cost-fragile`. It is a description of holding time; I left it.
