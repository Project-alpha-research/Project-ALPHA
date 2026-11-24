---
owner: web frontend
sources:
  - apps/alpha-web/frontend/index.html
  - apps/alpha-web/frontend/src/**
  - apps/alpha-web/frontend/e2e/**
  - apps/alpha-web/frontend/package.json
  - apps/alpha-web/frontend/vite.config.ts
  - apps/alpha-web/frontend/vitest.config.ts
  - apps/alpha-web/frontend/playwright.config.ts
  - apps/alpha-web/frontend/scripts/normalize-build.mjs
  - scripts/run_frontend_browser_lanes.py
  - tests/integration/test_web_spa_assets.py
  - tests/unit/test_web_menu_groups.py
---

# Web frontend charts, exports and API client

Rules for charts, exact exports and the generated API client in the Workstation app. The other browser rules are in [web frontend](web-frontend.md).

## Charts

- Study values come only from `alpha chart overlays`. A study the CLI refuses (for example, longer than the window) is dropped by name; an overlay failure
  shows `overlays unavailable`. Never estimate a missing value.
- Never resample, aggregate or substitute bars in the browser. An interval needs a compatible recorded native source; there is no automatic venue or market
  substitution.
- Archive, run and snapshot contexts never silently fall back to canonical stored bars. A run without a recorded price snapshot cannot borrow current candles.
  The one exception is the small walk-forward chart on the Gates tab: it draws the bars stored now, cut at the run's last date,
  and its legend says the run's own bars were not saved.
  A rule test records no snapshot, so its price comes from the same exception: the bars stored now, cut at the research cut-off and the run's
  last date, drawn only when their source fingerprint equals the one the run recorded. Otherwise the pane says why (`bars_changed_since_run`,
  `price_not_saved_with_run`) and draws nothing. A bar at or after the cut-off is never read.
  Archive charts stay separate from strategy context.
- `components/tearsheet/TearSheetStack.tsx` draws one BokehJS grid from `GET /api/runs/{id}/series`: price with entry and exit markers,
  equity against buy and hold (Log toggle), and drawdown, on one x-range with one crosshair and one readout. Tested periods and
  walk-forward tests are shaded and named. It draws stored values only; the model (`tearSheetModel.ts`) computes no statistic. Colours come from the theme.
- In `ChartWorkspace` (at most four panels) only the primary panel follows canonical market navigation. Comparison panels stay pinned, and changing a panel's
  source never changes canonical research context.
- Keep chart creation separate from option, evidence and selection updates; fit/reset happens only on request.
- Analytical panels default to the `scientific` (BokehJS) renderer; Lightweight Charts (`market`) is opt-in. The default `chartStyle` is `classic`
  (`components/technical/`).
- The technical chart spaces bars by observation. Where the series' own calendar (weekday or continuous) has no observation it draws a gap mark; it never
  interpolates a bar.
- Volume colouring uses exact native-index viewport intersections, including partly visible edge bars, and classifies up/down against the previous close (an
  unchanged close counts as up). Keep the full x/volume source.
- Price annotations keep unit isolation: only `unit: 'price'` annotations draw on the price pane.
- Bokeh views own standalone documents. Release the views and the document/model registries on cancel, failure and disposal.
- A canvas is invisible to a screen reader. Every canvas chart needs a real-markup alternative: `panels/ChartDataAlternative.tsx` for price bars, and
  `components/FigureCard.tsx` alt text, caveats and value tables for server figures.
- A figure card shows the plain chart with a "Show annotated" toggle, the long explanation beside it and an "Open full screen" action.
  Charts stay white (system `Canvas` under `color-scheme: light`) on every screen theme. The variant is part of the image URL and the cache key;
  `components/figureVariant.ts` holds the pure choices.
- Never change timing budgets or aggregate bars to make a performance test pass. The `@perf-budget` specs run only with `ALPHA_PERF_BUDGETS=1` on an idle
  reference machine.
- Screenshot baselines are kept per platform (`*-darwin.png`, `*-linux.png`). Re-take Linux images in the Playwright Linux container; never copy macOS images
  over them.

## UTC and exact exports

- Display timestamps through `util/formatTime.ts`: `17 Nov 2026, 14:33 UTC`, with raw ISO in the element title.
  Recorded durations use whole minutes/hours (`<1 min` below a minute). CSV exports keep ISO-8601 UTC and exact values —
  zero and negative kept, an empty cell for a missing value. Enforced by `src/panels/chartTableModel.test.ts` and
  `src/components/scientificPlotModel.test.ts`.
- Preserve backend null gaps; never join or fill them. Show a missing study value as `—`.
- Rounding is display-only (Market Watch shows 7 significant digits). Tables and exports keep exact values.
- Date windows (All / 30D / 90D / 1Y, custom) are display ranges over returned coverage. They never refetch or resample.

## Generated API client

- `src/api/generated.ts` is generated from `openapi.json` by `npm run generate:api` (openapi-typescript). Never edit it
  by hand. `src/api/types.ts` gives readable aliases over its `components`.
- Change the backend first, regenerate `openapi.json` (see [web-api.md § API contract](web-api.md#api-contract)), then
  regenerate the client and commit both. The frontend gate fails if `generated.ts` differs after regeneration.
- The SPA owner-action union must match the server's closed action list minus `record_semantic_event`, which the
  browser never sends (`src/api/ownerActions.test.ts`, `tests/unit/test_web_owner_actions_drift.py`).
