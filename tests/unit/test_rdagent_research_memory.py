"""Persistent RD-Agent knowledge and trace contracts, with opt-in runtime coverage."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
sys.path.insert(0, str(WORKER))
memory = importlib.import_module("research_memory")


def prepare(root: Path, run_id: str = "one", **kwargs: str) -> Any:
    return memory.prepare(
        root / "memory",
        run_id=run_id,
        run_dir=root / run_id,
        source_sha256=kwargs.get("source", "source"),
        judge_sha256=kwargs.get("judge", "judge"),
    )


def session(root: Path, run_id: str = "one", record: bool = True) -> Path:
    path = root / run_id / "work/log/__session__/0"
    path.mkdir(parents=True)
    (path / ("4_record" if record else "0_propose")).write_bytes(b"checkpoint")
    return path.parent


def record(
    plan: Any, root: Path, run_id: str = "one", secrets: tuple[str, ...] = ()
) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        memory.record(
            plan,
            run_id=run_id,
            run_dir=root / run_id,
            started_at="start",
            ended_at="end",
            secrets=secrets,
        ),
    )


def manifest(root: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads((root / "memory/memory.json").read_text()))


def codes(rows: list[dict[str, Any]]) -> set[str]:
    return {row["code"] for row in rows}


def test_prepare_fresh_exact_environment_and_loop_count(tmp_path: Path) -> None:
    plan = prepare(tmp_path)
    base = tmp_path / "memory"
    assert plan.env == {
        "FACTOR_CoSTEER_knowledge_base_path": str(base / "costeer/factor-knowledge.pkl"),
        "FACTOR_CoSTEER_new_knowledge_base_path": str(base / "costeer/factor-knowledge.pkl"),
        "FACTOR_CoSTEER_enable_filelock": "True",
        "FACTOR_CoSTEER_filelock_path": str(base / "costeer/factor-knowledge.lock"),
        "ARTIFACT_SIGNING_KEY_PATH": str(base / "signing/artifact_signing.key"),
        "ALPHA_RDAGENT_MEMORY_DIR": str(base),
        "ALPHA_RDAGENT_MEMORY_EVENTS": str(tmp_path / "one/memory-events.jsonl"),
    }
    assert plan.continue_from is None and plan.loops_before == 0
    assert manifest(tmp_path)["schema"] == "AlphaRdagentResearchMemoryV1"
    assert not (base / "signing/artifact_signing.key").exists()
    path = session(tmp_path)
    for name in ["1", "two", "2"]:
        (path / name).mkdir()
    (path / "1/0_propose").touch()
    (path / "two/4_record").touch()
    (path / "2/4_record").mkdir()
    assert memory.completed_loops(path) == 1
    continued = tmp_path / "continued/__session__"
    for name in ("2", "3"):
        (continued / name).mkdir(parents=True)
        (continued / name / "4_record").touch()
    assert memory.completed_loops(continued) == 4


@pytest.mark.parametrize("raw", ["broken", "[]", '{"schema":"wrong"}', None])
def test_prepare_quarantines_unreadable(tmp_path: Path, raw: str | None) -> None:
    plan = prepare(tmp_path)
    path = tmp_path / "memory/memory.json"
    if raw is None:
        value = manifest(tmp_path)
        value["runs"] = ["invalid"]
        raw = json.dumps(value)
    path.write_text(raw)
    knowledge = Path(plan.env["FACTOR_CoSTEER_knowledge_base_path"])
    knowledge.write_bytes(b"old knowledge")
    recovered = prepare(tmp_path)
    assert codes(recovered.warnings) == {"memory-unreadable"}
    assert not knowledge.exists()
    quarantined = list((tmp_path / "memory/quarantine").glob("*/costeer/factor-knowledge.pkl"))
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == b"old knowledge"
    assert manifest(tmp_path)["runs"] == []


def test_record_continuation_versions_and_events(tmp_path: Path) -> None:
    plan = prepare(tmp_path)
    path = session(tmp_path)
    event = {
        "schema": "AlphaRdagentMemoryEventV1",
        "code": "continued",
        "message": "continued",
        "ts": "now",
    }
    (tmp_path / "one/memory-events.jsonl").write_text(json.dumps(event) + "\n")
    result = record(plan, tmp_path)
    assert result["enabled"] and result["loops_after"] == 1
    assert "continued" in codes(result["warnings"])
    assert manifest(tmp_path)["latest_session"]["session_dir"] == str(path)
    assert len(manifest(tmp_path)["runs"]) == 1
    next_plan = prepare(tmp_path, "two", judge="new judge")
    assert next_plan.loops_before == 1
    assert next_plan.env["ALPHA_RDAGENT_CONTINUE_LOOPS"] == "1"
    assert codes(next_plan.warnings) == {"judge-version-changed"}
    knowledge = Path(plan.env["FACTOR_CoSTEER_knowledge_base_path"])
    knowledge.write_bytes(b"knowledge")
    newer = prepare(tmp_path, "three", source="new source")
    assert codes(newer.warnings) == {"rdagent-version-changed"}
    assert newer.continue_from is None and not knowledge.exists()
    assert len(manifest(tmp_path)["runs"]) == 1


@pytest.mark.parametrize("missing", [True, False])
def test_previous_missing_or_without_completed_loop(tmp_path: Path, missing: bool) -> None:
    plan = prepare(tmp_path)
    path = session(tmp_path)
    record(plan, tmp_path)
    assert manifest(tmp_path)["latest_session"]["completed_loops"] == 1
    if missing:
        shutil.rmtree(path)
    else:
        (path / "0/4_record").unlink()
    next_plan = prepare(tmp_path, "two")
    assert next_plan.continue_from is None
    assert codes(next_plan.warnings) == {"previous-session-missing"}


def test_crashed_run_keeps_the_previous_pointer(tmp_path: Path) -> None:
    plan = prepare(tmp_path)
    session(tmp_path)
    record(plan, tmp_path)
    plan = prepare(tmp_path, "two")
    assert plan.loops_before == 1
    crashed = tmp_path / "two/work/log/__session__/1"
    crashed.mkdir(parents=True)
    (crashed / "0_direct_exp_gen").write_bytes(b"half a loop")
    (tmp_path / "two/memory-events.jsonl").write_text('{"schema": "AlphaRdagent')  # cut off
    result = record(plan, tmp_path, "two")
    assert "memory-event-corrupt" in codes(result["warnings"])
    assert "memory-record-failed" not in codes(result["warnings"])
    assert manifest(tmp_path)["latest_session"]["run_id"] == "one"
    assert len(manifest(tmp_path)["runs"]) == 2
    # A continued run that finished no new round keeps the lineage's count, not 0.
    assert result["loops_after"] == 1
    assert manifest(tmp_path)["runs"][-1]["loops_after"] == 1


@pytest.mark.parametrize("location", ["knowledge", "session"])
def test_secret_deleted_without_new_metadata_leak(tmp_path: Path, location: str) -> None:
    plan = prepare(tmp_path)
    session(tmp_path)
    record(plan, tmp_path)
    previous = manifest(tmp_path)["latest_session"]
    plan = prepare(tmp_path, "two")
    path = session(tmp_path, "two")
    secret = "planted-secret-value"
    knowledge = Path(plan.env["FACTOR_CoSTEER_knowledge_base_path"])
    knowledge.write_bytes(secret.encode() if location == "knowledge" else b"clean")
    if location == "session":
        (path / "0/4_record").write_text(secret)
    result = record(plan, tmp_path, "two", ("", secret))
    assert "secret-found" in codes(result["warnings"])
    assert not knowledge.exists()
    assert manifest(tmp_path)["latest_session"] == previous
    assert secret not in json.dumps(result)
    for file in (tmp_path / "memory").rglob("*"):
        if file.is_file():
            assert secret.encode() not in file.read_bytes()


def test_record_internal_failure_is_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = prepare(tmp_path)
    monkeypatch.setattr(memory, "completed_loops", Mock(side_effect=OSError("sensitive text")))
    result = record(plan, tmp_path)
    assert "memory-record-failed" in codes(result["warnings"])
    assert "sensitive text" not in json.dumps(result)


def tree(path: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(path)): p.read_bytes() if p.is_file() else None for p in path.rglob("*")
    }


@pytest.mark.parametrize("populated", [True, False])
def test_inspector_manifest_only_read_only(tmp_path: Path, populated: bool) -> None:
    if populated:
        plan = prepare(tmp_path)
        session(tmp_path)
        record(plan, tmp_path)
    before = tree(tmp_path)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"ALPHA_FACTOR_PYTHON", "ALPHA_RDAGENT_SOURCE"}
    }
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(WORKER / "research_memory.py"),
            "show",
            "--memory-dir",
            str(tmp_path / "memory"),
            "--json",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    view = json.loads(result.stdout)
    assert view["schema"] == "AlphaRdagentMemoryViewV1"
    assert "runtime" in view["message"].lower() if populated else "no memory yet" in view["message"]
    assert tree(tmp_path) == before


def test_open_loop_without_memory_and_failed_session(tmp_path: Path) -> None:
    cls = Mock()
    loop, total = memory.open_factor_loop(cls, "settings", 2, {})
    assert loop is cls.return_value and total == 2
    cls.assert_called_once_with("settings")
    plan = prepare(tmp_path)
    (tmp_path / "one").mkdir()
    old = tmp_path / "old/__session__"
    for loop_index in ("0", "1", "2"):
        (old / loop_index).mkdir(parents=True)
        for step in ("3_feedback", "4_record"):
            (old / loop_index / step).write_bytes(b"dump")
    env = {
        **plan.env,
        "ALPHA_RDAGENT_CONTINUE_SESSION": str(old),
        "ALPHA_RDAGENT_CONTINUE_LOOPS": "3",
        "LOG_TRACE_PATH": str(tmp_path / "checkout"),
        "FACTOR_CoSTEER_max_loop": "2",
    }
    cls.load.return_value = SimpleNamespace(coder="pickled coder", trace=None)
    loop, total = memory.open_factor_loop(cls, "settings", 2, env)
    assert loop is cls.load.return_value and total == 5
    cls.load.assert_called_once_with(old / "2/4_record", checkout=tmp_path / "checkout")
    # A truncated newest dump: the next-older dump is used instead.
    cls.load.reset_mock()
    cls.load.side_effect = [ValueError("truncated"), SimpleNamespace(coder=None)]
    loop, total = memory.open_factor_loop(cls, "settings", 2, env)
    assert total == 5 and cls.load.call_args.args[0] == old / "2/3_feedback"
    cls.load.side_effect = ValueError("secret key path")
    loop, total = memory.open_factor_loop(cls, "settings", 2, env)
    assert total == 2 and loop is cls.return_value
    raw = Path(env["ALPHA_RDAGENT_MEMORY_EVENTS"]).read_text()
    assert "session-unloadable" in raw and "secret key path" not in raw


def test_fake_script_first_match_and_read_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = importlib.import_module("model_gateway")

    script = tmp_path / "script.json"
    script.write_text(
        json.dumps(
            [
                {"contains": "instruction\nprompt", "reply": "first"},
                {"contains": "prompt", "reply": "second"},
            ]
        )
    )
    monkeypatch.setenv("ALPHA_GATEWAY_FAKE_SCRIPT", str(script))
    chat = gateway.FakeChat()
    script.unlink()
    assert chat.complete({}, "prompt", "instruction", "", None).text == "first"
    assert json.loads(chat.complete({}, "unmatched", "", "", None).text)["fake"]


RUNTIME = pytest.mark.skipif(
    not (os.environ.get("ALPHA_FACTOR_PYTHON") and os.environ.get("ALPHA_RDAGENT_SOURCE")),
    reason="requires ALPHA_FACTOR_PYTHON and ALPHA_RDAGENT_SOURCE",
)


@RUNTIME
def test_runtime_signed_inspection_and_corrupt_knowledge(tmp_path: Path) -> None:
    plan = prepare(tmp_path)
    path = session(tmp_path)
    record(plan, tmp_path)
    script = r"""
import os, sys
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0, sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
from rdagent.core.serialization import dump
from rdagent.components.coder.CoSTEER.knowledge_management import CoSTEERKnowledgeBaseV2
root = Path(sys.argv[3])
k = CoSTEERKnowledgeBaseV2.__new__(CoSTEERKnowledgeBaseV2)
k.success_task_to_knowledge_dict = {'working factor': None}
k.working_trace_knowledge = {'failed factor': [None, None]}
k.working_trace_error_analysis = {'failed factor': [['RuntimeError']]}
k.graph = NS(nodes={'one': NS(label='error', content='RuntimeError', embedding=[1.0])})
with (root/'memory/costeer/factor-knowledge.pkl').open('wb') as f: dump(k, f)
experiment = NS(hypothesis=NS(hypothesis='Remember this hypothesis'),
                sub_tasks=[NS(factor_name='failed factor')])
feedback = NS(decision=False, reason='failure reason ' * 50)
with (root/'one/work/log/__session__/0/4_record').open('wb') as f:
    dump(NS(trace=NS(hist=[(experiment, feedback)])), f)
"""
    environment = {
        **os.environ,
        **plan.env,
        "HOME": str(tmp_path / "home"),
        "LOG_TRACE_PATH": str(tmp_path / "log"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    }
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
        env=environment,
        cwd=tmp_path,
        check=True,
        timeout=60,
    )
    before = tree(tmp_path / "memory")
    ledger = tmp_path / "trials.jsonl"
    ledger.write_text(
        json.dumps({"name": "failed factor", "status": "FAILED", "q": 1, "run_id": "one"}) + "\n"
    )
    view = memory.show(tmp_path / "memory", ledger=ledger)
    assert view["rounds"][0]["hypothesis"] == "Remember this hypothesis", view
    assert len(view["rounds"][0]["reason"]) == 300
    assert view["rounds"][0]["alpha_verdicts"]["failed factor"][0]["status"] == "FAILED"
    assert view["knowledge"]["working_factors"] == ["working factor"]
    assert view["knowledge"]["attempts_per_task"] == {"failed factor": 2}
    assert view["knowledge"]["error_kinds"] == ["RuntimeError"]
    assert view["knowledge"]["nodes_with_embeddings"] == 1
    assert tree(tmp_path / "memory") == before
    assert (path / "0/4_record").exists()
    corrupt = r"""
import os, sys, json
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
from research_memory import open_factor_loop
path=Path(os.environ['FACTOR_CoSTEER_knowledge_base_path'])
path.write_bytes(b'broken signed knowledge')
cls=Mock()
loop, total=open_factor_loop(cls, 'settings', 1, os.environ)
assert loop is cls.return_value and total == 1
assert not path.exists()
events=Path(os.environ['ALPHA_RDAGENT_MEMORY_EVENTS'])
rows=[json.loads(s) for s in events.read_text().splitlines()]
assert rows[-1]['code']=='knowledge-unloadable'
quarantine=Path(os.environ['ALPHA_RDAGENT_MEMORY_DIR'])/'quarantine'
assert list(quarantine.glob('*/factor-knowledge.pkl'))
"""
    subprocess.run(
        [
            os.environ["ALPHA_FACTOR_PYTHON"],
            "-I",
            "-B",
            "-c",
            corrupt,
            str(WORKER),
            os.environ["ALPHA_RDAGENT_SOURCE"],
        ],
        env=environment,
        cwd=tmp_path,
        check=True,
        timeout=60,
    )


FAILED_CODE = "raise RuntimeError('memory test deliberate failure')\n"
HYPOTHESIS = "Memory test: yesterday's return predicts tomorrow's reversal."


def _fake_replies(path: Path) -> None:
    replies = [
        ("working on generating new hypotheses", {"hypothesis": HYPOTHESIS, "reason": "test"}),
        (
            "based on the hypothesis generated in the previous step",
            {
                "memory_failure": {
                    "description": "One day reversal",
                    "formulation": "-return_1d",
                    "variables": {"return_1d": "one day close return"},
                }
            },
        ),
        ("Your code is expected to align", {"code": FAILED_CODE}),
        ("Your job is to check whether user's code", "The code deliberately raises RuntimeError."),
        ("component_no_list", {"component_no_list": []}),
        ("final_decision", {"final_decision": False, "final_feedback": "RuntimeError"}),
    ]
    path.write_text(
        json.dumps(
            [
                {"contains": match, "reply": reply if isinstance(reply, str) else json.dumps(reply)}
                for match, reply in replies
            ]
        )
    )


def _synthetic_panel(root: Path, timeout: float) -> None:
    script = r"""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, sys.argv[1])
from alpha_factor_data import prepare
root = Path(sys.argv[2])
dates = pd.date_range('2020-12-01','2023-12-31').date
idx = pd.MultiIndex.from_product([dates, ['A','B']], names=['date','instrument'])
f = pd.DataFrame({'open': range(1,len(idx)+1)}, index=idx).reset_index()
for col in ['close','high','low','volume','quote_volume']: f[col] = f['open'].astype(float)
f.to_parquet(root/'panel.parquet', index=False)
prepare(root/'panel.parquet', root/'factor_data')
"""
    subprocess.run(
        [os.environ["ALPHA_FACTOR_PYTHON"], "-I", "-B", "-c", script, str(WORKER), str(root)],
        cwd=root,
        check=True,
        timeout=timeout,
    )


def _run_memory_round(root: Path, run_id: str, base_url: str, token: str, deadline: float) -> Any:
    import shutil
    import time

    launch = importlib.import_module("factor_loop_launch")

    run = root / run_id
    (run / "work").mkdir(parents=True)
    (run / "home").mkdir()
    shutil.copytree(root / "factor_data", run / "factor_data")
    plan = prepare(root, run_id)
    env = launch.loop_environment(
        base_url=base_url,
        token=token,
        run=run,
        factor_python=Path(os.environ["ALPHA_FACTOR_PYTHON"]),
        ledger=root / "trials.jsonl",
        home=str(run / "home"),
        memory_env=plan.env,
    )
    with (run / "process.log").open("wb") as output:
        subprocess.run(
            [
                os.environ["ALPHA_FACTOR_PYTHON"],
                "-I",
                "-B",
                str(WORKER / "factor_loop_entry.py"),
                os.environ["ALPHA_RDAGENT_SOURCE"],
                "1",
            ],
            cwd=run / "work",
            env=env,
            stdout=output,
            stderr=output,
            check=True,
            timeout=max(1, deadline - time.monotonic()),
        )
    receipt = record(plan, root, run_id, (token,))
    assert "memory-record-failed" not in codes(receipt["warnings"])
    assert not (run / "evaluations.jsonl").exists()
    # Loop folders keep RD-Agent's numbering across a continued session.
    assert memory.completed_loops(run / "work/log/__session__") == plan.loops_before + 1
    return plan


@RUNTIME
@pytest.mark.parametrize("knowledge_only", [False, True])
def test_runtime_offline_e2e(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, knowledge_only: bool
) -> None:
    """Socket integration; run outside the restricted builder sandbox (under four minutes)."""
    import time

    launch = importlib.import_module("factor_loop_launch")

    deadline = time.monotonic() + 230
    _synthetic_panel(tmp_path, 45)
    fake = tmp_path / "fake.json"
    _fake_replies(fake)
    monkeypatch.setenv("ALPHA_GATEWAY_FAKE_SCRIPT", str(fake))
    parsed = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            str(tmp_path),
            "--run-dir",
            str(tmp_path / "gateway-run"),
            "--gateway-data-dir",
            str(tmp_path / "gateway"),
            "--trial-ledger",
            str(tmp_path / "trials.jsonl"),
            "--run-id",
            "memory-integration",
            "--chat-route",
            "fake",
            "--embedding-route",
            "fake",
            "--accept-unhonoured",
            "temperature",
        ]
    )
    gateway = launch.Launch(
        parsed,
        {
            "ALPHA_RDAGENT_SOURCE": Path(os.environ["ALPHA_RDAGENT_SOURCE"]),
            "ALPHA_FACTOR_PYTHON": Path(os.environ["ALPHA_FACTOR_PYTHON"]),
        },
    )
    (gateway.run / "logs").mkdir(parents=True)
    original_spawn = gateway.spawn

    def spawn(command: Sequence[str], log: str, **kwargs: Any) -> subprocess.Popen[bytes]:
        return cast(
            "subprocess.Popen[bytes]",
            original_spawn([*command, "--log-content"], log, **kwargs),
        )

    monkeypatch.setattr(gateway, "spawn", spawn)
    try:
        base_url, token = gateway.gateway()
        _run_memory_round(tmp_path, "one", base_url, token, deadline)
        first = memory.show(tmp_path / "memory")
        assert len(first["rounds"]) == 1, first
        reason = first["rounds"][0]["reason"]
        assert reason
        content = tmp_path / "gateway/model-gateway/content.jsonl"
        first_count = len(content.read_text().splitlines())
        if knowledge_only:
            value = manifest(tmp_path)
            value["latest_session"] = None
            (tmp_path / "memory/memory.json").write_text(json.dumps(value, sort_keys=True))
        _run_memory_round(tmp_path, "two", base_url, token, deadline)
        prompts = [json.loads(line) for line in content.read_text().splitlines()[first_count:]]
        coding = [
            p["instructions"] + "\n" + p["prompt"]
            for p in prompts
            if "Your code is expected to align" in p["instructions"]
        ]
        assert coding and FAILED_CODE.strip() in coding[0]
        view = memory.show(tmp_path / "memory")
        if not knowledge_only:
            hypothesis = [
                p["prompt"]
                for p in prompts
                if "working on generating new hypotheses" in p["instructions"]
            ]
            assert hypothesis and HYPOTHESIS in hypothesis[0] and reason in hypothesis[0]
            assert len(view["rounds"]) == 2, view
        else:
            assert len(view["rounds"]) == 1, view
        (tmp_path / "memory/costeer/factor-knowledge.pkl").write_bytes(b"corrupt")
        _run_memory_round(tmp_path, "three", base_url, token, deadline)
        events = [
            json.loads(line)
            for line in (tmp_path / "three/memory-events.jsonl").read_text().splitlines()
        ]
        assert "knowledge-unloadable" in codes(events)
        assert list((tmp_path / "memory/quarantine").glob("*/factor-knowledge.pkl"))
        assert time.monotonic() < deadline
    finally:
        gateway.stop()


def test_runtime_gateway_explicitly_waives_temperature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check the integration fixture's real launch command without opening a socket."""
    launch = importlib.import_module("factor_loop_launch")
    monkeypatch.setenv("ALPHA_FACTOR_PYTHON", str(tmp_path / "runtime/venv/bin/python"))
    monkeypatch.setenv("ALPHA_RDAGENT_SOURCE", str(tmp_path / "source"))
    monkeypatch.setattr(sys.modules[__name__], "_synthetic_panel", lambda root, timeout: None)

    def capture(
        self: Any, command: Sequence[str], log: str, **kwargs: Any
    ) -> subprocess.Popen[bytes]:
        assert command[command.index("--chat-route") + 1] == "fake"
        assert "--accept-unhonoured" in command
        assert command[command.index("--accept-unhonoured") + 1] == "temperature"
        assert "--log-content" in command
        raise launch.LaunchError("command captured before socket startup")

    monkeypatch.setattr(launch.Launch, "spawn", capture)
    with pytest.raises(launch.LaunchError, match="command captured"):
        test_runtime_offline_e2e(tmp_path, monkeypatch, knowledge_only=False)


@RUNTIME
def test_coder_restarts_the_knowledge_counter_per_experiment(tmp_path: Path) -> None:
    script = r"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
from rdagent.components.coder.factor_coder import FactorCoSTEER
import alpha_factor_coder
seen = []
FactorCoSTEER.develop = lambda self, exp: seen.append(self.rag.current_generated_trace_count) or exp
coder = alpha_factor_coder.AlphaFactorCoSTEER.__new__(alpha_factor_coder.AlphaFactorCoSTEER)
coder.rag = SimpleNamespace(current_generated_trace_count=5, dump_knowledge_base_path=None)
assert coder.develop("exp") == "exp" and seen == [0], seen
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
        ],
        check=True,
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        },
        timeout=120,
    )


def test_inspector_warns_about_unreadable_ledger_lines(tmp_path: Path) -> None:
    plan = prepare(tmp_path)
    session(tmp_path)
    record(plan, tmp_path)
    ledger = tmp_path / "trials.jsonl"
    ledger.write_text('{"name": "a", "status": "OK"}\nnot json\n')
    view = memory.show(tmp_path / "memory", ledger=ledger)
    assert "1 trial ledger line" in view["ledger_warning"]


def test_inspector_reports_alpha_rejected_task_names() -> None:
    task = SimpleNamespace(factor_name="leaky")
    knowledge = SimpleNamespace(
        graph=SimpleNamespace(
            nodes={"one": SimpleNamespace(label="alpha_rejected_implement", embedding=None)}
        ),
        node_to_implementation_knowledge_dict={"one": SimpleNamespace(target_task=task)},
        success_task_to_knowledge_dict={},
        working_trace_knowledge={"proposal": [None]},
        working_trace_error_analysis={},
    )
    view = memory._knowledge_view(knowledge)
    assert view["alpha_rejected"] == ["leaky"]
    assert "ALPHA rejected the code of: leaky" in memory._plain(
        {
            "manifest": {"runs": []},
            "rounds": [],
            "memory_dir": "memory",
            "knowledge": view,
        }
    )


@RUNTIME
def test_coder_demotes_real_signed_knowledge_and_refreshes(tmp_path: Path) -> None:
    script = r"""
import sys, os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from factor_loop_entry import install_source
install_source(Path(sys.argv[2]))
import alpha_factor_coder as c
from rdagent.components.coder.CoSTEER.knowledge_management import (
 CoSTEERKnowledgeBaseV2, CoSTEERKnowledge,
)
from rdagent.components.coder.factor_coder.factor import FactorTask, FactorFBWorkspace
from rdagent.components.knowledge_management.graph import UndirectedNode
from rdagent.core.serialization import dump, load
from rdagent.components.coder.CoSTEER.knowledge_management import CoSTEERRAGStrategyV2
k = CoSTEERKnowledgeBaseV2()
tasks = [FactorTask(n, 'description', 'close') for n in ['leaky', 'correct']]
infos = [t.get_task_information() for t in tasks]
def embed(self): self.embedding = [1., 0.]
with patch.object(UndirectedNode, 'create_embedding', embed):
 for task, info in zip(tasks, infos):
  workspace = FactorFBWorkspace(target_task=task)
  workspace.file_dict = {'factor.py': task.factor_name}
  unit = CoSTEERKnowledge(task, workspace, 'code ran')
  k.working_trace_knowledge[info] = [unit]
  k.success_task_to_knowledge_dict[info] = unit
  k.task_to_component_nodes[info] = []
  k.update_success_task(info)
nodes = {unit.target_task.factor_name: k.graph.nodes[node_id]
         for node_id, unit in k.node_to_implementation_knowledge_dict.items()}
description = k.graph.find_node(infos[0], 'task_description')
def retrieved():
 return k.graph_query_by_node(description, step=50,
                              constraint_labels=['task_success_implement'], block=True)
assert nodes['leaky'] in retrieved()
path = Path(sys.argv[3]) / 'knowledge.pkl'
with path.open('wb') as stream: dump(k, stream)
original = path.read_bytes()
assert c.demote(k, [infos[0], 'missing', infos[0]]) == [infos[0]]
assert infos[0] not in k.success_task_to_knowledge_dict
assert infos[1] in k.success_task_to_knowledge_dict
assert nodes['leaky'].label == 'alpha_rejected_implement'
assert nodes['correct'].label == 'task_success_implement'
assert nodes['leaky'] not in retrieved()
assert len(k.working_trace_knowledge[infos[0]]) == 1
assert c.demote(k, [infos[0]]) == []
env = {'FACTOR_CoSTEER_new_knowledge_base_path': str(path),
       'FACTOR_CoSTEER_enable_filelock': 'True',
       'FACTOR_CoSTEER_filelock_path': str(path.with_suffix('.lock'))}
assert c.demote_in_file(env, [infos[0]]) == ([infos[0]], None)
assert path.read_bytes() != original
with path.open('rb') as stream: loaded = load(stream)
assert infos[0] not in loaded.success_task_to_knowledge_dict
assert loaded.graph.nodes[nodes['leaky'].id].label == 'alpha_rejected_implement'
rag = CoSTEERRAGStrategyV2.__new__(CoSTEERRAGStrategyV2)
rag.dump_knowledge_base_path = path
rag.knowledgebase = k
rag.current_generated_trace_count = 8
coder = c.AlphaFactorCoSTEER.__new__(c.AlphaFactorCoSTEER)
coder.rag = rag
coder.settings = NS(enable_filelock=True, filelock_path=env['FACTOR_CoSTEER_filelock_path'])
with patch.object(c.FactorCoSTEER, 'develop', lambda self, exp: exp):
 assert coder.develop('experiment') == 'experiment'
assert rag.current_generated_trace_count == 0
assert rag.knowledgebase is not k
assert infos[0] not in rag.knowledgebase.success_task_to_knowledge_dict
path.write_bytes(b'corrupt')
demoted, note = c.demote_in_file(env, [infos[0]])
assert demoted == [] and note
assert path.read_bytes() == b'corrupt'
assert c.demote_in_file({}, infos) == ([], 'no persistent coding memory')
assert not list(path.parent.glob('.coder-verdict-*'))
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
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin:/bin",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "ARTIFACT_SIGNING_KEY_PATH": str(tmp_path / "signing.key"),
        },
        timeout=120,
    )
