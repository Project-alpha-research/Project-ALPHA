"""Pure prefix comparison plus opt-in Python 3.11 RD-Agent contracts."""

# ruff: noqa: E501  (the embedded subprocess scripts are kept literal)

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
spec = importlib.util.spec_from_file_location("alpha_factor_data", WORKER / "alpha_factor_data.py")
assert spec is not None and spec.loader is not None
data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(data)


def test_prefix_comparison_includes_index_nan_and_tolerance() -> None:
    idx = pd.MultiIndex.from_product(
        [pd.date_range("2023-01-01", periods=3), ["A", "B"]], names=["datetime", "instrument"]
    )
    full = pd.DataFrame({"x": [float("nan"), 1.0, 2.0, 3.0, 4.0, 5.0]}, index=idx)
    assert data.compare_prefix(full, full.iloc[:4], "2023-01-02") is None
    changed = full.iloc[:4].copy()
    changed.loc[changed.index[1], "x"] = 1.0 + 1e-11
    assert data.compare_prefix(full, changed, "2023-01-02") is None
    changed.loc[changed.index[1], "x"] = 1.1
    assert data.compare_prefix(full, changed, "2023-01-02") is not None
    changed = full.iloc[:4].fillna(0)
    assert data.compare_prefix(full, changed, "2023-01-02") is not None
    assert data.compare_prefix(full, full.iloc[:3], "2023-01-02") is not None


RUNTIME = pytest.mark.skipif(
    not (os.environ.get("ALPHA_FACTOR_PYTHON") and os.environ.get("ALPHA_RDAGENT_SOURCE")),
    reason="requires ALPHA_FACTOR_PYTHON and ALPHA_RDAGENT_SOURCE",
)


@RUNTIME
def test_prepare_and_causal_and_leaky_factors(tmp_path: Path) -> None:
    script = r"""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, sys.argv[1])
from alpha_factor_data import prepare, check_prefix_invariance
root = Path(sys.argv[2])
dates = pd.date_range('2020-12-01', '2023-12-31')
idx = pd.MultiIndex.from_product([dates.date, ['A', 'B']], names=['date','instrument'])
f = pd.DataFrame({'open':range(1,len(idx)+1)},index=idx).reset_index()
for col in ['close','low','high','volume','quote_volume']: f[col] = f['open'].astype(float)
f.to_parquet(root/'panel.parquet',index=False)
prepare(root/'panel.parquet', root/'prepared')
assert (root/'prepared/debug/README.md').exists()
import subprocess
for expression, expected in [
 ("f.groupby(level='instrument')['$close'].pct_change(5)", 'PASS'),
 ("f.groupby(level='instrument')['$close'].shift(-1)", 'LOOKAHEAD'),
 ("(f['$close']-f['$close'].mean())/f['$close'].std()", 'LOOKAHEAD')]:
 code = ("import pandas as pd\nf=pd.read_hdf('daily_pv.h5',key='data')\ns=" + expression + "\ns.to_frame('x').to_hdf('result.h5',key='data')\n").encode()
 work=root/'full'; work.mkdir(exist_ok=True)
 if not (work/'daily_pv.h5').exists(): (work/'daily_pv.h5').symlink_to(root/'prepared/full/daily_pv.h5')
 (work/'factor.py').write_bytes(code)
 subprocess.run([sys.executable,'factor.py'],cwd=work,check=True)
 full=pd.read_hdf(work/'result.h5',key='data')
 result=check_prefix_invariance(code,full,root/'prepared/cuts',sys.executable,30)
 assert result['status'] == expected, result
"""
    subprocess.run(
        [os.environ["ALPHA_FACTOR_PYTHON"], "-I", "-B", "-c", script, str(WORKER), str(tmp_path)],
        check=True,
        cwd=tmp_path,
        timeout=180,
    )


@RUNTIME
def test_upstream_imports_and_feedback_authority(tmp_path: Path) -> None:
    script = r"""
import sys, os, json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
import alpha_factor_judge as j
from rdagent.core.developer import Developer
from rdagent.core.proposal import Experiment2Feedback
from rdagent.scenarios.qlib.experiment.factor_experiment import QlibFactorScenario
assert issubclass(j.AlphaFactorScenario,QlibFactorScenario)
assert issubclass(j.AlphaFactorRunner,Developer)
assert issubclass(j.AlphaFactorFeedback,Experiment2Feedback)
os.environ['ALPHA_FACTOR_RUN_DIR']=sys.argv[3]
panel = Path(sys.argv[3]) / 'panel'
panel.mkdir()
(panel / 'panel-receipt.json').write_text(json.dumps({'instruments': {'A': {}}}))
exp=SimpleNamespace(hypothesis=SimpleNamespace(hypothesis='test'),sub_tasks=[],stdout='ALPHA test',alpha_evaluation={'iteration':0,'decision':False})
scen=SimpleNamespace(get_scenario_all_desc=lambda:'scenario')
with patch.object(j,'APIBackend') as backend:
 backend.return_value.build_messages_and_create_chat_completion.return_value=json.dumps({'Replace Best Result':True})
 fb=j.AlphaFactorFeedback(scen).generate_feedback(exp,None)
 assert fb.decision is False
row=json.loads((Path(sys.argv[3])/'feedback.jsonl').read_text())
assert row['model_decision'] is True and row['alpha_decision'] is False
assert 'reply' not in row
round_row=json.loads((Path(sys.argv[3])/'rounds.jsonl').read_text())
assert round_row['schema']=='AlphaRdagentRoundV1'
assert round_row['hypothesis']['hypothesis']=='test'
assert round_row['hypothesis']['concise_reason'] is None
assert round_row['model_decision'] is True and round_row['alpha_decision'] is False
runner=j.AlphaFactorRunner(scen)
base=SimpleNamespace(based_experiments=[],sub_tasks=[],result=None,stdout='')
runner.develop(base)
labels=['IC','1day.excess_return_without_cost.annualized_return','1day.excess_return_without_cost.max_drawdown']
assert list(base.result.loc[labels].index)==labels
"""
    subprocess.run(
        [
            os.environ["ALPHA_FACTOR_PYTHON"],
            "-I",
            "-B",
            "-c",
            script,
            str(WORKER),
            os.environ["ALPHA_RDAGENT_SOURCE"],
            str(tmp_path),
        ],
        check=True,
        cwd=tmp_path,
        timeout=60,
    )


def test_hypothesis_context_shows_imported_and_exposed_v2_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    namespace = swing_parts()
    ledger = tmp_path / "trials.jsonl"
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": "old",
            "code_sha256": "a" * 64,
            "status": "FAILED",
            "screen": {},
            "q": 1.0,
            "run_id": "old-run",
        },
        {
            "schema": "AlphaRdagentFactorTrialV2",
            "name": "imported",
            "code_sha256": "b" * 64,
            "status": "IMPORTED",
            "screen": {},
            "q": 1.0,
            "run_id": "external",
            "exposure": {"previously_exposed": True},
        },
        {
            "schema": "AlphaRdagentFactorTrialV2",
            "name": "repeat",
            "code_sha256": "b" * 64,
            "status": "REPEAT",
            "screen": {},
            "q": 1.0,
            "run_id": "new",
            "exposure": {"previously_exposed": True},
        },
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    context, flag = namespace["AlphaFactorHypothesisGen"]().prepare_context(None)
    assert flag is True
    summary = context["hypothesis_and_feedback"]
    assert (
        "imported: IMPORTED; mean rank IC not available; q 1; run external; "
        "protected window previously exposed" in summary
    )
    assert "old: FAILED; mean rank IC not available; q 1; run old-run" in summary
    assert "repeat:" not in summary


def judge_parts(*names: str) -> dict[str, Any]:
    import ast
    import hashlib
    import json
    from typing import Any

    tree = ast.parse((WORKER / "alpha_factor_judge.py").read_text())
    nodes: list[ast.stmt] = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        and (
            n.name in names
            or (
                ("AlphaFactorRunner" in names or "record_coder_verdicts" in names)
                and n.name
                in {"record_coder_verdicts", "_record_coder_verdicts", "family_definitions"}
            )
        )
    ]
    namespace = {
        "Any": Any,
        "Path": Path,
        "hashlib": hashlib,
        "os": os,
        "json": json,
        "pd": pd,
        "re": importlib.import_module("re"),
        "subprocess": subprocess,
        "sys": sys,
        "Developer": object,
        "FactorEmptyError": ValueError,
        "current_universe": lambda: "15 instruments; survivors-only synthetic fixture",
        "LEGACY_KEYS": ["IC"],
        "VIEWER_KEYS": [],
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<judge-evidence>", "exec"), namespace)
    return namespace


def test_runner_archives_code_exclusively_and_refuses_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import json
    from types import SimpleNamespace

    namespace = judge_parts("record_code", "AlphaFactorRunner")
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("ALPHA_FACTOR_EVAL_PYTHON", "unused-python")
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", "unused-ledger")
    code = 'print("factor bytes")\n'
    digest = hashlib.sha256(code.encode()).hexdigest()

    def evaluator(command: list[str], **kwargs: object) -> SimpleNamespace:
        path = Path(command[command.index("--out") + 1])
        path.write_text(json.dumps({"legacy_result": {"IC": 0}, "feedback_text": "test"}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", evaluator)
    task = SimpleNamespace(
        factor_name="test",
        description="declared_direction: +1; primary_clock: weekly; direction_reason: Persistence.",
        get_task_information=lambda: "proposal",
    )
    workspace = SimpleNamespace(file_dict={"factor.py": code})
    exp = SimpleNamespace(
        based_experiments=[],
        sub_tasks=[task],
        sub_workspace_list=[workspace],
        prop_dev_feedback=[False],
        hypothesis="test",
    )
    runner = namespace["AlphaFactorRunner"]()
    with pytest.raises(ValueError, match="every factor as FAILED"):
        runner.develop(exp)
    # The request carries the family the tally counts, so the ledger row stores it verbatim.
    sent = json.loads((tmp_path / "evaluations/iter-0/request.json").read_text())["factors"][0]
    assert sent["family"] == namespace["family_definitions"]().idea_family(
        "test", task.description, "", None
    )
    assert sent["family"] == "other: test"
    assert sent["critic_status"] == "unavailable"
    archive = tmp_path / "code" / f"{digest}.py"
    assert archive.read_bytes() == code.encode()
    before = archive.stat().st_mtime_ns
    with pytest.raises(ValueError, match="every factor as FAILED"):
        runner.develop(exp)
    assert archive.stat().st_mtime_ns == before
    archive.write_bytes(b"conflict")
    with pytest.raises(ValueError, match="conflict"):
        runner.develop(exp)
    assert archive.read_bytes() == b"conflict"
    workspace.file_dict = {}
    with pytest.raises(ValueError, match="every factor as FAILED"):
        runner.develop(exp)
    assert list((tmp_path / "code").iterdir()) == [archive]


def test_round_text_retains_words_and_factor_hashes(tmp_path: Path) -> None:
    import json
    from types import SimpleNamespace

    namespace = judge_parts("record_round")
    exp = SimpleNamespace(
        hypothesis=SimpleNamespace(hypothesis="  exact\nidea ", reason="why"),
        sub_tasks=[
            SimpleNamespace(
                factor_name="vol_7d",
                description="  RD words\n",
                factor_formulation="x / y",
                variables={"x": "price"},
            )
        ],
        alpha_evaluation={
            "factors": [
                {
                    "name": "vol_7d",
                    "code_sha256": "a" * 64,
                    "family": "volatility and beta",
                    "critic_status": "skipped",
                    "critic_reason": "earlier provider timeout",
                }
            ]
        },
    )
    feedback = SimpleNamespace(
        observations="unchanged\n",
        hypothesis_evaluation="maybe",
        new_hypothesis="next",
        reason="because",
    )
    row = {
        "iteration": 4,
        "model_decision": True,
        "alpha_decision": False,
        "reply_sha256": "b" * 64,
    }
    namespace["record_round"](tmp_path, exp, feedback, row)
    raw = (tmp_path / "rounds.jsonl").read_text()
    record = json.loads(raw)
    assert record["schema"] == "AlphaRdagentRoundV1"
    assert all(record[k] == v for k, v in row.items())
    assert record["hypothesis"] == {
        "hypothesis": "  exact\nidea ",
        "reason": "why",
        "concise_reason": None,
        "concise_observation": None,
        "concise_justification": None,
        "concise_knowledge": None,
    }
    assert record["tasks"] == [
        {
            "name": "vol_7d",
            "description": "  RD words\n",
            "formulation": "x / y",
            "variables": {"x": "price"},
            "code_sha256": "a" * 64,
            "family": "volatility and beta",
            "critic_status": "skipped",
            "critic_reason": "earlier provider timeout",
        }
    ]
    assert record["feedback"] == vars(feedback)
    assert raw == json.dumps(record, sort_keys=True) + "\n"


def swing_parts() -> dict[str, Any]:
    import ast
    import json

    tree = ast.parse((WORKER / "alpha_factor_judge.py").read_text())
    names = {
        "append_swing_context",
        "family_definitions",
        "known_families",
        "ledger_summary",
        "replay_note",
        "_rounded",
        "AlphaFactorHypothesisGen",
        "idea_family",
        "input_families",
        "name_tokens",
        "name_family",
        "name_matches",
        "family_permissions",
        "percent",
        "spread_line",
        "_rank",
        "family_summary",
        "append_ledger_context",
    }
    nodes: list[ast.stmt] = [
        n
        for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
        or (
            isinstance(n, ast.Assign)
            and any(
                isinstance(t, ast.Name)
                and t.id
                in (
                    "DECLARATION_TEMPLATE",
                    "SWING_BRIEF",
                    "FAMILY_KEYWORDS",
                    "COMPOSITE",
                    "WEAK_COMPOSITE",
                    "WINDOW_ONLY",
                    "FAMILY_REFUSALS",
                )
                for t in n.targets
            )
        )
    ]

    class Base:
        def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
            return {"hypothesis_and_feedback": "Existing context"}, True

    import re

    namespace = {
        "Any": Any,
        "Path": Path,
        "os": os,
        "re": re,
        "json": json,
        "QlibFactorHypothesisGen": Base,
        "current_universe": lambda: "15 instruments; survivors-only synthetic fixture",
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<swing-context>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("ledger_kind", ["absent", "empty", "v3"])
def test_swing_brief_always_precedes_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ledger_kind: str
) -> None:
    import json

    namespace = swing_parts()
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    if ledger_kind != "absent":
        monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
        ledger.write_text("")
    if ledger_kind == "v3":
        row = {
            "schema": "AlphaRdagentFactorTrialV3",
            "name": "slow",
            "code_sha256": "a" * 64,
            "status": "CANDIDATE",
            "lead_clock": "monthly",
            "clocks": {
                c: {
                    "status": "PASS" if c == "monthly" else "SCREEN_FAIL",
                    "screen": {"mean_ic": 0.2},
                    "q": 0.03,
                }
                for c in ("daily", "weekly", "monthly")
            },
            "exposure": {"previously_exposed": False},
        }
        ledger.write_text(json.dumps(row) + "\n")
    context, flag = namespace["AlphaFactorHypothesisGen"]().prepare_context(None)
    brief = namespace["SWING_BRIEF"]
    assert flag and len(brief) < 1800
    assert context["hypothesis_and_feedback"].startswith("Existing context\n" + brief)
    for wanted in (
        "retail swing",
        "never high frequency",
        "7-day",
        "28-day",
        "low turnover",
        "mechanism",
        "falsifier",
        "10 bps",
        "6 bps",
        "29%",
        "19%-79%",
        "not admitted",
    ):
        assert wanted in brief
    pure = {"hypothesis_and_feedback": "Existing context"}
    namespace["append_swing_context"](pure, str(ledger) if ledger_kind != "absent" else None)
    assert pure == context
    if ledger_kind == "v3":
        assert (
            "slow: CANDIDATE (daily SCREEN_FAIL, weekly SCREEN_FAIL, monthly PASS); lead monthly IC 0.2; q 0.03"
            in context["hypothesis_and_feedback"]
        )
        assert context["hypothesis_and_feedback"].index(brief) < context[
            "hypothesis_and_feedback"
        ].index("ALPHA trial ledger")


def _v3_row(name: str, digest: str, replay: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "AlphaRdagentFactorTrialV3",
        "name": name,
        "code_sha256": digest,
        "status": "REPLAY_FAIL",
        "lead_clock": "daily",
        "clocks": {
            c: {
                "status": "REPLAY_FAIL" if c == "daily" else "SCREEN_FAIL",
                "screen": {"mean_ic": -0.026404332182201326},
                "q": 5.8109182375914446e-08,
                "replay": replay if c == "daily" else {},
            }
            for c in ("daily", "weekly", "monthly")
        },
        "exposure": {"previously_exposed": False},
    }


def test_ledger_summary_says_why_a_replay_lost() -> None:
    """A replay failure tells the proposer whether it lost before or only after costs."""
    replay = {
        "gross": {"annualized_return": -0.2771},
        "net": {"annualized_return": -0.3125},
        "annual_cost": 0.0368,
        "mean_turnover": 0.0612,
    }
    line = swing_parts()["ledger_summary"](_v3_row("volatility_60d", "a" * 64, replay))
    assert line == (
        "volatility_60d: REPLAY_FAIL (daily REPLAY_FAIL, weekly SCREEN_FAIL, monthly SCREEN_FAIL); "
        "lead daily IC -0.0264; q 5.811e-08; daily replay: -27.71%/yr before costs, -31.25%/yr after "
        "3.68%/yr costs, turnover 6.12%/day; daily deflated Sharpe not recorded"
    )
    malformed = _v3_row("broken", "b" * 64, {"gross": {}})
    with pytest.raises(KeyError):
        swing_parts()["ledger_summary"](malformed)


def test_ledger_summary_keeps_whole_lines_and_counts_the_rest(tmp_path: Path) -> None:
    """The 4000-character budget never cuts a trial in half and says how many were left out."""
    import json

    ledger = tmp_path / "ledger.jsonl"
    replay = {
        "gross": {"annualized_return": 0.1},
        "net": {"annualized_return": 0.05},
        "annual_cost": 0.05,
        "mean_turnover": 0.1,
    }
    rows = [_v3_row(f"factor_{i:02d}_" + "x" * 60, f"{i:064x}", replay) for i in range(40)]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    context = {"hypothesis_and_feedback": ""}
    namespace = swing_parts()
    namespace["append_swing_context"](context, str(ledger))
    summary = context["hypothesis_and_feedback"].split("ALPHA trial ledger", 1)[1]
    shown = [line for line in summary.splitlines()[1:] if line.startswith("factor_")]
    assert len(summary) <= 4000
    assert all(line.endswith("deflated Sharpe not recorded") for line in shown)
    assert shown[0].startswith("factor_39_")  # newest first
    assert summary.rstrip().endswith(
        f"({40 - len(shown)} older distinct factors not shown)\n"
        "Current universe: 15 instruments; survivors-only synthetic fixture; "
        "earlier text saying otherwise is out of date"
    )


@RUNTIME
def test_real_proposer_gets_swing_brief_with_and_without_ledger(tmp_path: Path) -> None:
    script = r"""
import sys, os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
import alpha_factor_judge as j
with patch.object(j.QlibFactorHypothesisGen, 'prepare_context', return_value=({'hypothesis_and_feedback': ''}, True)):
 gen = object.__new__(j.AlphaFactorHypothesisGen)
 os.environ.pop('ALPHA_FACTOR_TRIAL_LEDGER', None)
 assert j.SWING_BRIEF in gen.prepare_context(None)[0]['hypothesis_and_feedback']
 ledger = Path(sys.argv[3]) / 'ledger.jsonl'
 ledger.write_text('')
 os.environ['ALPHA_FACTOR_TRIAL_LEDGER'] = str(ledger)
 assert j.SWING_BRIEF in gen.prepare_context(None)[0]['hypothesis_and_feedback']
"""
    subprocess.run(
        [
            os.environ["ALPHA_FACTOR_PYTHON"],
            "-I",
            "-B",
            "-c",
            script,
            str(WORKER),
            os.environ["ALPHA_RDAGENT_SOURCE"],
            str(tmp_path),
        ],
        check=True,
        cwd=tmp_path,
        timeout=60,
    )


def test_hypothesis_summary_skips_rule_families(tmp_path: Path) -> None:
    import json

    namespace = swing_parts()
    ledger = tmp_path / "ledger"
    ledger.write_text(json.dumps({"schema": "AlphaRuleTrialV1", "name": "human-rule"}) + "\n")
    context = {"hypothesis_and_feedback": ""}
    namespace["append_swing_context"](context, str(ledger))
    assert "human-rule" not in context["hypothesis_and_feedback"]


def test_hypothesis_skips_unknown_rows_but_refuses_malformed_known(tmp_path: Path) -> None:
    import json

    namespace = swing_parts()
    ledger = tmp_path / "ledger"
    rows = [{"schema": name} for name in ("FutureB", "FutureA", "FutureB")]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows) + '{"schema":')
    context = {"hypothesis_and_feedback": ""}
    namespace["append_swing_context"](context, str(ledger))
    assert (
        "3 ledger rows of other kinds were skipped (FutureA, FutureB)"
        in context["hypothesis_and_feedback"]
    )
    malformed_rows: tuple[object, ...] = (
        {"schema": "AlphaRdagentFactorTrialV1"},
        [],
        {"schema": None},
    )
    for row in malformed_rows:
        ledger.write_text(json.dumps(row) + "\n")
        with pytest.raises((ValueError, KeyError, TypeError)):
            namespace["append_swing_context"]({"hypothesis_and_feedback": ""}, str(ledger))


@pytest.mark.parametrize("persistent", [True, False])
@pytest.mark.parametrize("evaluator_failure", [True, False])
def test_runner_records_code_verdicts_before_evaluator_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, persistent: bool, evaluator_failure: bool
) -> None:
    import hashlib
    import json
    from types import SimpleNamespace as NS

    namespace = judge_parts("record_code", "record_coder_verdicts", "AlphaFactorRunner")
    for key, value in {
        "ALPHA_FACTOR_RUN_DIR": str(tmp_path),
        "ALPHA_FACTOR_CODE_PYTHON": "unused",
        "ALPHA_FACTOR_EVAL_PYTHON": "unused",
        "ALPHA_FACTOR_TRIAL_LEDGER": "unused",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def demote(
        environ: Any, tasks: list[str], digests: list[str] | None = None
    ) -> tuple[list[str], str | None]:
        calls.append(tasks)
        assert digests is not None and len(digests) == len(tasks)  # exact code identity
        return (tasks, None) if persistent else ([], "no persistent coding memory")

    namespace["demote_in_file"] = demote
    checks = iter([{"status": "LOOKAHEAD"}, {"status": "PASS"}, {"status": "PASS"}])
    namespace["check_prefix_invariance"] = lambda *args: next(checks)
    names = ["leaky", "shape", "screen_fail", "no_code", "not_run", "execution_failed"]
    tasks = [
        NS(
            factor_name=n,
            get_task_information=lambda n=n: n,
            description="declared_direction: +1; primary_clock: weekly; direction_reason: Demand persists.",
        )
        for n in names
    ]
    workspaces: list[NS | None] = [
        NS(
            file_dict={"factor.py": n},
            execute=lambda _, n=n: (
                "ran",
                None
                if n == "execution_failed"
                else pd.DataFrame(
                    {"a": [1], **({"b": [2]} if n == "shape" else {})},
                    index=pd.MultiIndex.from_tuples([("2023-01-01", "A")]),
                ),
            ),
        )
        for n in names
    ]
    workspaces[3] = None
    exp = NS(
        based_experiments=[],
        sub_tasks=tasks,
        sub_workspace_list=workspaces,
        prop_dev_feedback=[True, True, True, False, False, True],
        hypothesis="idea",
    )

    def evaluator(command: list[str], **kwargs: Any) -> NS:
        if evaluator_failure:
            return NS(returncode=1, stderr="evaluation failed")
        path = Path(command[command.index("--out") + 1])
        path.write_text(
            json.dumps(
                {
                    "legacy_result": {"IC": 0},
                    "feedback_text": "screen rejected the idea",
                    "factors": [{"name": "screen_fail", "status": "SCREEN_FAIL"}],
                }
            )
        )
        return NS(returncode=0)

    monkeypatch.setattr(subprocess, "run", evaluator)
    if evaluator_failure:
        with pytest.raises(ValueError, match="evaluation failed"):
            namespace["AlphaFactorRunner"]().develop(exp)
    else:
        namespace["AlphaFactorRunner"]().develop(exp)
        assert exp.alpha_evaluation["factors"][0]["status"] == "SCREEN_FAIL"
    assert calls == [["leaky", "shape"]]
    rows = [
        json.loads(line) for line in (tmp_path / "coder-verdicts.jsonl").read_text().splitlines()
    ]
    assert [r["status"] for r in rows] == ["LOOKAHEAD", "FAILED"]
    for row, name in zip(rows, names[:2], strict=True):
        assert row == {
            "schema": "AlphaCoderVerdictV1",
            "iteration": 0,
            "name": name,
            "code_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "status": row["status"],
            "task_information_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "demoted": persistent,
            "note": None if persistent else "no persistent coding memory",
        }


def _spread(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "top_third_mean_return": -0.004,
        "bottom_third_mean_return": 0.003,
        "annualized_spread": -0.36,
        "t": -1.6,
        "top_share_changed_per_rebalance": 0.12,
        "estimated_annual_cost": 0.05,
    }


def test_rejected_factor_line_gives_spread_turnover_and_cost() -> None:
    row = _v3_row("volatility_60d", "a" * 64, {})
    row["status"] = "SPREAD_FAIL"
    row["clocks"]["daily"].update(status="SPREAD_FAIL", spread=_spread("FAIL"), replay={})
    row["clocks"]["weekly"]["spread"] = _spread("PASS")  # screen failed: not repeated
    line = swing_parts()["ledger_summary"](row)
    assert line.endswith(
        "daily spread FAIL: top third -0.4% vs bottom +0.3% per hold (-36%/yr before costs, "
        "t -1.6), top third changes 12% per rebalance, about 5%/yr costs"
    )
    assert "weekly spread" not in line


def test_family_summary_groups_all_families_and_says_when_to_move_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    names = [
        "high_prox_126d_skip5",
        "high_prox_126d_skip10",
        "stoch_252d_rangepos",
        "amihud_illiquidity_28d",
        "amihud_illiquidity_60d",
        "skewness_60d",
    ]
    rows = [_v3_row(n, f"{i:064x}", {}) for i, n in enumerate(names)]
    for row in rows:
        row["status"] = "SCREEN_FAIL"
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows))
    namespace = swing_parts()
    for switch_after, closed in ((3, ["price near its high / range position"]), (2, None)):
        monkeypatch.setenv("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", str(switch_after))
        context = {"hypothesis_and_feedback": ""}
        namespace["append_swing_context"](context, str(ledger))
        text = context["hypothesis_and_feedback"]
        assert "- price near its high / range position: 3 tries; best " in text
        assert "- illiquidity: 2 tries" in text
        assert "- skewness and lottery returns: 1 try" in text
        assert text.index("ALPHA idea families") < text.index("ALPHA trial ledger")
        moved = text.split("no candidate: ", 1)[1].split(". Do not propose", 1)[0]
        if closed:
            assert moved.split("; ") == closed
        else:
            assert set(moved.split("; ")) == {
                "price near its high / range position",
                "illiquidity",
            }
        assert "move to a different family" in text


def test_idea_family_keywords_on_the_health_check_names() -> None:
    family = swing_parts()["idea_family"]
    assert family("vol_scaled_high_prox_252d") == "price near its high / range position"
    assert family("beta_hedged_momentum_28d_btc") == "past return (momentum or reversal)"
    assert family("downside_semivariance_120d") == "volatility and beta"
    assert family("ret_vol_corr_28d") == "return-volume relation"
    assert family("max_return_28d") == "skewness and lottery returns"
    assert family("mystery_signal") == "other: mystery_signal"
    # 2026-11-16 run: the model abbreviated "high proximity" as hp126
    assert family("hp126_skip10_lowvol") == "price near its high / range position"
    assert family("hp126_skip10_lowskew") == "price near its high / range position"


def test_a_counted_only_replay_is_never_shown_to_the_proposer_as_a_result() -> None:
    replay = {
        "gross": {"annualized_return": 0.5},
        "net": {"annualized_return": 0.4},
        "annual_cost": 0.01,
        "mean_turnover": 0.01,
        "counted_only": "spread check FAIL; replayed only to count the trial, not a result",
    }
    note = swing_parts()["replay_note"]("weekly", replay)
    assert note == "; weekly replay counted only, not a result"
    assert "%" not in note


def test_failure_message_never_prints_none_for_the_difference() -> None:
    """Old rows lack the difference; structural or non-finite mismatches have none to give."""
    from alpha_cli._rdagent_stability import failure_message

    base = {"cut": "2020-12-31", "date": "2019-02-01", "instrument": "ADAUSDT"}
    old = failure_message({"status": "LOOKAHEAD", "lookahead": {"first_mismatch": base}})
    none = failure_message(
        {
            "status": "LOOKAHEAD",
            "lookahead": {"first_mismatch": {**base, "absolute_difference": None}},
        }
    )
    value = failure_message(
        {
            "status": "UNSTABLE",
            "lookahead": {"first_mismatch": {**base, "absolute_difference": 0.25}},
        }
    )
    assert "None" not in old + none
    assert "absolute difference not recorded" in old
    assert "absolute difference not computable" in none
    assert "absolute difference 0.25" in value


@pytest.mark.parametrize(
    "feedback,expected",
    [
        (
            SimpleNamespace(
                execution_feedback="ValueError: bad input\ntrace", final_decision=False
            ),
            "exception",
        ),
        (
            SimpleNamespace(execution_feedback="call cap reached", final_decision=False),
            "cap_reached",
        ),
        (
            SimpleNamespace(
                execution_feedback='Traceback (most recent call last):\n  File "factor.py", '
                "line 3\nKeyError: 'close'",
                final_decision=False,
            ),
            "exception",
        ),
        (
            SimpleNamespace(
                execution_feedback="Code ran; the output looks wrong.", final_decision=False
            ),
            "critic_rejected",
        ),
    ],
)
def test_runner_keeps_execution_reason_before_critic(feedback: Any, expected: str) -> None:
    class Feedback:
        execution_feedback = feedback.execution_feedback

        def __bool__(self) -> bool:
            return False

    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    values, reason, detail = cls.execute_factor(Mock(), Feedback())
    assert values is None and reason == expected
    assert "\n" not in detail and not detail.startswith("Traceback")
    if "Traceback" in feedback.execution_feedback:
        assert detail == "KeyError: 'close'"


def test_runner_records_exception_and_bad_shape() -> None:
    cls = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    workspace = Mock()
    workspace.execute.side_effect = ValueError("broken first line\nsecond line")
    assert cls.execute_factor(workspace, True) == (
        None,
        "exception",
        "ValueError: broken first line",
    )
    workspace.execute.side_effect = None
    workspace.execute.return_value = ("ran", pd.DataFrame({"a": [1], "b": [2]}))
    assert cls.execute_factor(workspace, True)[1] == "bad_output"
    assert cls.execute_factor(workspace, False)[1] == "critic_rejected"


def test_bad_factor_format_is_recorded_before_prefix_check() -> None:
    frame = pd.DataFrame(
        {"factor": ["not numeric"]}, index=pd.MultiIndex.from_tuples([("bad date", "A")])
    )
    workspace = Mock()
    workspace.execute.return_value = ("ran", frame)
    runner = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    assert runner.execute_factor(workspace, True)[1] == "bad_output"


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


def test_structural_prefix_mismatch_has_row_and_instrument() -> None:
    index = pd.MultiIndex.from_product([pd.date_range("2021-01-01", periods=2), ["A", "B"]])
    full = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]}, index=index)
    result = data.compare_prefix(full, full.iloc[:3], "2021-01-02")
    assert result is not None
    assert result["date"].startswith("2021-01-02") and result["instrument"] == "B"
    assert "absolute_difference" in result and result["absolute_difference"] is None


def test_real_whole_panel_peek_is_reproducible_lookahead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run actual pandas factor subprocesses, replacing only the unavailable HDF serializer.

    Pickle stands in for HDF: Parquet starts pyarrow threads that sometimes abort the child at
    exit under load (exit -6, "terminate called without an active exception")."""
    cut = "2021-01-02"
    index = pd.MultiIndex.from_product(
        [pd.date_range("2021-01-01", periods=4), ["A", "B"]],
        names=["datetime", "instrument"],
    )
    prices = pd.DataFrame({"close": np.arange(1.0, 9.0)}, index=index)
    source = tmp_path / cut / "daily_pv.h5"
    source.parent.mkdir()
    prices.iloc[:4].to_pickle(source)
    full = prices / prices.mean()
    monkeypatch.setattr(data, "CUTS", (cut,))

    def read(path: Path, *, key: str) -> pd.DataFrame:
        assert key == "data"
        frame = pd.read_pickle(path)
        assert isinstance(frame, pd.DataFrame)
        return frame

    monkeypatch.setattr(data.pd, "read_hdf", read)
    code = (
        b"import pandas as pd\n"
        b"f = pd.read_pickle('daily_pv.h5')\n"
        b"(f / f.mean()).to_pickle('result.h5')\n"
    )
    result = data.check_prefix_invariance(code, full, tmp_path, sys.executable, 30)
    assert result["status"] == "LOOKAHEAD", result
    assert result["repeat_mismatch"] is None
    assert result["first_mismatch"]["absolute_difference"] > 0


def test_model_text_missing_and_small_figures() -> None:
    from tests.unit._rdagent_support import judge_namespace

    ns = judge_namespace()
    assert ns["_rounded"](None) == "not available"
    assert ns["_rounded"](0.00001234567) == "1.235e-05"
    note = ns["replay_note"](
        "weekly",
        {
            "gross": {"annualized_return": 0.123456},
            "net": {"annualized_return": 0.1},
            "annual_cost": 0.0000123456,
            "mean_turnover": 0.00000123456,
        },
    )
    assert "12.35%" in note and "0.001235%" in note and "0.0001235%" in note


def test_runner_records_reviewed_skipped_and_unavailable_critic() -> None:
    from types import SimpleNamespace

    runner = judge_parts("AlphaFactorRunner")["AlphaFactorRunner"]
    for opinion, marker, status in [
        ("checked implementation", None, "reviewed"),
        ("Final decision is True and there are no code critics.", None, "skipped"),
        (
            "code critic unavailable (provider timeout); judged on execution only",
            "unavailable",
            "unavailable",
        ),
        (
            "code critic unavailable (provider timeout); judged on execution only",
            "skipped",
            "skipped",
        ),
    ]:
        feedback = SimpleNamespace(code_feedback=opinion, alpha_critic_status=marker)
        fields = runner.critic_fields(feedback)
        assert fields["critic_status"] == status
        if status != "reviewed":
            assert opinion in fields["critic_reason"]
