"""Setup finding records matches without looking at outcomes."""

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import setup_cmds as find
from alpha_cli.spine.errors import SpineError, setup_error
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.setup_find import cluster_candidates
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def seed(home: Path, symbol: str = "SPY", n: int = 100) -> ParquetStore:
    seed_store(home, symbol=symbol, n=n)
    store = ParquetStore(home / "store")
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
    return store


def spec_file(home: Path, assets: tuple[str, ...] = ("SPY",), *, worked: bool = False) -> Path:
    path = home / "spec.toml"
    path.write_text(
        '[setup]\nname="Synthetic"\nidea="Inspect matches"\ntimeframe="1D"\n'
        f'assets={json.dumps(assets)}\nevent="volume == 1"\n'
        + (
            '[filters]\nuptrend="close > open"\n[trigger]\nwhen="high > 105"\nwithin=3\n'
            if worked
            else ""
        )
        + '[reference]\nbase="low"\n'
    )
    return path


def worked_store(home: Path, symbol: str = "SPY") -> pl.DataFrame:
    store = seed(home, symbol)
    frame = store.read_bars(symbol)
    events = [10, 14, 18, 29, 40, 44, 48, 60, 70, 99]
    frame = frame.with_columns(
        pl.Series("open", [100.0] * 100),
        pl.Series("high", [106.0 if i in [11, 14, 18, 29] else 102.0 for i in range(100)]),
        pl.Series("low", [98.0] * 100),
        pl.Series("close", [99.0 if i in [40, 44, 48] else 101.0 for i in range(100)]),
        pl.Series("volume", [1.0 if i in events else 0.0 for i in range(100)]),
    )
    store.write_bars(symbol, frame)
    return frame


def test_worked_counts_ledger_and_cluster_sheets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worked_store(tmp_path)
    panels: list[Any] = []

    def record(rows: list[Any], **kw: Any) -> bytes:
        panels.extend(rows)
        return b"png"

    monkeypatch.setattr(find, "draw_sheet", record)
    result = find.run_find(spec_file(tmp_path, worked=True), home=tmp_path)
    assert result["totals"] == dict(
        events=10,
        accepted=4,
        pending=1,
        rejected=5,
        rejected_by_reason={"uptrend": 3, "no-trigger": 2},
        clusters=5,
        accepted_clusters=2,
    )
    assert len([p for p in panels if p.mode == "accepted"]) == 2
    assert any("(+2 more days)" in p.title for p in panels)
    folder = Path(result["folder"])
    candidates = pl.read_parquet(folder / "candidates.parquet")
    assert candidates["cluster_id"].to_list() == [1, 1, 1, 2, 3, 3, 3, 4, 4, 5]
    assert candidates["cluster_first"].to_list() == [True, False, False, True] + [False] * 6
    assert candidates["resolved_symbol"].unique().to_list() == ["SPY"]
    facts = {f["metric"]: f["value"] for f in result["facts"]}
    assert facts == {
        f"setup_{key}": result["totals"][key]
        for key in ("events", "accepted", "pending", "rejected", "clusters", "accepted_clusters")
    }
    assert all(f["source"].startswith("summary.json:totals.") for f in result["facts"])
    assert {"pending-at-end", "short-history", "outcomes-not-viewed"} <= set(result["labels"])
    ledger = read_trials(tmp_path)[0]
    assert {
        k: ledger[k]
        for k in (
            "kind",
            "run_id",
            "accepted",
            "pending",
            "rejected",
            "accepted_clusters",
            "verdict",
        )
    } == dict(
        kind="setup_find",
        run_id=None,
        accepted=4,
        pending=1,
        rejected=5,
        accepted_clusters=2,
        verdict=None,
    )
    assert ledger["assets"] == ["SPY"] and ledger["find_id"] == result["find_id"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["schema"] == "AlphaSetupFindV1"
    assert manifest["assets"][0]["source_fingerprint"]
    assert manifest["assets"][0]["last_bar"]


def test_repeat_immutable_and_asset_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for symbol in ("SPY", "QQQ"):
        worked_store(tmp_path, symbol)
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    spec = spec_file(tmp_path, ("SPY", "QQQ"), worked=True)
    first = find.run_find(spec, home=tmp_path)
    folder = Path(first["folder"])
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in folder.rglob("*") if p.is_file()}
    again = find.run_find(spec, home=tmp_path, context_bars=5, max_sheets=1)
    assert first["find_id"] == again["find_id"] and "repeat" in again["labels"]
    assert again["trials_total"] == 2
    assert again["context_bars"] == 30  # the sheets on disk, not the ignored request
    assert "nothing was redrawn (its sheets show 30 bars" in find._text(again)
    assert before == {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in before}
    subset = find.run_find(spec, home=tmp_path, assets=["SPY"])
    assert subset["find_id"] != first["find_id"]
    assert [a["asset"] for a in first["assets"]] == ["SPY", "QQQ"]


def test_manifest_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worked_store(tmp_path)

    def broken(*a: Any, **k: Any) -> bytes:
        raise OSError("sheet failed")

    monkeypatch.setattr(find, "draw_sheet", broken)
    with pytest.raises(OSError, match="sheet failed"):
        find.run_find(spec_file(tmp_path, worked=True), home=tmp_path)
    assert not list((tmp_path / "setups").rglob("manifest.json"))
    assert read_trials(tmp_path) == []


def test_partial_failure_and_all_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worked_store(tmp_path)
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    spec = spec_file(tmp_path, ("MISSING", "SPY"), worked=True)
    out = find.run_find(spec, home=tmp_path)
    assert out["assets"][0]["error"]["code"] == "UNKNOWN_ASSET"
    assert out["assets"][1]["error"] is None
    with pytest.raises(SpineError) as caught:
        find.run_find(spec, home=tmp_path, assets=["MISSING"])
    assert caught.value.payload["code"] == "FIND_FAILED"
    assert "MISSING" in str(caught.value)


@pytest.mark.parametrize("text", ["bad", '[setup]\nname="bad"'])
def test_invalid_spec(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(text)
    with pytest.raises(SpineError) as caught:
        find.run_find(path, home=tmp_path)
    assert caught.value.payload["code"] == "SPEC_INVALID"


def test_asset_filter_error(tmp_path: Path) -> None:
    with pytest.raises(SpineError) as caught:
        find.run_find(spec_file(tmp_path), home=tmp_path, assets=["QQQ"])
    assert caught.value.payload["code"] == "ASSET_NOT_IN_SPEC"
    assert caught.value.payload["known"] == ["SPY"]


@pytest.mark.parametrize("n,step,code", [(10, 1, "FIND_FAILED"), (100, 7, "NOT_DAILY_BARS")])
def test_bad_frequency_keeps_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n: int, step: int, code: str
) -> None:
    from datetime import timedelta

    worked_store(tmp_path)
    store = seed(tmp_path, "BAD", n=n)
    frame = store.read_bars("BAD")
    frame = frame.with_columns(
        pl.Series("ts", [frame["ts"][0] + timedelta(days=i * step) for i in range(n)])
    )
    store.write_bars("BAD", frame)
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    out = find.run_find(spec_file(tmp_path, ("SPY", "BAD")), home=tmp_path)
    assert out["assets"][1]["error"]["code"] == code


def test_error_mapper() -> None:
    error = SpineError("NOT_DAILY_BARS", "bad", "fix")
    assert setup_error(error, ["home"]) is error
    assert setup_error(ValueError("unknown store x"), ["home"]).payload["known"] == ["home"]
    assert setup_error(OSError("disk"), []).payload["code"] == "FIND_FAILED"


def test_cluster_ids_from_event_positions(tmp_path: Path) -> None:
    from alpha_cli.spine.setup_find import CLUSTER_GAP_BARS
    from alpha_study.setup.evaluate import find_candidates
    from alpha_study.setup.spec import SetupSpec

    frame = worked_store(tmp_path)
    spec = SetupSpec.load(spec_file(tmp_path, worked=True))
    clustered = cluster_candidates(frame, find_candidates(spec, frame, symbol="SPY"))
    # Events 10, 14, 18 are four bars apart (one cluster); 29 is eleven bars after 18.
    assert clustered["cluster_id"].head(4).to_list() == [1, 1, 1, 2]
    assert CLUSTER_GAP_BARS == 10
    rows = pl.DataFrame(
        {
            "event_ts": [frame["ts"][i] for i in (0, 10, 21)],
            "status": ["rejected", "accepted", "accepted"],
        }
    )
    # Exactly ten bars after the previous event joins; eleven starts a new cluster.
    edge = cluster_candidates(frame, rows)
    assert edge["cluster_id"].to_list() == [1, 1, 2]
    # The first ACCEPTED candidate leads its cluster, not a rejected earlier one.
    assert edge["cluster_first"].to_list() == [False, True, True]


def _poison_after(frame: pl.DataFrame, cut: int) -> pl.DataFrame:
    """Extreme but valid bars after ``cut``; the bar after it keeps only its open."""
    index = pl.int_range(0, frame.height)
    return frame.with_columns(
        pl.when(index > cut).then(5000.0).otherwise(pl.col("high")).alias("high"),
        pl.when(index > cut).then(1.0).otherwise(pl.col("low")).alias("low"),
        pl.when(index > cut).then(3000.0).otherwise(pl.col("close")).alias("close"),
        pl.when(index > cut + 1).then(2000.0).otherwise(pl.col("open")).alias("open"),
        pl.when(index > cut).then(0.5).otherwise(pl.col("volume")).alias("volume"),
    )


@pytest.mark.parametrize("cut", [12, 20, 31, 45, 65, 80, 98])
def test_cluster_membership_never_depends_on_later_bars(tmp_path: Path, cut: int) -> None:
    from alpha_study.setup.evaluate import find_candidates
    from alpha_study.setup.spec import SetupSpec

    frame = worked_store(tmp_path)
    spec = SetupSpec.load(spec_file(tmp_path, worked=True))

    def clustered(bars: pl.DataFrame) -> pl.DataFrame:
        result: pl.DataFrame = cluster_candidates(bars, find_candidates(spec, bars, symbol="SPY"))
        return result

    full = clustered(frame)
    for later in (clustered(frame.head(cut + 1)), clustered(_poison_after(frame, cut))):
        known = later.filter(pl.col("event_ts") <= frame["ts"][cut])
        joined = known.join(full, on="event_ts", suffix="_full")
        assert joined.height == known.height > 0
        assert joined["cluster_id"].to_list() == joined["cluster_id_full"].to_list()
        settled = joined.filter(pl.col("status") == "accepted")
        assert settled["cluster_first"].to_list() == settled["cluster_first_full"].to_list()


def _blind_store(home: Path, poison: bool) -> None:
    """Five events; the last accepted one triggers at bar 29 and enters at bar 30's open."""
    store = seed(home)
    frame = store.read_bars("SPY")
    events = [3, 10, 14, 18, 29]
    frame = frame.with_columns(
        pl.Series("open", [100.0] * 100),
        pl.Series("high", [106.0 if i in [11, 14, 18, 29] else 102.0 for i in range(100)]),
        pl.Series("low", [98.0] * 100),
        pl.Series("close", [99.0 if i == 3 else 101.0 for i in range(100)]),
        pl.Series("volume", [1.0 if i in events else 0.0 for i in range(100)]),
    )
    store.write_bars("SPY", _poison_after(frame, 29) if poison else frame)


def _without_identity(document: Any) -> Any:
    if isinstance(document, dict):
        return {
            k: _without_identity(v)
            for k, v in document.items()
            if k not in {"find_id", "run_id", "source_fingerprint", "recorded_at", "folder"}
        }
    if isinstance(document, list):
        return [_without_identity(v) for v in document]
    return document


def test_nothing_after_the_trigger_reaches_any_file_or_sheet(tmp_path: Path) -> None:
    outputs, folders = [], []
    for poison in (False, True):
        home = tmp_path / f"poison-{poison}"
        home.mkdir()
        _blind_store(home, poison)
        outputs.append(find.run_find(spec_file(home, worked=True), home=home))
        folders.append(Path(outputs[-1]["folder"]))
    clean, poisoned = folders
    bars = [ParquetStore(f.parents[1] / "store").read_bars("SPY") for f in folders]
    assert not bars[0].equals(bars[1])  # the poison really changed the entry bar and later
    assert bars[0]["open"][30] == bars[1]["open"][30]
    assert outputs[0]["totals"]["accepted"] == 4 and outputs[0]["totals"]["rejected"] == 1
    sheets = sorted(p.relative_to(clean) for p in clean.glob("sheets/*.png"))
    assert [str(p) for p in sheets] == ["sheets/accepted-001.png", "sheets/rejected-001.png"]
    for stored in [*sheets, Path("candidates.parquet")]:
        assert (clean / stored).read_bytes() == (poisoned / stored).read_bytes(), stored
    for name in ("summary.json", "manifest.json", "spec.json"):
        documents = [_without_identity(json.loads((f / name).read_text())) for f in folders]
        assert documents[0] == documents[1], name
    printed = [{**o, "sheets": [Path(p).name for p in o["sheets"]]} for o in outputs]
    assert _without_identity(printed[0]) == _without_identity(printed[1])
    ledgers = [_without_identity(read_trials(f.parents[1])[0]) for f in folders]
    assert ledgers[0] == ledgers[1]


def test_stored_columns_and_fields_hold_no_forward_figure(tmp_path: Path) -> None:
    _blind_store(tmp_path, False)
    out = find.run_find(spec_file(tmp_path, worked=True), home=tmp_path)
    folder = Path(out["folder"])
    assert pl.read_parquet(folder / "candidates.parquet").columns == [
        "candidate_id",
        "symbol",
        "event_ts",
        "status",
        "reason",
        "detail",
        "trigger_ts",
        "entry_ts",
        "entry_price",
        "ref_base",
        "cluster_id",
        "cluster_first",
        "resolved_symbol",
        "store",
        "source",
    ]

    def keys(document: Any) -> set[str]:
        if isinstance(document, dict):
            return set(document) | {k for v in document.values() for k in keys(v)}
        if isinstance(document, list):
            return {k for v in document for k in keys(v)}
        return set()

    found = keys(out) | keys(read_trials(tmp_path)[0])
    for name in ("summary.json", "manifest.json"):
        found |= keys(json.loads((folder / name).read_text()))
    forward = {"exit", "exit_ts", "exit_price", "return", "returns", "pnl", "mfe", "mae"}
    assert not found & forward
    assert not [k for k in found if k.startswith(("forward", "horizon", "outcome"))]


def test_a_find_is_a_recorded_look_not_a_deflation_trial(tmp_path: Path) -> None:
    from alpha_cli.spine.trial_reader import family_counts, spine_snapshot, trials_for_deflation

    worked_store(tmp_path)
    out = find.run_find(spec_file(tmp_path, worked=True), home=tmp_path)
    snapshot = spine_snapshot(tmp_path)
    (record,) = snapshot.records
    assert record.kind == "setup_find" and not record.counts_for_deflation
    assert record.evidence_path == f"setups/{out['find_id']}/manifest.json"
    assert trials_for_deflation(snapshot, "spine:ma_cross")["all_trials"] == 0
    assert [r["reader_trials"] for r in family_counts(snapshot)] == [0]


def test_an_unfinished_folder_is_redrawn_without_leftover_sheets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worked_store(tmp_path)
    spec = spec_file(tmp_path, worked=True)

    def broken(*a: Any, **k: Any) -> bytes:
        raise OSError("sheet failed")

    monkeypatch.setattr(find, "draw_sheet", broken)
    with pytest.raises(OSError):
        find.run_find(spec, home=tmp_path)
    (leftover,) = (tmp_path / "setups").glob("*/sheets")
    (leftover / "accepted-009.png").write_bytes(b"old")
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    out = find.run_find(spec, home=tmp_path)
    assert sorted(p.name for p in leftover.iterdir()) == ["accepted-001.png", "rejected-001.png"]
    assert len(out["sheets"]) == 2


def test_explicit_store_and_default_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worked_store(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    worked_store(other)
    (tmp_path / "stores.toml").write_text('alt="other"\n')
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    out = find.run_find(
        spec_file(tmp_path, ("SPY@alt", "SPY")), home=tmp_path, assets=["SPY", "SPY@alt"]
    )
    assert [a["store"] for a in out["assets"]] == ["alt", "home"]
    assert "source-defaulted" in out["labels"]
    assert "source-defaulted" not in out["assets"][0]["labels"]


def test_empty_find_and_evaluator_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_core import DataError
    from alpha_study.setup import evaluate

    seed(tmp_path)
    empty = find.run_find(spec_file(tmp_path), home=tmp_path)
    assert empty["totals"]["events"] == empty["totals"]["clusters"] == 0
    assert empty["sheets"] == []

    def fail_evaluator(*a: Any, **kw: Any) -> pl.DataFrame:
        raise DataError("bad evaluation")

    monkeypatch.setattr(evaluate, "find_candidates", fail_evaluator)
    with pytest.raises(SpineError, match="bad evaluation"):
        find.run_find(spec_file(tmp_path), home=tmp_path)


def test_truncation_counts_clusters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.spine.setup_find import sheet_panels
    from alpha_study.setup.spec import SetupSpec

    frame = worked_store(tmp_path)
    spec = SetupSpec.load(spec_file(tmp_path))
    rows: list[dict[str, Any]] = [
        dict(
            symbol="SPY",
            candidate_id=i + 1,
            event_ts=frame["ts"][10],
            trigger_ts=frame["ts"][10],
            entry_price=100.0,
            status="accepted",
            reason=None,
            cluster_id=i + 1,
            cluster_first=True,
        )
        for i in range(18)
    ]
    sheets, counts = sheet_panels(spec, {"SPY": frame}, rows, 5, 1)
    assert counts == dict(accepted=16, accepted_not_drawn=2, rejected_sampled={})
    assert len(sheets) == 1 and len(sheets[0][1]) == 16
    monkeypatch.setattr(find, "_sheets", lambda *a: ([], counts))
    out = find.run_find(spec_file(tmp_path, worked=True), home=tmp_path, max_sheets=1)
    assert "sheets-truncated" in out["labels"]


def test_command_json_errors_and_human_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    worked_store(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(find, "draw_sheet", lambda *a, **k: b"png")
    runner = CliRunner()
    path = spec_file(tmp_path, worked=True)
    result = runner.invoke(find.setup_app, ["find", str(path), "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["totals"]["accepted_clusters"] == 2
    human = runner.invoke(find.setup_app, ["find", str(path)])
    assert "2 separate occurrences (4 matching days)" in human.stdout
    assert "Outcomes were not looked at." in human.stdout
    error = runner.invoke(find.setup_app, ["find", str(path), "--asset", "X", "--json"])
    assert error.exit_code == 1
    assert json.loads(error.stdout)["error"]["code"] == "ASSET_NOT_IN_SPEC"
    for option, value in [
        ("--context-bars", "4"),
        ("--context-bars", "251"),
        ("--max-sheets", "0"),
        ("--max-sheets", "51"),
    ]:
        assert runner.invoke(find.setup_app, ["find", str(path), option, value]).exit_code == 2
