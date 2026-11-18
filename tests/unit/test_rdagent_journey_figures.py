"""Check plotted numbers against tiny declared-clock series and the reserved boundary."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from PIL import Image
from typer.testing import CliRunner

from alpha_cli.main import app
from tests.unit.test_rdagent_journey import make_run


def test_plotted_numbers_and_reserved_boundary(tmp_path: Path) -> None:
    run, rows = make_run(tmp_path)
    row = rows[1]
    digest = row["code_sha256"]
    folder = run / "evaluations/iter-1"
    series = folder / "series"
    series.mkdir()
    dates = [date(2022, 12, 25), date(2023, 1, 1), date(2023, 1, 8), date(2024, 1, 1)]
    pl.DataFrame(
        {
            "clock": ["weekly"] * 4 + ["daily"],
            "date": dates + dates[:1],
            "rank_ic": [-0.25, 0.125, -0.25, 99.0, 88.0],
        }
    ).write_parquet(series / f"{digest}.screen.parquet")
    pl.DataFrame(
        {"bucket": [1, 2, 3], "mean_outcome": [-0.04, -0.01, 0.02], "clock": ["weekly"] * 3}
    ).write_parquet(series / f"{digest}.buckets.parquet")
    pl.DataFrame(
        [
            {
                "date": d,
                "bucket": b,
                "mean_outcome": 99.0 if d.year == 2024 else b / 100,
                "clock": "weekly",
            }
            for d in dates
            for b in (1, 2, 3)
        ]
    ).write_parquet(series / f"{digest}.buckets_daily.parquet")
    panel = run / "panel"
    panel.mkdir()
    data = pl.DataFrame(
        [
            {"date": d, "instrument": s, "score": j + 1.0, "close": 50 + j}
            for j, d in enumerate(dates)
            for s in ("TEST-A", "TEST-B")
        ]
    )
    data.select("date", "instrument", "score").write_parquet(folder / "factors.parquet")
    data.select("date", "instrument", "close").write_parquet(panel / "panel.parquet")
    ledger = run.parent / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    ledger.parent.mkdir()
    other = {**row, "trial_index": 3, "panel_sha256": "other"}
    ledger.write_text("".join(json.dumps(r) + "\n" for r in [*rows, other]))
    pl.DataFrame(
        {
            "clock": ["weekly"],
            "target_ts": dates[:1],
            "exit_ts": dates[1:2],
            "excess_return": [0.03],
            "turnover": [0.4],
        }
    ).write_parquet(series / f"{digest}.replay.parquet")
    output = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "ledger",
            "journey",
            "--run-dir",
            str(run),
            "--out",
            str(output),
            "--factor",
            "score",
            "--theme",
            "dark",
        ],
    )
    assert result.exit_code == 0, result.output or repr(result.exception)
    assert not (run / "journey").exists()
    dest = output / "journey" / f"1-score-{digest[:8]}"
    story = json.loads((dest / "journey.json").read_text())
    for name in ("signal", "quick-test", "over-time", "how-many-ideas"):
        assert story["figures"][name]["file"] == name + ".png"
        with Image.open(dest / (name + ".png")) as img:
            assert round(img.info["dpi"][0]) == 200
        raw = (dest / (name + ".json")).read_text()
        assert "2024" not in raw and "99.0" not in raw
    timeline = json.loads((dest / "over-time.json").read_text())
    assert timeline["cumulative"] == [0.25, 0.125, 0.375]
    assert timeline["year_means"] == {"2022": 0.25, "2023": 0.0625}
    quick = json.loads((dest / "quick-test.json").read_text())
    assert quick["overall"] == [-0.04, -0.01, 0.02]
    assert quick["by_year"]["2023"] == [0.01, 0.02, 0.03]
    looks = json.loads((dest / "how-many-ideas.json").read_text())
    assert looks["p"] == [0.43, 0.00031] and looks["pass_line"] == 0.00617
    assert story["figures"]["trading-test"]["file"] is None
    assert story["figures"]["trading-test"]["reason"]
    (series / f"{digest}.screen.parquet").unlink()
    rerun = CliRunner().invoke(
        app, ["ledger", "journey", "--run-dir", str(run), "--out", str(output)]
    )
    assert rerun.exit_code == 0, repr(rerun.exception)
    assert not (dest / "over-time.png").exists() and not (dest / "over-time.json").exists()


def test_trading_figure_uses_stored_rows_and_never_the_reserved_period(tmp_path: Path) -> None:
    from alpha_cli.figures.rdagent_journey_figures import draw, trading_data

    days = [date(2023, 12, 29), date(2023, 12, 30), date(2024, 1, 1)]
    path = tmp_path / "replay.parquet"
    pl.DataFrame(
        {
            "clock": ["daily", "daily", "daily"],
            "target_ts": [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in days],
            "gross_return": [0.1, 0.0, 9.0],
            "net_return": [0.05, 0.0, 9.0],
            "benchmark_return": [0.0, 0.1, 9.0],
            "turnover": [0.5, 0.5, 0.5],
        }
    ).write_parquet(path)
    data = trading_data(path, "daily", {"annual_cost": 0.08, "mean_turnover": 0.2})
    assert data is not None
    assert data["date"] == ["2023-12-29", "2023-12-30"]
    assert [round(v, 6) for v in data["after"]] == [105.0, 105.0]
    assert [round(v, 6) for v in data["basket"]] == [100.0, 110.0]
    assert trading_data(path, "weekly", {}) is None
    assert draw("trading-test", data, False)[:4] == b"\x89PNG"
