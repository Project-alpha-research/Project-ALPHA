"""MCP tools for the main research path: rule tests, checks, results and the trial ledger.

Each tool is a thin wrapper. It validates a closed, explicit argument list, builds one ``alpha``
argv ending in ``--json``, and runs it through :func:`alpha_mcp._invoke.run_json`. The server
computes nothing and reads no result files. No tool here can approve, promote, confirm reserved
data, override a bad-data stop, answer an RD-Agent proposal or place an order: those flags are
not in any argument list. Text inputs are written to a content-addressed file inside
``<data dir>/mcp-inputs``; a spec given by path must resolve inside the data directory.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Literal

from mcp.server.fastmcp import FastMCP

from alpha_cli.run_store import valid_run_id
from alpha_core.config import AlphaSettings
from alpha_mcp import _invoke

_LONG_TIMEOUT_S: Final = 3600.0
_MAX_TEXT: Final = 256
_MAX_DOCUMENT_CHARS: Final = 65_536
_MAX_ASSETS: Final = 100
_MAX_PARAMS: Final = 16
_INPUT_DIR: Final = "mcp-inputs"
_ASSET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:@[A-Za-z0-9][A-Za-z0-9._-]{0,63})?")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}")
_PARAM_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _data_dir() -> Path:
    return AlphaSettings().data_dir


def _text(value: object, label: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{label} must be a non-empty string of at most {max_length} characters")
    if any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError(f"{label} contains a forbidden control character")
    return value


def _matching(value: object, label: str, pattern: re.Pattern[str]) -> str:
    text = _text(value, label, max_length=128)
    if pattern.fullmatch(text) is None or ".." in text:
        raise ValueError(f"{label} is not a safe identifier")
    return text


def _run_id(value: object) -> str:
    text = _text(value, "run_id", max_length=64)
    if not valid_run_id(text):
        raise ValueError("run_id must be a 16-character run id")
    return text


def _number(value: float, label: str, *, low: float = 0.0) -> str:
    if isinstance(value, bool) or not math.isfinite(value) or value < low:
        raise ValueError(f"{label} must be a finite number of at least {low}")
    return repr(float(value))


def _key_values(values: dict[str, str] | None, label: str) -> list[str]:
    """``--param key=value`` pairs: declared-shape keys, numeric or short text values."""
    if not values:
        return []
    if len(values) > _MAX_PARAMS:
        raise ValueError(f"{label} accepts at most {_MAX_PARAMS} entries")
    flags: list[str] = []
    for key in sorted(values):
        if _PARAM_KEY.fullmatch(key) is None:
            raise ValueError(f"{label} name {key!r} is not a plain identifier")
        value = _text(str(values[key]), f"{label} {key}", max_length=128)
        if "=" in value:
            raise ValueError(f"{label} {key} must not contain '='")
        flags += ["--param", f"{key}={value}"]
    return flags


def _inside_data_dir(path_text: str, data_dir: Path) -> str:
    candidate = Path(_text(path_text, "path", max_length=1024)).expanduser()
    root = data_dir.resolve()
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("path must stay inside the ALPHA data directory")
    return str(resolved)


def _write_input(text: str, suffix: str, data_dir: Path) -> str:
    """Write caller text to a content-addressed file under the data directory; return its path."""
    body = _text_document(text)
    folder = data_dir / _INPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{hashlib.sha256(body.encode()).hexdigest()[:16]}{suffix}"
    if not target.exists():
        target.write_text(body, encoding="utf-8")
    return str(target)


def _text_document(text: object) -> str:
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_DOCUMENT_CHARS:
        raise ValueError(f"text must be non-empty and at most {_MAX_DOCUMENT_CHARS} characters")
    if "\x00" in text:
        raise ValueError("text contains a NUL character")
    return text


def _spec_argument(
    spec_text: str | None, spec_format: str, spec_path: str | None, data_dir: Path
) -> str | None:
    if spec_text is not None and spec_path is not None:
        raise ValueError("give spec_text or spec_path, not both")
    if spec_format not in {"toml", "json"}:
        raise ValueError("spec_format must be toml or json")
    if spec_text is not None:
        return _write_input(spec_text, f".{spec_format}", data_dir)
    if spec_path is not None:
        return _inside_data_dir(spec_path, data_dir)
    return None


def _assets(values: list[str] | None) -> list[str]:
    if not values:
        return []
    if len(values) > _MAX_ASSETS or len(set(values)) != len(values):
        raise ValueError(f"assets must be 1..{_MAX_ASSETS} distinct symbols")
    flags: list[str] = []
    for value in values:
        flags += ["--asset", _matching(value, "asset", _ASSET)]
    return flags


def _run(args: list[str], *, long: bool = False) -> Any:
    if long:
        return _invoke.run_json(args, data_dir=_data_dir(), timeout_seconds=_LONG_TIMEOUT_S)
    return _invoke.run_json(args, data_dir=_data_dir())


def rule_test(
    rule: Literal["ma_cross", "breakout", "tsmom"] | None = None,
    params: dict[str, str] | None = None,
    assets: list[str] | None = None,
    name: str | None = None,
    idea: str | None = None,
    fee_bps: float | None = None,
    slippage_bps: float | None = None,
    quick: bool = False,
    diagnose: bool = True,
    check_data: bool = False,
    spec_text: str | None = None,
    spec_format: str = "toml",
    spec_path: str | None = None,
) -> Any:
    """Run `alpha test`: test a long/flat rule on several assets and record every trial.

    Give a rule (ma_cross, breakout or tsmom) with params and assets, or a spec as text
    (spec_text) or as a path inside the ALPHA data directory (spec_path). Runs the stored-data
    gauntlet and returns the JSON result. Results are research records, not approvals.
    """
    data_dir = _data_dir()
    spec = _spec_argument(spec_text, spec_format, spec_path, data_dir)
    if spec is None and rule is None:
        raise ValueError("give a rule or a spec")
    if spec is not None and (rule is not None or params):
        raise ValueError("a spec already holds the rule and its parameters")
    args = ["test"] + ([spec] if spec is not None else [])
    if rule is not None:
        args += ["--rule", rule]
    args += _key_values(params, "params") + _assets(assets)
    if name is not None:
        args += ["--name", _text(name, "name")]
    if idea is not None:
        args += ["--idea", _text(idea, "idea", max_length=1024)]
    if fee_bps is not None:
        args += ["--fee-bps", _number(fee_bps, "fee_bps")]
    if slippage_bps is not None:
        args += ["--slippage-bps", _number(slippage_bps, "slippage_bps")]
    args += ["--quick"] if quick else []
    args += [] if diagnose else ["--no-diagnose"]
    args += ["--check-data"] if check_data else []
    return _run([*args, "--json"], long=True)


def tool_list(
    for_target: str | None = None,
    search: str | None = None,
    family: str | None = None,
    kind: str | None = None,
) -> Any:
    """Run `alpha tool list`: find investigation tools by target, question, family or kind.

    Returns the JSON list of tools. Results are research records, not approvals.
    """
    args = ["tool", "list"]
    for flag, value in (
        ("--for", for_target),
        ("--search", search),
        ("--family", family),
        ("--kind", kind),
    ):
        if value is not None:
            args += [flag, _text(value, flag.removeprefix("--"))]
    return _run([*args, "--json"])


def tool_describe(tool_id: str) -> Any:
    """Run `alpha tool describe`: read a tool's question, inputs, parameters and caveats.

    Returns the JSON description. Results are research records, not approvals.
    """
    return _run(["tool", "describe", _matching(tool_id, "tool_id", _ID), "--json"])


def tool_run(tool_id: str, target: str, params: dict[str, str] | None = None, seed: int = 0) -> Any:
    """Run `alpha tool run`: run one investigation tool on a target with key=value parameters.

    The run is recorded in the trial ledger and returns JSON. Results are research records,
    not approvals.
    """
    if isinstance(seed, bool) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be an integer from 0 to 2147483647")
    args = ["tool", "run", _matching(tool_id, "tool_id", _ID), _matching(target, "target", _TARGET)]
    return _run([*args, *_key_values(params, "params"), "--seed", str(seed), "--json"], long=True)


def tool_run_set(name: str, target: str) -> Any:
    """Run `alpha tool run-set`: run each member of a predeclared tool set on a target.

    Reports every outcome as JSON. Results are research records, not approvals.
    """
    args = ["tool", "run-set", _matching(name, "name", _ID), _matching(target, "target", _TARGET)]
    return _run([*args, "--json"], long=True)


def results_show(run_id: str) -> Any:
    """Run `alpha results show`: read a rule test's stored facts, checks and tool outputs.

    Returns JSON. Results are research records, not approvals.
    """
    return _run(["results", "show", _run_id(run_id), "--json"])


def results_cite(run_id: str, metric: str, tool_output: str | None = None) -> Any:
    """Run `alpha results cite`: quote exactly one stored fact of a rule test.

    It never recomputes a metric. Returns JSON. Results are research records, not approvals.
    """
    args = ["results", "cite", _run_id(run_id), _matching(metric, "metric", _ID)]
    if tool_output is not None:
        args += ["--tool-output", _matching(tool_output, "tool_output", _ID)]
    return _run([*args, "--json"])


def results_check(draft_text: str, allow_untagged: int = 0) -> Any:
    """Run `alpha results check`: check a draft's tagged numbers and labels against stored facts.

    The draft text is saved inside the ALPHA data directory first. Returns JSON. Results are
    research records, not approvals.
    """
    if isinstance(allow_untagged, bool) or not 0 <= allow_untagged <= 1000:
        raise ValueError("allow_untagged must be an integer from 0 to 1000")
    path = _write_input(draft_text, ".md", _data_dir())
    return _run(["results", "check", path, "--allow-untagged", str(allow_untagged), "--json"])


def ledger_summary() -> Any:
    """Run `alpha ledger summary`: summarise mapped trials, unknown rows and missing sources.

    Read-only. Returns JSON. Results are research records, not approvals.
    """
    return _run(["ledger", "summary", "--json"])


def ledger_history(
    kind: str | None = None,
    family: str | None = None,
    asset: str | None = None,
    outcome: str | None = None,
    source: str | None = None,
    limit: int = 50,
) -> Any:
    """Run `alpha ledger list`: list recorded trials, newest first, with their source.

    Read-only. Returns JSON. Results are research records, not approvals.
    """
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    args = ["ledger", "list"]
    for flag, value in (
        ("--kind", kind),
        ("--family", family),
        ("--asset", asset),
        ("--outcome", outcome),
        ("--source", source),
    ):
        if value is not None:
            args += [flag, _text(value, flag.removeprefix("--"))]
    return _run([*args, "--limit", str(limit), "--json"])


def diagnose_run(run_id: str) -> Any:
    """Run `alpha diagnose`: read the diagnostic pass and audit stored with a rule test.

    Returns JSON. Results are research records, not approvals.
    """
    return _run(["diagnose", _run_id(run_id), "--json"])


def data_health(asset: str, stored: bool = False) -> Any:
    """Run `alpha data health`: check daily bars for adjustment, timestamp and gap faults.

    With stored=True, read the saved report instead. Returns JSON. Results are research
    records, not approvals.
    """
    args = ["data", "health", _matching(asset, "asset", _ASSET)]
    return _run([*args, *(["--stored"] if stored else []), "--json"])


def setup_find(
    spec_text: str | None = None,
    spec_format: str = "toml",
    spec_path: str | None = None,
    asset: str | None = None,
    context_bars: int = 60,
    max_sheets: int = 10,
    check_data: bool = False,
) -> Any:
    """Run `alpha setup find`: record every match of a chart setup and draw contact sheets.

    Give the spec as text (spec_text) or as a path inside the ALPHA data directory. Returns
    JSON. Results are research records, not approvals.
    """
    spec = _spec_argument(spec_text, spec_format, spec_path, _data_dir())
    if spec is None:
        raise ValueError("give spec_text or spec_path")
    if not 5 <= context_bars <= 250 or not 1 <= max_sheets <= 50:
        raise ValueError("context_bars must be 5..250 and max_sheets 1..50")
    args = ["setup", "find", spec]
    if asset is not None:
        args += ["--asset", _matching(asset, "asset", _ASSET)]
    args += ["--context-bars", str(context_bars), "--max-sheets", str(max_sheets)]
    args += ["--check-data"] if check_data else []
    return _run([*args, "--json"], long=True)


def setup_study(find_id: str, check_data: bool = False) -> Any:
    """Run `alpha setup study`: measure forward returns and controls; record one exploratory trial.

    Returns JSON. Results are research records, not approvals.
    """
    args = ["setup", "study", _matching(find_id, "find_id", _ID)]
    return _run([*args, *(["--check-data"] if check_data else []), "--json"], long=True)


def setup_trade(find_id: str, check_data: bool = False) -> Any:
    """Run `alpha setup trade`: trade recorded occurrences with exits and matched controls.

    This is one counted test, recorded in the ledger. Returns JSON. Results are research
    records, not approvals.
    """
    args = ["setup", "trade", _matching(find_id, "find_id", _ID)]
    return _run([*args, *(["--check-data"] if check_data else []), "--json"], long=True)


SPINE_TOOLS: Final[tuple[Callable[..., Any], ...]] = (
    rule_test,
    tool_list,
    tool_describe,
    tool_run,
    tool_run_set,
    results_show,
    results_cite,
    results_check,
    ledger_summary,
    ledger_history,
    diagnose_run,
    data_health,
    setup_find,
    setup_study,
    setup_trade,
)


def register(server: FastMCP) -> None:
    """Register every spine tool and make each one refuse any argument it does not declare."""
    manager = server._tool_manager
    for function in SPINE_TOOLS:
        server.tool()(function)
        arguments = manager.get_tool(function.__name__)
        if arguments is None:
            raise RuntimeError(f"{function.__name__} was not registered")
        model = arguments.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)
