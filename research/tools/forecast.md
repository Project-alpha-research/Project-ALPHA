---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/forecast_cmds.py
  - packages/alpha-core/src/alpha_core/config.py
---
# Forecast (Kronos)

**Reach for it when** the owner wants the range of paths a pretrained price model samples for one symbol,
or wants to know how that model scored on past origins.

**Commands**
```text
alpha data pull SPY --start 2015-01-01 --end 2024-01-01     # bars must be stored first
alpha forecast run SPY --as-of 2023-12-31                   # 100 paths, 21 sessions, plus the cone picture
alpha forecast eval SPY                                     # quick look: the latest 6 origins
alpha forecast eval SPY --origins 0                         # every origin: hours on a CPU
```
`run` writes an outcome cone and prints the paths of two pictures: the plain cone and the cone with notes.
`eval` scores the model at rolling origins, `--stride` bars apart, against what happened and against baselines.

**Dates and context** An `--as-of` date with no bar (a weekend, a holiday) uses the last trading day before it, and says so.
The model reads the last `--context` bars (default 400; the model caps it at 512). With fewer bars the default
is lowered to what is there, and the output says so. A `--context` you set that is too long stops and names the largest that works.

**How long it takes** The model runs on the CPU. Each command prints an expected time first, then a progress
line every 10 seconds. Time grows with `--samples`, `--horizon`, `--context` and the number of origins.
The eval output says how long the full run (`--origins 0`) would take.

**How to read it**
- Read the cone (median and quartile band), not one path. Each skill number has a sentence under it:
  above 0% the model's error was smaller than the baseline's; below 0% it was larger.
- Eval holds the 2024-01-01 reserved bars back. `run` is forward use and records it. Both warn about overlap with the model's training period.
- The same seed and the CPU give the same paths. `--model fake` is a test double: never use it as evidence.

**What it cannot tell you**
- A cone is a sample from a model, not a prediction or a trade signal.
- The model may have seen the data it is scored on. A good score is not an edge.

**Next** Compare the eval against the baselines before quoting anything. See [data health](data-health.md) for the bars.
