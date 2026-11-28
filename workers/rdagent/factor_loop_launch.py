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
    from . import factor_loop_calls, factor_loop_checks, research_memory

WORKER = Path(__file__).resolve().parent
REPO = WORKER.parents[1]
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))

if not TYPE_CHECKING:
    research_memory = importlib.import_module("research_memory")
    factor_loop_calls = importlib.import_module("factor_loop_calls")
    factor_loop_checks = importlib.import_module("factor_loop_checks")
SOURCE_SHA256: str = importlib.import_module("source_pin").SOURCE_SHA256

LaunchError = factor_loop_checks.LaunchError
MAX_CALLS = factor_loop_checks.MAX_CALLS
GATEWAY_SECRETS = factor_loop_checks.GATEWAY_SECRETS
validate = factor_loop_checks.validate
label_calls = factor_loop_calls.label_calls
round_counts = factor_loop_calls.round_counts
call_split = factor_loop_calls.call_split
LABEL = "exploratory, not admitted, not yet confirmed"
AUTHORITY = dict.fromkeys(("admitted", "evidence", "approval", "promotion"), False)


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


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
        # The gateway process, its session files and its token, removed again by stop().
        self.gateway_session: tuple[subprocess.Popen[bytes], tuple[Path, Path], str] | None = None
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
                files = (state / f"session-{child.pid}.json", state / "session.json")
                self.gateway_session = (child, files, str(session["token"]))
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
        if self.args.discuss:
            environment.update(
                ALPHA_FACTOR_DISCUSS="1",
                ALPHA_DISCUSS_ROUNDS_TOTAL=str(self.args.loop_n),
                ALPHA_DISCUSS_WAIT_MINUTES=str(self.args.discuss_wait_minutes),
                ALPHA_DISCUSS_ON_TIMEOUT=self.args.discuss_on_timeout,
                ALPHA_DISCUSS_MAX_CALLS=str(self.args.run_max_calls),
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
            if self.gateway_session and self.gateway_session[0] is child:
                self._remove_gateway_session(*self.gateway_session[1:])
        self.children.clear()

    def _remove_gateway_session(self, files: tuple[Path, Path], token: str) -> None:
        """A gateway signalled before it installs its handler, or killed after the wait, cannot
        remove its own session files. Remove each one that still carries this run's token."""
        self.gateway_session = None
        for path in files:
            try:
                if json.loads(path.read_text()).get("token") == token:
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass

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
        if getattr(self.args, "discuss", False) and counters:
            self.receipt["discussion_usage"] = {
                "chat_used": self.receipt["counted_calls"],
                "chat_cap": self.args.run_max_calls,
                "embedding_used": counters.get("local_embedding_calls", 0)
                + counters.get("provider_embedding_calls", 0),
                "embedding_cap": importlib.import_module(
                    "gateway_embeddings"
                ).EMBEDDING_CALLS_PER_RUN,
            }
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
        if usage := self.receipt.get("discussion_usage"):
            print(
                f"Usage in this run: {usage['chat_used']} of {usage['chat_cap']} chat calls, "
                f"{usage['embedding_used']} of {usage['embedding_cap']} embedding calls."
            )
        discussion_path = self.run / "discussion/status.json"
        if discussion_path.exists():
            previous = json.loads(discussion_path.read_bytes())
            if previous["state"] != "stopped":
                importlib.import_module("discussion").status(
                    self.run,
                    "ended",
                    previous["round"],
                    datetime.fromisoformat(self.receipt["ended_at"]),
                )
        (self.run / "receipt.json").write_text(json.dumps(self.receipt, indent=2, sort_keys=True))
        return exit_status


def embedding_model(args: argparse.Namespace) -> str:
    route = getattr(args, "embedding_route", "local")
    if route == "provider":
        return str(args.provider_embed_model)
    return "fake" if route == "fake" else "nomic-embed-text"


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
    r.add_argument("--discuss", action="store_true", help="Wait for a reply before coding.")
    r.add_argument("--discuss-wait-minutes", type=int, default=30)
    r.add_argument("--discuss-on-timeout", choices=("proceed", "stop"), default="proceed")
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
