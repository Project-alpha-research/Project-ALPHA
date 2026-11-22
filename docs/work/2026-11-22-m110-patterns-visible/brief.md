# Brief: trend lines, pivots and chart patterns can be seen and tested

Branch: `feat/m110-patterns-visible`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner is a retail swing trader, NOT a coder. On
2026-11-22 testers used the product on real data as he would and wrote down what failed; this brief fixes one group of those failures.
His words: "I should just be able to use the product and it work properly like any proper software." So: fix exactly what is listed,
in the simplest way; no new options beyond those named; no shims; plain short English in every message. Tests first, on synthetic
fixtures. Do not edit protected paths. Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`. Add only
your own `report.md` in this task folder. Never delete anything that greps positive for `neurotrader`. Done = pull request ready with
a green `ci-ok`.

What failed: "`alpha chart overlays SPY -p trendlines` prints only '581 annotations'. There is no picture and no way to test these in
rules or setups. Head and shoulders is not offered, there is no tool card, and `alpha patterns` does not exist." The pattern code is the
owner's favourite source material (derived from neurotrader888: `packages/alpha-patterns`: trend-line fit, directional change / pivots,
flags and pennants, head and shoulders, harmonics, market structure, perceptually important points, and more). It must become usable.

Build:
1. SEE: `alpha chart overlays <SYMBOL> -p <pattern>` also writes a picture: the price with the pattern drawn on it (trend lines as
   lines, pivots as markers, flags and head-and-shoulders as outlined shapes with a label), for a chosen date window (default: the last
   two years of the data the command may read), as a plain and an annotated pair in the product's figure style (white, standard
   matplotlib; reuse the figure helpers in `apps/alpha-cli/src/alpha_cli/figures/`). Print the file path and a 3-line plain summary
   (how many found, the most recent one and its date), not just a count. Offer every pattern family the package has; list them in
   `--help` and in the error for an unknown name.
2. TEST: each pattern event can be used as a Setup Lab condition (`alpha setup find|study|trade`), so the owner can ask "every time a
   rising trend line broke on NVDA, what came next?". Use the existing Setup Lab alias mechanism (`setupLab`/`setup_expr`); a pattern
   event at bar t may use only bars up to t (a pivot is known only after its confirmation bars: use the confirmation time, never the
   pivot's own bar). Add a look-ahead test per pattern family: changing bars after t must not change events at or before t.
3. Two example setup specs under `research/examples/` (a trend-line break and a pivot reversal) and one tool card
   `research/tools/chart-patterns.md` (at most 40 lines): how to see a pattern and how to test one, in plain words.
Report: which pattern families are now visible and testable, and any that could not be made point-in-time safe (leave those visible
only, and say why).
