"""Launch one ALPHA-judged RD-Agent factor loop (ADR-0049): verify, freeze, gateway, loop, receipt.

Standard library only; run it with the repository's ``.venv/bin/python``. It verifies the pinned
RD-Agent source and the factor runtime profile, freezes ALPHA's panel, prepares RD-Agent's data
folders, starts the model gateway with its call cap, runs the loop in its own process group under
a wall-clock limit, always stops both, and writes a receipt. It is not the command line's native
job supervisor (no ControlStore job or reservation yet; see the backlog note
``docs/roadmap/backlog/rdagent-factor-loop-supervision.md``). Nothing it produces is evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import gateway_usage, research_memory

WORKER = Path(__file__).resolve().parent
REPO = WORKER.parents[1]
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

if not TYPE_CHECKING:
    research_memory = importlib.import_module("research_memory")
    gateway_usage = importlib.import_module("gateway_usage")
SOURCE_SHA256: str = importlib.import_module("source_pin").SOURCE_SHA256

MAX_CALLS = 60
LABEL = "exploratory, not admitted, not yet confirmed"
AUTHORITY = dict.fromkeys(("admitted", "evidence", "approval", "promotion"), False)
SETUP_HINT = "bash scripts/setup_rdagent.sh --with-factor-runtime"
# The paid route's settings reach only the gateway process, never another child.
GATEWAY_SECRETS = ("ALPHA_GATEWAY_API_KEY", "ALPHA_GATEWAY_API_BASE")


# The only environment values launch-command.json may hold: paths that locate the runtimes and
# data. Any other variable, a key above all, is never written; secrets are named, not valued.
LAUNCH_ENVIRONMENT = (
    "ALPHA_RDAGENT_SOURCE",
    "ALPHA_FACTOR_PYTHON",
    "ALPHA_DATA_DIR",
    "ALPHA_STOCK_PYTHON",
)


def write_launch_command(run_dir: Path, argv: Sequence[str], environ: dict[str, str]) -> None:
    """Record how this run was started, so the next run can repeat it exactly."""
    secrets = [environ[k] for k in GATEWAY_SECRETS if environ.get(k)]
    record = {
        "schema": "AlphaRdagentLaunchCommandV1",
        "program": "workers/rdagent/factor_loop_launch.py",
        "argv": ["[redacted]" if a in secrets else a for a in argv],
        "environment": {k: environ[k] for k in LAUNCH_ENVIRONMENT if k in environ},
        "secret_names_set": sorted(k for k in GATEWAY_SECRETS if environ.get(k)),
    }
    (run_dir / "launch-command.json").write_text(json.dumps(record, indent=2) + "\n")


def _without_secrets() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in GATEWAY_SECRETS}


class LaunchError(Exception):
    """A refusal or failed step, with a plain message."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def label_calls(calls: list[dict[str, Any]], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy calls with the latest-starting completed step that contains each timestamp."""
    active: dict[tuple[int, int, str], list[dict[str, Any]]] = {}
    intervals = []
    for row in steps:
        key = (row["loop"], row["step_index"], row["step"])
        if row["event"] == "start":
            active.setdefault(key, []).append(row)
        elif row["event"] == "end" and active.get(key):
            start = active[key].pop()
            intervals.append(
                (datetime.fromisoformat(start["ts"]), datetime.fromisoformat(row["ts"]), start)
            )
    labelled = []
    for call in calls:
        ts = datetime.fromisoformat(call["ts"])
        matching = [(start, row) for start, end, row in intervals if start <= ts <= end]
        step = max(matching, key=lambda item: item[0])[1] if matching else None
        labelled.append(
            {
                **call,
                "schema": "AlphaRdagentCallLabelV1",
                "loop": step["loop"] if step else None,
                "step": step["step"] if step else "outside-step",
            }
        )
    return labelled


def _inside_git(path: Path) -> bool:
    probe = path
    while not probe.exists():
        probe = probe.parent
    result = subprocess.run(
        ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def validate(args: argparse.Namespace, environ: dict[str, str]) -> dict[str, Path]:
    if not 1 <= args.coder_max_loop <= 3:
        raise LaunchError("--coder-max-loop must be 1, 2 or 3")
    if not 1 <= args.loop_n <= 3:
        raise LaunchError("--loop-n must be 1, 2 or 3")
    if not 1 <= args.run_max_calls <= MAX_CALLS:
        raise LaunchError(f"--run-max-calls must be between 1 and {MAX_CALLS}")
    if args.wall_seconds <= 0:
        raise LaunchError("--wall-seconds must be positive")
    if not 0 < args.api_timeout <= 900:
        raise LaunchError("--api-timeout must be between 0 and 900 seconds")
    if not 0 <= args.provider_retries <= 3:
        raise LaunchError("--provider-retries must be 0, 1, 2 or 3")
    if args.family_switch_after < 1:
        raise LaunchError("--family-switch-after must be at least 1")
    if args.coding_reasoning_tokens is not None:
        raise LaunchError(
            "--coding-reasoning-tokens is unset until the provider request field is confirmed"
        )
    if args.universe is not None and not args.universe.is_absolute():
        raise LaunchError("--universe must be an absolute path")
    if args.chat_route == "api":
        if not args.api_model or not args.api_price_in_per_mtok or not args.api_price_out_per_mtok:
            raise LaunchError(
                "--chat-route api needs --api-model, --api-price-in-per-mtok and "
                "--api-price-out-per-mtok"
            )
        if any(not environ.get(key) for key in GATEWAY_SECRETS):
            raise LaunchError(
                "--chat-route api needs ALPHA_GATEWAY_API_BASE and ALPHA_GATEWAY_API_KEY in the "
                "launcher's environment (load the owner's file in the same command; never print it)"
            )
    if args.embedding_route == "provider":
        price = args.provider_embed_usd_per_mtok
        if not args.provider_embed_model or price is None or not math.isfinite(price) or price <= 0:
            raise LaunchError(
                "--embedding-route provider needs --provider-embed-model and a positive "
                "--provider-embed-usd-per-mtok"
            )
        if any(not environ.get(key) for key in GATEWAY_SECRETS):
            raise LaunchError(
                "--embedding-route provider needs ALPHA_GATEWAY_API_BASE and ALPHA_GATEWAY_API_KEY"
            )
    for name in ("data_dir", "run_dir", "gateway_data_dir", "trial_ledger"):
        if not getattr(args, name).is_absolute():
            raise LaunchError(f"--{name.replace('_', '-')} must be an absolute path")
    if args.run_dir.exists():
        raise LaunchError(f"run directory already exists: {args.run_dir}")
    if not args.trial_ledger.parent.is_dir():
        raise LaunchError("the trial ledger's parent directory must exist")
    for name in ("run_dir", "gateway_data_dir", "trial_ledger"):
        if _inside_git(getattr(args, name)):
            raise LaunchError(f"--{name.replace('_', '-')} must be outside every git work tree")
    # Memory is checked after the trial ledger, whose folder gives its default location, so a
    # relative --trial-ledger is reported as such rather than as a bad --memory-dir.
    if not args.no_memory:
        args.memory_dir = args.memory_dir or args.trial_ledger.parent / "research-memory"
        if not args.memory_dir.is_absolute():
            raise LaunchError("--memory-dir must be an absolute path")
        if _inside_git(args.memory_dir.resolve()):
            raise LaunchError("--memory-dir must be outside every git work tree")
    paths = {}
    for key in ("ALPHA_RDAGENT_SOURCE", "ALPHA_FACTOR_PYTHON"):
        value = environ.get(key, "")
        if not value or not Path(value).exists():
            raise LaunchError(f"{key} is not set or missing; run: {SETUP_HINT}")
        paths[key] = Path(value)
    return paths


def loop_environment(
    *,
    base_url: str,
    token: str,
    run: Path,
    factor_python: Path,
    ledger: Path,
    home: str,
    memory_env: dict[str, str] | None = None,
    coder_max_loop: int = 2,
    family_switch_after: int = 3,
    universe_text: str = "15 surviving coins only",
    embedding_model: str | None = None,
    embedding_route: str = "local",
) -> dict[str, str]:
    """The loop's whole environment: exactly these keys and nothing inherited."""
    return {
        "HOME": home,
        "USER": os.environ.get("USER", "alpha"),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "PATH": f"{factor_python.parent}:/usr/bin:/bin",
        "CHAT_MODEL": "lm_studio/alpha-chat",
        "EMBEDDING_MODEL": "lm_studio/alpha-embed",
        **({"ALPHA_EMBEDDING_ROUTE": "provider"} if embedding_route == "provider" else {}),
        **({"ALPHA_EMBEDDING_MODEL": embedding_model} if embedding_model is not None else {}),
        "LM_STUDIO_API_BASE": f"{base_url}/v1",
        "LM_STUDIO_API_KEY": token,
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        # Upstream's attempt count for every chat failure, provider or unusable reply alike:
        # its one retry is the only retry of a reply that fails upstream's own schema check.
        "MAX_RETRY": "2",
        "CONDA_DEFAULT_ENV": "alpha-no-conda",
        # RD-Agent runs generated factor code as a shell string `<python_bin> factor.py` that
        # inherits this environment; strip the gateway settings so that code cannot read them.
        "FACTOR_CoSTEER_python_bin": (
            f"env -u LM_STUDIO_API_KEY -u LM_STUDIO_API_BASE {factor_python}"
        ),
        "ALPHA_FACTOR_CODE_PYTHON": str(factor_python),
        "FACTOR_CoSTEER_max_loop": str(coder_max_loop),
        "FACTOR_CoSTEER_data_folder": str(run / "factor_data" / "full"),
        "FACTOR_CoSTEER_data_folder_debug": str(run / "factor_data" / "debug"),
        "QLIB_FACTOR_SCEN": "alpha_factor_judge.AlphaFactorScenario",
        "QLIB_FACTOR_CODER": "alpha_factor_coder.AlphaFactorCoSTEER",
        "QLIB_FACTOR_RUNNER": "alpha_factor_judge.AlphaFactorRunner",
        "QLIB_FACTOR_SUMMARIZER": "alpha_factor_judge.AlphaFactorFeedback",
        "QLIB_FACTOR_HYPOTHESIS_GEN": "alpha_factor_judge.AlphaFactorHypothesisGen",
        "QLIB_FACTOR_TRAIN_START": "2017-08-17",
        "QLIB_FACTOR_TRAIN_END": "2020-12-31",
        "QLIB_FACTOR_VALID_START": "2021-01-01",
        "QLIB_FACTOR_VALID_END": "2023-12-24",
        "QLIB_FACTOR_TEST_START": "2023-12-25",
        "QLIB_FACTOR_TEST_END": "2023-12-31",
        "LOG_TRACE_PATH": str(run / "work" / "log"),
        "ALPHA_FACTOR_RUN_DIR": str(run),
        "ALPHA_FACTOR_EVAL_PYTHON": str(REPO / ".venv" / "bin" / "python"),
        "ALPHA_FACTOR_TRIAL_LEDGER": str(ledger),
        # ADR-0055: the proposer is told to leave an idea family after this many failed tries.
        "ALPHA_FACTOR_FAMILY_SWITCH_AFTER": str(family_switch_after),
        "ALPHA_FACTOR_UNIVERSE_TEXT": universe_text,
        **(memory_env or {}),
    }


class Launch:
    def __init__(self, args: argparse.Namespace, paths: dict[str, Path]) -> None:
        self.memory_plan: research_memory.MemoryPlan | None = None
        self.token = ""
        self.api_key = os.environ.get("ALPHA_GATEWAY_API_KEY", "")
        self.args = args
        self.run = args.run_dir
        self.source = paths["ALPHA_RDAGENT_SOURCE"]
        self.factor_python = paths["ALPHA_FACTOR_PYTHON"]
        self.bundle = self.factor_python.parents[2]
        self.repo_python = REPO / ".venv" / "bin" / "python"
        self.children: list[subprocess.Popen[bytes]] = []
        self.universe_text = "15 surviving coins only"
        self.receipt: dict[str, Any] = {
            "schema": "AlphaRdagentFactorRunReceiptV1",
            "label": LABEL,
            "authority": AUTHORITY,
            "run_id": args.run_id,
            "loop_n": args.loop_n,
            "run_max_calls": args.run_max_calls,
            "started_at": _now(),
        }

    def log(self, step: str, event: str | None = None, **fields: Any) -> None:
        if event is not None:
            fields["event"] = event
        line = json.dumps({"ts": _now(), "step": step, **fields}, sort_keys=True)
        with (self.run / "launch.jsonl").open("a") as stream:
            stream.write(line + "\n")

    def check(self, step: str, command: Sequence[str], **kwargs: Any) -> str:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            check=False,
            **{"env": _without_secrets(), **kwargs},
        )
        if result.returncode:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            self.log(step, status="failed", exit=result.returncode, detail=tail[0][:300])
            raise LaunchError(f"{step} failed: {tail[0][:300]}")
        self.log(step, status="ok")
        return str(result.stdout.strip())

    def verify(self) -> None:
        self.log("verify", event="start")
        self.receipt["factor_runtime_identity"] = self.check(
            "verify-runtime",
            [
                sys.executable,
                "-B",
                str(WORKER / "install_stock_profile.py"),
                "--profile",
                "factor",
                "--verify",
                str(self.bundle),
            ],
        )
        self.receipt["source_sha256"] = self.check(
            "verify-source",
            [
                sys.executable,
                "-B",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); from source_pin import verify_source;"
                " print(verify_source(__import__('pathlib').Path(sys.argv[2])))",
                str(WORKER),
                str(self.source),
            ],
        )

    def prepare(self) -> None:
        self.log("prepare", event="start")
        panel = self.run / "panel"
        self.check(
            "freeze",
            [
                str(self.repo_python),
                "-I",
                "-m",
                "alpha_cli.rdagent_factor_eval",
                "freeze",
                "--data-dir",
                str(self.args.data_dir),
                "--out",
                str(panel),
                *(["--universe", str(self.args.universe)] if self.args.universe else []),
                *(
                    ["--funding-dir", str(self.args.funding_dir)]
                    if getattr(self.args, "funding_dir", None) is not None
                    else []
                ),
            ],
        )
        receipt = (panel / "panel-receipt.json").read_bytes()
        frozen = json.loads(receipt)
        self.receipt["panel_sha256"] = frozen["panel_sha256"]
        if getattr(self.args, "funding_dir", None) is not None:
            self.receipt["funding_dir"] = str(self.args.funding_dir)
            self.receipt["funding"] = frozen["funding"]
        universe = (
            json.loads((panel / "universe.json").read_bytes())
            if (panel / "universe.json").exists()
            else None
        )
        self.receipt["universe"] = universe["name"] if universe else "default (all coins in store)"
        self.universe_text = (
            f"{len(frozen['instruments'])} instruments ({self.receipt['universe']}); "
            + (universe["survivorship"] if universe else "surviving coins only")
        )
        if "gap_policy" in frozen:
            self.receipt["missing_bars"] = {
                key: frozen[key]
                for key in (
                    "gap_policy",
                    "instruments_ended_early",
                    "missing_instrument_days",
                    "longest_gap",
                )
            }
            self.universe_text += (
                f"; {frozen['instruments_ended_early']} instruments ended early; "
                f"{frozen['missing_instrument_days']} missing instrument-days inside spans. "
                "Haircut counts are reported per evaluation; 30% is a conservative assumption"
            )
        self.receipt["panel_receipt_sha256"] = hashlib.sha256(receipt).hexdigest()
        self.check(
            "prepare",
            [
                str(self.factor_python),
                "-I",
                "-B",
                str(WORKER / "alpha_factor_data.py"),
                "prepare",
                "--panel",
                str(panel / "panel.parquet"),
                "--out",
                str(self.run / "factor_data"),
            ],
        )

    def spawn(self, command: Sequence[str], log: str, **kwargs: Any) -> subprocess.Popen[bytes]:
        with (
            (self.run / "logs" / f"{log}.stdout.log").open("ab") as out,
            (self.run / "logs" / f"{log}.stderr.log").open("ab") as err,
        ):
            child = subprocess.Popen(
                list(command),
                stdout=out,
                stderr=err,
                start_new_session=True,
                **{"env": _without_secrets(), **kwargs},
            )
        self.children.append(child)
        return child

    def gateway(self) -> tuple[str, str]:
        self.log("gateway", event="start")
        self.args.gateway_data_dir.mkdir(parents=True, exist_ok=True)
        state = self.args.gateway_data_dir / "model-gateway"
        command = [
            str(self.repo_python),
            "-B",
            str(WORKER / "model_gateway.py"),
            "serve",
            "--data-dir",
            str(self.args.gateway_data_dir),
            "--run-id",
            self.args.run_id,
            "--run-max-calls",
            str(self.args.run_max_calls),
            "--chat-route",
            self.args.chat_route,
            "--embedding-route",
            self.args.embedding_route,
            "--api-timeout",
            str(self.args.api_timeout),
            "--provider-retries",
            str(self.args.provider_retries),
        ]
        if self.args.embedding_route == "provider":
            command += [
                "--provider-embed-model",
                self.args.provider_embed_model,
                "--provider-embed-usd-per-mtok",
                str(self.args.provider_embed_usd_per_mtok),
            ]
        accept = self.args.accept_unhonoured
        if accept is None:  # the owner accepted losing temperature on the Codex route only
            accept = "temperature" if self.args.chat_route == "codex" else ""
        if accept:
            command += ["--accept-unhonoured", accept]
        if self.args.chat_route == "api":
            command += [
                "--api-model",
                self.args.api_model,
                "--api-price-in-per-mtok",
                str(self.args.api_price_in_per_mtok),
                "--api-price-out-per-mtok",
                str(self.args.api_price_out_per_mtok),
            ]
            if getattr(self.args, "no_router_session", False):
                command.append("--no-router-session")
            if self.args.api_openrouter:
                command.append("--api-openrouter")
        self.receipt["route"] = {
            "chat": self.args.chat_route,
            "embedding": self.args.embedding_route,
            "embedding_model": embedding_model(self.args),
            "provider_embed_usd_per_mtok": self.args.provider_embed_usd_per_mtok,
            "api_model": self.args.api_model,
            "api_price_in_per_mtok": self.args.api_price_in_per_mtok,
            "api_price_out_per_mtok": self.args.api_price_out_per_mtok,
            "api_openrouter": self.args.api_openrouter,
            "router_session_enabled": self.args.chat_route == "api"
            and not getattr(self.args, "no_router_session", False),
            "accept_unhonoured": accept,
            "api_timeout_seconds": self.args.api_timeout,
            "provider_retries": self.args.provider_retries,
            "coding_reasoning_tokens": self.args.coding_reasoning_tokens,
        }
        # Only the gateway inherits the paid route's settings.
        child = self.spawn(command, "gateway", env=dict(os.environ))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise LaunchError(f"model gateway exited with {child.returncode}; see logs")
            try:
                session = json.loads((state / f"session-{child.pid}.json").read_text())
            except (OSError, ValueError):
                session = {}
            if session.get("pid") == child.pid:
                self.log("gateway", status="ok", base_url=session["base_url"])
                return str(session["base_url"]), str(session["token"])
            time.sleep(0.2)
        raise LaunchError("model gateway did not write its session within 30 s")

    def loop(self, base_url: str, token: str) -> int:
        self.log("loop", event="start")
        self.token = token
        if not self.args.no_memory:
            try:
                self.memory_plan = research_memory.prepare(
                    self.args.memory_dir or self.args.trial_ledger.parent / "research-memory",
                    run_id=self.args.run_id,
                    run_dir=self.run,
                    source_sha256=SOURCE_SHA256,
                    judge_sha256=research_memory.judge_sha256(),
                )
            except Exception as error:  # memory is a warning, never a refusal
                self.receipt["memory_warning"] = (
                    f"memory unavailable ({type(error).__name__}); this run starts fresh"
                )
                self.log("memory", status="unavailable", error_type=type(error).__name__)
            else:
                self.log("memory", warnings=[w["code"] for w in self.memory_plan.warnings])
        work = self.run / "work"
        work.mkdir()
        environment = loop_environment(
            base_url=base_url,
            token=token,
            run=self.run,
            factor_python=self.factor_python,
            ledger=self.args.trial_ledger,
            home=str(self.run / "home"),
            memory_env=self.memory_plan.env if self.memory_plan else None,
            coder_max_loop=self.args.coder_max_loop,
            family_switch_after=self.args.family_switch_after,
            universe_text=self.universe_text,
            embedding_route=self.args.embedding_route,
            embedding_model=embedding_model(self.args)
            if self.args.embedding_route in ("provider", "fake")
            else None,
        )
        environment.update(
            ALPHA_GATEWAY_CALLS=str(self.args.gateway_data_dir / "model-gateway/calls.jsonl"),
            ALPHA_GATEWAY_RUN_ID=self.args.run_id,
        )
        (self.run / "home").mkdir()
        self.log("loop", status="started", keys=sorted(environment))
        child = self.spawn(
            [
                str(self.factor_python),
                "-I",
                "-B",
                str(WORKER / "factor_loop_entry.py"),
                str(self.source),
                str(self.args.loop_n),
            ],
            "loop",
            cwd=work,
            env=environment,
        )
        try:
            return child.wait(timeout=self.args.wall_seconds)
        except subprocess.TimeoutExpired:
            self.log("loop", status="timeout", wall_seconds=self.args.wall_seconds)
            self.receipt["loop_reason"] = "wall-clock limit"
            return -1

    def stop(self) -> None:
        # Signal every group even when its leader has exited: orphaned members (a factor run,
        # the evaluator) keep the group alive.
        for child in reversed(self.children):
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    break
                deadline = time.monotonic() + (10.0 if sig == signal.SIGTERM else 5.0)
                while time.monotonic() < deadline:
                    child.poll()
                    try:
                        os.killpg(child.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.1)
                else:
                    continue
                break
        self.children.clear()

    def gateway_status(self) -> Any:
        result = subprocess.run(
            [
                str(self.repo_python),
                "-B",
                str(WORKER / "model_gateway.py"),
                "status",
                "--data-dir",
                str(self.args.gateway_data_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=_without_secrets(),
        )
        try:
            state = json.loads(result.stdout)
        except ValueError:
            return {"error": (result.stderr or "no output").strip()[:300]}
        return {
            "caps": state.get("caps"),
            "this_run": state.get("runs", {}).get(self.args.run_id),
            "months": state.get("months"),
        }

    def write_call_labels(self) -> dict[str, Any]:
        output = self.run / "calls-labelled.jsonl"
        paths = (self.args.gateway_data_dir / "model-gateway/calls.jsonl", self.run / "steps.jsonl")
        try:
            missing = [str(p) for p in paths if not p.exists()]
            if not paths[0].exists():
                output.write_bytes(b"")
                return {"calls": 0, "reason": "missing files: " + ", ".join(missing)}
            skipped = 0
            parsed: list[list[dict[str, Any]]] = []
            for p in paths:
                rows = []
                for line in p.read_text().splitlines() if p.exists() else []:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        skipped += 1  # a line cut short by a killed process
                parsed.append(rows)
            calls = [row for row in parsed[0] if row.get("run_id") == self.args.run_id]
            labelled = label_calls(calls, parsed[1]) if paths[1].exists() else []
            output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in labelled))
            self.receipt["call_split"] = call_split(calls, labelled)
            return {"calls": len(labelled), "skipped_lines": skipped}
        except Exception as error:  # labelling is best effort, with receipt diagnostics
            note = f"{type(error).__name__}: {error}"
            try:
                output.write_bytes(b"")
            except OSError as write_error:
                note += f"; empty output: {type(write_error).__name__}: {write_error}"
            return {"calls": 0, "reason": note}

    def finish(self, exit_status: int, reason: str) -> int:
        evaluations = self.run / "evaluations.jsonl"
        stop = self.run / "loop-stop.json"
        if stop.exists():
            reason = json.loads(stop.read_text())["loop_reason"]
        self.receipt.update(
            ended_at=_now(),
            exit_status=exit_status,
            loop_reason=self.receipt.get("loop_reason", reason),
            gateway_status=self.gateway_status(),
            calls_labelled=self.write_call_labels(),
            # Coding-memory entries left out because their embedding was refused (ADR-0055).
            memory_entries_skipped=len((self.run / "memory-skips.jsonl").read_text().splitlines())
            if (self.run / "memory-skips.jsonl").exists()
            else 0,
            evaluations_sha256=hashlib.sha256(evaluations.read_bytes()).hexdigest()
            if evaluations.exists()
            else None,
        )
        self.receipt.update(round_counts(self.run))
        vectors = self.run / "knowledge-vectors.json"
        if vectors.exists():
            self.receipt.update(json.loads(vectors.read_text()))
        history = self.run / "history-context.json"
        self.receipt.update(
            json.loads(history.read_text())
            if history.exists()
            else {"history_rounds_full": 0, "history_rounds_summarised": 0}
        )
        split = self.receipt.get("call_split", {})
        for key in (
            "reask_calls",
            "reask_usd",
            "provider_embedding_requests",
            "provider_embedding_inputs",
            "embedding_single_retries",
            "embedding_model_not_reported",
            "embedding_cache_hits",
            "embedding_requests",
            "embedding_inputs_sent",
        ):
            self.receipt[key] = split.get(key, 0)
        self.receipt["provider_call_seconds_with_retries"] = split.get(
            "provider_call_seconds_with_retries", split.get("provider_wait_seconds", 0)
        )
        counters = self.receipt["gateway_status"].get("this_run") or {}
        self.receipt.update(
            counted_calls=counters.get("counted_calls", counters.get("calls")),
            local_embedding_calls=counters.get("local_embedding_calls", 0) if counters else None,
            embedding_route=getattr(self.args, "embedding_route", "local"),
            embedding_model=embedding_model(self.args),
            provider_embedding_calls=counters.get("provider_embedding_calls", 0)
            if counters
            else None,
            provider_embedding_usd=counters.get("provider_embedding_usd", 0.0)
            if counters
            else None,
            provider_embedding_tokens=counters.get("provider_embedding_tokens", 0)
            if counters
            else None,
            memory_entries_reembedded=len(
                (self.run / "memory-reembedded.jsonl").read_text().splitlines()
            )
            if (self.run / "memory-reembedded.jsonl").exists()
            else 0,
            call_cap_note=(
                "Provider embeddings count toward money caps and the shared embedding limit, "
                "not the 60-call cap or monthly call count."
                if getattr(self.args, "embedding_route", "local") == "provider"
                else "Local embeddings are free and are not counted toward the 60-call cap."
            ),
        )
        self.receipt["memory"] = (
            research_memory.record(
                self.memory_plan,
                run_id=self.args.run_id,
                run_dir=self.run,
                started_at=self.receipt["started_at"],
                ended_at=self.receipt["ended_at"],
                secrets=(self.token, self.api_key),
                exit_reason=self.receipt["loop_reason"],
            )
            if self.memory_plan
            else {"enabled": False}
        )
        self.log(
            "loop", event="end", exit_reason=self.receipt["loop_reason"], exit_status=exit_status
        )
        print(f"RD-Agent loop ended: {self.receipt['loop_reason']}.")
        (self.run / "receipt.json").write_text(json.dumps(self.receipt, indent=2, sort_keys=True))
        return exit_status


def round_counts(run: Path) -> dict[str, int | float]:
    rounds_path, evaluations = run / "rounds.jsonl", run / "evaluations.jsonl"
    rounds = (
        [json.loads(line) for line in rounds_path.read_text().splitlines()]
        if rounds_path.exists()
        else []
    )
    evaluated = (
        [json.loads(line) for line in evaluations.read_text().splitlines()]
        if evaluations.exists()
        else []
    )
    refused = [
        row
        for row in rounds
        if row.get("refused_families", row.get("closed_families"))
        or row.get("reason") == "refused_closed_family"
    ]
    return {
        "rounds_with_trial": len({row["iteration"] for row in evaluated if row.get("factors")}),
        "rounds_no_admissible_idea": sum(
            row.get("status") == "no_admissible_idea" for row in rounds
        ),
        "proposals_refused": len(refused),
        "rounds_failed_provider": len(
            {
                r["iteration"]
                for r in rounds
                if str(r.get("status", "")).startswith(
                    ("coding_failed_provider_", "proposal_failed_provider_")
                )
            }
        ),
        "provider_failed_wait_seconds": sum(
            float(r.get("provider_wait_seconds", 0)) for r in rounds
        ),
    }


def embedding_model(args: argparse.Namespace) -> str:
    route = getattr(args, "embedding_route", "local")
    if route == "provider":
        return str(args.provider_embed_model)
    return "fake" if route == "fake" else "nomic-embed-text"


def call_split(
    calls: list[dict[str, Any]], labelled: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Model calls versus free local embeddings, as the gateway logged them.

    Only embedding rows the gateway marked ``local_embedding`` or ``provider_embedding`` are exempt
    (owner decision 2026-11-17); old logs without the mark stay counted as they were.
    """
    split: dict[str, Any] = {
        "model_chat": {"requests": 0, "attempts": 0, "usd": 0.0},
        "local_embedding": {"requests": 0, "attempts": 0, "usd": 0.0},
        "provider_embedding": {"requests": 0, "attempts": 0, "usd": 0.0},
        "counted_calls": 0,
        "local_embedding_calls": 0,
        "provider_embedding_calls": 0,
        "provider_embedding_requests": 0,
        "provider_embedding_inputs": 0,
        "embedding_single_retries": 0,
        "embedding_model_not_reported": 0,
        "provider_embedding_usd": 0.0,
        "provider_embedding_tokens": 0,
        "provider_timeouts": 0,
        "empty_or_invalid_replies": 0,
        "retried_attempts": 0,
        "timeout_retry_attempts": 0,
        "failed_requests": {},
        "chunked_embedding_inputs": 0,
        "embedding_chunks": 0,
        "embedding_cache_hits": 0,
        "embedding_requests": 0,
        "embedding_inputs_sent": 0,
        "provider_call_seconds_with_retries": 0.0,
    }
    routes: set[str] = set()
    models: set[str] = set()
    for call in calls:
        split["embedding_cache_hits"] += int(call.get("embedding_cache_hits", 0))
        if call.get("cache_only"):
            continue
        if call.get("endpoint") == "/v1/chat/completions" and call.get("provider_errors"):
            split["provider_call_seconds_with_retries"] += float(call.get("latency_ms", 0)) / 1000
        if call.get("endpoint") == "/v1/embeddings":
            split["embedding_requests"] += int(call.get("attempts", 0))
            split["embedding_inputs_sent"] += int(call.get("embedding_inputs_sent", 0))
            if isinstance(call.get("route"), str):
                routes.add(call["route"])
            if isinstance(call.get("model_used"), str):
                models.add(call["model_used"])
        kind = "model_chat" if call.get("endpoint") == "/v1/chat/completions" else "local_embedding"
        if kind == "local_embedding" and call.get("local_embedding") is False:
            kind = "provider_embedding"
        split[kind]["requests"] += 1
        split[kind]["attempts"] += int(call.get("attempts") or 0)
        split[kind]["usd"] += float(call.get("usd") or 0.0)
        split["chunked_embedding_inputs"] += int(call.get("chunked_inputs") or 0)
        split["embedding_chunks"] += int(call.get("chunks") or 0)
        errors = call.get("provider_errors") or []
        split["provider_timeouts"] += errors.count("provider_timeout")
        split["empty_or_invalid_replies"] += errors.count("invalid_provider_response")
        attempts = int(call.get("attempts") or 0)
        local = kind == "local_embedding" and call.get("local_embedding") is True
        provider = kind == "provider_embedding" and call.get("provider_embedding") is True
        bucket = (
            "local_embedding_calls"
            if local
            else "provider_embedding_calls"
            if provider
            else "counted_calls"
        )
        split[bucket] += attempts
        if provider:
            split["provider_embedding_requests"] += attempts
            split["provider_embedding_inputs"] += (
                int(call.get("input_count") or 0) if not call.get("single_retry") else 0
            )
            split["embedding_single_retries"] += int(bool(call.get("single_retry"))) * attempts
            split["embedding_model_not_reported"] += int(
                call.get("model_check") == "model_not_reported"
            )
            split["provider_embedding_usd"] += float(call.get("usd") or 0)
            split["provider_embedding_tokens"] += int(call.get("prompt_tokens") or 0)
        split["retried_attempts"] += max(0, attempts - 1)
        split["timeout_retry_attempts"] += int(
            call.get(
                "timeout_retry_attempts", errors[: max(0, attempts - 1)].count("provider_timeout")
            )
        )
        if call.get("status") != 200:
            code = str(call.get("error_code"))
            split["failed_requests"][code] = split["failed_requests"].get(code, 0) + 1
    split.update(
        embedding_route=next(iter(routes)) if len(routes) == 1 else None,
        embedding_model=next(iter(models)) if len(models) == 1 else None,
        embedding_routes=sorted(routes),
        embedding_models=sorted(models),
    )
    reasks = [
        c
        for c in labelled or []
        if c.get("step") == "proposal_reask" and c.get("endpoint") == "/v1/chat/completions"
    ]
    split["proposal_prompt_chars"] = [
        {"loop": c.get("loop"), "step": c["step"], "chars": c["total_prompt_chars"]}
        for c in labelled or []
        if c.get("step") in ("direct_exp_gen", "proposal_reask")
        and c.get("endpoint") == "/v1/chat/completions"
        and "total_prompt_chars" in c
    ]
    split["reask_calls"] = sum(int(c.get("attempts") or 0) for c in reasks)
    split["reask_usd"] = sum(float(c.get("usd") or 0) for c in reasks)
    split["chat_usage"] = gateway_usage.receipt_usage(calls, labelled)
    split["counted_toward_call_cap"] = split["counted_calls"]
    return split


def exit_reason(code: int, gateway_state: Any, args: argparse.Namespace) -> str:
    """A plain reason for a failed loop; names the call cap when the run used all of it."""
    embedding_limit = importlib.import_module("gateway_embeddings").EMBEDDING_CALLS_PER_RUN

    this_run = gateway_state.get("this_run") if isinstance(gateway_state, dict) else None
    local = (this_run or {}).get("local_embedding_calls", 0) + (this_run or {}).get(
        "provider_embedding_calls", 0
    )
    if local >= embedding_limit:
        return f"loop exit {code}: embedding limit reached (EMBEDDING_CALLS_PER_RUN: {local})"
    calls = (this_run or {}).get("counted_calls", (this_run or {}).get("calls")) or 0
    if calls >= args.run_max_calls:
        return f"loop exit {code}: model call cap reached ({calls} of {args.run_max_calls} calls)"
    return f"loop exit {code}"


def run(args: argparse.Namespace, environ: dict[str, str]) -> int:
    paths = validate(args, environ)
    args.run_dir.mkdir()
    write_launch_command(args.run_dir, getattr(args, "command_line", sys.argv[1:]), environ)
    with (args.run_dir / "run-identity.json").open("x") as stream:
        stream.write(json.dumps({"run_id": args.run_id}) + "\n")
    (args.run_dir / "logs").mkdir()
    launch = Launch(args, paths)
    launch.api_key = environ.get("ALPHA_GATEWAY_API_KEY", "")

    def interrupted(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)}
    status, reason = 1, "not started"
    try:
        launch.verify()
        launch.prepare()
        base_url, token = launch.gateway()
        code = launch.loop(base_url, token)
        status, reason = (
            (0, "completed") if code == 0 else (1, exit_reason(code, launch.gateway_status(), args))
        )
    except LaunchError as error:
        reason = str(error)
    except KeyboardInterrupt:
        launch.log("cancel", status="cancelled")
        reason = "cancelled"
    except Exception as error:  # every failure still stops children and writes a receipt
        launch.log("error", status="failed", detail=repr(error)[:300])
        reason = f"unexpected error: {error!r}"[:300]
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)  # a second signal must not abort the cleanup
        try:
            launch.stop()
            status = launch.finish(status, reason)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    return status


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Launch one ALPHA-judged RD-Agent factor loop (ADR-0049)."
    )
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run")
    r.add_argument("--data-dir", type=Path, required=True)
    r.add_argument("--funding-dir", type=Path)
    r.add_argument("--run-dir", type=Path, required=True)
    r.add_argument("--gateway-data-dir", type=Path, required=True)
    r.add_argument("--trial-ledger", type=Path, required=True)
    r.add_argument("--run-id", required=True)
    r.add_argument("--loop-n", type=int, default=2)
    r.add_argument("--memory-dir", type=Path)
    r.add_argument("--no-memory", action="store_true")
    r.add_argument("--coder-max-loop", type=int, default=2)
    r.add_argument("--run-max-calls", type=int, default=MAX_CALLS)
    r.add_argument("--wall-seconds", type=float, default=5400)
    r.add_argument("--chat-route", choices=("codex", "api", "fake"), default="codex")
    r.add_argument(
        "--embedding-route", choices=("local", "provider", "ollama", "fake"), default="local"
    )
    r.add_argument("--provider-embed-model")
    r.add_argument("--provider-embed-usd-per-mtok", type=float)
    r.add_argument("--accept-unhonoured", default=None)
    r.add_argument("--api-model")
    r.add_argument("--api-price-in-per-mtok", type=float)
    r.add_argument("--api-price-out-per-mtok", type=float)
    r.add_argument("--api-openrouter", action="store_true")
    r.add_argument("--no-router-session", action="store_true")
    r.add_argument("--api-timeout", type=float, default=180)
    r.add_argument("--provider-retries", type=int, default=1)
    r.add_argument("--coding-reasoning-tokens", type=int, default=None)
    r.add_argument("--family-switch-after", type=int, default=3)
    r.add_argument("--universe", type=Path)
    return p


def main(argv: Sequence[str] | None = None, *, runner: Callable[..., int] = run) -> int:
    args = parser().parse_args(argv)
    args.command_line = list(sys.argv[1:] if argv is None else argv)
    try:
        return runner(args, dict(os.environ))
    except LaunchError as error:
        print(f"factor-loop-launch: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
