"""The research cut-off must make a rule test's run and its canonical files future-poison invariant.

Ported from the old `alpha backtest run --as-of` lane to `alpha test`. In the new pipeline the
research cut-off of a rule test is the held-back boundary (`alpha_core.reserve`, applied by
`alpha_cli.spine.run.prepare_asset` with `alpha_cli.spine.reserve.CUTOFF`). A user-chosen cut-off
lives on in the engine loader (`_runner.load_bars(as_of=...)`, which `spine.reserve.hold` passes for
other commands); the last two tests keep that case on the engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.main import app
from alpha_cli.spine.reserve import CUTOFF_DATE
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import Bar
from alpha_core.reserve import RESERVED_DAY
from alpha_data.store import ParquetStore
from tests.fixtures.forecast_fixtures import store_bars

pytestmark = pytest.mark.bias_guard

ARTIFACTS = (
    "manifest.json",
    "equity_curve.parquet",
    "decision_trace.parquet",
    "indicator_series.parquet",
)
ARGS = [
    "test", "--rule", "ma_cross", "--param", "fast=5", "--param", "slow=20",
    "--asset", "SPY", "--fee-bps", "1", "--slippage-bps", "2", "--quick", "--no-diagnose", "--json",
]  # fmt: skip


def _bars() -> list[Bar]:
    """Weekday bars of a noisy walk from 2023-01-02 to 2024-02-23: 251 before the boundary."""
    rng = np.random.default_rng(3)
    days = [date(2023, 1, 2) + timedelta(days=i) for i in range(420)]
    days = [d for d in days if d.weekday() < 5]
    close = 100.0 * np.cumprod(1.0 + 0.0004 + rng.normal(0.0, 0.012, len(days)))
    out: list[Bar] = []
    for i, d in enumerate(days):
        prev = float(close[i - 1]) if i else float(close[0])
        c = float(close[i])
        out.append(
            Bar(
                symbol="SPY",
                ts=datetime.combine(d, time.min, tzinfo=UTC),
                open=round(prev, 2),
                high=round(max(prev, c) * 1.003, 2),
                low=round(min(prev, c) * 0.997, 2),
                close=round(c, 2),
                volume=1_000.0,
            )
        )
    return out


CLEAN = _bars()
LAST_IN = max(i for i, bar in enumerate(CLEAN) if bar.ts.date() < RESERVED_DAY)


def _spike(bar: Bar) -> Bar:
    close = bar.close * 7.0
    return Bar(
        symbol=bar.symbol,
        ts=bar.ts,
        open=bar.open,
        high=max(bar.high, close),
        low=bar.low,
        close=close,
        volume=bar.volume,
    )


def _home(root: Path, bars: list[Bar]) -> Path:
    store_bars(root, bars)
    ParquetStore(root / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return root


@dataclass(frozen=True)
class Run:
    run_id: str
    test_id: str
    files: dict[str, bytes]


def _run(home: Path) -> Run:
    """One `alpha test` in its own fresh home, so a second run can never be a stored repeat."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("ALPHA_DATA_DIR", str(home))
        result = CliRunner().invoke(app, ARGS)
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    out = output["results"][0]
    assert out["error"] is None, out["error"]
    assert out["executed"] is True
    run_dir = Path(out["run_dir"])
    assert json.loads((run_dir / "manifest.json").read_text())["research_cutoff"] == CUTOFF_DATE
    files = {name: (run_dir / name).read_bytes() for name in ARTIFACTS}
    return Run(str(out["run_id"]), str(output["test_id"]), files)


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    poisoned = CLEAN[: LAST_IN + 1] + [_spike(bar) for bar in CLEAN[LAST_IN + 1 :]]
    spiked = [*CLEAN[:LAST_IN], _spike(CLEAN[LAST_IN]), *CLEAN[LAST_IN + 1 :]]
    return {
        name: _run(_home(tmp_path_factory.mktemp(name), bars))
        for name, bars in (("clean", CLEAN), ("poisoned", poisoned), ("spiked", spiked))
    }


def _results(run: Run) -> dict[str, object]:
    """The run's files with its own identity masked: every decision, value and number stays."""
    out: dict[str, object] = {}
    for name, data in run.files.items():
        for word in (run.run_id, run.test_id):
            data = data.replace(word.encode(), b"<id>")
        if name == "manifest.json":
            manifest = json.loads(data)
            manifest.pop("data_health")  # its whole-file fingerprint: see the identity test
            manifest["artifacts"].pop("tearsheet.html")  # the page prints the run id
            out[name] = manifest
        else:
            out[name] = data
    return out


def test_post_cutoff_price_mutation_cannot_change_research_results(runs: dict[str, Run]) -> None:
    assert len(CLEAN) - LAST_IN - 1 >= 30  # the poison covers many held-back bars
    assert _results(runs["poisoned"]) == _results(runs["clean"])


def test_post_cutoff_price_mutation_cannot_change_research_run(runs: dict[str, Run]) -> None:
    """The original property: the run id itself is invariant under held-back poison."""
    assert runs["poisoned"].run_id == runs["clean"].run_id
    assert runs["poisoned"].files == runs["clean"].files


def test_cutoff_guard_has_in_window_discriminating_power(runs: dict[str, Run]) -> None:
    assert runs["spiked"].run_id != runs["clean"].run_id
    assert _results(runs["spiked"]) != _results(runs["clean"])


def _as_of(k: int) -> datetime:
    """The old `--as-of YYYY-MM-DD` of bar ``k``, parsed as the old command parsed it."""
    parsed = _runner.parse_as_of(CLEAN[k].ts.date().isoformat())
    assert parsed is not None
    return parsed


def _engine(home: Path, as_of: datetime) -> tuple[list[Bar], list[tuple[object, ...]]]:
    bars, _ = _runner.load_bars("SPY", data_dir=home, as_of=as_of)
    idea = IdeaSpec.model_validate(
        {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 5, "slow": 20}}
    )
    result = _runner.run_full_backtest(bars, assemble_run_spec(idea, "SPY", 252, len(bars)))
    trace = [(r.ts, r.signal, r.target_quantity) for r in result.decision_trace]
    values = [(r.ts, r.name, r.value) for r in result.indicator_trace]
    return bars, [*trace, *values, *result.equity_curve]


def test_a_user_cutoff_on_the_engine_loader_is_future_poison_invariant(tmp_path: Path) -> None:
    """The old `--as-of` case at an arbitrary in-history cut-off, on the loader that stays."""
    k = 150
    as_of = _as_of(k)
    clean_bars, clean = _engine(_home(tmp_path / "a", CLEAN), as_of)
    poisoned = CLEAN[: k + 1] + [_spike(bar) for bar in CLEAN[k + 1 :]]
    poisoned_bars, after = _engine(_home(tmp_path / "b", poisoned), as_of)

    assert clean_bars[-1].ts == CLEAN[k].ts and poisoned_bars == clean_bars
    assert after == clean


def test_the_user_cutoff_has_in_window_discriminating_power(tmp_path: Path) -> None:
    k = 150
    as_of = _as_of(k)
    _, clean = _engine(_home(tmp_path / "a", CLEAN), as_of)
    spiked = [*CLEAN[:k], _spike(CLEAN[k]), *CLEAN[k + 1 :]]
    _, after = _engine(_home(tmp_path / "b", spiked), as_of)

    assert after != clean
