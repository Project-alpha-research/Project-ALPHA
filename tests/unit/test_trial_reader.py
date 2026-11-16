"""Tolerant, non-mutating snapshots and conservative family counts."""

import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.trial_reader import (
    family_counts,
    ledger_sources,
    read_ledgers,
    trials_for_deflation,
)
from tests.unit.test_trial_record import factor, rule, spine


def write_rows(path: Any, rows: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join((json.dumps(row) if isinstance(row, dict) else row) + "\n" for row in rows)
    )


def example(tmp_path: Path) -> tuple[Path, Path]:
    home, rd = tmp_path / "home", tmp_path / "runs/ledger/factors.jsonl"
    write_rows(
        home / "ledger/trials.jsonl",
        [
            spine(),
            spine(trial_index=2, verdict="D"),
            spine(trial_index=3, verdict=None, labels=["error"]),
        ],
    )
    write_rows(
        rd,
        [
            factor(1, status="SCREEN_FAIL", code_sha256="a" * 64),
            factor(trial_index=2),
            factor(trial_index=3, status="REPEAT"),
            rule(trial_index=4),
            {"schema": "SomethingElseV9", "trial_index": 5},
            "not json",
        ],
    )
    return home, rd


def test_worked_example(tmp_path: Path) -> None:
    home, rd = example(tmp_path)
    snapshot = read_ledgers(ledger_sources(home, rd))
    assert len(snapshot.records) == 7 and len(snapshot.unknown) == 2
    counts = {r["family_id"]: r for r in family_counts(snapshot)}
    assert counts["rdagent-factors"]["reader_trials"] == 6
    assert counts["rdagent-factors"]["outcomes"] == {"rejected": 1, "supported": 1, "recorded": 1}
    assert counts["rule:f1"]["reader_trials"] == 1
    assert counts["rule:f1"]["family_size_recorded"] == 2
    assert counts["spine:ma_cross"]["reader_trials"] == 2
    assert counts["spine:ma_cross"]["outcomes"] == {"supported": 1, "rejected": 1, "error": 1}
    result = trials_for_deflation(snapshot, "rdagent-factors")
    assert (
        result["family_trials"] == 6
        and result["all_trials"] == 9
        and result["unknown_rows"] == 2
        and result["basis"]
    )
    assert trials_for_deflation(snapshot, "absent")["family_trials"] == 0


@pytest.mark.parametrize("lock", [False, True])
def test_reads_create_and_modify_nothing(
    tmp_path: Path, lock: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, rd = example(tmp_path)
    if lock:
        for path in (home / "ledger/trials.jsonl", rd):
            path.with_suffix(".jsonl.lock").write_bytes(b"lock")

    def state() -> Any:
        return {
            str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in tmp_path.rglob("*")
        }

    before = state()
    import fcntl

    real_flock, calls = fcntl.flock, []

    def observe(fd: Any, operation: Any) -> Any:
        calls.append(operation)
        return real_flock(fd, operation)

    monkeypatch.setattr(fcntl, "flock", observe)
    read_ledgers(ledger_sources(home, rd))
    assert state() == before
    assert calls.count(fcntl.LOCK_SH) == (2 if lock else 0)


def test_sources_precedence_missing_and_invalid(tmp_path: Path) -> None:
    assert len(ledger_sources(tmp_path, None)) == 1
    config = tmp_path / "ledger/sources.toml"
    config.parent.mkdir()
    configured = tmp_path / "configured.jsonl"
    config.write_text(f'[rdagent]\nfactor_ledger = "{configured}"\n')
    assert ledger_sources(tmp_path, None)[1].file == str(configured)
    override = tmp_path / "override.jsonl"
    assert ledger_sources(tmp_path, override)[1].file == str(override)
    snapshot = read_ledgers(ledger_sources(tmp_path, None))
    assert all(s.state == "missing" for s in snapshot.sources)
    for text in (
        "[broken",
        '[rdagent]\nfactor_ledger = "relative"',
        "[rdagent]\nfactor_ledger = 4",
    ):
        config.write_text(text)
        with pytest.raises(SpineError) as error:
            ledger_sources(tmp_path, None)
        assert error.value.payload["code"] == "LEDGER_SOURCE_INVALID"


def test_bad_rows_and_incomplete_last_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger/trials.jsonl"
    write_rows(
        path,
        [
            "[]",
            "{}",
            spine(verdict="Z"),
            {"schema": "AlphaTrialV1"},
            spine(labels="bad"),
            spine(oos_sharpe=float("nan")),
        ],
    )
    with path.open("ab") as stream:
        stream.write(json.dumps(spine()).encode())
    snapshot = read_ledgers(ledger_sources(tmp_path, None))
    assert not snapshot.records and len(snapshot.unknown) == 7
    assert snapshot.unknown[-1].reason == "incomplete last line (a writer may be mid-append)"
    assert trials_for_deflation(snapshot, "absent")["all_trials"] == 7


def test_repeat_and_latest_count(tmp_path: Path) -> None:
    path = tmp_path / "ledger/trials.jsonl"
    write_rows(path, [spine(), spine(trial_index=2, labels=["repeat"]), spine(kind="tool:acf")])
    snapshot = read_ledgers(ledger_sources(tmp_path, None))
    counts = {r["family_id"]: r for r in family_counts(snapshot)}
    assert counts["spine:ma_cross"]["reader_trials"] == 1
    assert counts["spine-tool:acf"]["reader_trials"] == 0


def test_malformed_family_and_windows_are_unknown(tmp_path: Path) -> None:
    rd = tmp_path / "rd.jsonl"
    write_rows(
        rd,
        [
            rule(family_id=None),
            rule(family_id=3),
            factor(
                windows={
                    "history": "bad",
                    "exploration": "bad",
                    "panel_end": None,
                    "reserved_start": None,
                }
            ),
        ],
    )
    snapshot = read_ledgers(ledger_sources(tmp_path, rd))
    assert not snapshot.records and len(snapshot.unknown) == 3
    # Two unmapped rule rows add one each; the malformed V3 factor row is counted the way the
    # writer counts a V3 row: one attempt per clock (daily, weekly, monthly).
    assert family_counts(snapshot)[0]["reader_trials"] == 5


def test_factor_count_deduplicates_code_and_imported_clock(tmp_path: Path) -> None:
    rd = tmp_path / "rd.jsonl"
    write_rows(
        rd,
        [
            factor(trial_index=1),
            factor(trial_index=2, family_size=9),
            factor(trial_index=3, status="IMPORTED", code_sha256="x" * 64),
        ],
    )
    snapshot = read_ledgers(ledger_sources(tmp_path, rd))
    counts = family_counts(snapshot)[0]
    assert counts["rows"] == 3 and counts["reader_trials"] == 4
    assert counts["family_size_recorded"] == 4


def test_unmapped_factor_status_still_counts_like_the_writer_counts_it(tmp_path: Path) -> None:
    """A status written by a newer writer (here SPREAD_FAIL) is shown as unknown, yet the
    factor family count never falls below what the writer's own counter gives."""
    rd = tmp_path / "rd.jsonl"
    rows = [
        factor(trial_index=1),
        factor(trial_index=2, code_sha256="d" * 64, status="SPREAD_FAIL"),
    ]
    write_rows(rd, rows)
    snapshot = read_ledgers(ledger_sources(tmp_path, rd))
    assert len(snapshot.records) == 1 and len(snapshot.unknown) == 1
    assert "unknown status: SPREAD_FAIL" in snapshot.unknown[0].reason
    from alpha_cli._rdagent_clocks import trial_family

    assert family_counts(snapshot)[0]["reader_trials"] == len(trial_family(rows))


def test_all_trials_counts_each_row_once(tmp_path: Path) -> None:
    """Unknown RD-Agent rows sit inside the factor count; unknown spine rows are added once."""
    home, rd = example(tmp_path)
    write_rows(home / "ledger/trials.jsonl", [spine(), "not json"])
    snapshot = read_ledgers(ledger_sources(home, rd))
    families = {r["family_id"]: r["reader_trials"] for r in family_counts(snapshot)}
    assert trials_for_deflation(snapshot, "x")["all_trials"] == sum(families.values()) + 1
