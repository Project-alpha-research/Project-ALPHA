"""Regression contracts for sparse evidence and descriptive tool honesty."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine import controls
from alpha_cli.spine.facts import build_facts
from alpha_cli.toolbox.families import market as tools


def test_wfe_most_folds_never_traded_and_zero_has_count() -> None:
    rows = [dict(is_cagr=0.1, oos_cagr=0.0, oos_had_trade=False) for _ in range(3)]
    rows[-1].update(oos_had_trade=True)
    result = controls.walk_forward_efficiency(rows)
    assert result["wfe"] is None
    assert result["reasons"]["wfe"] == "most folds never traded out of sample (2 of 3)"
    rows[1].update(oos_had_trade=True)
    result = controls.walk_forward_efficiency(rows)
    assert result["wfe"] == 0.0
    assert "1 of 3 folds never traded out of sample" in result["sentence"]
    assert [r["oos_had_trade"] for r in result["folds"]] == [False, True, True]


@pytest.mark.parametrize(
    "grade,expected", [("A", "C"), ("B", "C"), ("C", "C"), ("D", "D"), ("F", "F")]
)
def test_four_trades_cap_grade_without_improving_it(grade: str, expected: str) -> None:
    from alpha_cli.spine.audit import capped_verdict
    from alpha_validation.verdict import VerdictSummary

    verdict = VerdictSummary("A", "A", "A", "A", grade, {"overall_gpa": 4.0})
    assert capped_verdict(verdict, 4).overall == expected
    assert capped_verdict(verdict, 30) == verdict
    assert capped_verdict(verdict, 4).detail["overall_gpa"] <= 2.0


def test_few_trade_facts_keep_numbers_and_label(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "spine": {"labels": ["too-few-trades"]},
                "verdict": {"overall": "C"},
                "dsr": {"dsr": 0.84, "psr": 0.9},
            }
        )
    )
    facts = {f["metric"]: f for f in build_facts(tmp_path)}
    for metric in ("dsr", "trial_dsr", "psr", "verdict"):
        assert "too-few-trades" in facts[metric]["labels"]
    assert facts["dsr"]["value"] == 0.84
    assert facts["psr"]["value"] == 0.9


@pytest.mark.parametrize(
    "sharpe,hit,mean,daily,expected",
    [
        (3.01, 0.5, 0.01, True, True),
        (1, 0.81, 0.01, True, True),
        (1, 0.5, 0.051, True, True),
        (3, 0.8, 0.05, True, False),
        (1, 0.5, 0.051, False, False),
    ],
)
def test_plausibility_triggers(
    sharpe: float, hit: float, mean: float, daily: bool, expected: bool
) -> None:
    from alpha_cli.spine.audit import plausibility

    assert bool(plausibility(sharpe, hit, mean, 30, daily=daily)) is expected
    assert not plausibility(sharpe, hit, mean, 29, daily=daily)


def test_position_change_proximity_and_behaviour_counts() -> None:
    dates = tuple(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(50))
    states = tuple(i >= 10 for i in range(50))
    result = tools.describe_changes([5, 15, 16, 35], dates, states, shift=0)
    assert [r["position_change"] for r in result["breaks"]] == [True, True, False, False]
    assert result["behaviour_shifts"] == result["position_changes"] == 2
    assert (
        "2 shifts while in the market; 2 are just the rule stepping in or out" in result["sentence"]
    )
    only = tools.describe_changes([9, 10], dates, states, shift=1)
    assert only["sentence"].startswith(
        "No shift in behaviour found beyond entering and leaving the market"
    )


def test_causal_regime_reading_leads_and_labels_disagreement() -> None:
    causal = [
        {"regime": 0, "name": "calm", "share_of_log_return": 1.2},
        {"regime": 1, "name": "turbulent", "share_of_log_return": -0.2},
    ]
    hindsight = [
        {"regime": 0, "name": "calm", "share_of_log_return": -0.2},
        {"regime": 1, "name": "turbulent", "share_of_log_return": 1.2},
    ]
    reading = tools.regime_reading(causal, hindsight)
    assert reading["labels"] == ["hindsight-disagrees"]
    assert reading["sentence"].startswith("Causal split:")
    assert "with hindsight (not knowable at the time)" in reading["sentence"]
    assert (
        "Hindsight would tell a different story here; use the causal split." in reading["sentence"]
    )
    assert tools.regime_reading(causal, causal)["labels"] == []


def test_idea_identity_ignores_code_but_not_spec_or_data() -> None:
    from alpha_cli._identity import RunIdentity
    from alpha_cli.spine.run import idea_id

    first = RunIdentity("a" * 16, "code-one", None, "data-one", None)
    second = replace(first, run_id="b" * 16, execution_fingerprint="code-two")
    assert idea_id("spec-one", first.source_fingerprint) == idea_id(
        "spec-one", second.source_fingerprint
    )
    assert idea_id("spec-one", first.source_fingerprint) != idea_id(
        "spec-two", first.source_fingerprint
    )
    assert idea_id("spec-one", first.source_fingerprint) != idea_id("spec-one", "data-two")


@pytest.mark.parametrize(
    "ratio,expected",
    [(0.76, "fell 24% less than"), (1.1, "fell 10% more than"), (1.0, "fell about as much as")],
)
def test_plain_ratio(ratio: float, expected: str) -> None:
    from alpha_cli.spine.plain_ratio import fall_comparison

    assert fall_comparison(ratio) == expected


def test_old_documents_load_with_explained_missing_noise(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "diagnostics.json").write_text("{}")
    facts: dict[str, Any] = {f["metric"]: f for f in build_facts(tmp_path)}
    assert facts["price_noise_median_sharpe"]["value"] is None
    assert facts["price_noise_median_sharpe"]["reason"]


def test_plausibility_flag_does_not_change_verdict() -> None:
    from alpha_cli.spine.diagnostics import flags

    sections: dict[str, Any] = {
        "full_sample": {"sharpe": 4.0},
        "benchmark": {"sharpe": 3.0},
        "drawdowns": {"episodes": []},
        "concentration": {"top_3": None},
        "sensitivity": {"variants": []},
        "delay": {"base_sharpe": 4.0, "delayed_sharpe": 4.0},
        "verdict": "D",
        "plausibility": [{"flag": "implausibly-good", "detail": "check data"}],
    }
    before = json.dumps(sections, sort_keys=True)
    assert flags(sections) == sections["plausibility"]
    assert json.dumps(sections, sort_keys=True) == before


def test_published_sparse_headlines_and_idea_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from alpha_cli.main import app
    from alpha_cli.spine.facts import read_json
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, n=400)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    output = run_idea(idea, home=tmp_path, quick=True)
    result = output["results"][0]
    assert result["error"] is None, result
    manifest = read_json(Path(result["run_dir"]) / "manifest.json")
    diagnostic = read_json(Path(result["run_dir"]) / "diagnostics.json")
    assert diagnostic["closed_oos_trades"] < 30
    assert manifest["verdict"]["overall"] in {"C", "D", "F"}
    assert "too-few-trades" in manifest["verdict"]["labels"]
    assert "too-few-trades" in manifest["dsr"]["labels"]
    assert diagnostic["sentence"].startswith(
        f"Only {diagnostic['closed_oos_trades']} closed trades: too few to judge."
    )
    assert manifest["idea_id"] == result["idea_id"]
    # The ledger row records the same capped verdict the screen shows, with the caveat.
    from alpha_cli.spine.ledger import read_trials

    row = read_trials(tmp_path)[-1]
    assert row["verdict"] == manifest["verdict"]["overall"]
    assert "too-few-trades" in row["labels"]
    assert row["idea_id"] == result["idea_id"]
    assert diagnostic["price_noise"]["copies"] == 50
    assert all(
        row["oos_had_trade"] is not None for row in diagnostic["walk_forward_efficiency"]["folds"]
    )
    listing = CliRunner().invoke(app, ["results", "--idea-id", result["idea_id"], "--json"])
    assert listing.exit_code == 0, listing.output
    assert json.loads(listing.stdout)["items"][0]["run_id"] == result["run_id"]
    citation = CliRunner().invoke(app, ["results", "cite", result["run_id"], "dsr"])
    assert "too-few-trades" in citation.output
    absent = CliRunner().invoke(app, ["results", "--idea-id", "absent", "--json"])
    assert json.loads(absent.stdout)["items"] == []


def test_plausibility_uses_net_profit_not_the_gross_trade_return() -> None:
    from types import SimpleNamespace

    from alpha_cli.spine.diagnose import _evidence_reading

    trade = SimpleNamespace(realized_return=0.1, realized_pnl=-1.0, quantity=1.0, entry_price=100.0)
    out: Any = SimpleNamespace(
        result=SimpleNamespace(trades=[trade] * 30),
        report=SimpleNamespace(oos_metrics={"sharpe": 1.0}),
    )
    document: dict[str, Any] = {}
    _evidence_reading(out, document)
    assert document["plausibility"] == []


def test_zero_wfe_citation_carries_the_empty_fold_count(tmp_path: Path) -> None:
    section = controls.walk_forward_efficiency(
        [
            {"is_cagr": 0.1, "oos_cagr": 0.0, "oos_had_trade": True},
            {"is_cagr": 0.1, "oos_cagr": 0.0, "oos_had_trade": False},
        ]
    )
    (tmp_path / "diagnostics.json").write_text(json.dumps({"walk_forward_efficiency": section}))
    fact = next(row for row in build_facts(tmp_path) if row["metric"] == "wfe")
    assert fact["value"] == 0.0
    assert "1 of 2 folds never traded out of sample" in fact["basis"]


@pytest.mark.parametrize("ratio", [0.996, 1.004, 1.0])
def test_plain_ratio_that_rounds_to_zero_reads_about_as_much(ratio: float) -> None:
    from alpha_cli.spine.plain_ratio import fall_comparison

    # "fell 0% less than" would be a contradiction in plain words.
    assert fall_comparison(ratio) == "fell about as much as"


def test_every_change_point_a_position_change_reads_as_one_sentence() -> None:
    dates = tuple(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(100))
    states = tuple(i >= 10 for i in range(100))
    only = tools.describe_changes([9, 10], dates, states, shift=1)
    assert only["sentence"] == (
        "No shift in behaviour found beyond entering and leaving the market "
        "(2 change points, all the rule stepping in or out)."
    )


def test_change_points_without_a_recorded_position_say_the_state_is_unknown() -> None:
    dates = tuple(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(50))
    result = tools.describe_changes([5, 30], dates, (), shift=0)
    assert [row["position_change"] for row in result["breaks"]] == [None, None]
    assert {row["label"] for row in result["breaks"]} == {"position state unknown"}
    assert result["behaviour_shifts"] is None and result["position_changes"] is None
    assert "position state was not recorded" in result["sentence"]
    assert "shift" not in result["sentence"].split(";")[0].lower().replace("shifts", "")


def test_check_refuses_a_too_few_trades_figure_without_the_caveat(tmp_path: Path) -> None:
    from alpha_cli.spine.check import check_text
    from tests.unit.test_spine_compare import A, make_lookup

    lookup = make_lookup(tmp_path)

    def sparse(run_id: str, metric: str) -> dict[str, Any]:
        return {**lookup(run_id, metric), "labels": ["quick", "too-few-trades"]}

    trials = f"12 [{A}:total_trials] trials."
    refused = check_text(f"Quick run: Sharpe 0.8 [{A}:oos_sharpe]. {trials}", sparse)
    assert [p["stored"] for p in refused["problems"] if p["kind"] == "LABEL_OMITTED"] == [
        "too-few-trades"
    ]
    stated = f"Quick run, too few trades to judge: Sharpe 0.8 [{A}:oos_sharpe]. {trials}"
    assert check_text(stated, sparse)["ok"]


def test_undefined_noise_copies_are_counted_and_warn_on_a_positive_rule() -> None:
    from alpha_cli.spine.price_noise import noise_summary

    runs: list[dict[str, Any]] = [
        {"sharpe": None if copy < 3 else 1.0, "trades": 0 if copy < 3 else 4, "reasons": {}}
        for copy in range(50)
    ]
    result = noise_summary(runs, 1.0)
    assert result["undefined_copies"] == 3
    assert result["median_sharpe"] is None and result["p05_sharpe"] is None
    assert "3 of 50 copies" in result["sentence"]
    # A positive rule that goes flat on a slightly different feed is fragile, not robust.
    assert result["labels"] == ["fragile-to-price-noise"]
    assert noise_summary(runs, -1.0)["labels"] == []


def test_report_grade_line_carries_the_sparse_trade_caveat(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from alpha_cli.main import app

    rdir = tmp_path / "runs" / ("c" * 16)
    rdir.mkdir(parents=True)
    verdict = {
        "overall": "C",
        "edge": "A",
        "robustness": "B",
        "risk": "B",
        "sample": "C",
        "labels": ["too-few-trades"],
        "sentence": "Only 4 closed trades: too few to judge.",
    }
    (rdir / "manifest.json").write_text(json.dumps({"command": "validate", "verdict": verdict}))
    printed = CliRunner(env={"ALPHA_DATA_DIR": str(tmp_path)}).invoke(app, ["report", "c" * 16])
    assert printed.exit_code == 0, printed.output
    line = next(row for row in printed.output.splitlines() if row.startswith("reading:"))
    assert "too-few-trades" in line and "Only 4 closed trades" in line


def test_run_id_hashing_inputs_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import _gauntlet, _runner
    from alpha_cli.spine import run as spine_run
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    # Code fingerprints pinned, so only the hashed payload and the data can move the id; the
    # expected value was computed with the same pins on main before idea_id existed.
    monkeypatch.setattr(_runner, "execution_fingerprint", lambda: "code-fixed")
    monkeypatch.setattr(_runner, "strategy_fingerprint", lambda name: "strategy-fixed")
    monkeypatch.delenv("ALPHA_RUN_CONTEXT_JSON", raising=False)
    seed_store(tmp_path, n=400)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    knobs = replace(
        _gauntlet.GauntletParams(seed=7),
        tier1_paths=20,
        tier2_paths=4,
        tier3_paths=4,
        n_resamples=50,
        max_workers=1,
    )
    result: dict[str, Any] = {"labels": ["all-in", "dev-machine-data", "quick"]}
    from alpha_cli._identity import RunIdentity

    original = _runner.run_identity_for
    captured: dict[str, Any] = {}

    def record_payload(payload: dict[str, Any], *, source_fingerprint: str) -> RunIdentity:
        captured.update(payload)
        return original(payload, source_fingerprint=source_fingerprint)

    monkeypatch.setattr(_runner, "run_identity_for", record_payload)
    prepared = spine_run.prepare_asset(idea, "SPY", tmp_path, knobs, result)
    assert captured.pop("data_health")["verdict"] == "unchecked"
    assert "data-health-unchecked" in captured["labels"]
    captured["labels"] = [label for label in captured["labels"] if label != "data-health-unchecked"]
    legacy = original(captured, source_fingerprint=prepared.identity.source_fingerprint)
    assert legacy.run_id == "3d7c42078dd76b34"
    assert prepared.identity.run_id != legacy.run_id
    assert result["idea_id"] == spine_run.idea_id(
        idea.spec_sha256, prepared.identity.source_fingerprint
    )


def test_implausibly_good_fires_on_a_rule_over_a_steadily_rising_demo_series() -> None:
    from types import SimpleNamespace

    import numpy as np

    from alpha_cli import _runner
    from alpha_cli.spine.diagnose import _evidence_reading
    from alpha_cli.spine.diagnostics import performance
    from alpha_cli.spine.run import assemble_run_spec
    from alpha_cli.spine.spec import load_spec
    from alpha_core import Bar

    # Like the README's made-up demo bars: a steady uptrend with small daily noise.
    rng = np.random.default_rng(0)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.002, 0.005, 1200)))
    bars = [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=float(price),
            high=float(price) * 1.002,
            low=float(price) * 0.998,
            close=float(price),
            volume=1_000_000,
        )
        for i, price in enumerate(closes)
    ]
    idea = load_spec(None, rule="ma_cross", param=["fast=3", "slow=10"], asset=["SPY"])
    spec = assemble_run_spec(idea, "SPY", 252, len(bars))
    full = _runner.run_full_backtest(bars, spec)
    sharpe = performance([v for _, v in full.equity_curve], 252, "demo")["sharpe"]
    assert len(full.trades) >= 30
    out: Any = SimpleNamespace(result=full, report=SimpleNamespace(oos_metrics={"sharpe": sharpe}))
    document: dict[str, Any] = {}
    _evidence_reading(out, document)
    assert [flag["flag"] for flag in document["plausibility"]] == ["implausibly-good"]


def test_wfe_says_when_the_median_fold_never_traded() -> None:
    # Real BTC 50/200 shape: the median of seven defined folds is the one fold that stayed flat.
    rows = [
        {"is_cagr": 0.3, "oos_cagr": oos, "oos_had_trade": oos != 0.0}
        for oos in (-0.34, -0.2, -0.03, 0.0, 0.43, 1.04, 2.13)
    ]
    result = controls.walk_forward_efficiency(rows)
    assert result["wfe"] == 0.0
    assert (
        "The median fold never traded out of sample, so 0% measures nothing."
        in (result["sentence"])
    )
    rows[3]["oos_had_trade"] = True
    assert "measures nothing" not in controls.walk_forward_efficiency(rows)["sentence"]


def test_change_point_split_says_when_switches_cover_much_of_the_history() -> None:
    dates = tuple(datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(100))
    busy = tuple((i // 10) % 2 == 0 for i in range(100))  # a switch every 10 bars
    result = tools.describe_changes([40], dates, busy, shift=0)
    assert result["near_switch_share"] == pytest.approx(0.91)
    assert "91% of all bars lie within 5 bars of a switch" in result["sentence"]
    calm = tuple(i >= 50 for i in range(100))
    quiet = tools.describe_changes([20], dates, calm, shift=0)
    assert quiet["near_switch_share"] == pytest.approx(11 / 100)
    assert "of all bars lie" not in quiet["sentence"]
