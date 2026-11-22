# Report: Workstation rough edges (m116)

Branch `fix/m116-workstation-rough-edges`. Synthetic fixtures only. Each item: cause, change, test.

1. **Slow market view.** Cause: for each of up to 200 assets, every stored bar was validated into an object, then all but the newest 400 were dropped.
   Change: `load_bars(last=)` and `PointInTimeSource.as_of(last=)` cut to the window before bars are built; the route keeps the last 8 answers in memory,
   keyed by the request and the name, size and change time of the bar files; the Market screen shows empty tile frames (no word "Loading").
   A synthetic 200-asset, 6,000-bar store now reads in about 1.9 s. Tests: `tests/unit/test_market_overview.py` (2 new, failed first on the old code),
   `tests/integration/test_web_api_market.py` (cache), `MarketOverview.test.tsx`.
   Decision: the cache lives in the web route, because the CLI is a new process per call and cannot keep memory. `bar_count` is now at most 400.
2. **"not stored" Reading.** Cause: the table relayed only the stored word. Change: an older run with out-of-sample numbers gets its word from
   `alpha_cli.spine.reading.build_reading` (the report's function); with no numbers the cell is the link "older run: open the report".
   Tests: `tests/unit/test_web_recent_runs.py` (failed first), `recentTestsModel.test.ts`.
3. **Labels without meaning.** Cause: `LABEL_MEANING` lacked 20 labels the spine writes. Change: all added, in the one table `ruleTestModel.ts`.
   Test: `tests/unit/test_label_meanings.py` fails for any spine label without a meaning (failed first). Decision: Setup Lab keeps its own
   backend table; merging the two needs a new route and is not in this brief.
4. **Internal tag and paper legend.** Change: the header shows source, venue and bar size only; the legend is "D decision · F fill".
   Test: `chartHeaderModel.test.ts`.
5. **Machine learning screen.** Change: `GET /api/ml-runs` (new, typed, read-only) lists stored `ml_replay` runs with the split sentence, assets, model,
   costs, numbers and folds; the screen adds the reading words, equity and drawdown charts (existing `/api/runs/{id}/equity`) and the fold table; the empty
   state names `alpha ml run`. OpenAPI, `generated.ts` and the authority matrix are regenerated. Tests: `tests/unit/test_web_ml_runs.py`,
   `mlRunsModel.test.ts`, `MachineLearning.test.tsx`. Decision: the manifest stores only `worker.kind`, so the window names the model only for a rank ensemble (LightGBM and ridge) and otherwise says the type is not recorded. `split_sentence` in `ml_run.py` lost its underscore so the web can import it.
6. **Headline periods.** Cause: the sentence did not say the period. Both returns already come from the same stored period row. Change: the sentence now
   ends "…for simply holding the market over the same days (A to B)". Test: `ruleTestModel.test.ts`.

Not done: no browser (Playwright) spec was added or run. The commit trailer names the model that did the work, not the one the brief names.
