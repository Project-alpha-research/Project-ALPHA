"""A model run (`alpha ml run`) in the figures and the toolbox: draw, read or refuse."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import ml_cmds, ml_run
from alpha_cli.main import app
from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox import registry, runner
from tests.integration.test_ml_run import _fake_worker, _seed_store, _spec

REPO = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def ml_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, str]]:
    patch = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("ml-tools")
    patch.setattr(ml_cmds, "train_exchange", _fake_worker)
    patch.setattr(ml_run, "_require_worker", lambda project: REPO / "workers/qlib")
    data = root / "alpha-data"
    _seed_store(data)
    patch.setenv("ALPHA_DATA_DIR", str(data))
    result = ml_run.run_spec(_spec(root), data_dir=data)
    yield data, result["run_id"]
    patch.undo()


def _alpha(*args: str) -> Any:
    return CliRunner().invoke(app, list(args))


def _figure_rows(run_id: str) -> list[dict[str, Any]]:
    out = _alpha("figures", "list", "--run", run_id, "--json")
    assert out.exit_code == 0, out.output
    items: list[dict[str, Any]] = json.loads(out.output)["items"]
    return items


def test_every_listed_figure_of_a_model_run_draws(
    ml_home: tuple[Path, str], tmp_path: Path
) -> None:
    _, run_id = ml_home
    rows = _figure_rows(run_id)
    available = {row["figure_id"] for row in rows if row["available"]}
    assert {"equity_vs_passive", "fold_sharpe"} <= available
    for figure in sorted(available):
        out = _alpha(
            "figures", "export", run_id, "--figure", figure, "--format", "svg",
            "--out", str(tmp_path / f"{figure}.svg"),
        )  # fmt: skip
        assert out.exit_code == 0, f"{figure}: {out.output}"
        assert out.exception is None, figure
        assert (tmp_path / f"{figure}.svg").stat().st_size > 0


def test_a_figure_that_cannot_draw_says_why_in_plain_words(
    ml_home: tuple[Path, str], tmp_path: Path
) -> None:
    _, run_id = ml_home
    rows = [row for row in _figure_rows(run_id) if not row["available"]]
    assert rows
    for row in rows:
        reason = row["unavailable_reason"]
        assert " " in reason, row  # a sentence, not a stored token such as artifact_missing:x
        out = _alpha(
            "figures", "export", run_id, "--figure", row["figure_id"],
            "--out", str(tmp_path / "x.png"),
        )  # fmt: skip
        assert out.exit_code == 1
        assert out.exception is None or isinstance(out.exception, SystemExit)
        assert "Traceback" not in out.output
        assert reason in out.output


def test_the_passive_line_is_the_equal_weight_basket(ml_home: tuple[Path, str]) -> None:
    import polars as pl

    home, run_id = ml_home
    frame = pl.read_parquet(home / "runs" / run_id / "benchmark_comparison.parquet")
    periods = pl.read_parquet(home / "runs" / run_id / "ml_periods.parquet").sort("target_ts")
    assert all(frame["available"])
    assert set(frame["benchmark_kind"]) == {"equal_weight_basket_open_to_open_price_only"}
    expected = (1.0 + periods["benchmark_return"]).cum_prod().to_list()
    levels = (frame["benchmark_equity"] / frame["benchmark_equity"][0]).to_list()
    assert levels[1:] == pytest.approx(expected, rel=1e-9, abs=1e-12)


def test_costs_are_stored_per_period_and_reconcile(ml_home: tuple[Path, str]) -> None:
    import polars as pl

    home, run_id = ml_home
    frame = pl.read_parquet(home / "runs" / run_id / "equity_curve.parquet")
    net = (frame["equity"] / frame["equity"].shift(1) - 1.0).to_list()[1:]
    gross = frame["gross_return"].to_list()[1:]
    cost = frame["cost_return"].to_list()[1:]
    assert all(c >= 0 for c in cost) and any(c > 0 for c in cost)
    assert [g - c for g, c in zip(gross, cost, strict=True)] == pytest.approx(
        net, rel=1e-9, abs=1e-12
    )


@pytest.mark.parametrize("spec", registry.SPECS, ids=lambda spec: spec.id)
def test_every_check_reads_or_refuses_a_model_run(ml_home: tuple[Path, str], spec: Any) -> None:
    home, run_id = ml_home
    try:
        result = runner.run(home, spec.id, run_id)
    except SpineError as refusal:
        message = refusal.payload["message"]
        assert message.count(". ") == 0, message  # one sentence
        assert "rule test" not in f"{message} {refusal.payload['next']}".lower(), message
        return
    assert "rule test" not in json.dumps(result, default=str).lower(), spec.id


def test_break_even_and_bull_bear_give_a_reading_on_a_new_model_run(
    ml_home: tuple[Path, str],
) -> None:
    home, run_id = ml_home
    costs = runner.run(home, "costs.break_even", run_id)
    assert "before costs were stored" not in json.dumps(costs, default=str)
    assert costs["values"]["cost_share"] is not None
    bull_bear = runner.run(home, "regimes.bull_bear", run_id)
    assert "requires a stored buy-and-hold" not in json.dumps(bull_bear, default=str)


def test_an_old_model_run_says_it_was_made_before_and_to_run_it_again(
    ml_home: tuple[Path, str], tmp_path: Path
) -> None:
    import shutil

    import polars as pl

    from alpha_cli.figures import available_figures

    home, run_id = ml_home
    old = tmp_path / run_id
    shutil.copytree(home / "runs" / run_id, old)
    frame = pl.read_parquet(old / "benchmark_comparison.parquet")
    frame.with_columns(pl.lit(False).alias("available")).write_parquet(
        old / "benchmark_comparison.parquet"
    )
    (old / "ml_periods.parquet").unlink()
    manifest = json.loads((old / "manifest.json").read_text())
    reasons = {
        entry.definition.figure_id: entry.unavailable_reason
        for entry in available_figures(old, manifest)
    }
    for figure in ("equity_vs_passive", "fold_sharpe"):
        assert "made before" in str(reasons[figure])
        assert "alpha ml run" in str(reasons[figure])


def test_chart_titles_of_a_model_run_are_short_and_plain(
    ml_home: tuple[Path, str], tmp_path: Path
) -> None:
    from alpha_cli.figures import available_figures, build_figure_spec, resolve_run

    home, run_id = ml_home
    rdir, manifest = resolve_run(run_id, data_dir=home)
    for entry in available_figures(rdir, manifest):
        if not entry.available:
            continue
        spec = build_figure_spec(
            entry.definition.figure_id, run_id=run_id, rdir=rdir, manifest=manifest, data_dir=home
        )
        text = f"{spec.title} {spec.subtitle} {spec.caption}"
        assert "counterfactual" not in text and "OOS replay validated" not in text, text
        assert "20 assets" in spec.subtitle


def test_the_model_run_reads_in_plain_words(ml_home: tuple[Path, str]) -> None:
    home, run_id = ml_home
    shown = _alpha("results", "show", run_id).output
    assert "Reading: " in shown
    assert "The model returned less than holding the basket." in shown
    assert "Flags raised: none" not in shown
    report = _alpha("report", run_id).output
    for raw in ("costed_excess_total_return=", "dsr=", "psr=", "total_fees="):
        assert raw not in report
    assert "Reading: " in report and "(the chance" in report
    assert "bars for each of 20 assets" in report
    assert "Held back 2160 bars" not in report


def test_ml_run_prints_the_expected_time_and_fold_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import time

    from alpha_cli import ml_progress

    def slow_worker(exchange: Path, **kwargs: object) -> object:
        time.sleep(0.5)
        return _fake_worker(exchange, **kwargs)

    monkeypatch.setattr(ml_cmds, "train_exchange", slow_worker)
    monkeypatch.setattr(ml_run, "_require_worker", lambda project: REPO / "workers/qlib")
    monkeypatch.setattr(ml_progress, "PROGRESS_EVERY", 0.1)
    data = tmp_path / "alpha-data"
    _seed_store(data)
    ml_run.run_spec(_spec(tmp_path), data_dir=data)
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("The model trains ") and "Expected time: about " in lines[0]
    beats = [line for line in lines if line.startswith("Model training:")]
    assert beats and all(" of " in line and "about fold " in line for line in beats)
    assert (data / "ml_timing.json").is_file()
