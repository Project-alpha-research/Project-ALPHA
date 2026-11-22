# Report: patterns visible and testable (M110)

## Answer
Twelve pattern families are visible. Nine are also testable as Setup Lab conditions. Three are visible only.

## Visible and testable
swings, dc_extremes, structure_levels, trendlines, flags, head_shoulders, wedges, triple_taps, harmonics.
Each event is 1 on the bar where it became known and 0 elsewhere. The first 60 bars are missing (`series-warm-up`).
Head and shoulders and wedges are re-run on the bars up to each pivot confirmation, so a later bar never changes an earlier event.
Each family has a look-ahead test in `tests/unit/test_pattern_events.py`.

## Visible only
- `pips`: the points move as the window moves. There is no event with a time.
- `market_profile`: it draws price levels at the last bar, not an event.
- `levels` (Fibonacci grid): it draws a grid at the last bar, not an event.

## What changed
1. `alpha chart overlays SYM -p <pattern>` writes a plain and an annotated PNG and prints 3 lines (count, most recent, paths).
   Files go to `<data home>/chart_patterns/`, named with a hash of their bytes. Default window: last two years. `--since` moves it.
2. `--help` and the unknown-name error list every family, including `head_shoulders`, `wedges`, `triple_taps`.
3. Examples: `research/examples/setup-trendline-break.example.toml`, `setup-pivot-reversal.example.toml` (a test runs both).
   Tool card: `research/tools/chart-patterns.md`.

## Decisions
- `--json` writes no picture. The web chart calls it, and a display read should not write files.
- The three new families are not added to `PATTERNS`: the web list must match it (`test_overlay_tables_drift.py`) and the web change is out of scope.
  They live in `ALL_PATTERNS`, used by the command and the picture.
- One new option, `--since`, for the "chosen date window" in the brief.
- Commit trailer: the brief names `Claude Fable 5.2`. The session itself named a different trailer. I used the brief's line as the more specific owner instruction.
- The tool card has no verified hash (`verified: 0000...`). I did not run `fs.py verify`, as the rules say.

## Fail-first evidence
`tests/unit/test_chart_pattern_picture.py` first failed with `ModuleNotFoundError: alpha_cli.chart_pattern_picture`, before the module existed.

## Not done
No data of the owner's was used. Pictures were checked on synthetic random prices only: on random prices, many trend lines are normal.
