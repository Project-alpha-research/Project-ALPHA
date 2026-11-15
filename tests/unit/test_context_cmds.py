"""Context command contracts on local synthetic vintages."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.context_cmds import context_app
from alpha_core import DataError
from alpha_data.context.fred import parse_observations, store_series


def seed(data_dir: Path) -> None:
    rows = [
        dict(date="2024-01-01", value="1", realtime_start="2024-01-02", realtime_end="2024-03-14"),
        dict(date="2024-01-01", value="9", realtime_start="2024-03-15", realtime_end="9999-12-31"),
        dict(date="2024-02-01", value="3", realtime_start="2024-02-02", realtime_end="9999-12-31"),
        dict(date="2024-03-01", value="5", realtime_start="2024-03-02", realtime_end="9999-12-31"),
    ]
    metadata = dict(
        title="Example",
        units="Percent",
        frequency="Monthly",
        seasonal_adjustment="None",
        last_updated="2024-03-15",
    )
    store_series(
        "X",
        parse_observations("X", rows),
        metadata,
        data_dir=data_dir,
        fetched_at=datetime(2024, 4, 1, tzinfo=UTC),
    )


@pytest.fixture
def stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed(tmp_path)
    return tmp_path


def invoke(*args: str) -> dict[str, Any]:
    result = CliRunner().invoke(context_app, list(args))
    assert result.exit_code == 0, result.output + str(result.exception)
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def test_show_list_window_json(stored: Path) -> None:
    shown = invoke("show", "X", "--as-of", "2024-03-10", "--json")
    assert shown["view"] == "as_known" and shown["as_of"] == "2024-03-10"
    assert shown["rows"] == [
        {"obs_date": "2024-01-01", "value": 1.0, "known_from": "2024-01-02"},
        {"obs_date": "2024-02-01", "value": 3.0, "known_from": "2024-02-02"},
        {"obs_date": "2024-03-01", "value": 5.0, "known_from": "2024-03-02"},
    ]
    listed = invoke("list", "--json")["series"]
    assert listed == [
        {
            "series_id": "X",
            "title": "Example",
            "label": "Example",
            "frequency": "Monthly",
            "last_obs": "2024-03-01",
            "fetched_at": "2024-04-01T00:00:00+00:00",
        }
    ]
    window = invoke("window", "--start", "2024-01-15", "--end", "2024-03-10", "--json")
    assert window["as_of"] == "2024-03-10" and window["view"] == "as_known"
    assert window["series"] == [
        {
            "series_id": "X",
            "start_value": 1.0,
            "end_value": 5.0,
            "change": 4.0,
            "min": 3.0,
            "max": 5.0,
        }
    ]


def test_explicit_views_filters_and_today_default(stored: Path) -> None:
    for view, value in [("first", 1.0), ("latest", 9.0)]:
        result = invoke("show", "X", "--view", view, "--end", "2024-01-31", "--json")
        assert result["view"] == {"first": "first_release", "latest": "latest"}[view]
        assert len(result["rows"]) == 1 and result["rows"][0]["value"] == value
    result = invoke("show", "X", "--start", "2024-02-01", "--json")
    assert result["view"] == "as_known" and len(result["rows"]) == 2
    assert result["as_of"] == datetime.now(UTC).date().isoformat()
    assert "latest" in CliRunner().invoke(context_app, ["show", "X", "--view", "latest"]).stdout


def test_window_cutoff_and_empty_boundaries(stored: Path) -> None:
    result = invoke(
        "window",
        "--start",
        "2024-01-01",
        "--end",
        "2024-03-20",
        "--as-of",
        "2024-02-10",
        "--series",
        "X",
        "--json",
    )
    assert result["series"][0] == {
        "series_id": "X",
        "start_value": None,
        "end_value": 3.0,
        "change": None,
        "min": 1.0,
        "max": 3.0,
    }


@pytest.fixture
def expiry_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    # (observation date, value, publication start, inclusive publication end).
    series_rows = {
        "ONLY": [("2024-02-01", "90", "2024-02-02", "2024-02-10")],
        "CARRY": [
            ("2024-02-08", "4", "2024-02-09", "9999-12-31"),
            ("2024-02-09", "90", "2024-02-10", "2024-02-10"),
        ],
        "LIVE_NULL": [
            ("2024-01-01", "4", "2024-01-02", "9999-12-31"),
            ("2024-02-01", ".", "2024-02-02", "9999-12-31"),
        ],
        "EXPIRED_NULL": [
            ("2024-01-01", "4", "2024-01-02", "9999-12-31"),
            ("2024-02-01", ".", "2024-02-02", "2024-02-10"),
        ],
        "MONTHLY": [
            ("2024-01-01", "1", "2024-01-02", "2024-02-14"),
            ("2024-01-01", "9", "2024-02-15", "9999-12-31"),
            ("2024-02-01", "3", "2024-02-02", "2024-02-19"),
            ("2024-02-01", "30", "2024-02-20", "9999-12-31"),
            ("2024-03-01", "5", "2024-03-02", "2024-03-14"),
            ("2024-04-01", "999", "2024-04-02", "9999-12-31"),
        ],
        "DAILY": [
            ("2024-01-14", "2", "2024-01-15", "2024-01-20"),
            ("2024-01-15", "4", "2024-01-16", "2024-01-31"),
            ("2024-01-15", "40", "2024-02-01", "9999-12-31"),
            ("2024-02-09", "-8", "2024-02-10", "2024-02-10"),
            ("2024-03-09", "6", "2024-03-10", "9999-12-31"),
            ("2024-03-10", "100", "2024-03-11", "9999-12-31"),
            ("2024-03-21", "999", "2024-03-22", "9999-12-31"),
        ],
    }
    for series_id, rows in series_rows.items():
        metadata = dict(
            title=series_id,
            units="Percent",
            frequency="Daily" if series_id in {"DAILY", "CARRY"} else "Monthly",
            seasonal_adjustment="None",
            last_updated="2024-04-02",
        )
        store_series(
            series_id,
            parse_observations(
                series_id,
                [
                    dict(date=day, value=value, realtime_start=start, realtime_end=end)
                    for day, value, start, end in rows
                ],
            ),
            metadata,
            data_dir=tmp_path,
            fetched_at=datetime(2024, 4, 2, tzinfo=UTC),
        )
    return tmp_path


@pytest.mark.parametrize(
    ("series_id", "expected"),
    [
        ("ONLY", []),
        (
            "CARRY",
            [{"obs_date": "2024-02-08", "value": 4.0, "known_from": "2024-02-09"}],
        ),
        (
            "LIVE_NULL",
            [
                {"obs_date": "2024-01-01", "value": 4.0, "known_from": "2024-01-02"},
                {"obs_date": "2024-02-01", "value": None, "known_from": "2024-02-02"},
            ],
        ),
        (
            "EXPIRED_NULL",
            [{"obs_date": "2024-01-01", "value": 4.0, "known_from": "2024-01-02"}],
        ),
    ],
)
def test_show_expired_and_live_null_observations(
    expiry_store: Path, series_id: str, expected: list[dict[str, Any]]
) -> None:
    result = invoke("show", series_id, "--as-of", "2024-02-11", "--json")
    assert result["view"] == "as_known" and result["as_of"] == "2024-02-11"
    assert result["rows"] == expected


@pytest.mark.parametrize(
    ("series_id", "start_value", "end_value", "change"),
    [
        ("ONLY", 90.0, None, None),
        ("CARRY", 90.0, 4.0, -86.0),
        ("LIVE_NULL", None, None, None),
        ("EXPIRED_NULL", None, 4.0, None),
    ],
)
def test_window_expiry_missing_and_legitimate_carry(
    expiry_store: Path,
    series_id: str,
    start_value: float | None,
    end_value: float | None,
    change: float | None,
) -> None:
    result = invoke(
        "window", "--start", "2024-02-10", "--end", "2024-02-11", "--series", series_id, "--json"
    )
    assert result["series"] == [
        {
            "series_id": series_id,
            "start_value": start_value,
            "end_value": end_value,
            "change": change,
            "min": None,
            "max": None,
        }
    ]


def test_window_terminal_expiry_has_no_values(expiry_store: Path) -> None:
    result = invoke(
        "window", "--start", "2024-02-11", "--end", "2024-02-12", "--series", "ONLY", "--json"
    )
    assert result["series"] == [
        {
            "series_id": "ONLY",
            "start_value": None,
            "end_value": None,
            "change": None,
            "min": None,
            "max": None,
        }
    ]


@pytest.mark.parametrize(
    ("cutoff", "monthly", "daily"),
    [
        ("2024-02-10", (3.0, 3.0, 3.0), (-8.0, -8.0, 40.0)),
        ("2024-03-10", (5.0, 5.0, 30.0), (6.0, 6.0, 40.0)),
        ("2024-03-20", (30.0, 30.0, 30.0), (100.0, 6.0, 100.0)),
        ("2024-04-10", (30.0, 30.0, 30.0), (100.0, 6.0, 100.0)),
        (None, (30.0, 30.0, 30.0), (100.0, 6.0, 100.0)),
    ],
)
def test_window_mixed_frequencies_own_cutoffs_and_extrema(
    expiry_store: Path,
    cutoff: str | None,
    monthly: tuple[float, float, float],
    daily: tuple[float, float, float],
) -> None:
    args = [
        "window",
        "--start",
        "2024-01-15",
        "--end",
        "2024-03-20",
        "--series",
        "MONTHLY",
        "--series",
        "DAILY",
        "--json",
    ]
    if cutoff is not None:
        args.extend(["--as-of", cutoff])
    result = invoke(*args)
    assert result["view"] == "as_known"
    assert result["as_of"] == (cutoff or "2024-03-20")
    assert result["start"] == "2024-01-15" and result["end"] == "2024-03-20"
    assert result["series"] == [
        {
            "series_id": series_id,
            "start_value": start_value,
            "end_value": end_value,
            "change": end_value - start_value,
            "min": minimum,
            "max": maximum,
        }
        for series_id, start_value, (end_value, minimum, maximum) in [
            ("MONTHLY", 1.0, monthly),
            ("DAILY", 2.0, daily),
        ]
    ]


def test_pull_partial_and_total_failure(stored: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import alpha_cli.context_cmds as commands

    def pull(series_id: str, *, data_dir: Path) -> dict[str, object]:
        if series_id == "BAD":
            raise DataError("provider refused")
        return dict(rows=4, first_obs="2024-01-01", last_obs="2024-03-01", vintages=4)

    monkeypatch.setattr(commands, "pull_series", pull)
    result = invoke("pull", "--series", "BAD", "--series", "X", "--json")
    assert result["errors"] == [{"series_id": "BAD", "error": "provider refused"}]
    assert result["series"][0]["series_id"] == "X"
    failed = CliRunner().invoke(context_app, ["pull", "--series", "BAD", "--json"])
    assert failed.exit_code == 1 and json.loads(failed.stdout)["errors"]
    default = invoke("pull", "--json")
    assert len(default["series"]) == 18


@pytest.mark.parametrize(
    "args",
    [
        ["show", "X", "--as-of", "bad"],
        ["show", "X", "--view", "wrong"],
        ["show", "MISSING"],
        ["window", "--start", "2024-03-10", "--end", "2024-01-01"],
        ["show", "X", "--start", "2024-03-10", "--end", "2024-01-01"],
    ],
)
def test_bad_arguments_fail(stored: Path, args: list[str]) -> None:
    assert CliRunner().invoke(context_app, args).exit_code != 0
