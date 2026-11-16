"""Pure prefix comparison plus opt-in Python 3.11 RD-Agent contracts."""

# ruff: noqa: E501  (the embedded subprocess scripts are kept literal)

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

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
        "imported: IMPORTED; mean rank IC None; q 1.0; run external; protected window previously exposed"
        in summary
    )
    assert "old: FAILED; mean rank IC None; q 1.0; run old-run" in summary
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
                and n.name in {"record_coder_verdicts", "_record_coder_verdicts"}
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
        "subprocess": subprocess,
        "sys": sys,
        "Developer": object,
        "FactorEmptyError": ValueError,
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
    task = SimpleNamespace(factor_name="test", get_task_information=lambda: "proposal")
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
        alpha_evaluation={"factors": [{"name": "vol_7d", "code_sha256": "a" * 64}]},
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
        "ledger_summary",
        "replay_note",
        "_rounded",
        "AlphaFactorHypothesisGen",
    }
    nodes: list[ast.stmt] = [
        n
        for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
        or (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "SWING_BRIEF" for t in n.targets)
        )
    ]

    class Base:
        def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
            return {"hypothesis_and_feedback": "Existing context"}, True

    namespace = {"Any": Any, "Path": Path, "os": os, "json": json, "QlibFactorHypothesisGen": Base}
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
        "lead daily IC -0.026; q 0.0; daily replay: -28%/yr before costs, -31%/yr after "
        "4%/yr costs, turnover 6%/day"
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
    assert all(line.endswith("turnover 10%/day") for line in shown)
    assert shown[0].startswith("factor_39_")  # newest first
    assert summary.rstrip().endswith(f"({40 - len(shown)} older distinct factors not shown)")


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
    tasks = [NS(factor_name=n, get_task_information=lambda n=n: n) for n in names]
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
