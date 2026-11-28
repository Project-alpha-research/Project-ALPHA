"""Offline contracts of the ALPHA-judged factor-loop launcher (ADR-0049)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

from workers.rdagent import model_gateway as gateway

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
spec = importlib.util.spec_from_file_location(
    "factor_loop_launch", WORKER / "factor_loop_launch.py"
)
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)
loop_calls = importlib.import_module("factor_loop_calls")
loop_checks = importlib.import_module("factor_loop_checks")


def args(tmp_path: Path, *extra: str) -> argparse.Namespace:
    (tmp_path / "ledger").mkdir(exist_ok=True)
    parsed: argparse.Namespace = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            str(tmp_path / "data"),
            "--run-dir",
            str(tmp_path / "run"),
            "--gateway-data-dir",
            str(tmp_path / "gateway"),
            "--trial-ledger",
            str(tmp_path / "ledger" / "trials.jsonl"),
            "--run-id",
            "test-run",
            *extra,
        ]
    )
    return parsed


def environ(tmp_path: Path) -> dict[str, str]:
    python = tmp_path / "bundle/venv/bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.touch()
    (tmp_path / "source").mkdir(exist_ok=True)
    return {"ALPHA_RDAGENT_SOURCE": str(tmp_path / "source"), "ALPHA_FACTOR_PYTHON": str(python)}


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--run-max-calls", "61"], "between 1 and 60"),
        (["--loop-n", "4"], "--loop-n"),
        (["--wall-seconds", "0"], "positive"),
    ],
)
def test_refuses_bad_arguments(tmp_path: Path, extra: list[str], message: str) -> None:
    with pytest.raises(loop_checks.LaunchError, match=message):
        loop_checks.validate(args(tmp_path, *extra), environ(tmp_path))


def test_refuses_existing_run_dir_git_tree_and_missing_runtime(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    with pytest.raises(loop_checks.LaunchError, match="already exists"):
        loop_checks.validate(args(tmp_path), environ(tmp_path))
    (tmp_path / "run").rmdir()
    with pytest.raises(loop_checks.LaunchError, match="setup_rdagent.sh --with-factor-runtime"):
        loop_checks.validate(args(tmp_path), {})
    inside = args(tmp_path)
    inside.run_dir = Path(__file__).resolve().parent / "never-created-run"
    with pytest.raises(loop_checks.LaunchError, match="outside every git work tree"):
        loop_checks.validate(inside, environ(tmp_path))


def test_main_reports_refusal_plainly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["run", "--data-dir", "/d", "--run-dir", "/r", "--gateway-data-dir", "/g"]
    argv += ["--trial-ledger", "/nonexistent-parent/x.jsonl", "--run-id", "r"]

    def refuse(parsed: argparse.Namespace, env: dict[str, str]) -> int:
        raise loop_checks.LaunchError("refused for test")

    assert launch.main(argv, runner=refuse) == 2
    assert "refused for test" in capsys.readouterr().err


def test_loop_environment_is_exact_and_names_alpha_classes(tmp_path: Path) -> None:
    env = launch.loop_environment(
        base_url="http://127.0.0.1:1",
        token="secret-token",
        run=tmp_path,
        factor_python=tmp_path / "py/bin/python",
        ledger=tmp_path / "trials.jsonl",
        home=str(tmp_path),
    )
    assert env["QLIB_FACTOR_RUNNER"] == "alpha_factor_judge.AlphaFactorRunner"
    assert env["QLIB_FACTOR_SUMMARIZER"] == "alpha_factor_judge.AlphaFactorFeedback"
    assert env["QLIB_FACTOR_SCEN"] == "alpha_factor_judge.AlphaFactorScenario"
    assert env["QLIB_FACTOR_CODER"] == "alpha_factor_coder.AlphaFactorCoSTEER"
    assert env["QLIB_FACTOR_HYPOTHESIS_GEN"] == "alpha_factor_judge.AlphaFactorHypothesisGen"
    assert env["FACTOR_CoSTEER_max_loop"] == "2"
    assert env["CONDA_DEFAULT_ENV"] == "alpha-no-conda"
    assert not any(k.startswith(("OPENAI", "ALPHA_GATEWAY", "MODEL_CoSTEER")) for k in env)
    assert len(env) == 34
    assert env["ALPHA_FACTOR_FAMILY_SWITCH_AFTER"] == "3"
    assert env["ALPHA_FACTOR_UNIVERSE_TEXT"] == "15 surviving coins only"
    assert env["FACTOR_CoSTEER_python_bin"].startswith(
        "env -u LM_STUDIO_API_KEY -u LM_STUDIO_API_BASE "
    )
    assert env["ALPHA_FACTOR_CODE_PYTHON"] == str(tmp_path / "py/bin/python")


def test_stop_kills_the_whole_process_group(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "logs").mkdir(parents=True)
    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run = run
    child = job.spawn(
        [
            sys.executable,
            "-c",
            "import subprocess,time; subprocess.Popen(['sleep','300']); time.sleep(300)",
        ],
        "stand-in",
    )
    time.sleep(0.5)
    group = child.pid
    job.stop()
    assert child.poll() is not None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("a process of the stopped group is still alive")


def test_gateway_starts_with_fake_routes_and_token_stays_out_of_logs(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "logs").mkdir(parents=True)
    parsed = args(
        tmp_path, "--chat-route", "fake", "--embedding-route", "fake", "--run-max-calls", "3"
    )
    job = launch.Launch(
        parsed, {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"}
    )
    job.run = run
    job.repo_python = Path(sys.executable)
    try:
        base_url, token = job.gateway()
        assert base_url.startswith("http://127.0.0.1:")
    finally:
        job.stop()
    status = job.gateway_status()
    assert "error" not in status
    logged = (run / "launch.jsonl").read_text() + "".join(
        p.read_text() for p in (run / "logs").iterdir()
    )
    assert token not in logged
    receipt_exit = job.finish(0, "test")
    assert receipt_exit == 0
    receipt = json.loads((run / "receipt.json").read_text())
    assert token not in json.dumps(receipt)
    assert receipt["label"] == launch.LABEL
    assert not any(receipt["authority"].values())


def test_api_route_needs_model_prices_and_keys(tmp_path: Path) -> None:
    with pytest.raises(loop_checks.LaunchError, match="--api-model"):
        loop_checks.validate(args(tmp_path, "--chat-route", "api"), environ(tmp_path))
    priced = args(
        tmp_path,
        "--chat-route",
        "api",
        "--api-model",
        "deepseek/x",
        "--api-price-in-per-mtok",
        "0.1",
        "--api-price-out-per-mtok",
        "0.5",
    )
    with pytest.raises(loop_checks.LaunchError, match="ALPHA_GATEWAY_API_KEY"):
        loop_checks.validate(priced, environ(tmp_path))
    keyed = {
        **environ(tmp_path),
        "ALPHA_GATEWAY_API_BASE": "https://x",
        "ALPHA_GATEWAY_API_KEY": "k",
    }
    assert loop_checks.validate(priced, keyed)


def test_only_the_gateway_inherits_the_paid_route_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_GATEWAY_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ALPHA_GATEWAY_API_BASE", "https://example.com/v1")
    assert "ALPHA_GATEWAY_API_KEY" not in launch._without_secrets()
    run = tmp_path / "run"
    (run / "logs").mkdir(parents=True)
    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run = run
    probe = [sys.executable, "-c", "import os; print('ALPHA_GATEWAY_API_KEY' in os.environ)"]
    assert job.check("probe", probe) == "False"
    child = job.spawn(probe, "probe")
    child.wait(timeout=10)
    assert (run / "logs/probe.stdout.log").read_text().strip() == "False"


@pytest.mark.parametrize(("route", "waived"), [("codex", True), ("api", False), ("fake", False)])
def test_codex_route_alone_waives_temperature_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, waived: bool
) -> None:
    extra = ["--chat-route", route]
    if route == "api":
        extra += [
            "--api-model",
            "m",
            "--api-price-in-per-mtok",
            "1",
            "--api-price-out-per-mtok",
            "1",
        ]
    run = tmp_path / "run"
    (run / "logs").mkdir(parents=True)
    job = launch.Launch(
        args(tmp_path, *extra),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run = run
    commands: list[list[str]] = []

    def capture(command: list[str], log: str, **kwargs: object) -> object:
        commands.append(list(command))
        raise loop_checks.LaunchError("stop after building the command")

    monkeypatch.setattr(job, "spawn", capture)
    with pytest.raises(loop_checks.LaunchError):
        job.gateway()
    gateway_command = commands[0]
    assert ("--accept-unhonoured" in gateway_command) is waived
    if waived:
        assert gateway_command[gateway_command.index("--accept-unhonoured") + 1] == "temperature"
    assert ("--api-model" in gateway_command) is (route == "api")


def test_step_wrapper_records_success_failure_and_unset_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    sys.path.insert(0, str(WORKER))
    try:
        entry = importlib.import_module("factor_loop_entry")
    finally:
        sys.path.remove(str(WORKER))

    class FakeLoop:
        step_idx = {7: 0}
        steps = ["coding"]

        async def _run_step(self, li: int, force_subproc: bool = False) -> str:
            assert li == 7
            if force_subproc:
                raise ValueError("step failed")
            self.step_idx[li] = 1
            return "done"

    original = FakeLoop._run_step
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    entry.record_steps(FakeLoop)
    assert FakeLoop._run_step is original
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    entry.record_steps(FakeLoop)
    loop = FakeLoop()
    assert asyncio.run(loop._run_step(7)) == "done"
    loop.step_idx[7] = 0
    with pytest.raises(ValueError, match="step failed"):
        asyncio.run(loop._run_step(7, force_subproc=True))
    rows = [json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["start", "end", "start", "end"]
    assert all(
        r["schema"] == "AlphaRdagentStepV1"
        and r["loop"] == 7
        and r["step_index"] == 0
        and r["step"] == "coding"
        for r in rows
    )
    assert rows[1]["status"] == "ok" and rows[1]["error_type"] is None
    assert rows[3]["status"] == "error" and rows[3]["error_type"] == "ValueError"
    from datetime import datetime

    for row in rows:
        offset = datetime.fromisoformat(row["ts"]).utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0


def test_label_calls_inside_outside_overlap_and_boundaries() -> None:
    def step(event: str, loop: int, name: str, stamp: str) -> dict[str, object]:
        return {
            "event": event,
            "loop": loop,
            "step_index": loop,
            "step": name,
            "ts": f"2026-11-15T00:{stamp}+00:00",
        }

    steps = [
        step("start", 0, "propose", "00:00"),
        step("start", 1, "coding", "01:00"),
        step("end", 1, "coding", "02:00"),
        step("end", 0, "propose", "03:00"),
    ]
    calls = [
        {"id": i, "ts": f"2026-11-15T00:{stamp}+00:00"}
        for i, stamp in enumerate(["00:00", "01:30", "02:00", "02:30", "04:00"])
    ]
    original = json.dumps(calls)
    rows = loop_calls.label_calls(calls, steps)
    assert [(r["loop"], r["step"]) for r in rows] == [
        (0, "propose"),
        (1, "coding"),
        (1, "coding"),
        (0, "propose"),
        (None, "outside-step"),
    ]
    assert all(r["schema"] == "AlphaRdagentCallLabelV1" for r in rows)
    assert json.dumps(calls) == original
    assert [r["id"] for r in rows] == list(range(5))


def test_finish_labels_only_this_run_and_handles_missing_or_bad_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    assert job.finish(0, "test") == 0
    assert (job.run / "calls-labelled.jsonl").read_bytes() == b""
    assert job.receipt["calls_labelled"]["calls"] == 0
    assert "missing" in job.receipt["calls_labelled"]["reason"]
    state = job.args.gateway_data_dir / "model-gateway"
    state.mkdir(parents=True)
    calls = [
        {"run_id": rid, "ts": "2026-11-15T00:00:00+00:00", "payload": "unchanged"}
        for rid in ["test-run", "other"]
    ]
    (state / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in calls))
    (job.run / "steps.jsonl").write_text("")
    job.finish(0, "test")
    rows = [
        json.loads(line) for line in (job.run / "calls-labelled.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1 and rows[0]["run_id"] == "test-run"
    assert rows[0]["payload"] == "unchanged" and rows[0]["step"] == "outside-step"
    # A line cut short by a killed loop is skipped and counted; the other calls stay labelled.
    (job.run / "steps.jsonl").write_text("invalid json\n")
    assert job.finish(0, "test") == 0
    assert job.receipt["calls_labelled"] == {"calls": 1, "skipped_lines": 1}


@pytest.mark.parametrize("method", ["verify", "prepare", "gateway", "loop"])
def test_launcher_logs_start_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()

    def refuse(*args: object, **kwargs: object) -> None:
        raise loop_checks.LaunchError("stop at first work")

    monkeypatch.setattr(job, "check", refuse)
    monkeypatch.setattr(job, "spawn", refuse)
    with pytest.raises(loop_checks.LaunchError):
        getattr(job, method)(*(["http://unused", "token"] if method == "loop" else []))
    row = json.loads((job.run / "launch.jsonl").read_text().splitlines()[0])
    assert row["step"] == method and row["event"] == "start"


@pytest.mark.parametrize("value", ["0", "4"])
def test_coder_max_loop_bounds(tmp_path: Path, value: str) -> None:
    with pytest.raises(loop_checks.LaunchError, match="--coder-max-loop"):
        loop_checks.validate(args(tmp_path, "--coder-max-loop", value), environ(tmp_path))


def test_memory_path_inside_git_refused(tmp_path: Path) -> None:
    with pytest.raises(loop_checks.LaunchError, match="--memory-dir.*outside"):
        loop_checks.validate(
            args(tmp_path, "--memory-dir", str(WORKER / "never-memory")), environ(tmp_path)
        )


@pytest.mark.parametrize("disabled", [False, True])
def test_launcher_memory_default_opt_out_and_determinism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disabled: bool
) -> None:
    from types import SimpleNamespace

    parsed = args(tmp_path, *(["--no-memory"] if disabled else []))
    paths = loop_checks.validate(parsed, environ(tmp_path))
    job = launch.Launch(parsed, paths)
    job.run.mkdir()
    captured: dict[str, str] = {}

    def spawn(command: Sequence[str], log: str, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs["env"])
        return SimpleNamespace(wait=lambda timeout: 0)

    monkeypatch.setattr(job, "spawn", spawn)
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    assert job.loop("http://unused", "token") == 0
    assert job.finish(0, "test") == 0
    assert job.receipt["memory"]["enabled"] is (not disabled)
    base = launch.loop_environment(
        base_url="http://unused",
        token="token",
        run=job.run,
        factor_python=job.factor_python,
        ledger=parsed.trial_ledger,
        home=str(job.run / "home"),
    )
    base.update(
        ALPHA_GATEWAY_CALLS=str(parsed.gateway_data_dir / "model-gateway/calls.jsonl"),
        ALPHA_GATEWAY_RUN_ID=parsed.run_id,
    )
    assert {k: captured[k] for k in base} == base
    assert captured["ALPHA_FACTOR_EVAL_PYTHON"] == base["ALPHA_FACTOR_EVAL_PYTHON"]
    assert captured["ALPHA_FACTOR_TRIAL_LEDGER"] == str(parsed.trial_ledger)
    memory_dir = parsed.trial_ledger.parent / "research-memory"
    if disabled:
        assert captured == base
        assert not memory_dir.exists()
    else:
        assert (memory_dir / "memory.json").exists()
        assert len(captured.keys() - base.keys()) == 7
        assert captured["ARTIFACT_SIGNING_KEY_PATH"].startswith(str(memory_dir))


def test_step_wrapper_records_a_skipped_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    sys.path.insert(0, str(WORKER))
    try:
        entry = importlib.import_module("factor_loop_entry")
    finally:
        sys.path.remove(str(WORKER))

    class FakeLoop:
        EXCEPTION_KEY = "_EXCEPTION"
        step_idx = {0: 0}
        steps = ["coding"]

        def __init__(self) -> None:
            self.loop_prev_out: dict[int, dict[str, object]] = {0: {}}

        async def _run_step(self, li: int, force_subproc: bool = False) -> None:
            # RD-Agent swallows a skip-loop error and stores it instead of raising.
            self.loop_prev_out[li][self.EXCEPTION_KEY] = KeyError("coder failed")

    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    entry.record_steps(FakeLoop)
    asyncio.run(FakeLoop()._run_step(0))
    rows = [json.loads(line) for line in (tmp_path / "steps.jsonl").read_text().splitlines()]
    assert rows[1]["status"] == "skipped" and rows[1]["error_type"] == "KeyError"


def test_exit_reason_names_the_call_cap(tmp_path: Path) -> None:
    namespace = launch.parser().parse_args(
        ["run", "--data-dir", "/d", "--run-dir", "/r", "--gateway-data-dir", "/g",
         "--trial-ledger", "/l", "--run-id", "x", "--run-max-calls", "4"]
    )  # fmt: skip
    capped = {"this_run": {"calls": 4, "usd": 0.0}}
    assert launch.exit_reason(1, capped, namespace) == (
        "loop exit 1: model call cap reached (4 of 4 calls)"
    )
    assert launch.exit_reason(1, {"this_run": {"calls": 2}}, namespace) == "loop exit 1"
    assert launch.exit_reason(1, {"error": "no output"}, namespace) == "loop exit 1"


def test_relative_trial_ledger_is_named_not_memory_dir(tmp_path: Path) -> None:
    parsed = args(tmp_path)
    parsed.trial_ledger = Path("relative/trials.jsonl")
    with pytest.raises(loop_checks.LaunchError, match="--trial-ledger must be an absolute path"):
        loop_checks.validate(parsed, environ(tmp_path))


@pytest.mark.parametrize("force_race", [False, True], ids=["real-server", "forced-race"])
def test_runs_sharing_one_gateway_state_each_get_their_own_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, force_race: bool
) -> None:
    """Concurrent runs must share the gateway state (one monthly cap), so each finds its own
    gateway: on 2026-11-16 two of three runs started together failed with 'did not write its
    session within 30 s' because every gateway wrote the same session.json. The forced race stops
    gateway a after it publishes its session and before it installs its SIGTERM handler; the
    launcher must then remove that gateway's session files itself."""
    from tests.unit._rdagent_support import spawn_socket_free_gateway

    published = Barrier(3, timeout=60)
    jobs = []
    state = tmp_path / "gateway" / "model-gateway"
    for name in ("a", "b", "c"):
        run = tmp_path / f"run-{name}"
        (run / "logs").mkdir(parents=True)
        parsed = args(tmp_path, "--chat-route", "fake", "--embedding-route", "fake")
        parsed.run_id = f"test-run-{name}"
        job = launch.Launch(
            parsed,
            {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
        )
        job.run = run
        job.repo_python = Path(sys.executable)
        jobs.append(job)

    def start(job: Any, port: int, *, stop_before_handler: bool) -> str:
        original_spawn = job.spawn

        def spawn(command: Sequence[str], log: str, **kwargs: object) -> subprocess.Popen[bytes]:
            child = spawn_socket_free_gateway(
                original_spawn,
                command,
                log,
                port=port,
                stop_before_handler=stop_before_handler,
                **kwargs,
            )
            # Let all three children publish before any launcher looks for its session.
            published.wait()
            return child

        if force_race:
            monkeypatch.setattr(job, "spawn", spawn)
        connection: tuple[str, str] = job.gateway()
        base_url, token = connection
        if force_race:
            assert base_url == f"http://127.0.0.1:{port}"
        pid = job.children[0].pid
        session = json.loads((state / f"session-{pid}.json").read_text())
        assert session["pid"] == pid
        assert token == session["token"]
        return base_url

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            starts = [
                pool.submit(start, job, port, stop_before_handler=(offset == 0))
                for offset, (job, port) in enumerate(zip(jobs, (41001, 41002, 41003), strict=True))
            ]
            assert len({future.result() for future in starts}) == 3
        pid = jobs[0].children[0].pid
        jobs[0].stop()
        assert not (state / f"session-{pid}.json").exists()
        for job in jobs[1:]:
            pid = job.children[0].pid
            assert json.loads((state / f"session-{pid}.json").read_text())["pid"] == pid
    finally:
        for job in jobs:
            job.stop()
    assert not list(state.glob("session*.json"))


def test_receipt_splits_paid_model_calls_from_free_local_embeddings() -> None:
    calls = [
        {"endpoint": "/v1/chat/completions", "attempts": 1, "usd": 0.002, "status": 200},
        {
            "endpoint": "/v1/chat/completions",
            "attempts": 2,
            "usd": 0.004,
            "status": 504,
            "error_code": "provider_timeout",
            "provider_errors": ["provider_timeout", "provider_timeout"],
        },
        {
            "endpoint": "/v1/chat/completions",
            "attempts": 2,
            "usd": 0.003,
            "status": 200,
            "provider_errors": ["invalid_provider_response"],
        },
        {"endpoint": "/v1/embeddings", "attempts": 1, "usd": 0.0, "status": 200},
        {"endpoint": "/v1/embeddings", "attempts": 1, "usd": 0.0, "status": 200},
    ]
    split = loop_calls.call_split(calls)
    assert split["model_chat"] == {"requests": 3, "attempts": 5, "usd": pytest.approx(0.009)}
    assert split["local_embedding"] == {"requests": 2, "attempts": 2, "usd": 0.0}
    assert split["counted_toward_call_cap"] == 7
    assert split["provider_timeouts"] == 2
    assert split["empty_or_invalid_replies"] == 1
    assert split["retried_attempts"] == 2
    assert split["failed_requests"] == {"provider_timeout": 1}


def test_gateway_gets_the_per_call_limit_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed = args(tmp_path, "--api-timeout", "90", "--provider-retries", "2")
    job = launch.Launch(
        parsed, {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/py"}
    )
    seen: list[list[str]] = []

    def spawn(command: Sequence[str], log: str, **kwargs: Any) -> Any:
        seen.append(list(command))
        raise loop_checks.LaunchError("stop here")

    monkeypatch.setattr(job, "spawn", spawn)
    job.run.mkdir()
    with pytest.raises(loop_checks.LaunchError):
        job.gateway()
    command = seen[0]
    assert command[command.index("--api-timeout") + 1] == "90.0"
    assert command[command.index("--provider-retries") + 1] == "2"
    assert job.receipt["route"]["api_timeout_seconds"] == 90.0


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--api-timeout", "0"], "--api-timeout"),
        (["--provider-retries", "4"], "--provider-retries"),
        (["--family-switch-after", "0"], "--family-switch-after"),
        (["--universe", "relative.json"], "--universe"),
    ],
)
def test_new_options_are_bounded(tmp_path: Path, extra: list[str], message: str) -> None:
    with pytest.raises(loop_checks.LaunchError, match=message):
        loop_checks.validate(args(tmp_path, *extra), environ(tmp_path))


def test_receipt_counts_chunked_embeddings_and_skipped_memory_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    split = loop_calls.call_split(
        [
            {"endpoint": "/v1/embeddings", "attempts": 2, "status": 200, "chunked_inputs": 1,
             "chunks": 5, "provider_errors": ["provider_error"]},
            {"endpoint": "/v1/embeddings", "attempts": 1, "status": 200},
        ]
    )  # fmt: skip
    assert split["chunked_embedding_inputs"] == 1 and split["embedding_chunks"] == 5
    assert split["local_embedding"]["attempts"] == 3
    job = launch.Launch(
        args(tmp_path),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    job.finish(0, "test")
    assert job.receipt["memory_entries_skipped"] == 0
    (job.run / "memory-skips.jsonl").write_text('{"a": 1}\n{"b": 2}\n')
    job.finish(0, "test")
    assert job.receipt["memory_entries_skipped"] == 2


def test_launch_command_records_argv_and_only_allow_listed_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Earlier agents had to rebuild launch arguments from receipts; the run folder now keeps
    # them. Only allow-listed path variables keep a value; a key's value can never be written.
    class Stopped:
        def __init__(self, *a: Any) -> None:
            pass

        def verify(self) -> None:
            raise loop_checks.LaunchError("stopped for test")

        def log(self, *a: Any, **k: Any) -> None:
            pass

        def stop(self) -> None:
            pass

        def finish(self, status: int, reason: str) -> int:
            return status

    monkeypatch.setattr(launch, "Launch", Stopped)
    argv = ["run", "--data-dir", str(tmp_path / "data"), "--run-dir", str(tmp_path / "run")]
    argv += ["--gateway-data-dir", str(tmp_path / "gw"), "--trial-ledger"]
    argv += [str(tmp_path / "ledger/trials.jsonl"), "--run-id", "r", "--loop-n", "3"]
    (tmp_path / "ledger").mkdir()
    secrets = {
        "ALPHA_GATEWAY_API_KEY": "sk-or-v1-secret-value-1",
        "ALPHA_GATEWAY_API_BASE": "https://router.example/secret-value-2",
        "OPENROUTER_API_KEY": "sk-secret-value-3",
        "ANTHROPIC_AUTH_TOKEN": "secret-value-4",
        "ALPHA_PASSWORD": "secret-value-5",
    }
    env = {**environ(tmp_path), "ALPHA_DATA_DIR": str(tmp_path / "data"), **secrets}
    assert launch.main(argv, runner=lambda a, _: launch.run(a, env)) == 1
    raw = (tmp_path / "run/launch-command.json").read_text()
    assert not any(value in raw for value in secrets.values())
    record = json.loads(raw)
    assert record["argv"] == argv
    assert set(record["environment"]) <= set(launch.LAUNCH_ENVIRONMENT)
    assert record["environment"]["ALPHA_RDAGENT_SOURCE"] == env["ALPHA_RDAGENT_SOURCE"]
    assert record["environment"]["ALPHA_DATA_DIR"] == env["ALPHA_DATA_DIR"]
    assert record["secret_names_set"] == ["ALPHA_GATEWAY_API_BASE", "ALPHA_GATEWAY_API_KEY"]


def test_reasoning_limit_unconfirmed_default_is_unset() -> None:
    args = launch.parser().parse_args(
        [
            "run",
            "--data-dir",
            "/data",
            "--run-dir",
            "/run",
            "--gateway-data-dir",
            "/gateway",
            "--trial-ledger",
            "/ledger",
            "--run-id",
            "id",
        ]
    )
    assert args.coding_reasoning_tokens is None
    assert gateway.Settings(data_dir=Path("/data"), run_id="id").coding_reasoning_tokens is None


def test_receipt_round_counts_and_old_refusal_key(tmp_path: Path) -> None:
    records = [
        {"iteration": 0, "status": "refused_closed_family", "closed_families": ["volatility"]},
        {"iteration": 0, "alpha_decision": False, "tasks": [{"name": "price_delay"}]},
        {
            "iteration": 1,
            "status": "no_admissible_idea",
            "reason": "refused_closed_family",
            "refused_families": ["volatility"],
        },
    ]
    (tmp_path / "rounds.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    (tmp_path / "evaluations.jsonl").write_text(
        json.dumps({"iteration": 0, "factors": [{"name": "price_delay"}]}) + "\n"
    )
    result = loop_calls.round_counts(tmp_path)
    assert result == {
        "rounds_with_trial": 1,
        "rounds_no_admissible_idea": 1,
        "proposals_refused": 2,
        "rounds_failed_provider": 0,
        "provider_failed_wait_seconds": 0.0,
    }


def test_receipt_end_event_and_plain_console_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from workers.rdagent import factor_loop_launch as launch

    parsed = args(tmp_path)
    job = launch.Launch(
        parsed, {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"}
    )
    job.run.mkdir()
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    monkeypatch.setattr(job, "write_call_labels", lambda: {})
    assert job.finish(1, "budget exhausted") == 1
    assert capsys.readouterr().out == "RD-Agent loop ended: budget exhausted.\n"
    end = json.loads((job.run / "launch.jsonl").read_text().splitlines()[-1])
    assert end["event"] == "end" and end["exit_reason"] == "budget exhausted"


def test_receipt_contains_vector_counts_and_internal_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workers.rdagent import factor_loop_launch as launch

    job = launch.Launch(
        args(tmp_path),
        {
            "ALPHA_RDAGENT_SOURCE": tmp_path,
            "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python",
        },
    )
    job.run.mkdir()
    stats = {
        "knowledge_vectors": 106,
        "knowledge_vectors_reembedded": 106,
        "knowledge_vectors_left_out": 1,
        "knowledge_vector_dimension": 4096,
    }
    (job.run / "knowledge-vectors.json").write_text(json.dumps(stats))
    reason = "Two consecutive rounds ended with an internal coding error; run stopped"
    (job.run / "loop-stop.json").write_text(json.dumps({"loop_reason": reason}))
    monkeypatch.setattr(job, "gateway_status", lambda: {})
    job.finish(1, "loop exited")
    receipt = json.loads((job.run / "receipt.json").read_text())
    assert {key: receipt[key] for key in stats} == stats
    assert receipt["loop_reason"] == reason
