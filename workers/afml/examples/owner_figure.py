"""The owner's picture on real daily bars, outside git (SPY and, for numbers only, BTC).

Run from ``workers/afml``:

    uv run python examples/owner_figure.py \\
        --spy /home/hunta/alpha-clean-base/data-alpaca/store/bars/SPY.parquet \\
        --btc /home/hunta/alpha-clean-base/data/store/bars/BTC/USDT.parquet \\
        --out /home/hunta/alpha-clean-base/owner/afml

Reads the bar files only. Writes ``spy-labels-and-uniqueness.png`` and ``summary.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from alpha_afml_worker.figure import draw, summarise
from alpha_afml_worker.labels import LabelParams

# ALPHA's committed figure theme, read as data, relative to workers/afml (run from there).
THEME = Path(
    "../../packages/alpha-research/src/alpha_research/figures/themes/terminal_classic.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spy", type=Path, required=True)
    parser.add_argument("--btc", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    params = LabelParams()
    spy = pl.read_parquet(args.spy)
    numbers, frames = summarise(spy, params)
    theme = json.loads(THEME.read_text("utf-8"))
    draw(spy, numbers, frames, theme, args.out / "spy-labels-and-uniqueness.png", "SPY daily")
    summary = {"SPY": numbers}
    if args.btc:
        summary["BTC"] = summarise(pl.read_parquet(args.btc), params)[0]
    text = json.dumps(summary, indent=2, sort_keys=True, default=str)
    (args.out / "summary.json").write_text(text + "\n", "utf-8")
    print(text)


if __name__ == "__main__":
    main()
