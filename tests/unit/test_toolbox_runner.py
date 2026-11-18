"""Audit, idempotency and reserve boundaries shared by all toolbox entries."""

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import append_trial, read_trials
from alpha_cli.toolbox import inputs
from alpha_cli.toolbox.reserve import RESERVED_DAY
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN, _series


def test_settings_and_failed_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    series = _series(tmp_path)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    with pytest.raises(SpineError):
        run(tmp_path, "market.changepoints", RUN, ["on=bad"])
    assert [r["outcome"] for r in read_trials(tmp_path)] == ["attempted", "error"]
    assert read_trials(tmp_path)[-1]["error_code"]
    run(tmp_path, "market.changepoints", RUN)
    doc = run(tmp_path, "market.changepoints", RUN, ["on=equity"])
    assert "non-default-params" in doc["labels"]
    assert {"on": "bad"} in doc["settings_tried"]
    assert {"on": "returns"} in doc["settings_tried"]
    assert {"on": "equity"} in doc["settings_tried"]
    assert run(tmp_path, "market.changepoints", RUN, ["on=equity"]) == doc
    rows = read_trials(tmp_path)
    assert [r["outcome"] for r in rows] == [
        "attempted",
        "error",
        "attempted",
        "ok",
        "attempted",
        "ok",
    ]
    assert all(r["verdict"] is None for r in rows)


@pytest.mark.parametrize("days", [-1, 0, 1])
def test_reserved_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, days: int) -> None:
    series = _series(tmp_path)
    offset = RESERVED_DAY - series.dates[-1].date() + timedelta(days=days)
    moved = replace(series, dates=tuple(date + offset for date in series.dates))
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: moved)
    doc = run(tmp_path, "market.changepoints", RUN)
    assert ("reserved-period-seen" in doc["labels"]) == (days >= 0)
    assert sum(s["bars"] for s in doc["result"]["segments"]) == len(series.equity) - 1


def test_future_market_bars_do_not_change_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from alpha_cli import _runner
    from tests.unit.test_spine_tools import _other_asset

    series = _series(tmp_path)
    _other_asset(monkeypatch, tmp_path, keep=1)
    resolved = inputs.resolve(tmp_path, RUN)
    baseline = inputs.comparison(tmp_path, resolved, "QQQ")
    original = _runner.load_bars

    def poisoned(symbol: str, *, data_dir: Path, as_of: datetime) -> tuple[list[object], None]:
        bars, _ = original(symbol, data_dir=data_dir, as_of=as_of)
        return [*bars, SimpleNamespace(ts=series.dates[-1] + timedelta(days=1), open=-100)], None

    monkeypatch.setattr(_runner, "load_bars", poisoned)
    assert inputs.comparison(tmp_path, resolved, "QQQ") == baseline


def test_future_bars_do_not_enter_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from alpha_cli import _runner
    from tests.unit.test_spine_tools import _other_asset

    series = _series(tmp_path)
    _other_asset(monkeypatch, tmp_path, keep=1)
    last = series.dates[-1]
    bars = [SimpleNamespace(ts=last), SimpleNamespace(ts=last + timedelta(days=1), open=-100)]
    monkeypatch.setattr(_runner, "load_bars", lambda *a, **kw: (bars, None))
    monkeypatch.setattr(_runner, "load_dividends", lambda *a, **kw: [])

    def fingerprint(selected: list[SimpleNamespace], **kwargs: object) -> str:
        assert selected == bars[:1]
        return "modified source"

    monkeypatch.setattr(_runner, "source_fingerprint", fingerprint)
    with pytest.raises(SpineError, match="no longer reproduces"):
        inputs.load_run(tmp_path, inputs.resolve(tmp_path, RUN))


def test_discovery_set_and_cached_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    from alpha_cli.tool_cmds import tool_app
    from alpha_cli.toolbox.sets import SETS

    series = _series(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    cli = CliRunner()
    listed = cli.invoke(
        tool_app,
        [
            "list",
            "--for",
            RUN,
            "--search",
            "benchmark",
            "--family",
            "market",
            "--kind",
            "diagnostic",
            "--json",
        ],
    )
    assert json.loads(listed.stdout)[0]["id"] == "market.attribution"
    card = cli.invoke(tool_app, ["describe", "market.vol_regimes", "--json"])
    assert json.loads(card.stdout)["params"][1]["allowed"] == [2, 3, 4]
    docs = json.loads(cli.invoke(tool_app, ["run-set", "market-context", RUN, "--json"]).stdout)
    assert tuple(d["tool"] for d in docs) == SETS["market-context"]
    assert all("ad-hoc" not in d["labels"] for d in docs)
    assert [
        r["outcome"] for r in json.loads(cli.invoke(tool_app, ["history", RUN, "--json"]).stdout)
    ] == ["attempted", "ok"] * 3

    def unexpected_replay(home: Path, run_id: str) -> inputs.RunSeries:
        pytest.fail("cache hit replayed the run")

    monkeypatch.setattr(inputs, "load_run", unexpected_replay)
    assert run(tmp_path, "market.attribution", RUN)["file"] == docs[0]["file"]
    assert len(read_trials(tmp_path)) == 6


def test_legacy_facts_and_ledger_family(tmp_path: Path) -> None:
    import json

    from alpha_cli.spine.facts import tool_fact
    from alpha_cli.spine.trial_record import map_row

    folder = tmp_path / "diagnostics" / RUN
    folder.mkdir(parents=True)
    file = folder / "attribution-12345678.json"
    old = {
        "metric": "market_beta",
        "value": 0.5,
        "source": f"{file}:result.beta",
        "run_id": RUN,
        "basis": "stored benchmark",
        "labels": [],
        "reason": None,
    }
    file.write_text(
        json.dumps(
            {
                "tool": "attribution",
                "run_id": RUN,
                "params": {},
                "recorded_at": "2020-01-01",
                "labels": [],
                "facts": [old],
            }
        )
    )
    assert tool_fact(tmp_path, RUN, "market_beta", None) == old
    assert tool_fact(tmp_path, RUN, "market.attribution.beta", "12345678") == {
        **old,
        "metric": "market.attribution.beta",
    }
    for name in ("attribution", "market.attribution"):
        row = {
            "schema": "AlphaTrialV1",
            "trial_index": 1,
            "kind": f"tool:{name}",
            "labels": [],
            "recorded_at": "2020-01-01",
        }
        record = map_row("spine", tmp_path, 1, row)
        assert record.family_id == "spine-tool:attribution"
        assert record.counts_for_deflation is False


def test_checker_requires_current_settings_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from alpha_cli.results_cmds import fact_lookup
    from alpha_cli.spine.check import check_text
    from alpha_cli.spine.facts import tool_fact

    series = _series(tmp_path)
    series = replace(series, positions=(True,) * len(series.dates))
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    (tmp_path / "runs" / RUN / "diagnostics.json").write_text(
        json.dumps({"trials": {"total_trials": 8}})
    )
    doc = run(tmp_path, "market.changepoints", RUN, ["on=equity"])
    run(tmp_path, "market.changepoints", RUN)
    output_id = Path(doc["file"]).stem.rsplit("-", 1)[1]
    metric = "market.changepoints.count"
    fact = tool_fact(tmp_path, RUN, metric, output_id)
    assert fact["settings_count"] == 2
    quote = f"Quick look. {fact['value']} [{RUN}:{metric}@{output_id}]"
    trials = f"\n8 [{RUN}:total_trials]"
    lookup = fact_lookup(tmp_path)
    for note in ("", " (1 of 1 settings tried)"):
        assert "SETTINGS_OMITTED" in [
            p["kind"] for p in check_text(quote + note + trials, lookup)["problems"]
        ]
    checked = check_text(quote + " (1 of 2 settings tried)" + trials, lookup)
    assert checked["ok"], checked


def test_concurrent_identical_requests_and_changed_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from concurrent.futures import ThreadPoolExecutor

    series = _series(tmp_path)
    calls = []

    def replay(home: Path, target: inputs.Target) -> inputs.RunSeries:
        calls.append(target.run_id)
        assert read_trials(home)[-1]["outcome"] == "attempted"
        return series

    monkeypatch.setattr(inputs, "load_run", replay)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run, tmp_path, "market.attribution", RUN) for _ in range(2)]
        first, cached = [job.result() for job in jobs]
    assert calls == [RUN] and first == cached
    manifest = tmp_path / "runs" / RUN / "manifest.json"
    manifest.write_text(json.dumps({**series.manifest, "source_fingerprint": "changed"}))
    new = run(tmp_path, "market.attribution", RUN)
    assert new["file"] != first["file"]
    assert calls == [RUN, RUN]


def test_search_by_full_registry_id() -> None:
    import json

    from typer.testing import CliRunner

    from alpha_cli.tool_cmds import tool_app

    result = CliRunner().invoke(tool_app, ["list", "--search", "market.vol_regimes", "--json"])
    assert json.loads(result.stdout)[0]["id"] == "market.vol_regimes"


def test_interrupted_publication_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from alpha_cli.spine.facts import tool_outputs
    from alpha_cli.toolbox import runner

    series = _series(tmp_path)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)

    def interrupted(home: Path, row: dict[str, Any]) -> dict[str, Any]:
        if row["outcome"] == "ok":
            raise OSError("interrupted outcome append")
        return append_trial(home, row)

    monkeypatch.setattr(runner, "append_trial", interrupted)
    with pytest.raises(SpineError, match="interrupted"):
        run(tmp_path, "market.attribution", RUN)
    assert [r["outcome"] for r in read_trials(tmp_path)] == ["attempted", "error"]
    assert tool_outputs(tmp_path, RUN) == []
    monkeypatch.setattr(runner, "append_trial", append_trial)
    result = run(tmp_path, "market.attribution", RUN)
    assert [o["file"] for o in tool_outputs(tmp_path, RUN)] == [result["file"]]
    assert [r["outcome"] for r in read_trials(tmp_path)] == [
        "attempted",
        "error",
        "attempted",
        "ok",
    ]


def test_kind_and_look_are_on_every_attempt_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = _series(tmp_path)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    run(tmp_path, "market.changepoints", RUN)
    with pytest.raises(SpineError):
        run(tmp_path, "market.nowhere", RUN)
    rows = read_trials(tmp_path)
    assert [(r["outcome"], r.get("tool_kind"), r.get("look")) for r in rows[:2]] == [
        ("attempted", "diagnostic", "describe"),
        ("ok", "diagnostic", "describe"),
    ]
    # An unknown id still leaves a trace, with its error code.
    assert [(r["kind"], r["outcome"], r.get("error_code")) for r in rows[2:]] == [
        ("tool:market.nowhere", "attempted", None),
        ("tool:market.nowhere", "error", "UNKNOWN_TOOL"),
    ]
    assert all(r["verdict"] is None for r in rows)


def test_a_reseeded_entry_is_labelled_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = _series(tmp_path)
    monkeypatch.setattr(inputs, "load_run", lambda home, run_id: series)
    default = run(tmp_path, "market.vol_regimes", RUN)
    assert "non-default-params" not in default["labels"]
    reseeded = run(tmp_path, "market.vol_regimes", RUN, seed=7)
    assert "non-default-params" in reseeded["labels"]
    assert reseeded["settings_tried"] == [
        {"market": None, "k": 2, "seed": 0},
        {"market": None, "k": 2, "seed": 7},
    ]
