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
alpha forecast run SPY --horizon 21 --samples 100 --as-of 2023-12-29
alpha forecast eval SPY --horizon 21 --stride 21 --samples 30
```
`run` writes an outcome cone: many sampled paths for the next `--horizon` sessions (default 21).
`eval` scores the model at rolling origins, `--stride` bars apart, against what happened and against baselines.

**Context length rule** The model reads the last `--context` bars (default 400; the model caps it at 512).
The stored series must hold at least that many bars, or the command stops with "need >= N context bars".
Pull more history, or lower `--context`.

**How long it takes** The model runs on the CPU by default. Time grows with `--samples` and `--horizon`.
`eval` repeats the run at every origin, so it takes far longer than `run`. Try a small `--samples` first.
The first run may download the model weights. The program does not record timings.

**How to read it**
- Read the cone (median and quartile band), not one path. Eval compares the model with the baselines.
- Eval holds the 2024-01-01 reserved bars back. `run` is forward use and records it. Both warn about overlap with the model's training period.
- The same seed and the CPU give the same paths. `--model fake` is a test double: never use it as evidence.

**What it cannot tell you**
- A cone is a sample from a model, not a prediction or a trade signal.
- The model may have seen the data it is scored on. A good score is not an edge.

**Next** Compare the eval against the baselines before quoting anything. See [data health](data-health.md) for the bars.
