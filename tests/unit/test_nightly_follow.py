"""Nightly N4 (follow update), the third anchor, N0 (refresh followed bars), readiness."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import follow_cmds
from alpha_cli.main import app
from alpha_cli.nightly_refresh import pull_tail
from alpha_cli.nightly_run import run_nightly
from alpha_cli.nightly_status import read_records, readiness, status_facts, status_text
from alpha_cli.nightly_steps import Outcome
from alpha_data.store import ParquetStore
from tests.fixtures.follow_fixtures import BUY_AND_SELL, World
from tests.unit.test_nightly import FakeRunner, config, ok, states

CLI = CliRunner()
FOLLOW = "f" * 12
ROW = {"follow_id": FOLLOW, "state": "active", "assets": ["SPY"], "kind": "rule_test"}
HEAD = "a" * 64


def _today(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"as_of": "x", "groups": [], "rows": list(rows), "behind": 0}


def _n4(tmp_path: Path, **replies: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "follow list": ok({"follows": [ROW]}),
        "follow update": ok({"follows": [{"follow_id": FOLLOW, "status": "no-op"}]}),
        "follow today": ok(_today({"follow_id": FOLLOW, "group": "nothing_today"})),
        "follow verify": ok({"follow_id": FOLLOW, "ok": True, "entries": 3, "head": HEAD}),
    }
    runner = FakeRunner({**base, **replies})
    return run_nightly(config(tmp_path), tmp_path / "home", runner, only=("N4",))


def test_a_clean_follow_night_passes_and_a_would_sell_is_not_a_defect(tmp_path: Path) -> None:
    sell = {"follow_id": FOLLOW, "group": "new_signal", "decision": "would sell at the next open"}
    record = _n4(tmp_path, **{"follow today": ok(_today(sell))})
    assert record["blocking"] == 0 and record["minor"] == 0
    assert record["paths_run"] == ["N4"] and record["follows"] == 1
    assert record["follow_heads"] == {FOLLOW: {"entries": 3, "head": HEAD}}


@pytest.mark.parametrize(
    ("replies", "step", "state"),
    [
        ({"follow update": Outcome(1, "{}", "boom", 0.1, False)}, "N4.update", "defect-blocking"),
        ({"follow update": Outcome(None, "", "", 9.0, True)}, "N4.update", "defect-blocking"),
        ({"follow today": Outcome(0, "not json", "", 0.1, False)}, "N4.today", "defect-blocking"),
        ({"follow today": ok({"as_of": "x"})}, "N4.today", "defect-blocking"),
        (
            {
                "follow verify": Outcome(
                    1,
                    json.dumps(
                        {
                            "ok": False,
                            "entries": 3,
                            "head": HEAD,
                            "first_break": {"seq": 2, "reason": "x"},
                        }
                    ),
                    "",
                    0.1,
                    False,
                )
            },
            f"N4.verify.{FOLLOW}",
            "defect-blocking",
        ),
        (
            {"follow today": ok(_today({"follow_id": FOLLOW, "group": "late_or_missed"}))},
            "N4.today",
            "defect-minor",
        ),
        (
            {
                "follow update": ok(
                    {
                        "follows": [
                            {
                                "follow_id": FOLLOW,
                                "status": "written",
                                "replay": {"agrees": False, "differences": []},
                            }
                        ]
                    }
                )
            },
            "N4.update",
            "defect-minor",
        ),
    ],
)
def test_classification_table(
    tmp_path: Path, replies: dict[str, Any], step: str, state: str
) -> None:
    record = _n4(tmp_path, **replies)
    assert states(record)[step] == state
    assert record["blocking"] == (state == "defect-blocking")


def test_nothing_followed_is_not_run_and_is_not_counted(tmp_path: Path) -> None:
    record = _n4(tmp_path, **{"follow list": ok({"follows": [{**ROW, "state": "stopped"}]})})
    assert states(record) == {"N4.list": "not-run"}
    assert record["steps"][0]["note"] == "not run: nothing is followed"
    assert record["paths_run"] == [] and record["follows"] == 0


def test_update_is_the_real_command_with_all_and_json(tmp_path: Path) -> None:
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [ROW]}),
            "follow update": ok({"follows": []}),
            "follow today": ok(_today()),
            "follow verify": ok({"ok": True, "entries": 1, "head": HEAD}),
        }
    )
    run_nightly(config(tmp_path), tmp_path / "home", runner, only=("N4",))
    assert ["follow", "update", "--all", "--json"] in runner.calls
    assert ["follow", "today", "--json"] in runner.calls
    assert ["follow", "verify", FOLLOW, "--json"] in runner.calls


# ---- the third anchor, end to end through the real commands ---------------------------------


def _bridge(home: Path) -> Any:
    def run(argv: Any, timeout: float) -> Outcome:
        result = CLI.invoke(app, list(argv)[3:], env={"ALPHA_DATA_DIR": str(home)})
        return Outcome(result.exit_code, result.stdout, "", 0.0, False)

    return run


def _rewrite_history(home: Path, follow: str) -> None:
    """Change entry 2 and recompute every later hash and the stored head: `verify` still passes."""
    from alpha_cli.follow_journal import entry_hash_of

    folder = home / "forward" / follow
    lines = [json.loads(x) for x in (folder / "journal.jsonl").read_text().splitlines()]
    lines[1]["payload"]["decision"]["words"] = "rewritten"
    prev = lines[0]["entry_hash"]
    for entry in lines[1:]:
        entry["prev_hash"] = prev
        entry["entry_hash"] = prev = entry_hash_of(entry)
    (folder / "journal.jsonl").write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in lines)
    )
    (folder / "head.json").write_text(json.dumps({"entries": len(lines), "head": prev}))


def test_a_rewritten_journal_and_head_break_the_third_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(tmp_path / "home", -0.2, BUY_AND_SELL)
    follow = world.start()
    now = [world.close_of(0)]
    monkeypatch.setattr(follow_cmds, "CLOCK", lambda: now[0])
    cfg = config(tmp_path)
    for k, day in enumerate((date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 23))):
        world.grow()
        now[0] = world.close_of(k)
        record = run_nightly(
            cfg, tmp_path / "home", _bridge(tmp_path / "home"), only=("N4",), today=day
        )
        assert record["blocking"] == 0, record["defects"]
        assert record["follow_heads"][follow]["entries"] == k + 2
    _rewrite_history(tmp_path / "home", follow)
    verified = CLI.invoke(
        app, ["follow", "verify", follow], env={"ALPHA_DATA_DIR": str(tmp_path / "home")}
    )
    assert verified.exit_code == 0  # the chain and the head agree: only the third anchor sees it
    world.grow()
    now[0] = world.close_of(3)
    record = run_nightly(
        cfg, tmp_path / "home", _bridge(tmp_path / "home"), only=("N4",), today=date(2026, 11, 24)
    )
    assert states(record)[f"N4.verify.{follow}"] == "defect-blocking"
    assert "journal history changed since the last nightly record" in record["defects"][0]["text"]
    assert record["follow_heads"][follow]["entries"] == 4  # the old anchor is carried forward


# ---- N0: refresh the stored bars of followed assets only -----------------------------------


def _store(home: Path, symbols: list[str], source: str = "yfinance") -> None:
    rows = [
        {
            "ts": datetime(2026, 11, d, tzinfo=UTC),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
        for d in (2, 3, 4)
    ]
    bars = ParquetStore(home / "store")
    for symbol in symbols:
        bars.write_bars(symbol, pl.DataFrame(rows))
        bars.write_provenance(symbol, source=source, adapter_version="1", parser_version="1")


def _pull_adds_a_bar(home: Path, symbol: str) -> Callable[[list[str]], Outcome]:
    def reply(tail: list[str]) -> Outcome:
        _grow(home, symbol)
        return pull_result(added=1)

    return reply


def _grow(home: Path, symbol: str) -> None:
    bars = ParquetStore(home / "store")
    frame = bars.read_bars(symbol)
    extra = frame.tail(1).with_columns(pl.col("ts") + pl.duration(days=1))
    bars.write_bars(symbol, pl.concat([frame, extra]))


def pull_result(
    added: int = 0,
    revised: int = 0,
    dropped: int = 0,
    snapshot: str | None = "pull-20261120T030000-AAA",
) -> Outcome:
    """The JSON `alpha data pull --json` prints: counts and dates only."""
    body = {
        "snapshot": None if snapshot is None else {"id": snapshot, "reused": False},
        "bars_added": {"count": added, "first": None, "last": None},
        "bars_removed": {"count": dropped},
        "bars_revised": {
            "count": revised,
            "first_date": "2026-11-03" if revised else None,
            "columns": ["close"] if revised else [],
        },
    }
    return Outcome(0, json.dumps(body), "", 1, False)


def _refresh(tmp_path: Path, runner: FakeRunner) -> dict[str, Any]:
    cfg = config(tmp_path, refresh_followed=True)
    return run_nightly(cfg, tmp_path / "home", runner, only=("N0",), today=date(2026, 11, 20))


def _pulls(runner: FakeRunner) -> list[list[str]]:
    return [c for c in runner.calls if c[:2] == ["data", "pull"]]


def test_only_followed_assets_are_pulled_and_a_new_bar_is_computed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["AAA", "BBB", "CCC", "DDD", "EEE"])
    follows = {
        "follows": [{**ROW, "assets": ["CCC"]}, {**ROW, "state": "stopped", "assets": ["AAA"]}]
    }
    runner = FakeRunner(
        {
            "follow list": ok(follows),
            "data pull": _pull_adds_a_bar(home, "CCC"),
        }
    )
    record = _refresh(tmp_path, runner)
    assert _pulls(runner) == [
        [
            "data",
            "pull",
            "CCC",
            "--source",
            "yfinance",
            "--start",
            "2026-11-02",
            "--end",
            "2026-11-20",
            "--json",
        ]
    ]
    step = next(s for s in record["steps"] if s["id"] == "N0.pull.CCC")
    assert step["state"] == "pass" and step["evidence"] == "computed"
    assert record["blocking"] == 0


def test_no_new_bar_is_reused_and_unreadable_evidence_is_unknown(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": pull_result(),
        }
    )
    step = next(s for s in _refresh(tmp_path, runner)["steps"] if s["id"] == "N0.pull.CCC")
    assert step["evidence"] == "reused" and step["note"] == "no new bar"


def test_a_failed_pull_is_a_minor_defect_and_n4_then_says_late(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    late = {"follow_id": FOLLOW, "group": "late_or_missed", "entry_kind": "late"}
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": Outcome(2, "", "Error: no key token=abc123 set", 1, False),
            "follow update": ok({"follows": []}),
            "follow today": ok(_today(late)),
            "follow verify": ok({"ok": True, "entries": 2, "head": HEAD}),
        }
    )
    cfg = config(tmp_path, refresh_followed=True)
    record = run_nightly(cfg, home, runner, only=("N0", "N4"), today=date(2026, 11, 20))
    assert states(record)["N0.pull.CCC"] == "defect-minor"
    text = next(d["text"] for d in record["defects"] if d["step"] == "N0.pull.CCC")
    assert text.startswith("no fresh bars for CCC: exit code 2") and "abc123" not in text
    assert states(record)["N4.today"] == "defect-minor" and record["blocking"] == 0


def test_refresh_is_off_by_default_and_each_store_kind_has_its_pull_form() -> None:
    first, end = date(2015, 1, 2), date(2026, 11, 20)
    assert pull_tail("BTC/USD", {"source": "ccxt:coinbase"}, first, end) == [
        "data",
        "pull",
        "BTC/USD",
        "--source",
        "ccxt",
        "--exchange",
        "coinbase",
        "--start",
        "2015-01-02",
        "--end",
        "2026-11-20",
    ]
    dataset = {
        "provider": "tiingo",
        "asset_class": "etf",
        "venue": "US",
        "calendar": "XNYS",
        "currency": "USD",
    }
    assert pull_tail("SPY", {"dataset": dataset}, first, end) == [
        "data",
        "pull",
        "SPY",
        "--source",
        "tiingo",
        "--asset-class",
        "etf",
        "--venue",
        "US",
        "--calendar",
        "XNYS",
        "--currency",
        "USD",
        "--start",
        "2015-01-02",
        "--end",
        "2026-11-19",
    ]
    assert config(Path("/dev/shm/ft/x")).refresh_followed is False


# ---- the readiness rule with and without follows --------------------------------------------


def _write(home: Path, name: str, **more: Any) -> None:
    steps = [
        {"id": "N1.test", "scenario": "N1", "state": "pass", "evidence": "computed"},
        {"id": "N2.find", "scenario": "N2", "state": "pass", "evidence": "computed"},
    ]
    body = {
        "date": name[:10],
        "run_number": 1,
        "full": True,
        "blocking": 0,
        "minor": 0,
        "scenarios": ["N1", "N2", "N3", "N4"],
        "paths_run": ["N1", "N2", "N3"],
        "summary_line": "x",
        "steps": steps,
        "defects": [],
        "follows": 0,
        **more,
    }
    folder = home / "nightly" / f"{name}-1"
    folder.mkdir(parents=True)
    (folder / "record.json").write_text(json.dumps(body))


def test_n4_is_required_only_when_follows_exist(tmp_path: Path) -> None:
    _write(tmp_path, "2026-11-18")
    _write(tmp_path, "2026-11-19")
    assert readiness(read_records(tmp_path))["ready"] is True  # nothing followed: N4 not needed
    _write(tmp_path, "2026-11-20", follows=2)  # two follows, but N4 never ran
    verdict = readiness(read_records(tmp_path))
    assert verdict["missing"] == ["c"] and "follow update (N4)" in verdict["reasons"][0]
    _write(tmp_path, "2026-11-21", follows=2, paths_run=["N1", "N2", "N3", "N4"])
    _write(tmp_path, "2026-11-22", follows=2, paths_run=["N1", "N2", "N3", "N4"])
    assert readiness(read_records(tmp_path))["ready"] is True


def test_a_run_without_n4_selected_is_partial_and_status_gives_the_timing_rule(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "2026-11-18")
    _write(tmp_path, "2026-11-19")
    _write(tmp_path, "2026-11-20", scenarios=["N1", "N2", "N3"])
    assert readiness(read_records(tmp_path))["ready"] is True
    out = status_text(status_facts(tmp_path, Path("nightly.toml")))
    assert "after the exchange close" in out and "before the next open" in out
    assert "may be wrong for your timezone" in out and "N4" in out


def _truncate_history(home: Path, follow: str, keep: int) -> None:
    """Cut the journal below an earlier count and make the stored head agree with the cut."""
    folder = home / "forward" / follow
    lines = [json.loads(x) for x in (folder / "journal.jsonl").read_text().splitlines()][:keep]
    (folder / "journal.jsonl").write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in lines)
    )
    (folder / "head.json").write_text(
        json.dumps({"entries": keep, "head": lines[-1]["entry_hash"]})
    )


def test_first_night_has_no_alarm_growth_is_quiet_and_a_cut_below_the_old_count_alarms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    world = World(home, -0.2, BUY_AND_SELL)
    follow = world.start()
    now = [world.close_of(0)]
    monkeypatch.setattr(follow_cmds, "CLOCK", lambda: now[0])
    cfg = config(tmp_path)
    days = (date(2026, 11, 19), date(2026, 11, 20), date(2026, 11, 23))
    for k, day in enumerate(days):
        world.grow()
        now[0] = world.close_of(k)
        record = run_nightly(cfg, home, _bridge(home), only=("N4",), today=day)
        step = next(s for s in record["steps"] if s["id"] == f"N4.verify.{follow}")
        assert record["blocking"] == 0 and step["state"] == "pass"
        assert ("no earlier anchor" in str(step["note"])) is (k == 0)
    _truncate_history(home, follow, keep=2)
    plain = CLI.invoke(app, ["follow", "verify", follow], env={"ALPHA_DATA_DIR": str(home)})
    assert plain.exit_code == 0  # a shorter chain with its own head is self-consistent
    world.grow()
    now[0] = world.close_of(3)
    record = run_nightly(cfg, home, _bridge(home), only=("N4",), today=date(2026, 11, 24))
    assert states(record)[f"N4.verify.{follow}"] == "defect-blocking"
    assert record["follow_heads"][follow]["entries"] == 4  # the old anchor stays


def test_the_secret_in_stderr_never_reaches_the_record(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    stderr = (
        "failed apikey=XYZ; key=XYZ; Authorization: Bearer XYZ; Authorization: Token XYZ; "
        'api_key": "XYZ"; url?token=XYZ&x=1; secret: XYZ'
    )
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": Outcome(2, "", stderr, 1, False),
        }
    )
    record = _refresh(tmp_path, runner)
    assert "XYZ" not in json.dumps(record) and "[removed]" in json.dumps(record)


def test_a_provider_that_revises_old_bars_is_a_minor_defect_with_the_first_date(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": pull_result(revised=2, snapshot="pull-20261120T030000-CCC"),
        }
    )
    record = _refresh(tmp_path, runner)
    assert states(record)["N0.pull.CCC"] == "defect-minor" and record["blocking"] == 0
    text = next(d["text"] for d in record["defects"] if d["step"] == "N0.pull.CCC")
    assert text.startswith(
        "the provider revised history for CCC: first changed bar 2026-11-03 (close)"
    )
    assert "snapshot pull-20261120T030000-CCC" in text and "alpha data snapshots" in text
    quiet = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": pull_result(),
        }
    )
    assert states(_refresh(tmp_path, quiet))["N0.pull.CCC"] == "pass"


def test_dropped_old_bars_are_a_minor_defect_naming_the_snapshot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": pull_result(dropped=2),
        }
    )
    record = _refresh(tmp_path, runner)
    text = next(d["text"] for d in record["defects"] if d["step"] == "N0.pull.CCC")
    assert "2 earlier bars are gone" in text and "snapshot pull-" in text


# ---- the pull itself freezes; N0 only reads what it says ------------------------------------


def test_n0_runs_only_the_pull_and_records_the_snapshot_the_pull_names(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["AAA", "BBB"])
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["AAA", "BBB"]}]}),
            "data pull": pull_result(),
        }
    )
    record = _refresh(tmp_path, runner)
    assert [c[1] for c in runner.calls if c[0] == "data"] == ["pull", "pull"]  # no snapshot child
    for asset in ("AAA", "BBB"):
        pull = next(s for s in record["steps"] if s["id"] == f"N0.pull.{asset}")
        assert pull["state"] == "pass" and pull["ids"] == {"snapshot": "pull-20261120T030000-AAA"}
    assert not [s for s in record["steps"] if s["id"].startswith("N0.freeze.")]


def test_a_freeze_that_fails_is_blocking_for_that_asset_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["AAA", "BBB"])

    def pull(tail: list[str]) -> Outcome:
        if tail[2] == "AAA":
            return Outcome(3, "", "cannot replace the stored AAA: token=abc123", 1, False)
        return pull_result()

    runner = FakeRunner(
        {"follow list": ok({"follows": [{**ROW, "assets": ["AAA", "BBB"]}]}), "data pull": pull}
    )
    record = _refresh(tmp_path, runner)
    assert states(record)["N0.pull.AAA"] == "defect-blocking"
    text = next(d["text"] for d in record["defects"] if d["step"] == "N0.pull.AAA")
    assert text.startswith("could not freeze AAA before the refresh") and "abc123" not in text
    assert states(record)["N0.pull.BBB"] == "pass" and record["blocking"] == 1


def test_a_pull_result_that_cannot_be_read_is_a_minor_defect(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _store(home, ["CCC"])
    runner = FakeRunner(
        {
            "follow list": ok({"follows": [{**ROW, "assets": ["CCC"]}]}),
            "data pull": Outcome(0, "pulled", "", 1, False),
        }
    )
    record = _refresh(tmp_path, runner)
    assert states(record)["N0.pull.CCC"] == "defect-minor"
