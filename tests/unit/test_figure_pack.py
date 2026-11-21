"""The figure pack: readable on a full screen, honest about its data, one theme rule."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli.figures import build_figure_spec
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_core import DataError
from alpha_data.store import ParquetStore
from alpha_research.figures import HistogramMark, RuleMark
from tests.fixtures.cli_fixtures import seed_store


@pytest.fixture(scope="module")
def rule_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any], Path]:
    home = tmp_path_factory.mktemp("pack")
    seed_store(home, symbol="SPY", n=400)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="fixture", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(idea, home=home, quick=True)["results"][0]
    assert result["error"] is None, result["error"]
    rdir = Path(result["run_dir"])
    return rdir, json.loads((rdir / "manifest.json").read_bytes()), rdir.parent.parent


def test_return_distribution_mean_is_the_mean_of_the_stored_daily_returns(
    rule_run: tuple[Path, dict[str, Any], Path],
) -> None:
    rdir, manifest, data_dir = rule_run
    equity = pl.read_parquet(rdir / "equity_curve.parquet")["equity"].to_numpy()
    stored_mean = float(np.mean(equity[1:] / equity[:-1] - 1.0))
    spec = build_figure_spec(
        "return_distribution", run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
    )
    rule = next(m for m in spec.panels[0].marks if isinstance(m, RuleMark))
    assert rule.position == pytest.approx(stored_mean, abs=1e-12)


def test_return_distribution_mean_does_not_come_from_bin_centres(tmp_path: Path) -> None:
    """Bins start at the minimum, so a centre-weighted mean can flip sign; stored returns cannot."""
    rng = np.random.default_rng(3)
    returns = np.sort(np.append(rng.normal(0.0008, 0.004, 1500), [-0.12, 0.09]))
    counts, edges = np.histogram(returns, bins=20)
    rows: list[dict[str, Any]] = [
        {
            "kind": "histogram",
            "index": i,
            "left": float(edges[i]),
            "right": float(edges[i + 1]),
            "count": int(c),
            "probability": None,
            "theoretical": None,
            "sample": None,
        }
        for i, c in enumerate(counts)
    ] + [
        {
            "kind": "qq",
            "index": i,
            "left": None,
            "right": None,
            "count": None,
            "probability": (i + 0.5) / len(returns),
            "theoretical": float(i) / len(returns),
            "sample": float(v),
        }
        for i, v in enumerate(returns)
    ]
    schema = {
        "kind": pl.String,
        "index": pl.Int64,
        "left": pl.Float64,
        "right": pl.Float64,
        "count": pl.Int64,
        "probability": pl.Float64,
        "theoretical": pl.Float64,
        "sample": pl.Float64,
    }
    pl.DataFrame(rows, schema=schema).write_parquet(tmp_path / "return_distribution.parquet")
    spec = build_figure_spec(
        "return_distribution", run_id="fixture", rdir=tmp_path, manifest={}, data_dir=tmp_path
    )
    marks = spec.panels[0].marks
    rule = next(m for m in marks if isinstance(m, RuleMark))
    assert rule.position == pytest.approx(float(returns.mean()), abs=1e-12)
    hist = marks[0]
    assert isinstance(hist, HistogramMark)
    # range follows the data quantiles, not the two outliers; bins are finer than 20-over-range
    assert hist.edges[0] > -0.05 and hist.edges[-1] < 0.05
    assert len(hist.counts) >= 15


def test_every_rule_run_figure_keeps_its_text_inside_the_figure(
    rule_run: tuple[Path, dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.figures import available_figures
    from tests.unit._figure_probe import measure

    rdir, manifest, data_dir = rule_run
    problems: dict[str, list[str]] = {}
    tested: list[str] = []
    for entry in available_figures(rdir, manifest):
        if not entry.available:
            continue
        figure_id = entry.definition.figure_id
        try:
            spec = build_figure_spec(
                figure_id, run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
            )
        except DataError:
            continue
        tested.append(figure_id)
        for dark in (False, True):
            seen = measure(spec, monkeypatch, dark=dark)
            found = seen.outside() + seen.overlapping_ticks()
            if found:
                problems[f"{figure_id}/{'dark' if dark else 'light'}"] = found
    assert len(tested) >= 5, tested
    assert not problems, problems


def test_drawdown_window_numbers_never_sit_on_the_date_labels(
    rule_run: tuple[Path, dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._figure_probe import measure

    rdir, manifest, data_dir = rule_run
    spec = build_figure_spec(
        "drawdown_episodes", run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
    )
    seen = measure(spec, monkeypatch, dark=False)
    assert not seen.overlapping_texts(), seen.overlapping_texts()


def test_the_monthly_heatmap_scale_is_in_the_unit_its_label_and_cells_use(
    rule_run: tuple[Path, dict[str, Any], Path],
) -> None:
    """Cells print percent; the colour bar said percent but its ticks were ratios."""
    from alpha_research.figures import HeatmapMark

    rdir, manifest, data_dir = rule_run
    spec = build_figure_spec(
        "monthly_heatmap", run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
    )
    mark = next(m for m in spec.panels[0].marks if isinstance(m, HeatmapMark))
    assert mark.colorbar_label == "Return (%)"
    for row, texts in zip(mark.values, mark.cell_text, strict=True):
        for value, text in zip(row, texts, strict=True):
            if value is not None and text:
                assert text == f"{value:.1f}"


def test_the_drawdown_sentence_is_about_the_worst_episode_not_any_open_one(
    tmp_path: Path,
) -> None:
    """The worst drawdown recovered; a smaller, later one is still open."""
    stamps = [datetime(2021, 1, 4, tzinfo=UTC) + timedelta(days=i) for i in range(60)]
    equity = [*(1.0 - 0.01 * i for i in range(10)), *(0.91 + 0.02 * i for i in range(10))]
    equity += [1.1 - 0.005 * i for i in range(10)] + [1.1 - 0.05 + 0.001 * i for i in range(30)]
    rdir = _synthetic(tmp_path)
    pl.DataFrame({"ts": stamps, "equity": equity}).write_parquet(rdir / "equity_curve.parquet")
    answer = _build(rdir, "drawdown_episodes").plain_language_answer
    assert "recovering in" in answer and "had not recovered" not in answer, answer


# ------------------------------------------------------------------ synthetic run helpers
_RUN = "0f0f0f0f0f0f0f0f"


def _synthetic(tmp_path: Path, command: str = "validate", **metadata: object) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": _RUN,
                "command": command,
                "artifact_contract_version": 3,
                "metadata": {"symbol": "TEST", "strategy_name": "synthetic", **metadata},
            }
        )
    )
    return tmp_path


def _build(rdir: Path, figure_id: str) -> Any:
    manifest = json.loads((rdir / "manifest.json").read_text())
    return build_figure_spec(
        figure_id, run_id=_RUN, rdir=rdir, manifest=manifest, data_dir=rdir.parent
    )


def _contrast(foreground: str, background: str) -> float:
    def luminance(colour: str) -> float:
        channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _blend(foreground: str, background: str, alpha: float) -> str:
    mixed = [
        round(int(foreground[i : i + 2], 16) * alpha + int(background[i : i + 2], 16) * (1 - alpha))
        for i in (1, 3, 5)
    ]
    return "#" + "".join(f"{value:02x}" for value in mixed)


# ------------------------------------------------------------------ items 2, 3, 7
def test_a_thirty_year_heatmap_thins_its_labels_and_drops_cell_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._figure_probe import measure

    rng = np.random.default_rng(1)
    rows = [
        {"period_type": "month", "year": 1993 + y, "month": m, "return_value": float(v)}
        for y in range(30)
        for m, v in enumerate(rng.normal(0.01, 0.04, 12), start=1)
    ] + [
        {"period_type": "year", "year": 1993 + y, "month": None, "return_value": 0.1}
        for y in range(30)
    ]
    rdir = _synthetic(tmp_path)
    pl.DataFrame(rows).write_parquet(rdir / "calendar_returns.parquet")
    spec = _build(rdir, "monthly_heatmap")
    mark = spec.panels[0].marks[0]
    assert mark.cell_text == ()
    assert len(mark.rows) == 30
    assert sum(1 for label in mark.rows if label.strip()) <= 8
    seen = measure(spec, monkeypatch)
    assert seen.outside() == [] and seen.overlapping_ticks() == []


def test_a_short_history_keeps_every_year_and_its_numbers(tmp_path: Path) -> None:
    rows = [
        {"period_type": "month", "year": 2020 + y, "month": m, "return_value": 0.01}
        for y in range(5)
        for m in range(1, 13)
    ]
    rdir = _synthetic(tmp_path)
    pl.DataFrame(rows).write_parquet(rdir / "calendar_returns.parquet")
    mark = _build(rdir, "monthly_heatmap").panels[0].marks[0]
    assert mark.rows == ("2020", "2021", "2022", "2023", "2024")
    assert mark.cell_text and mark.cell_text[0][0] == "1.0"


def _ledger(rdir: Path, sharpes: list[float]) -> None:
    pl.DataFrame(
        {
            "trial": list(range(len(sharpes))),
            "status": ["passed"] * len(sharpes),
            "annualized_sharpe": sharpes,
            "config_json": [
                json.dumps(
                    [["lookback", 20.0 + 20 * (i % 3)], ["target_vol", 0.1 + 0.05 * (i // 3)]]
                )
                for i in range(len(sharpes))
            ],
        }
    ).write_parquet(rdir / "trial_ledger.parquet")


def test_the_parameter_surface_colour_follows_the_data_median(tmp_path: Path) -> None:
    rdir = _synthetic(tmp_path, "optim_grid")
    sharpes = [0.30, 0.31, 0.35, 0.28, 0.33, 0.36]
    _ledger(rdir, sharpes)
    mark = _build(rdir, "optim_surface").panels[0].marks[0]
    assert mark.diverging_center == pytest.approx(float(np.median(sharpes)))
    printed = {text for row in mark.cell_text for text in row}
    assert {"0.30", "0.36", "0.28"} <= printed


def test_trial_equity_lines_are_distinct_and_named(tmp_path: Path) -> None:
    rdir = _synthetic(tmp_path, "optim_grid", best_trial=2)
    frames = [
        pl.DataFrame(
            {"trial": [t] * 6, "step": list(range(6)), "oos_return": [0.001 * (t + 1)] * 6}
        )
        for t in range(6)
    ]
    pl.concat(frames).write_parquet(rdir / "trials.parquet")
    manifest = json.loads((rdir / "manifest.json").read_text())
    manifest["best_trial"] = 2
    (rdir / "manifest.json").write_text(json.dumps(manifest))
    spec = _build(rdir, "optim_trials")
    marks = spec.panels[0].marks
    named = [m for m in marks if m.palette_index is not None]
    assert len({m.palette_index for m in named}) == len(named) == 3
    labels = [m.label for m in marks if m.label]
    assert "Selected configuration" in labels and any(x.startswith("Other trials") for x in labels)
    assert len(set(labels)) == len(labels)


def test_the_drawdown_strip_prints_its_first_and_last_dates(tmp_path: Path) -> None:
    stamps = [datetime(2021, 1, 4, tzinfo=UTC) + timedelta(days=i) for i in range(120)]
    equity = [1.0 + 0.2 * np.sin(i / 9.0) + i * 0.001 for i in range(120)]
    rdir = _synthetic(tmp_path)
    pl.DataFrame({"ts": stamps, "equity": equity}).write_parquet(rdir / "equity_curve.parquet")
    spec = _build(rdir, "drawdown_episodes")
    labels = [
        m.annotate.text for m in spec.panels[0].marks if isinstance(m, RuleMark) and m.annotate
    ]
    assert labels == ["2021-01-04", "2021-05-03"]


# ------------------------------------------------------------------ item 6 (Monte Carlo)
def _paths(rdir: Path) -> None:
    rng = np.random.default_rng(5)
    frames = []
    for family in ("iid_empirical", "regime_switching"):
        for index in range(40):
            frames.append(
                pl.DataFrame(
                    {
                        "family": [family] * 20,
                        "path_index": [index] * 20,
                        "step": list(range(20)),
                        "account_return": rng.normal(0.002, 0.01, 20).tolist(),
                    }
                )
            )
    pl.concat(frames).write_parquet(rdir / "paths.parquet")
    pl.DataFrame(
        {"step": list(range(20)), "equity": [1.0 + 0.002 * i for i in range(20)]}
    ).write_parquet(rdir / "observed_oos.parquet")
    pl.DataFrame(
        {
            "family": ["iid_empirical"] * 50 + ["regime_switching"] * 50,
            "path_index": list(range(50)) * 2,
            "terminal_return": rng.normal(0.05, 0.2, 100).tolist(),
            "maximum_drawdown": rng.uniform(0.05, 0.6, 100).tolist(),
            "ruined": [False] * 90 + [True] * 10,
        }
    ).write_parquet(rdir / "path_metrics.parquet")


@pytest.fixture
def mc_run(tmp_path: Path) -> Path:
    rdir = _synthetic(tmp_path, "monte_carlo", paths=40)
    _paths(rdir)
    return rdir


def test_terminal_returns_use_one_unit_percent(mc_run: Path) -> None:
    spec = _build(mc_run, "monte_carlo_terminal_returns")
    assert "(%)" in spec.x_label
    panel = spec.panels[0]
    values = (
        pl.read_parquet(mc_run / "path_metrics.parquet")
        .filter(pl.col("family") == "iid_empirical")["terminal_return"]
        .to_numpy()
    )
    hist, _, median_rule = panel.marks
    assert hist.edges[0] == pytest.approx(values.min() * 100.0)
    assert median_rule.position == pytest.approx(float(np.median(values)) * 100.0)
    assert median_rule.annotate.text == f"median {np.median(values) * 100:.1f}%"


@pytest.mark.parametrize("dark", [False, True])
def test_the_fan_band_keeps_contrast_on_both_themes(mc_run: Path, dark: bool) -> None:
    from alpha_cli.figures.rdagent_journey_figures import figure_theme

    theme = figure_theme(dark)
    outer = next(
        m for m in _build(mc_run, "monte_carlo_equity_fans").panels[0].marks if m.label == "5-95%"
    )
    colour = theme.series_colour(outer.palette_index)
    assert _contrast(_blend(colour, theme.panel, outer.alpha), theme.panel) >= 1.5


def test_ruin_and_median_labels_stay_inside_the_figure(
    mc_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._figure_probe import measure

    for figure_id in ("monte_carlo_drawdown_ruin", "monte_carlo_terminal_returns"):
        for dark in (False, True):
            assert measure(_build(mc_run, figure_id), monkeypatch, dark=dark).outside() == []


def test_regime_matrix_is_sequential_and_both_states_have_a_visible_outline(tmp_path: Path) -> None:
    rng = np.random.default_rng(2)
    rdir = _synthetic(tmp_path, "monte_carlo")
    state = rng.integers(0, 2, 200)
    pl.DataFrame(
        {
            "step": list(range(200)),
            "state": state.tolist(),
            "account_return": rng.normal(0, 0.01, 200).tolist(),
        }
    ).write_parquet(rdir / "regime_emissions.parquet")
    pl.DataFrame(
        {
            "from_state": [0, 0, 1, 1],
            "to_state": [0, 1, 0, 1],
            "transition_probability": [0.8, 0.2, 0.4, 0.6],
        }
    ).write_parquet(rdir / "regime_diagnostics.parquet")
    spec = _build(rdir, "monte_carlo_regimes")
    heat = spec.panels[1].marks[0]
    assert heat.diverging_center is None
    outlines = [m for m in spec.panels[0].marks if getattr(m, "step", False)]
    assert [m.label for m in outlines] == ["Calm", "Volatile"]
    fills = [m for m in spec.panels[0].marks if m.label is None]
    assert all(m.alpha <= 0.3 for m in fills)


# ------------------------------------------------------------------ item 5 and 11
def test_the_subtitle_names_the_dates_actually_plotted(tmp_path: Path) -> None:
    stamps = [datetime(1995, 3, 1, tzinfo=UTC) + timedelta(days=i) for i in range(4)]
    rdir = _synthetic(tmp_path, start="1993-01-04T00:00:00+00:00", end="1995-03-04T00:00:00+00:00")
    pl.DataFrame(
        {
            "ts": stamps,
            "strategy_equity": [1.0, 1.5, 1.25, 1.3],
            "benchmark_equity": [1.0, 1.1, 1.0, 1.05],
            "available": [True] * 4,
        }
    ).write_parquet(rdir / "benchmark_comparison.parquet")
    spec = _build(rdir, "equity_vs_passive")
    assert "plotted 1995-03-01 to 1995-03-04" in spec.subtitle
    assert "run data 1993-01-04 to 1995-03-04" in spec.subtitle
    assert spec.panels[1].y_label == "Ahead (%)"


def test_the_buy_and_hold_caption_says_why_the_basis_differs(
    rule_run: tuple[Path, dict[str, Any], Path], tmp_path: Path
) -> None:
    rdir, manifest, data_dir = rule_run
    rule = build_figure_spec(
        "equity_vs_passive", run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
    )
    assert "Rule tests add dividends when the store holds them" in rule.caveat
    stamps = [datetime(2020, 1, 1 + i, tzinfo=UTC) for i in range(3)]
    other = _synthetic(tmp_path)
    pl.DataFrame(
        {
            "ts": stamps,
            "strategy_equity": [1.0, 1.2, 1.1],
            "benchmark_equity": [1.0, 1.1, 1.05],
            "available": [True] * 3,
            "benchmark_kind": ["passive_open_to_open_price_only"] * 3,
        }
    ).write_parquet(other / "benchmark_comparison.parquet")
    engine = _build(other, "equity_vs_passive")
    assert "never adds dividends" in engine.caveat
    assert "price only" in engine.panels[0].marks[0].label


# ------------------------------------------------------------------ item 8
def test_price_is_cut_to_the_run_and_many_fills_become_shading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.figures import _sources

    first = datetime(2022, 1, 3, tzinfo=UTC)
    days = [first + timedelta(days=i) for i in range(200)]
    rows = [
        {
            "t": d.timestamp(),
            "o": 100.0 + i,
            "h": 101.0 + i,
            "l": 99.0 + i,
            "c": 100.5 + i,
            "v": 1.0,
        }
        for i, d in enumerate(days)
    ]
    monkeypatch.setattr(_sources, "bars", lambda *a, **k: (rows, None))
    rdir = _synthetic(tmp_path, snapshot_id="snap")
    run_days = days[:100]
    pl.DataFrame({"ts": run_days, "equity": [1.0 + i * 0.001 for i in range(100)]}).write_parquet(
        rdir / "equity_curve.parquet"
    )
    fills = [
        {
            "sequence_id": i,
            "event_type": "fill",
            "ts": days[i],
            "side": "BUY" if i % 2 == 0 else "SELL",
            "price": 100.0 + i,
        }
        for i in range(80)
    ]
    pl.DataFrame(fills).write_parquet(rdir / "execution_trace.parquet")
    pl.DataFrame(
        {
            "entry_ts": [days[i] for i in range(0, 80, 2)],
            "exit_ts": [days[i] for i in range(1, 80, 2)],
            "side": ["BUY"] * 40,
        }
    ).write_parquet(rdir / "trades.parquet")
    spec = _build(rdir, "price_signal")
    price = spec.panels[0]
    xs = [x for m in price.marks if hasattr(m, "x") and isinstance(m.x, tuple) for x in m.x]
    assert max(xs) <= run_days[-1].timestamp()
    kinds = {type(m).__name__ for m in price.marks}
    assert "ScatterMark" not in kinds and "ZoneMark" in kinds
    assert price.note is None
    assert "no chart annotations" in spec.caption and "shaded held periods" in spec.caption


# ------------------------------------------------------------------ item 10
def test_holding_period_uses_one_colour_family_and_leaves_head_room(
    rule_run: tuple[Path, dict[str, Any], Path],
) -> None:
    rdir, manifest, data_dir = rule_run
    spec = build_figure_spec(
        "holding_period", run_id=rdir.name, rdir=rdir, manifest=manifest, data_dir=data_dir
    )
    panel = spec.panels[0]
    bars = [m for m in panel.marks if hasattr(m, "counts")]
    assert {m.palette_index for m in bars} == {0}
    assert panel.y_limits is not None and panel.y_limits[1] >= 1.3 * max(
        max(m.counts) for m in bars
    )


def _capture_figures(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from matplotlib.figure import Figure

    seen: list[Any] = []
    original = Figure.savefig

    def keep(self: Any, *args: Any, **kwargs: Any) -> Any:
        self.canvas.draw()
        seen.append(self)
        self.clear = lambda *a, **k: None  # keep the artists for the assertions
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", keep)
    return seen


def test_event_study_zoomed_ticks_do_not_all_round_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.spine.event_study_figure import draw_event_study

    seen = _capture_figures(monkeypatch)
    draw_event_study(
        paths=[[0.0, 0.002, 0.004], [0.0, -0.002, None]],
        mean=[0.0, 0.0006, 0.0012],
        drift=[0.0, 0.0002, 0.0004],
        lower=[0.0, -0.0015, -0.003],
        upper=[0.0, 0.0015, 0.003],
        horizons=[1, 2],
        primary=2,
        title="Synthetic",
    )
    bottom = seen[0].axes[1]
    labels = [t.get_text() for t in bottom.get_yticklabels() if t.get_text()]
    assert len(set(labels)) == len(labels) and labels != ["0%"] * len(labels)


def test_setup_trades_keep_bars_clear_of_the_legend_and_the_dot_above_the_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alpha_cli.spine.setup_trade_figure import draw_trades

    rows = [
        {
            "entry_ts": i,
            "asset": "X",
            "candidate_id": i,
            "net_return": v,
            "reason": r,
            "complete": True,
        }
        for i, (v, r) in enumerate(
            [(-0.05, "stop"), (0.12, "target"), (0.12, "target"), (0.02, "time")]
        )
    ]
    primary = {
        "mean": 0.0125,
        "drift_mean": 0.001,
        "random_date_5": -0.02,
        "random_date_95": 0.03,
        "trades": 4,
        "hit_rate": 0.5,
    }
    seen = _capture_figures(monkeypatch)
    draw_trades(rows=rows, primary=primary, title="Synthetic")
    top, controls = seen[0].axes[0], seen[0].axes[1]
    legend_top = top.get_legend().get_window_extent().y0
    tallest = top.transData.transform((0, 0.12))[1]
    assert legend_top > tallest
    dot = next(line for line in controls.lines if line.get_marker() == "o")
    assert dot.get_zorder() > max(p.get_zorder() for p in controls.patches)


# ------------------------------------------------------------------ item 12
def test_every_price_mark_shares_the_plotted_window_and_the_first_candle_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.figures import _sources

    first = datetime(2022, 1, 3, tzinfo=UTC)
    days = [first + timedelta(days=i) for i in range(60)]
    rows = [{"t": d.timestamp(), "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 1.0} for d in days]
    monkeypatch.setattr(_sources, "bars", lambda *a, **k: (rows, None))
    rdir = _synthetic(tmp_path, snapshot_id="snap")
    # The equity recorder stamps each session one microsecond after its candle.
    run = [d + timedelta(microseconds=1) for d in days[10:40]]
    pl.DataFrame({"ts": run, "equity": [1.0 + i * 0.01 for i in range(30)]}).write_parquet(
        rdir / "equity_curve.parquet"
    )
    pl.DataFrame(
        {
            "annotation_id": ["a"] * 60,
            "anchor_index": list(range(60)),
            "label": ["ma"] * 60,
            "kind": ["line"] * 60,
            "unit": ["price"] * 60,
            "ts": days,
            "value": [1.2] * 60,
        }
    ).write_parquet(rdir / "chart_annotations.parquet")
    pl.DataFrame(
        {
            "entry_ts": [days[2], days[35]],
            "exit_ts": [days[20], days[55]],
            "side": ["BUY", "BUY"],
        }
    ).write_parquet(rdir / "trades.parquet")
    fills = [
        {"sequence_id": i, "event_type": "fill", "ts": days[i], "side": "BUY", "price": 1.0}
        for i in range(60)
    ]
    pl.DataFrame(fills).write_parquet(rdir / "execution_trace.parquet")
    spec = _build(rdir, "price_signal")
    low, high = days[10].timestamp(), days[39].timestamp()
    price = spec.panels[0]
    candle = price.marks[0]
    assert candle.x[0] == days[10].timestamp()  # the run's first candle is kept
    for mark in price.marks:
        if hasattr(mark, "x") and isinstance(mark.x, tuple):
            if mark.label == "ma":  # an annotation keeps its whole line; x-limits crop it
                assert min(mark.x) <= high and max(mark.x) >= low
            else:
                assert min(mark.x) >= low - 1.0 and max(mark.x) <= high + 1.0
        if hasattr(mark, "x0"):
            assert mark.x0 >= low - 1.0 and mark.x1 <= high + 1.0
    assert spec.x_limits is not None
    assert spec.x_limits[0] < low < high < spec.x_limits[1]


def _many_fill_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, equity_from: int) -> Path:
    from alpha_cli.figures import _sources

    first = datetime(2022, 1, 3, tzinfo=UTC)
    days = [first + timedelta(days=i) for i in range(80)]
    rows = [{"t": d.timestamp(), "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 1.0} for d in days]
    monkeypatch.setattr(_sources, "bars", lambda *a, **k: (rows, None))
    rdir = _synthetic(tmp_path, snapshot_id="snap")
    pl.DataFrame(
        {"ts": days[equity_from:], "equity": [1.0 + i * 0.01 for i in range(80 - equity_from)]}
    ).write_parquet(rdir / "equity_curve.parquet")
    # 30 round trips (60 fills) then one open entry: 61 fills, the last never closed.
    fills = [
        {
            "sequence_id": i,
            "event_type": "fill",
            "ts": days[i],
            "side": "BUY" if i % 2 == 0 or i == 60 else "SELL",
            "price": 1.0,
            "quantity": 10.0,
            "filled_quantity": 10.0,
        }
        for i in range(61)
    ]
    pl.DataFrame(fills).write_parquet(rdir / "execution_trace.parquet")
    pl.DataFrame(
        {
            "entry_ts": [days[i] for i in range(0, 60, 2)],
            "exit_ts": [days[i] for i in range(1, 60, 2)],
            "side": ["BUY"] * 30,
        }
    ).write_parquet(rdir / "trades.parquet")
    return rdir


def test_many_fills_keep_the_position_that_is_still_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rdir = _many_fill_run(tmp_path, monkeypatch, equity_from=0)
    marks = _build(rdir, "price_signal").panels[0].marks
    open_zone = next(m for m in marks if getattr(m, "label", None) == "Open position")
    assert open_zone.x1 > open_zone.x0


def test_the_annotation_cap_counts_only_annotations_in_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rdir = _many_fill_run(tmp_path, monkeypatch, equity_from=50)
    days = [datetime(2022, 1, 3, tzinfo=UTC) + timedelta(days=i) for i in range(80)]
    ids = [f"a{i}" for i in range(48)]
    early = [days[i] for i in range(45)] + [days[60]] * 3
    pl.DataFrame(
        {
            "annotation_id": ids * 2,
            "anchor_index": [0] * 48 + [1] * 48,
            "label": ["x"] * 96,
            "kind": ["line"] * 96,
            "unit": ["price"] * 96,
            "ts": early + [d + timedelta(days=1) for d in early],
            "value": [1.2] * 96,
        }
    ).write_parquet(rdir / "chart_annotations.parquet")
    marks = _build(rdir, "price_signal").panels[0].marks
    assert sum(1 for m in marks if type(m).__name__ == "LineMark" and m.role == "feature") == 3


def test_a_position_opened_before_the_window_is_not_mistaken_for_a_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rdir = _many_fill_run(tmp_path, monkeypatch, equity_from=1)
    days = [datetime(2022, 1, 3, tzinfo=UTC) + timedelta(days=i) for i in range(80)]
    # Fill 0 (the entry) sits before the window; 61 visible fills then end flat.
    fills = [
        {
            "sequence_id": i,
            "event_type": "fill",
            "ts": days[i],
            "side": "BUY" if i % 2 == 0 else "SELL",
            "price": 1.0,
            "quantity": 10.0,
            "filled_quantity": 10.0,
        }
        for i in range(62)
    ]
    pl.DataFrame(fills).write_parquet(rdir / "execution_trace.parquet")
    marks = _build(rdir, "price_signal").panels[0].marks
    assert not any(getattr(m, "label", None) == "Open position" for m in marks)


def test_a_reversal_starts_a_new_open_position_at_the_reversing_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rdir = _many_fill_run(tmp_path, monkeypatch, equity_from=0)
    days = [datetime(2022, 1, 3, tzinfo=UTC) + timedelta(days=i) for i in range(80)]
    rows = []
    for i in range(60):  # 30 round trips
        rows.append((i, "BUY" if i % 2 == 0 else "SELL", 10.0))
    rows += [(60, "BUY", 10.0), (70, "SELL", 20.0)]  # long, then a one-fill reversal to short
    pl.DataFrame(
        [
            {
                "sequence_id": n,
                "event_type": "fill",
                "ts": days[d],
                "side": side,
                "price": 1.0,
                "quantity": q,
                "filled_quantity": q,
            }
            for n, (d, side, q) in enumerate(rows)
        ]
    ).write_parquet(rdir / "execution_trace.parquet")
    marks = _build(rdir, "price_signal").panels[0].marks
    zone = next(m for m in marks if getattr(m, "label", None) == "Open position")
    assert zone.role == "down"
    assert zone.x0 == days[70].timestamp()
