"""The MCP server's tools drive the real `alpha` CLI end-to-end (offline, no network).

These call the tool functions directly (FastMCP leaves them ordinary callables) against a temp
ALPHA_DATA_DIR seeded with the shared fixture, so a real `alpha` subprocess runs each time —
exercising subprocess invocation, run-id parsing, manifest reads, run-type routing, the
filesystem read tools, and the FastMCP registration.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import anyio
import pytest

from alpha_cli.control_store import ControlStore
from alpha_core import DataError
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore
from alpha_mcp import _invoke, server, spine_tools
from tests.fixtures.cli_fixtures import seed_store

# small-parameter knobs so the fixture's 60 bars warm up, trade, and cost nothing
_OPTS = {
    "lookback": "5",
    "skip": "1",
    "vol-window": "3",
    "rebalance-every": "2",
    "fee-bps": "0",
    "slippage-bps": "0",
    "starting-cash": "100000",
}


def test_backtest_run_tool_returns_a_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=60)

    manifest = server.backtest_run("SPY", options=_OPTS)
    assert manifest["command"] == "backtest_run"
    run_id = manifest["run_id"]

    # the read tools see the same run from disk, no engine
    assert server.get_run(run_id)["run_id"] == run_id
    assert any(r["run_id"] == run_id for r in server.list_runs())


def test_propfirm_from_run_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=60)

    bt = server.backtest_run("SPY", options=_OPTS)
    pf = server.propfirm_run(
        from_run=bt["run_id"], firm="topstep", options={"n-paths": "200", "seed": "7"}
    )
    assert pf["command"] == "propfirm"
    assert pf["firm"] == "topstep"


def test_forecast_run_tool_returns_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=30)

    manifest = server.forecast_run(
        "SPY", options={"model": "fake", "context": "8", "horizon": "4", "samples": "6"}
    )
    assert manifest["command"] == "forecast_run"
    assert manifest["model"]["model_id"] == "fake"
    assert server.get_run(manifest["run_id"])["run_id"] == manifest["run_id"]
    assert any(r["run_id"] == manifest["run_id"] for r in server.list_runs())
    jobs = ControlStore(tmp_path).list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["kind"] == "kronos_forecast"
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["result_run_id"] == manifest["run_id"]


def test_failed_run_surfaces_the_cli_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=60)
    # no such symbol stored -> the CLI fails loud -> the tool raises with the CLI's message
    with pytest.raises(RuntimeError):
        server.backtest_run("NOPE", options=_OPTS)


def test_list_strategies_includes_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "ts_momentum" in server.list_strategies()


def test_all_expected_tools_are_registered() -> None:
    names = {t.name for t in anyio.run(server.mcp.list_tools)}
    assert {
        "data_pull",
        "backtest_run",
        "backtest_portfolio",
        "backtest_cross_sectional",
        "validate",
        "optim_grid",
        "propfirm_run",
        "forecast_run",
        "forecast_eval",
        "get_run",
        "list_runs",
        "list_strategies",
    } <= names
    assert {
        "create_development_job",
        "list_development_jobs",
        "get_development_job",
        "cancel_development_suite",
        "reconcile_development_jobs",
        "get_chart_bundle",
        "get_portfolio_analytics",
        "compare_runs",
    } <= names
    assert (
        not {
            "reveal_holdout",
            "place_order",
            "run_command",
            "run_python",
            "raw_sql",
            "read_file",
            "review_monte_carlo",
        }
        & names
    )


def test_control_plane_tools_round_trip_through_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    job = server.create_development_job(
        "validation_suite",
        {"families": ["bootstrap", "student_t", "garch"]},
    )
    assert job["status"] == "queued"
    assert server.list_development_jobs(limit=1)["items"][0]["job_id"] == job["job_id"]
    ControlStore(tmp_path).append_job_event(
        job["job_id"], event_type="log", payload={"message": "latest"}
    )
    journal = server.get_development_job(job["job_id"], event_limit=1)
    assert journal["events"][0]["payload"] == {"message": "latest"}
    assert journal["event_total"] == 2
    assert journal["event_tail"] is True
    assert journal["events_has_more"] is True
    prior = server.get_development_job(job["job_id"], event_limit=1, event_offset=1)
    assert prior["events"][0]["event_type"] == "created"
    assert prior["events_has_more"] is False


def test_control_plane_tool_bounds_fail_before_cli() -> None:
    with pytest.raises(ValueError, match="limit"):
        server.list_runs(limit=501)


def test_legacy_action_options_are_closed_per_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_subprocess(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("invalid MCP input reached the CLI subprocess")

    monkeypatch.setattr(_invoke, "run_alpha", unexpected_subprocess)
    calls: tuple[Callable[[], object], ...] = (
        lambda: server.backtest_run("SPY", options={"stride": "2"}),
        lambda: server.backtest_portfolio(["SPY", "QQQ"], options={"top-quantile": "0.2"}),
        lambda: server.backtest_cross_sectional(["SPY", "QQQ"], options={"account-type": "MARGIN"}),
        lambda: server.validate("SPY", options={"size-on-equity": ""}),
        lambda: server.optim_grid("SPY", {"lookback": [5.0]}, options={"tier1-paths": "10"}),
        lambda: server.forecast_run("SPY", options={"stride": "2"}),
        lambda: server.forecast_eval("SPY", options={"halt-drawdown": "0.1"}),
        lambda: server.propfirm_run(from_run="0" * 16, options={"as-of": "2026-01-01"}),
    )
    for call in calls:
        with pytest.raises(ValueError, match="unsupported"):
            call()


def test_legacy_action_inputs_are_counted_and_length_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_subprocess(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("invalid MCP input reached the CLI subprocess")

    monkeypatch.setattr(_invoke, "run_alpha", unexpected_subprocess)
    with pytest.raises(ValueError, match="32-option limit"):
        server.backtest_run("SPY", options={f"unknown-{index}": "1" for index in range(33)})
    with pytest.raises(ValueError, match="256 characters"):
        server.backtest_run("SPY", options={"as-of": "x" * 257})
    with pytest.raises(ValueError, match="duplicate normalized"):
        server.backtest_run("SPY", options={"fee-bps": "1", "fee_bps": "2"})
    with pytest.raises(ValueError, match="filesystem-like"):
        server.backtest_run("../SPY")
    with pytest.raises(ValueError, match="2..100"):
        server.backtest_portfolio([f"S{index}" for index in range(101)])
    with pytest.raises(ValueError, match="16-parameter limit"):
        server.backtest_run("SPY", params={f"param_{index}": "1" for index in range(17)})
    with pytest.raises(ValueError, match="4096-configuration"):
        server.optim_grid(
            "SPY",
            {
                "lookback": [float(value) for value in range(65)],
                "skip": [float(value) for value in range(65)],
            },
        )


def test_data_pull_dates_are_canonical_valid_and_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_subprocess(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("invalid MCP input reached the CLI subprocess")

    monkeypatch.setattr(_invoke, "run_alpha", unexpected_subprocess)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        server.data_pull("SPY", start="20260719", end="2026-07-20")
    with pytest.raises(ValueError, match="valid YYYY-MM-DD"):
        server.data_pull("SPY", start="2026-02-30", end="2026-07-20")
    with pytest.raises(ValueError, match="on or before"):
        server.data_pull("SPY", start="2026-07-20", end="2026-07-19")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("model", "/tmp/Kronos", "managed repository id"),
        ("model", "../Kronos", "managed repository id"),
        ("model", "org/repo/weights", "managed repository id"),
        ("tokenizer", r"C:\\models\\tokenizer", "managed repository id"),
        ("model-revision", "refs/heads/main", "immutable revision"),
    ],
)
def test_forecast_actions_reject_path_like_model_inputs(
    key: str,
    value: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_subprocess(*args: object, **kwargs: object) -> dict[str, object]:
        raise AssertionError("invalid MCP input reached the CLI subprocess")

    monkeypatch.setattr(_invoke, "run_alpha", unexpected_subprocess)
    for call in (server.forecast_run, server.forecast_eval):
        with pytest.raises(ValueError, match=message):
            call("SPY", options={key: value})


def test_forecast_action_preserves_safe_managed_identifier_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(args: list[str], *, data_dir: Path, run_type: str | None) -> dict[str, object]:
        captured.update(args=args, data_dir=data_dir, run_type=run_type)
        return {"run_id": "0" * 16}

    monkeypatch.setattr(_invoke, "run_alpha", fake_run)
    result = server.forecast_run(
        "SPY",
        options={
            "model": "NeoQuasar/Kronos-small",
            "model_revision": "0123456789abcdef",
            "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
            "tokenizer_revision": "fedcba9876543210",
        },
    )
    assert result["run_id"] == "0" * 16
    assert captured["run_type"] == "forecast"
    assert captured["args"] == [
        "forecast",
        "run",
        "SPY",
        "--model",
        "NeoQuasar/Kronos-small",
        "--model-revision",
        "0123456789abcdef",
        "--tokenizer",
        "NeoQuasar/Kronos-Tokenizer-base",
        "--tokenizer-revision",
        "fedcba9876543210",
    ]


def test_v3_control_tools_publish_named_output_schemas() -> None:
    tools = {tool.name: tool for tool in anyio.run(server.mcp.list_tools)}
    typed_names = {
        "create_development_job",
        "list_development_jobs",
        "get_development_job",
        "cancel_development_suite",
        "reconcile_development_jobs",
        "get_chart_bundle",
        "get_portfolio_analytics",
        "compare_runs",
        "get_run",
        "list_runs",
    }
    for name in typed_names:
        schema = tools[name].outputSchema
        assert schema is not None
        assert schema.get("type") == "object"
        assert schema.get("properties"), name
        assert schema.get("additionalProperties") is not True


def test_chart_bundle_and_run_comparison_are_snapshot_locked_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=70)
    create_snapshot(
        ParquetStore(tmp_path / "store"),
        tmp_path / "snapshots",
        "frozen",
        ["SPY"],
        source="fixture",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    first = server.backtest_run("SPY", options={**_OPTS, "snapshot": "frozen"})
    second = server.backtest_run(
        "SPY", options={**_OPTS, "snapshot": "frozen", "rebalance-every": "3"}
    )

    bundle = server.get_chart_bundle(first["run_id"], limit=25, bar_limit=30)
    assert bundle["bars_status"] == "available"
    assert len(bundle["bars"]) == 30
    assert bundle["trace_status"] == "available"
    assert bundle["provenance"]["snapshot_id"] == "frozen"
    assert bundle["provenance"]["snapshot_hash"] == first["snapshot_hash"]
    assert bundle["truncated"]["bars"] is True

    comparison = server.compare_runs([first["run_id"], second["run_id"]])
    assert comparison["same_snapshot_hash"] is True
    assert [row["run_id"] for row in comparison["rows"]] == [
        first["run_id"],
        second["run_id"],
    ]
    assert all(
        metric["source_artifact"] == "manifest.json"
        for row in comparison["rows"]
        for metric in row["metrics"]
    )


def test_portfolio_analytics_tool_is_typed_bounded_and_cited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=80, seed=0)
    seed_store(tmp_path, symbol="QQQ", n=80, seed=1)
    create_snapshot(
        ParquetStore(tmp_path / "store"),
        tmp_path / "snapshots",
        "portfolio-frozen",
        ["SPY", "QQQ"],
        source="fixture",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    options = {
        **_OPTS,
        "train-size": "15",
        "test-size": "5",
        "embargo": "1",
        "snapshot": "portfolio-frozen",
    }
    manifest = server.backtest_portfolio(["SPY", "QQQ"], options=options)

    projection = server.get_portfolio_analytics(
        manifest["run_id"], timestamp_limit=7, symbol_limit=2
    )

    assert projection["symbols"] == ["QQQ", "SPY"]
    assert len(projection["correlations"]) == 4
    assert projection["bounds"]["allocation_timestamps"]["returned"] == 7
    assert projection["bounds"]["allocation_timestamps"]["truncated"] is True
    assert projection["provenance"]["snapshot_hash"] == manifest["snapshot_hash"]
    assert projection["provenance"]["association_label"] == "association, not causation"
    assert projection["provenance"]["artifact_sha256"]["correlations.parquet"]
    with pytest.raises(DataError, match="symbol_limit"):
        server.get_portfolio_analytics(manifest["run_id"], symbol_limit=101)


def test_spine_rule_test_then_ledger_summary_reads_the_new_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_setup_find import seed

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed(tmp_path, symbol="SPY", n=400)

    before = spine_tools.ledger_summary()
    result = spine_tools.rule_test(
        rule="breakout", params={"window": "20"}, assets=["SPY"], quick=True
    )
    after = spine_tools.ledger_summary()

    assert isinstance(result, dict)
    assert after != before
    rows = spine_tools.ledger_history(kind=None, asset="SPY", limit=5)
    assert "SPY" in str(rows)


def test_data_pull_cannot_be_called_without_dates_and_relays_the_pull_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = next(t for t in anyio.run(server.mcp.list_tools) if t.name == "data_pull")
    assert {"symbol", "start", "end"} <= set(tool.inputSchema["required"])
    words = " ".join((tool.description or "").split())
    assert "first freezes the current one as a snapshot" in words
    assert "never deletes snapshots" in words
    without_end = {"symbol": "SPY", "start": "2026-01-01"}
    with pytest.raises(TypeError, match="end"):
        server.data_pull(**without_end)
    calls: list[list[str]] = []
    answer = {"snapshot": {"id": "pull-x-SPY", "reused": False}, "bars_added": {"count": 2}}

    def fake(args: list[str], *, data_dir: Path, run_type: str | None) -> dict[str, object]:
        calls.append(args)
        return {"stdout": json.dumps(answer)}

    monkeypatch.setattr(_invoke, "run_alpha", fake)
    assert server.data_pull("SPY", start="2026-01-01", end="2026-02-01") == answer
    assert calls == [
        [
            "data",
            "pull",
            "SPY",
            "--source",
            "yfinance",
            "--start",
            "2026-01-01",
            "--end",
            "2026-02-01",
            "--json",
        ]
    ]  # the same `alpha data pull` path, so the freeze applies
