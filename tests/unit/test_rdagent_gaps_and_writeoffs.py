"""How delisting write-offs reach the ledger and proposer feedback."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_membership as membership
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_stability import writeoff_summary
from tests.unit._rdagent_support import judge_namespace, universe_run
from tests.unit.test_rdagent_factor_eval import fixture


def test_evaluator_records_actual_universe_and_writeoff_names(tmp_path: Path) -> None:
    run = tmp_path / "run"
    path = fixture(run)
    _, bars, _, _ = ev._inputs(run, path)
    bars = bars.filter(
        ~((pl.col("instrument") == "C13USDT") & (pl.col("date") >= date(2022, 1, 1)))
    )
    bars.write_parquet(run / "panel/panel.parquet")
    values = pl.read_parquet(run / "factors.parquet")
    held_before_end = (pl.col("instrument") == "C13USDT") & pl.col("date").is_between(
        date(2021, 12, 20), date(2021, 12, 31)
    )
    values.with_columns(
        pl.when(held_before_end).then(1.0).otherwise(pl.col("factor")).alias("factor")
    ).write_parquet(run / "factors.parquet")
    from alpha_cli import _rdagent_universe as universes

    spec = {**universes.DEFAULT, "survivorship": "15 instruments, 1 later delisted"}
    (run / "panel/universe.json").write_bytes(judge.canonical(spec))
    receipt = {
        **membership.panel_summary(bars),
        "panel_sha256": judge.sha((run / "panel/panel.parquet").read_bytes()),
        "universe_sha256": judge.sha(judge.canonical(spec)),
    }
    (run / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    result = ev.evaluate(run, path, run / "result.json", tmp_path / "ledger")
    row = result["factors"][0]
    assert row["universe_includes_delisted"] is True
    assert "15 instruments, 1 later delisted" in result["feedback_text"]
    assert row["writeoff_count"] > 0
    assert "C13USDT" in row["writeoff_message"]
    assert "assuming a 30% loss" in row["writeoff_message"]
    assert row["writeoff_message"] in result["feedback_text"]


def test_writeoff_names_are_bounded_and_legacy_replay_name_stays_readable() -> None:
    from alpha_cli._rdagent_stability import replay_output, writeoff_summary

    old = {"missing_coin_days": 7}
    assert replay_output(old) == {"unrankable_instrument_rebalances": 7}
    assert old == {"missing_coin_days": 7}
    row = {
        "name": "test",
        "clocks": {
            "weekly": {
                "replay": {
                    "haircuts_applied": 9,
                    "writeoff_instruments": [f"C{i}" for i in range(7)],
                }
            }
        },
    }
    count, message = writeoff_summary(row, membership.DELISTING_HAIRCUT)
    assert count == 9
    assert "C0, C1, C2, C3, C4 and 2 more" in message
    assert "C5" not in message and "C6" not in message


def test_writeoff_sentence_names_only_replayed_clocks() -> None:
    row = {
        "name": "idea",
        "clocks": {
            "daily": {"replay": {}},
            "weekly": {"replay": {"haircuts_applied": 1, "writeoff_instruments": ["C0"]}},
            "monthly": {"replay": {}},
        },
    }
    count, message = writeoff_summary(row, 0.3)
    assert count == 1
    assert "weekly" in message and "daily" not in message and "monthly" not in message
    assert "1 position in 1 coin was written off" in message


def test_writeoff_sentence_skips_errored_and_unreplayed_clocks() -> None:
    trial = {"replay": {"haircuts_applied": 2, "writeoff_instruments": ["C0", "C1"]}}
    row: dict[str, Any] = {
        "name": "idea",
        "clocks": {"daily": {"replay": {"error": "ValueError: x"}}, "weekly": trial},
    }
    count, message = writeoff_summary(row, 0.3)
    assert count == 2 and "replayed weekly holding clock;" in message and "daily" not in message
    row["clocks"]["monthly"] = trial
    assert "replayed weekly and monthly holding clocks;" in writeoff_summary(row, 0.3)[1]
    none = {"name": "idea", "clocks": {"daily": {"replay": {}}}}
    assert writeoff_summary(none, 0.3) == (
        0,
        "idea: no holding clock was replayed, so nothing was written off.",
    )


def test_writeoffs_positions_in_coins() -> None:
    row = {
        "name": "idea",
        "clocks": {
            "weekly": {"replay": {"haircuts_applied": 4, "writeoff_instruments": ["A", "B"]}}
        },
    }
    assert "4 positions in 2 coins were written off" in writeoff_summary(row, 0.3)[1]


def test_feedback_force_appends_writeoffs_and_current_universe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    message = (
        "factor: 7 held positions were written off after their coin stopped trading, "
        "assuming a 30% loss of last value; C0, C1, C2, C3, C4 and 2 more."
    )
    backend = Mock(return_value=json.dumps({"Observations": "Model omitted the write-offs."}))
    ns["APIBackend"] = lambda: SimpleNamespace(build_messages_and_create_chat_completion=backend)
    ns["T"] = lambda _: SimpleNamespace(r=lambda **kw: json.dumps(kw))
    exp = SimpleNamespace(
        hypothesis=SimpleNamespace(hypothesis="idea"),
        sub_tasks=[],
        stdout="",
        alpha_evaluation={
            "iteration": 0,
            "decision": False,
            "factors": [{"name": "factor", "code_sha256": "a" * 64, "writeoff_message": message}],
        },
    )
    feedback = ns["AlphaFactorFeedback"]()
    feedback.scen = SimpleNamespace(get_scenario_all_desc=lambda: "old scenario")
    result = feedback.generate_feedback(exp, None)
    assert message in result.observations
    assert (
        "Current universe: 141 instruments, 66 later delisted"
        in backend.call_args.kwargs["system_prompt"]
    )
    row = {
        "schema": "AlphaRdagentFactorTrialV2",
        "name": "factor",
        "status": "REPLAY_FAIL",
        "screen": {},
        "q": 1,
        "run_id": "run",
        "writeoff_count": 7,
    }
    assert "7 write-offs" in ns["ledger_summary"](row)


def test_single_trial_and_writeoff_use_singular_text() -> None:
    ns = judge_namespace()
    row = {
        "schema": "AlphaRdagentFactorTrialV2",
        "name": "price_delay_120d",
        "status": "SCREEN_FAIL",
        "screen": {},
        "q": 1.0,
        "run_id": "test",
        "writeoff_count": 1,
    }
    assert ": 1 try;" in ns["family_summary"]([row], 3)
    assert ns["ledger_summary"](row).endswith("; 1 write-off")
