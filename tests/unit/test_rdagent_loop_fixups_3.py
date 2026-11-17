"""Proposer and code reproducibility contracts without network or upstream runtime."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from tests.unit.test_rdagent_factor_judge import WORKER, data


def judge_namespace() -> dict[str, Any]:
    """Run ALPHA definitions with inert upstream boundaries; never import a model backend."""

    class Base:
        def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
            return {"hypothesis_and_feedback": "Old scenario description"}, True

    ns: dict[str, Any] = {
        "Any": Any,
        "Path": Path,
        "os": os,
        "json": json,
        "re": re,
        "hashlib": hashlib,
        "subprocess": subprocess,
        "sys": sys,
        "pd": pd,
        "Developer": object,
        "FactorEmptyError": ValueError,
        "Experiment2Feedback": object,
        "QlibFactorScenario": object,
        "QlibQuantScenario": type("Scenario", (), {}),
        "QlibFactorHypothesisGen": Base,
        "HypothesisFeedback": SimpleNamespace,
        "convert2bool": bool,
    }
    for name in ("current_universe", "check_prefix_invariance"):
        if hasattr(data, name):
            ns[name] = getattr(data, name)
    tree = ast.parse((WORKER / "alpha_factor_judge.py").read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<loop-fixups>", "exec"), ns)
    return ns


def universe_run(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "panel").mkdir(parents=True)
    receipt = {"instruments": {f"C{i}": {"last_day": "2023-12-31"} for i in range(141)}}
    (root / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    (root / "panel/universe.json").write_text(
        json.dumps({"survivorship": "141 instruments, 66 later delisted; not survivorship-free"})
    )
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(root))
    monkeypatch.delenv("ALPHA_FACTOR_UNIVERSE_TEXT", raising=False)


def test_current_universe_replaces_fallback_and_corrects_restored_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    context = {"hypothesis_and_feedback": "restored scenario"}
    ns["append_swing_context"](context, None)
    text = context["hypothesis_and_feedback"]
    assert "15" not in text
    assert text.endswith("earlier text saying otherwise is out of date")
    assert "Current universe: 141 instruments, 66 later delisted" in text
    assert "141 instruments" in ns["AlphaFactorScenario"]().experiment_setting
    monkeypatch.setenv("ALPHA_FACTOR_UNIVERSE_TEXT", "15 surviving coins only")
    assert "15" not in ns["AlphaFactorScenario"]().experiment_setting


def test_missing_universe_information_refuses_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    monkeypatch.delenv("ALPHA_FACTOR_UNIVERSE_TEXT", raising=False)
    with pytest.raises(ValueError, match="universe"):
        judge_namespace()["append_swing_context"]({"hypothesis_and_feedback": ""}, None)


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


@pytest.mark.parametrize("first", ["2020-12-30", "2021-01-01"])
def test_cut_copies_keep_not_yet_listed_instruments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    saved: dict[str, pd.DataFrame] = {}

    def write(frame: pd.DataFrame, path: Path, *, key: str, mode: str) -> None:
        saved[str(path.relative_to(tmp_path / "out"))] = frame.copy()
        path.write_bytes(b"hdf boundary")

    monkeypatch.setattr(pd.DataFrame, "to_hdf", write)
    frame = pd.DataFrame({"date": pd.to_datetime([first, "2021-01-02"]), "instrument": ["A", "B"]})
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = [1.0, 2.0]
    frame.to_parquet(tmp_path / "panel.parquet")
    data.prepare(tmp_path / "panel.parquet", tmp_path / "out")
    cut = saved["cuts/2020-12-31/daily_pv.h5"]
    assert set(cut.index.get_level_values("instrument")) == {"A", "B"}
    assert cut.xs("B", level="instrument").isna().all().all()


@pytest.mark.parametrize("unstable", [True, False])
def test_same_input_regression_instability_is_distinct_from_real_peek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unstable: bool
) -> None:
    cut = "2021-03-31"
    source = tmp_path / cut / "daily_pv.h5"
    source.parent.mkdir()
    source.write_bytes(b"identical truncated data")
    monkeypatch.setattr(data, "CUTS", (cut,))
    idx = pd.MultiIndex.from_product(
        [pd.date_range("2021-03-30", periods=2), ["A", "B"]], names=["datetime", "instrument"]
    )
    full = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    # Exactly identified, ill-conditioned two-equation regression. Different reduction
    # orders perturb its coefficients despite identical underlying observations.
    x = np.array([[1.0, 1.0], [1.0, 1.0 + 1e-12]])
    y = np.array([1.0, 2.0])
    values = [float(np.linalg.solve(x, y)[0]), float(np.linalg.lstsq(x, y, rcond=None)[0][0])]
    assert abs(values[0] - values[1]) > 1
    calls: list[bytes] = []

    def run(command: list[str], *, cwd: Path, **kwargs: Any) -> SimpleNamespace:
        calls.append((cwd / "daily_pv.h5").read_bytes())
        return SimpleNamespace(returncode=0)

    def read(path: Path, *, key: str) -> pd.DataFrame:
        result = full.copy()
        result.iloc[0, 0] = values[min(len(calls) - 1, 1)] if unstable else 10.0
        return result

    monkeypatch.setattr(data.subprocess, "run", run)
    monkeypatch.setattr(data.pd, "read_hdf", read)
    result = data.check_prefix_invariance(b"regression", full, tmp_path, sys.executable, 10)
    assert result["status"] == ("UNSTABLE" if unstable else "LOOKAHEAD")
    assert len(calls) == 2 and calls[0] == calls[1]
    detail = result["first_mismatch"]
    assert detail["cut"] == cut and detail["instrument"] == "A"
    assert detail["date"].startswith("2021-03-30")
    assert detail["absolute_difference"] > 0


@pytest.mark.parametrize("status", ["LOOKAHEAD", "UNSTABLE", "FAILED"])
def test_code_failures_do_not_close_idea_family(status: str) -> None:
    ns = judge_namespace()
    rows = [
        {
            "name": f"volatility_{i}",
            "status": status,
            "schema": "AlphaRdagentFactorTrialV2",
            "screen": {},
            "failure_reason": "exception",
        }
        for i in range(3)
    ]
    summary = ns["family_summary"](rows, 3)
    assert "Do not propose another" not in summary
    for row in rows:
        row["status"] = "SCREEN_FAIL"
    assert "Do not propose another" in ns["family_summary"](rows, 3)


def test_closed_composite_is_refused_before_coding_without_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ns = judge_namespace()
    ledger = tmp_path / "ledger"
    rows = [
        {
            "name": f"volatility_{i}",
            "status": "SCREEN_FAIL",
            "code_sha256": str(i),
            "schema": "AlphaRdagentFactorTrialV2",
            "screen": {},
        }
        for i in range(3)
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    before = ledger.read_bytes()
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    task = SimpleNamespace(
        factor_name="ridge_composite",
        description="volatility and momentum",
        factor_formulation="regression",
        variables={},
    )
    coder = SimpleNamespace(develop=Mock())
    exp = SimpleNamespace(sub_tasks=[task], hypothesis=SimpleNamespace(hypothesis="idea"))
    guard = ns["FamilyGuard"](coder)
    with pytest.raises(ValueError, match="closed families.*volatility.*open families"):
        guard.develop(exp)
    coder.develop.assert_not_called()
    records = [json.loads(line) for line in (tmp_path / "rounds.jsonl").read_text().splitlines()]
    assert records[-1]["status"] == "no_admissible_idea"
    assert records[-1]["reason"] == "refused_closed_family"
    assert records[-1]["trial_created"] is False
    assert ledger.read_bytes() == before


def test_new_loop_installs_family_guard_before_any_coder_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import ModuleType

    from tests.unit.test_rdagent_research_memory import memory

    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    boundary = ModuleType("alpha_factor_judge")
    boundary.FamilyGuard = ns["FamilyGuard"]
    boundary.current_universe = ns["current_universe"]
    monkeypatch.setitem(sys.modules, "alpha_factor_judge", boundary)
    original = SimpleNamespace(develop=Mock())
    factory = Mock(return_value=SimpleNamespace(coder=original))
    loop, count = memory.open_factor_loop(factory, "settings", 2, os.environ)
    assert isinstance(loop.coder, ns["FamilyGuard"])
    assert loop.coder.coder is original and count == 2


def test_refused_round_feedback_reaches_trace_without_model_call() -> None:
    ns = judge_namespace()
    message = "Refused closed families: volatility. open families: momentum."
    exp = SimpleNamespace(alpha_family_refusal={"message": message})
    backend = Mock(side_effect=AssertionError("a refused round must not ask a feedback model"))
    ns["APIBackend"] = backend
    result = ns["AlphaFactorFeedback"]().generate_feedback(exp, None)
    assert result.decision is False
    assert message in result.observations
    backend.assert_not_called()


def test_structural_prefix_mismatch_has_row_and_instrument() -> None:
    index = pd.MultiIndex.from_product([pd.date_range("2021-01-01", periods=2), ["A", "B"]])
    full = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}, index=index)
    result = data.compare_prefix(full, full.iloc[:3], "2021-01-02")
    assert result is not None
    assert result["date"].startswith("2021-01-02") and result["instrument"] == "B"
    assert "absolute_difference" in result and result["absolute_difference"] is None


def test_universe_receipt_binding_is_checked_before_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    path = tmp_path / "panel/panel-receipt.json"
    receipt = json.loads(path.read_text())
    receipt["universe_sha256"] = "0" * 64
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="universe.*differs"):
        data.current_universe()


def test_real_whole_panel_peek_is_reproducible_lookahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run actual factor subprocesses, replacing only the unavailable HDF serializer."""
    cut = "2021-01-02"
    index = pd.MultiIndex.from_product(
        [pd.date_range("2021-01-01", periods=4), ["A", "B"]],
        names=["datetime", "instrument"],
    )
    prices = pd.DataFrame({"close": np.arange(1.0, 9.0)}, index=index)
    source = tmp_path / cut / "daily_pv.h5"
    source.parent.mkdir()
    prices.iloc[:4].to_parquet(source)
    full = prices / prices.mean()
    monkeypatch.setattr(data, "CUTS", (cut,))

    def read(path: Path, *, key: str) -> pd.DataFrame:
        assert key == "data"
        return pd.read_parquet(path)

    monkeypatch.setattr(data.pd, "read_hdf", read)
    code = (
        b"import pandas as pd\n"
        b"f = pd.read_parquet('daily_pv.h5')\n"
        b"(f / f.mean()).to_parquet('result.h5')\n"
    )
    result = data.check_prefix_invariance(code, full, tmp_path, sys.executable, 30)
    assert result["status"] == "LOOKAHEAD"
    assert result["repeat_mismatch"] is None
    assert result["first_mismatch"]["absolute_difference"] > 0
