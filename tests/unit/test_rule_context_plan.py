"""`alpha test <spec> --plan` for a context spec: a dry description; plain run is refused."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.unit._context_attach_support import cot_rows, store_cot

FIRST_REPORT = date(2020, 1, 7)
LAST_BEFORE_RESERVE = date(2023, 12, 26)
SPEC = (
    'assets = ["SPY"]\nwhen = "es > 0.5"\n[rule]\nkind = "tsmom"\nlookback = 60\n'
    '[context]\nes = "cot_nc_net_oi@13874A"\n'
)


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
    }


def _blocks(extra: bool) -> list[dict[str, Any]]:
    """Weekly reports; eight weeks high (0.9), eight low (0.1), alternating."""
    rows: list[dict[str, Any]] = []
    last = date(2024, 3, 5) if extra else LAST_BEFORE_RESERVE
    day, n = FIRST_REPORT, 0
    while day <= last:
        rows.append(dict(report_date=day, nl=900 if (n // 8) % 2 == 0 else 100))
        day, n = day + timedelta(weeks=1), n + 1
    return rows


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=1500)  # runs to 2024-02, past the reserved day
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    store_cot(tmp_path, cot_rows(_blocks(extra=False)))
    (tmp_path / "spec.toml").write_text(SPEC)
    return tmp_path


def _run(home: Path, *args: str) -> Any:
    return CliRunner().invoke(app, ["test", str(home / "spec.toml"), *args])


def test_plan_describes_the_gate_and_writes_nothing(home: Path) -> None:
    before = _listing(home)
    result = _run(home, "--plan", "--json")
    assert result.exit_code == 0, result.output
    assert _listing(home) == before  # no file, size or modification time changed
    out = json.loads(result.output)
    row = out["results"][0]
    blocks = len(range(0, (len(_blocks(False)) - 1) // 8 + 1, 2))
    assert row["spells"] == blocks and row["error"] is None
    assert row["context_span"]["last"] < "2024-01-01"
    assert row["gate_true_bars"] > 0 and row["span_bars"] >= row["gate_true_bars"]
    assert row["labels"].count("held-back-period") <= 1
    assert "short-context-history" not in row["labels"]  # about four years
    assert len(row["test_key"]) == 7 and row["data_id"] and len(row["context_fp"]) == 64
    assert row["sentence"].startswith("The condition data covers 2020-")
    assert "separate spells. The reading uses this span only." in row["sentence"]
    text = result.output.lower()
    assert "pass" not in text and "fail" not in text and "profit" not in text


def test_plain_text_output_and_short_history_label(home: Path) -> None:
    store_cot(home, cot_rows(_blocks(False)[-60:]))  # about 14 months of reports
    result = _run(home, "--plan")
    assert result.exit_code == 0, result.output
    assert "short-context-history" in result.output
    assert "separate spells" in result.output and "null gate bars by reason" in result.output


def test_plain_test_of_a_context_spec_is_refused(home: Path) -> None:
    before = _listing(home)
    result = _run(home)
    assert result.exit_code == 1
    assert "the gated engine is not built yet; use --plan" in result.output
    assert _listing(home) == before
    assert _run(home, "--recheck").exit_code == 1


def test_plan_on_a_spec_without_context_is_refused(home: Path) -> None:
    (home / "plain.toml").write_text('assets = ["SPY"]\n[rule]\nkind = "tsmom"\nlookback = 60\n')
    result = CliRunner().invoke(app, ["test", str(home / "plain.toml"), "--plan"])
    assert result.exit_code == 1 and "has none" in result.output


def test_post_reserve_context_rows_do_not_change_the_test_key(home: Path) -> None:
    first = json.loads(_run(home, "--plan", "--json").output)["results"][0]
    store_cot(home, cot_rows(_blocks(extra=True)))  # rows after the reserved day
    second = json.loads(_run(home, "--plan", "--json").output)["results"][0]
    assert second["test_key"] == first["test_key"] and second["context_fp"] == first["context_fp"]
    # The gate times come from the same bars, so the plans agree on every number.
    assert {k: v for k, v in second.items()} == {k: v for k, v in first.items()}
    assert datetime(2024, 1, 1, tzinfo=UTC) > datetime.combine(
        date.fromisoformat(first["context_span"]["last"]), time.min, tzinfo=UTC
    )
