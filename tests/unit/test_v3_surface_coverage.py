"""High-value safety and orchestration coverage for the Workstation v3 control surfaces."""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, cast

import pytest
from fastapi import HTTPException

from alpha_mcp import _control
from alpha_web import _ml
from alpha_web.api import ml as ml_api


def _boom(*args: object, **kwargs: object) -> NoReturn:
    del args, kwargs
    raise RuntimeError("bounded projection failed")


def _expect_http(status_code: int, call: Callable[[], object]) -> None:
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status_code


def test_ml_api_wrappers_cover_happy_paths_and_typed_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    exchange_id = "a" * 32
    input_id = "b" * 32
    calls: list[tuple[str, tuple[object, ...]]] = []

    def record(name: str) -> Callable[..., dict[str, object]]:
        def inner(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append((name, args + tuple(kwargs.values())))
            return {"name": name}

        return inner

    for name in (
        "readiness",
        "service_status",
        "list_input_bundles",
        "input_bundle",
        "launch_input_generation",
        "list_exchanges",
        "list_experiments",
        "launch_experiment_generation",
        "exchange_detail",
        "exchange_result",
        "evaluate_exchange",
        "exchange_tearsheet",
        "replay_tearsheet",
        "launch_action",
    ):
        monkeypatch.setattr(_ml, name, record(name))
    monkeypatch.setattr(_ml, "new_input_id", lambda: input_id)
    monkeypatch.setattr(_ml, "new_exchange_id", lambda: exchange_id)
    monkeypatch.setattr(_ml, "experiment_preflight", lambda **_: {"ready": True})

    assert ml_api.get_readiness()["name"] == "readiness"
    assert ml_api.get_service_status()["name"] == "service_status"
    assert ml_api.get_inputs(10, 0)["name"] == "list_input_bundles"
    assert ml_api.get_input(input_id)["name"] == "input_bundle"
    assert (
        ml_api.generate_input(ml_api.MlInputGenerateRequest(spec={"snapshot_id": "snapshot"}))[
            "name"
        ]
        == "launch_input_generation"
    )
    assert ml_api.get_exchanges(10, 0)["name"] == "list_exchanges"
    assert ml_api.get_experiments("project", 10, 0)["name"] == "list_experiments"
    assert (
        ml_api.generate_experiment(
            ml_api.MlExperimentGenerateRequest(spec={"snapshot_id": "snapshot"})
        )["name"]
        == "launch_experiment_generation"
    )
    assert ml_api.get_exchange(exchange_id)["name"] == "exchange_detail"
    assert ml_api.get_exchange_result(exchange_id)["name"] == "exchange_result"
    assert ml_api.get_evaluation(exchange_id)["name"] == "evaluate_exchange"
    assert ml_api.get_exchange_tearsheet(exchange_id, 5, 10, 0, 5)["name"] == ("exchange_tearsheet")
    assert ml_api.get_replay_tearsheet("0123456789abcdef", 10, 0)["name"] == ("replay_tearsheet")
    assert (
        ml_api.prepare_exchange(ml_api.MlPrepareRequest(input_bundle_id=input_id))["name"]
        == "launch_action"
    )
    assert ml_api.train_exchange(exchange_id, ml_api.MlTrainRequest(mode="fake"))["name"] == (
        "launch_action"
    )
    scoped = ml_api.MlScopedActionRequest(project_id="project")
    assert ml_api.import_exchange(exchange_id, scoped)["name"] == "launch_action"
    assert ml_api.prepare_replay(exchange_id, scoped)["name"] == "launch_action"
    assert ml_api.replay_exchange(exchange_id, ml_api.MlReplayRequest())["name"] == (
        "launch_action"
    )
    assert len(calls) == 18

    assert ml_api._http_error(_ml.MlNotFoundError("missing")).status_code == 404
    assert ml_api._http_error(_ml.MlBusyError("busy")).status_code == 409
    assert ml_api._http_error(_ml.MlError("invalid")).status_code == 422

    monkeypatch.setattr(_ml, "input_bundle", _boom)
    _expect_http(422, lambda: ml_api.get_input(input_id))
    monkeypatch.setattr(_ml, "launch_action", _boom)
    _expect_http(
        422,
        lambda: ml_api.train_exchange(exchange_id, ml_api.MlTrainRequest(mode="fake")),
    )


def test_ml_projection_parsers_and_safe_resource_pages(tmp_path: Path) -> None:
    with pytest.raises(_ml.MlNotFoundError, match="invalid exchange_id"):
        _ml.exchange_result("../escape", data_dir=tmp_path)
    with pytest.raises(_ml.MlError, match="invalid immutable"):
        _ml._json_object(tmp_path / "missing.json", "record")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    with pytest.raises(_ml.MlError, match="invalid immutable"):
        _ml._json_object(invalid, "record")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
    with pytest.raises(_ml.MlError, match="duplicate key"):
        _ml._json_object(duplicate, "record")
    constant = tmp_path / "constant.json"
    constant.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(_ml.MlError, match="non-finite"):
        _ml._json_object(constant, "record")

    with pytest.raises(_ml.MlError, match="invalid object projection"):
        _ml._object([], "object")
    with pytest.raises(_ml.MlError, match="invalid objects projection"):
        _ml._objects({}, "objects")
    with pytest.raises(_ml.MlError, match="must be finite"):
        _ml._finite(True, "metric")
    with pytest.raises(_ml.MlError, match="must be finite"):
        _ml._finite(float("inf"), "metric")
    assert _ml._optional_finite(None, "metric") is None
    assert _ml._bounded_series([1.0, 2.0, 3.0], 1) == [3.0]
    with pytest.raises(_ml.MlError, match="arrays"):
        _ml._bounded_series({}, 2)

    inputs = tmp_path / "control" / "ml" / "inputs"
    ready = inputs / ("1" * 32)
    ready.mkdir(parents=True)
    (ready / "spec.json").write_text("{}", encoding="utf-8")
    (ready / "panel.parquet").write_bytes(b"parquet")
    (inputs / "unsafe-name").mkdir()
    page = _ml.list_input_bundles(data_dir=tmp_path, limit=10, offset=0)
    assert page["total"] == 1
    assert page["items"][0]["ready"] is True
    assert _ml.input_bundle("1" * 32, data_dir=tmp_path)["ready"] is True

    exchanges = tmp_path / "control" / "ml" / "exchanges"
    empty = exchanges / ("2" * 32)
    empty.mkdir(parents=True)
    exchange_page = _ml.list_exchanges(data_dir=tmp_path, limit=10, offset=0)
    assert exchange_page["items"][0]["status"] == "empty"
    prepared = exchanges / ("3" * 32)
    prepared.mkdir()
    (prepared / "request.json").write_text(
        '{"panel":{"sha256":"abc","rows":1},"universe":[]}',
        encoding="utf-8",
    )
    with pytest.raises(_ml.MlNotFoundError, match="result is not available"):
        _ml.exchange_result("3" * 32, data_dir=tmp_path)
    tear = _ml.exchange_tearsheet(
        "3" * 32,
        data_dir=tmp_path,
        feature_limit=10,
        timeline_limit=10,
        timeline_offset=0,
        history_limit=10,
    )
    assert tear["available"] is False


def test_ml_readiness_status_and_diagnostic_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = tmp_path / "worker"
    (worker / ".venv").mkdir(parents=True)
    (worker / "pyproject.toml").write_text("[project]\nname='worker'\n", encoding="utf-8")
    (worker / "uv.lock").write_text("lock", encoding="utf-8")
    (worker / ".venv" / "pyvenv.cfg").write_text("home=x", encoding="utf-8")
    monkeypatch.setattr(_ml, "_worker_project", lambda: worker)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(
        _ml,
        "_heavy_capacity",
        lambda **kwargs: {"busy": False, "active_jobs": [], "limit": 1},
    )
    ready = _ml.readiness(data_dir=tmp_path)
    assert ready["isolation_ready"] is True
    assert ready["worker_environment_present"] is True

    monkeypatch.setattr(_ml, "_has_input_producer", lambda **kwargs: False)
    status = _ml.service_status(data_dir=tmp_path)
    assert status["worker_ready"] is False
    assert "producer" in cast(str, status["message"])

    monkeypatch.setattr(_ml, "_has_input_producer", lambda **kwargs: True)
    monkeypatch.setattr(
        _ml,
        "_heavy_capacity",
        lambda **kwargs: {
            "busy": True,
            "active_jobs": [{"kind": "ml_train", "status": "running", "job_id": "job-1"}],
            "limit": 1,
        },
    )
    status = _ml.service_status(data_dir=tmp_path)
    assert status["active_job_id"] == "job-1"
    assert "active" in cast(str, status["message"])

    assert _ml._job_exchange({"request": "invalid"}) is None
    assert _ml._job_exchange({"request": {"exchange_id": "bad"}}) is None
    assert _ml._diagnostic_metrics(None) == {
        "ic": None,
        "rank_ic": None,
        "turnover": None,
        "costed_return": None,
    }
    assert _ml._diagnostic_metrics({"diagnostics": "invalid"})["ic"] is None
    assert _ml._diagnostic_metrics({"diagnostics": {"signal_analysis": "invalid"}})["ic"] is None


def test_ml_durable_job_execution_journals_success_failure_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal: list[list[str]] = []

    def journal_call(args: list[str], **kwargs: object) -> dict[str, object]:
        del kwargs
        journal.append(args)
        return {"status": "ok"}

    monkeypatch.setattr(_ml, "_journal", journal_call)
    monkeypatch.setattr(
        _ml,
        "_run_process",
        lambda *args, **kwargs: (2, "", f"{tmp_path}/secret failure"),
    )
    _ml._execute_job("job-fail", "train", ["ml", "train"], data_dir=tmp_path, timeout_seconds=60)
    assert journal[-1][3] == "failed"
    assert str(tmp_path) not in " ".join(journal[-1])

    monkeypatch.setattr(
        _ml,
        "_run_process",
        lambda *args, **kwargs: (
            0,
            'noise\n{"status":"succeeded","run_id":"0123456789abcdef","private":"drop"}',
            "",
        ),
    )
    _ml._execute_job(
        "job-success", "replay", ["ml", "replay"], data_dir=tmp_path, timeout_seconds=60
    )
    assert "--result-run-id" in journal[-1]
    assert "private" not in " ".join(item for row in journal for item in row)

    def timeout(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise subprocess.TimeoutExpired(["alpha"], 60)

    monkeypatch.setattr(_ml, "_run_process", timeout)
    _ml._execute_job("job-timeout", "train", ["ml", "train"], data_dir=tmp_path, timeout_seconds=60)
    assert "exceeded 60 seconds" in " ".join(journal[-1])

    monkeypatch.setattr(_ml, "_run_process", lambda *args, **kwargs: (0, "not-json", ""))
    _ml._execute_job(
        "job-invalid", "import", ["ml", "import"], data_dir=tmp_path, timeout_seconds=60
    )
    assert journal[-1][3] == "failed"


def test_ml_pipeline_journals_each_terminal_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal: list[list[str]] = []

    def journal_call(args: list[str], **kwargs: object) -> dict[str, object]:
        del kwargs
        journal.append(args)
        return {"status": "ok"}

    monkeypatch.setattr(_ml, "_journal", journal_call)
    monkeypatch.setattr(
        _ml,
        "_run_process",
        lambda *args, **kwargs: (0, '{"status":"prepared","rows":20}', ""),
    )
    _ml._execute_pipeline("job-success", [("prepare", ["ml", "prepare"], 60)], data_dir=tmp_path)
    assert journal[-1][3] == "succeeded"

    monkeypatch.setattr(_ml, "_run_process", lambda *args, **kwargs: (2, "", "failed"))
    _ml._execute_pipeline("job-fail", [("prepare", ["ml"], 60)], data_dir=tmp_path)
    assert journal[-1][3] == "failed"

    def timeout(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise subprocess.TimeoutExpired(["alpha"], 60)

    monkeypatch.setattr(_ml, "_run_process", timeout)
    _ml._execute_pipeline("job-timeout", [("prepare", ["ml"], 60)], data_dir=tmp_path)
    assert "exceeded 60 seconds" in " ".join(journal[-1])

    monkeypatch.setattr(_ml, "_run_process", lambda *args, **kwargs: (0, "invalid", ""))
    _ml._execute_pipeline("job-invalid", [("prepare", ["ml"], 60)], data_dir=tmp_path)
    assert journal[-1][3] == "failed"


def test_ml_action_builder_is_allowlisted_and_records_only_opaque_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exchange_id = "a" * 32
    exchange = tmp_path / "control" / "ml" / "exchanges" / exchange_id
    exchange.mkdir(parents=True)
    journal: list[list[str]] = []
    started: list[tuple[str, list[str], int]] = []

    def journal_call(args: list[str], **kwargs: object) -> dict[str, object]:
        del kwargs
        journal.append(args)
        return {"job_id": "job-1"}

    def start_job(
        job_id: str,
        action: _ml.MlAction,
        args: list[str],
        *,
        data_dir: Path,
        timeout_seconds: int,
    ) -> None:
        del data_dir
        started.append((action, args, timeout_seconds))
        assert job_id == "job-1"

    monkeypatch.setattr(_ml, "_journal", journal_call)
    monkeypatch.setattr(_ml, "_start_job", start_job)
    for action in ("train", "import", "prepare-replay", "replay"):
        result = _ml.launch_action(
            action,
            data_dir=tmp_path,
            exchange_id=exchange_id,
            project_id="project",
            experiment_id="experiment",
            mode="fake",
            no_sync=True,
            timeout_seconds=700,
            starting_cash=500_000,
            periods_per_year=365,
        )
        assert result["job_id"] == "job-1"
    assert [row[0] for row in started] == ["train", "import", "prepare-replay", "replay"]
    assert "--no-sync" in started[0][1]
    assert started[1][2] == 600
    assert "--starting-cash" in started[3][1]
    assert any("--project-id" in row for row in journal)

    def busy_journal(args: list[str], **kwargs: object) -> dict[str, object]:
        del kwargs
        if args[:2] == ["project", "job-create"]:
            raise RuntimeError("heavyweight job capacity is occupied by suite:kronos job x")
        return {"job_id": "job-1"}

    monkeypatch.setattr(_ml, "_journal", busy_journal)
    with pytest.raises(_ml.MlBusyError, match="heavyweight"):
        _ml.launch_action(
            "train",
            data_dir=tmp_path,
            exchange_id=exchange_id,
            project_id=None,
            experiment_id=None,
        )

    with pytest.raises(_ml.MlError, match="requires input_bundle_id"):
        _ml.launch_action(
            "prepare",
            data_dir=tmp_path,
            exchange_id="b" * 32,
            project_id=None,
            experiment_id=None,
        )


def test_mcp_control_validates_bounds_and_json() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _control.offset(-1)
    with pytest.raises(RuntimeError, match="invalid object"):
        _control._object([], "object")
    with pytest.raises(RuntimeError, match="invalid objects"):
        _control._objects({}, "objects")
    with pytest.raises(ValueError, match="finite JSON"):
        _control._json({"bad": float("nan")})


def test_ml_process_helpers_parse_sanitize_and_propagate_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _ml._parse_process_output('noise\n{"status":"ok"}') == {"status": "ok"}
    with pytest.raises(_ml.MlError, match="machine-readable"):
        _ml._parse_process_output("noise only")
    with pytest.raises(_ml.MlError, match="finite JSON"):
        _ml._canonical_json({"bad": float("nan")})
    sanitized = _ml._sanitize_message(f"failed at {tmp_path}/secret", data_dir=tmp_path)
    assert str(tmp_path) not in sanitized

    captured: dict[str, object] = {}

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "out", "err")

    monkeypatch.setattr(subprocess, "run", run)
    result = _ml._run_process(["ml", "import"], data_dir=tmp_path, timeout_seconds=60)
    assert result == (0, "out", "err")
    environment = cast(dict[str, str], cast(dict[str, object], captured["kwargs"])["env"])
    assert environment["ALPHA_DATA_DIR"] == str(tmp_path)
