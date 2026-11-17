"""Synthetic identity boundaries: freeze refusal, causal splits and unchanged legacy inputs."""

from __future__ import annotations

import io
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_membership as membership
from alpha_cli import _rdagent_universe as universes
from alpha_cli._rdagent_clocks import CLOCKS, clock_samples
from alpha_core import DataError
from tests.unit.test_rdagent_gapped_universe import walk_panel


def declaration(day: str = "2021-02-10", instrument: str = "C0") -> dict[str, str]:
    return {"instrument": instrument, "new_from": day, "reason": "ticker_reused"}


def freeze_panel(
    root: Path, panel: pl.DataFrame, breaks: list[dict[str, str]] | None = None
) -> tuple[dict[str, Any], pl.DataFrame]:
    """Exercise freeze with small verified-artifact stand-ins, no real store."""
    manifests = root / "control/crypto/manifests"
    manifests.mkdir(parents=True)
    artifacts: dict[str, tuple[dict[str, Any], bytes]] = {}
    for (symbol,), group in panel.partition_by("instrument", as_dict=True).items():
        manifest: dict[str, Any] = {
            "artifact_kind": "normalized",
            "dataset": {
                "family": "market_bars",
                "venue": "binance",
                "market_type": "spot",
                "frequency": "1d",
                "timestamp_convention": "interval_start_utc",
                "instrument": symbol,
            },
            "quality": {"state": "qualified", "warnings": [], "failures": []},
        }
        buffer = io.BytesIO()
        group.drop("instrument").rename(
            {"date": "open_time", "volume": "base_volume"}
        ).write_parquet(buffer)
        payload = buffer.getvalue()
        manifest["artifact_sha256"] = judge.sha(payload)
        artifacts[str(symbol)] = manifest, payload
        (manifests / f"{symbol}.json").write_text(json.dumps(manifest))

    class Store:
        def read_verified_normalized(
            self, key: str, *, max_bytes: int
        ) -> tuple[dict[str, Any], bytes]:
            assert len(artifacts[key][1]) <= max_bytes
            return artifacts[key]

    spec = {**universes.DEFAULT, "min_names": 1, "min_universe": 3}
    if breaks is not None:
        spec["identity_breaks"] = breaks
    universe = root / "universe.json"
    universe.write_text(json.dumps(spec))
    with patch.object(judge, "configured_crypto_bulk_store", return_value=Store()):
        receipt = judge.freeze(root / "control", root / "panel", universe)
    return receipt, pl.read_parquet(root / "panel/panel.parquet")


def jump_panel(gap: int, ratio: float) -> pl.DataFrame:
    rows = []
    for symbol in ("C0", "C1", "C2"):
        for i in (0, gap + 1):
            price = 10.0 * (ratio if i and symbol == "C0" else 1.0)
            rows.append(
                {
                    "date": date(2021, 1, 1) + timedelta(days=i),
                    "instrument": symbol,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1.0,
                    "quote_volume": 10.0,
                }
            )
    return pl.DataFrame(rows).sort(["date", "instrument"])


@pytest.mark.parametrize("ratio", [10.0, 0.1])
def test_undeclared_jump_refuses_freeze_with_typed_context(tmp_path: Path, ratio: float) -> None:
    # Import inside the test: the first red run must reach the missing guard, not fail collection.
    with pytest.raises(DataError, match="identity_breaks") as caught:
        freeze_panel(tmp_path, jump_panel(10, ratio))
    from alpha_cli._rdagent_identity import IdentityJumpError

    assert isinstance(caught.value, IdentityJumpError)
    for word in ("C0", "2021-01-01", "2021-01-12", "10.0", str(10 * ratio), str(ratio)):
        assert word in str(caught.value)
    assert not (tmp_path / "panel").exists()


@pytest.mark.parametrize(("gap", "ratio"), [(10, 3.0), (7, 5.0), (7, 0.2), (0, 10.0), (0, 0.1)])
def test_allowed_gap_and_ratio_boundaries(tmp_path: Path, gap: int, ratio: float) -> None:
    _, actual = freeze_panel(tmp_path, jump_panel(gap, ratio))
    assert actual.equals(jump_panel(gap, ratio))


@pytest.mark.parametrize(("gap", "ratio"), [(1, 5.01), (3, 10.0), (3, 0.1)])
def test_one_missing_day_is_the_first_checked_gap(tmp_path: Path, gap: int, ratio: float) -> None:
    with pytest.raises(DataError, match="identity_breaks"):
        freeze_panel(tmp_path, jump_panel(gap, ratio))


def test_declared_break_splits_and_receipt_binds_policy(tmp_path: Path) -> None:
    breaks = [declaration("2021-01-12")]
    receipt, panel = freeze_panel(tmp_path, jump_panel(10, 1000), breaks)
    assert panel.filter(pl.col("instrument") == "C0")["date"].to_list() == [date(2021, 1, 1)]
    assert panel.filter(pl.col("instrument") == "C0~2")["date"].to_list() == [date(2021, 1, 12)]
    assert receipt["identity_breaks"] == [{**breaks[0], "new_name": "C0~2"}]
    assert receipt["identity_jump_policy"] == {"min_gap_days": 1, "ratio": 5.0}
    frozen = universes.frozen(tmp_path / "panel")
    assert receipt["universe_sha256"] == judge.sha(judge.canonical(frozen))


@pytest.mark.parametrize(
    "breaks",
    [
        None,
        {},
        [None],
        [{}],
        [declaration("not-a-date")],
        [declaration("2021-02-30")],
        [declaration("2021-02-10T00:00:00")],
        [{**declaration(), "reason": "split"}],
        [{**declaration(), "extra": 1}],
        [declaration(instrument="absent")],
        [declaration(), declaration()],
        [declaration(), declaration("2021-01-01")],
        [{**declaration(), "instrument": []}],
    ],
)
def test_invalid_declarations_fail_loud(breaks: Any) -> None:
    with pytest.raises(DataError, match="identity"):
        universes.validate({**universes.DEFAULT, "instruments": ["C0"], "identity_breaks": breaks})


def test_all_store_membership_and_name_collision_are_checked_at_freeze(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="identity.*absent"):
        freeze_panel(tmp_path / "absent", jump_panel(10, 10), [declaration(instrument="absent")])
    bars = jump_panel(10, 10)
    collision = bars.filter(pl.col("instrument") == "C1").with_columns(
        pl.lit("C0~2").alias("instrument")
    )
    with pytest.raises(DataError, match="collision"):
        freeze_panel(
            tmp_path / "collision", pl.concat([bars, collision]), [declaration("2021-01-12")]
        )


def test_multiple_breaks_relabel_once_without_crossing_boundaries(tmp_path: Path) -> None:
    bars = walk_panel()
    breaks = [declaration("2021-01-10"), {**declaration("2021-02-10"), "reason": "redenominated"}]
    receipt, actual = freeze_panel(tmp_path, bars, breaks)
    assert actual.height == bars.height
    assert [b["new_name"] for b in receipt["identity_breaks"]] == ["C0~2", "C0~3"]
    for day, symbol in (
        actual.filter(pl.col("instrument").str.starts_with("C0"))
        .select("date", "instrument")
        .iter_rows()
    ):
        assert symbol == (
            "C0" if day < date(2021, 1, 10) else "C0~2" if day < date(2021, 2, 10) else "C0~3"
        )


def test_split_position_writes_off_and_new_asset_earns_warmup(tmp_path: Path) -> None:
    bars = walk_panel()
    boundary = date(2021, 2, 10)
    bars = bars.with_columns(
        [
            pl.when((pl.col("instrument") == "C0") & (pl.col("date") >= boundary))
            .then(pl.col(c) * 1000)
            .otherwise(pl.col(c))
            .alias(c)
            for c in judge.PRICE_COLUMNS
        ]
    )
    _, panel = freeze_panel(tmp_path, bars, [declaration()])
    symbols = sorted(panel["instrument"].unique().to_list())
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(85)]
    prices = judge.matrix(panel, "close", days, symbols)
    old, new = symbols.index("C0"), symbols.index("C0~2")
    account = membership.Account(symbols, fee_bps=0, slippage_bps=0)
    account.trade(old, 1.0, prices[0, old], days[0], "open")
    for day, values in zip(days, prices, strict=True):
        account.observe(day, values)
    exit_ = account.events[-1]
    last = prices[days.index(boundary) - 1, old]
    assert exit_["basis"] == "writeoff"
    assert exit_["date"] == boundary - timedelta(days=1) + timedelta(days=30)
    assert exit_["price"] == pytest.approx(last * 0.7)
    assert exit_["realized_pnl_before_fees"] < 0
    mask = judge.panel_membership(panel, days, symbols)
    assert not mask[days.index(boundary) :, old].any()
    assert not mask[: days.index(boundary) + 19, new].any()
    assert mask[days.index(boundary) + 19, new]
    for label in (membership.forward_returns, membership.holding_returns):
        result, _ = label(
            prices, prices, days, [days.index(boundary) - 1], [days.index(boundary) + 1]
        )
        assert result[0, old] == pytest.approx(-0.3)


@pytest.mark.parametrize("clock", ["daily", "weekly", "monthly"])
@pytest.mark.parametrize("name_count", [9, 15])
def test_future_break_changes_no_past_decision_or_realized_figure(
    tmp_path: Path, clock: str, name_count: int
) -> None:
    bars = walk_panel(names=name_count)
    boundary = date(2021, 2, 20)
    _, split = freeze_panel(tmp_path, bars, [declaration(boundary.isoformat())])
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(70)]
    cutoff = boundary - timedelta(days=membership.WRITE_OFF_AFTER_DAYS)
    results: list[dict[str, Any]] = []
    masks: list[np.ndarray] = []
    names: list[list[str]] = []
    for panel in (bars, split):
        symbols = sorted(panel["instrument"].unique().to_list())
        scores = np.column_stack(
            [np.full(len(days), 20.0 if s.startswith("C0") else float(s[1:])) for s in symbols]
        )
        series: dict[str, Any] = {}
        judge.replay(
            panel,
            scores,
            days,
            1,
            clock=clock,
            gap_policy=True,
            series=series,
            identity_segments=frozenset({"C0~2"}) if "C0~2" in symbols else frozenset(),
        )
        results.append(series)
        names.append(symbols)
        masks.append(judge.panel_membership(panel, days, symbols))
    through = days.index(cutoff) + 1
    for j, symbol in enumerate(names[0]):
        assert np.array_equal(masks[0][:through, j], masks[1][:through, names[1].index(symbol)])
    for key in ("events", "periods", "targets"):

        def before(item: Any, key: str = key) -> bool:
            if key == "events":
                return bool(item["date"] <= cutoff)
            if key == "periods":
                return bool(item.exit_ts.date() <= cutoff)
            return bool(item.origin_ts.date() <= cutoff and item.symbol != "C0~2")

        assert [v for v in results[0][key] if before(v)] == [
            v for v in results[1][key] if before(v)
        ]
    for left, right in zip(
        results[0]["positions"][:through], results[1]["positions"][:through], strict=True
    ):
        assert left["cash"] == right["cash"] and left["equity"] == right["equity"]
        assert left["quantities"] == [right["quantities"][names[1].index(s)] for s in names[0]]
    assert any(e["basis"] == "writeoff" and e["instrument"] == "C0" for e in results[1]["events"])
    assert results[0]["events"] != results[1]["events"]  # poison has power


def test_no_break_panel_bytes_and_legacy_universe_are_unchanged(tmp_path: Path) -> None:
    bars = walk_panel()
    _, frozen = freeze_panel(tmp_path / "absent", bars)
    _, empty = freeze_panel(tmp_path / "empty", bars, [])
    buffer = io.BytesIO()
    judge.validate_panel(bars.select(judge.PANEL_COLUMNS)).write_parquet(buffer)
    assert (tmp_path / "absent/panel/panel.parquet").read_bytes() == buffer.getvalue()
    assert (tmp_path / "empty/panel/panel.parquet").read_bytes() == buffer.getvalue()
    assert frozen.equals(empty)
    assert universes.load(None) == universes.DEFAULT
    assert "identity_breaks" not in universes.frozen(tmp_path / "absent/panel")


@pytest.mark.parametrize("declared", [False, True])
def test_run_report_and_proposer_receive_split_count(tmp_path: Path, declared: bool) -> None:
    from alpha_cli import rdagent_factor_eval as ev
    from tests.unit.test_rdagent_factor_eval import fixture

    request_path = fixture(tmp_path / "run")
    run = request_path.parent
    request = json.loads(request_path.read_bytes())
    request["factors"][0]["status"] = "FAILED"
    request_path.write_text(json.dumps(request))
    path = run / "panel/panel-receipt.json"
    receipt = json.loads(path.read_bytes())
    breaks = [{**declaration(), "new_name": "C0~2"}] if declared else []
    receipt.update(identity_breaks=breaks, identity_jump_policy={"min_gap_days": 1, "ratio": 5.0})
    path.write_text(json.dumps(receipt))
    result = ev.evaluate(run, request_path, run / "result.json", tmp_path / "ledger")
    expected = f"{int(declared)} tickers were split at declared identity breaks."
    assert expected in result["feedback_text"]
    assert result["disclosures"]["identity_breaks"]["message"] == expected
    assert result["disclosures"]["identity_breaks"]["applied"] == breaks
    assert expected in result["legacy_result"]["factor.feedback"]


def test_legacy_receipt_still_loads_without_identity_fields(tmp_path: Path) -> None:
    from alpha_cli import rdagent_factor_eval as ev
    from tests.unit.test_rdagent_factor_eval import fixture

    request = fixture(tmp_path)
    loaded, panel, _, _ = ev._inputs(tmp_path, request)
    assert loaded["schema"] == "AlphaRdagentFactorRequestV1"
    assert panel.height > 0
    receipt = json.loads((tmp_path / "panel/panel-receipt.json").read_bytes())
    assert "identity_breaks" not in receipt


def test_feedback_keeps_authoritative_split_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ast
    from types import SimpleNamespace
    from unittest.mock import Mock

    from tests.unit.test_rdagent_factor_judge import judge_parts

    ns = judge_parts("record_round")
    ns["Experiment2Feedback"] = object
    source = Path(__file__).resolve().parents[2] / "workers/rdagent/alpha_factor_judge.py"
    nodes: list[ast.stmt] = [
        n
        for n in ast.parse(source.read_text()).body
        if isinstance(n, ast.ClassDef) and n.name == "AlphaFactorFeedback"
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<identity-feedback>", "exec"), ns)
    message = "2 tickers were split at declared identity breaks."
    reply = json.dumps({"Observations": "A model summary without the count."})
    ns["APIBackend"] = Mock(
        return_value=SimpleNamespace(
            build_messages_and_create_chat_completion=Mock(return_value=reply)
        )
    )
    ns["T"] = Mock(return_value=SimpleNamespace(r=Mock(return_value="prompt")))
    ns["QlibQuantScenario"] = type("Scenario", (), {})
    ns["HypothesisFeedback"] = SimpleNamespace
    ns["convert2bool"] = bool
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    feedback = ns["AlphaFactorFeedback"]()
    feedback.scen = SimpleNamespace(get_scenario_all_desc=lambda: "scenario")
    exp = SimpleNamespace(
        hypothesis=SimpleNamespace(hypothesis="test"),
        sub_tasks=[],
        stdout=message,
        alpha_evaluation={
            "iteration": 0,
            "decision": False,
            "disclosures": {"identity_breaks": {"message": message}},
        },
    )
    result = feedback.generate_feedback(exp, None)
    assert message in result.observations


def _without(bars: pl.DataFrame, name: str, first: date, last: date) -> pl.DataFrame:
    """Drop one instrument's bars on [first, last]: the old coin's pre-break gap."""
    hole = (pl.col("instrument") == name) & pl.col("date").is_between(first, last)
    return bars.filter(~hole)


@pytest.mark.parametrize("clock", ["daily", "weekly", "monthly"])
@pytest.mark.parametrize("gap_days", [0, 12])
def test_break_changes_nothing_before_new_from_except_differing_bars(
    tmp_path: Path, clock: str, gap_days: int
) -> None:
    """Decisions, trades, positions and periods stay identical through new_from - 1.

    Bars only differ from new_from on (they move to the new name), so the old coin must behave
    like one whose bars stop there. Labels look forward up to the write-off wait, so they are
    compared for windows whose wait ends before new_from. Signals are masked by membership as
    the evaluator does, so the new name never scores before it has earned its warm-up.
    """
    boundary = date(2021, 2, 20)
    bars = walk_panel(names=9)
    if gap_days:
        bars = _without(bars, "C0", boundary - timedelta(days=gap_days), boundary - timedelta(1))
    _, split = freeze_panel(tmp_path, bars, [declaration(boundary.isoformat())])
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(70)]
    open_days = [days[0] + timedelta(days=i) for i in range(len(days) + 2)]
    stop = days.index(boundary)
    out: list[dict[str, Any]] = []
    for panel in (bars, split):
        symbols = sorted(panel["instrument"].unique().to_list())
        mask = judge.panel_membership(panel, days, symbols)
        raw = np.column_stack([np.full(len(days), float(s[1:].replace("~", "."))) for s in symbols])
        raw[:, symbols.index("C0")] = 20.0
        signal = np.where(mask, raw, np.nan)
        replayed: dict[str, Any] = {}
        judge.replay(
            panel,
            signal,
            days,
            1,
            clock=clock,
            gap_policy=True,
            series=replayed,
            identity_segments=frozenset({"C0~2"}) if "C0~2" in symbols else frozenset(),
        )
        opens = judge.matrix(panel, "open", open_days, symbols)
        closes = judge.matrix(panel, "close", open_days, symbols)
        screened = clock_samples(
            signal, opens, days, open_days, clock, closes=closes, gap_policy=True
        )
        keep = [symbols.index(s) for s in symbols if s != "C0~2"]
        out.append({"replay": replayed, "screen": screened, "mask": mask[:, keep], "keep": keep})
    old, new = out
    assert np.array_equal(old["mask"][:stop], new["mask"][:stop])
    assert not new["mask"][stop:, 0].any()  # the old coin never re-enters
    early = [e for e in old["replay"]["events"] if e["date"] < boundary]
    assert early == [e for e in new["replay"]["events"] if e["date"] < boundary]
    assert [p for p in old["replay"]["periods"] if p.exit_ts.date() < boundary] == [
        p for p in new["replay"]["periods"] if p.exit_ts.date() < boundary
    ]
    assert [t for t in old["replay"]["targets"] if t.origin_ts.date() < boundary] == [
        t for t in new["replay"]["targets"] if t.origin_ts.date() < boundary and t.symbol != "C0~2"
    ]
    assert all(
        t.target_weight == 0
        for t in new["replay"]["targets"]
        if t.symbol == "C0~2" and t.origin_ts.date() < boundary + timedelta(days=19)
    )
    for left, right in zip(
        old["replay"]["positions"][:stop], new["replay"]["positions"][:stop], strict=True
    ):
        assert left["date"] < boundary
        assert (left["cash"], left["equity"]) == (right["cash"], right["equity"])
        assert left["quantities"] == [right["quantities"][j] for j in new["keep"]]
    wait = timedelta(days=membership.WRITE_OFF_AFTER_DAYS + 1 + CLOCKS[clock])
    settled = [i for i, day in enumerate(old["screen"]["days"]) if day + wait < boundary]
    assert settled or clock == "monthly"  # a 28-day window plus the wait outruns this panel
    for i in settled:
        assert old["screen"]["outcome"][i].tolist() == [
            new["screen"]["outcome"][i][j] for j in new["keep"]
        ]
    # Poison has power: the held old coin is written off as a loss, never exited at a jump.
    assert old["replay"]["events"] != new["replay"]["events"]
    late = [e["basis"] for e in new["replay"]["events"] if e["instrument"] == "C0"]
    assert "writeoff" in late and "resume-close" not in late


def test_refusal_names_every_undeclared_jump_at_once(tmp_path: Path) -> None:
    """The owner fixes the break list in one pass, not one refusal per instrument."""
    bars = jump_panel(10, 10.0)
    down = pl.col("instrument") == "C1"
    late = pl.col("date") > date(2021, 1, 1)
    bars = bars.with_columns(
        [
            pl.when(down & late).then(pl.col(c) * 0.1).otherwise(pl.col(c)).alias(c)
            for c in judge.PRICE_COLUMNS
        ]
    )
    with pytest.raises(DataError, match="identity_breaks") as caught:
        freeze_panel(tmp_path, bars)
    message = str(caught.value)
    assert "2 undeclared" in message
    assert "C0" in message and "C1" in message
    assert message.count("new_from=") == 2
