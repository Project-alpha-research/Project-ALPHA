"""`alpha nightly run`: the golden paths, one real command at a time, on the stored data.

N1 is the rule path, N2 the setup path, N3 the RD-Agent path (off until `rdagent_config` is
set). Each step is the installed command in a child process. A failed step does not stop the
independent steps after it; steps that need it are marked "not run".
"""

from __future__ import annotations

import shlex
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_record import ALL, N3_STUB, build_record, new_folder, write_record
from alpha_cli.nightly_steps import (
    BLOCKING,
    MINOR,
    PASS,
    Runner,
    alpha_argv,
    evidence_of,
    mark,
    new_step,
    not_run,
    run_step,
    stderr_tail,
)
from alpha_cli.spine.reading import old_grade_text, reading_word


def _ok(step: dict[str, Any]) -> bool:
    return step["state"] in (PASS, MINOR)


def _grades(results: list[dict[str, Any]]) -> str:
    return ", ".join(f"{r.get('asset')} {_word(r)}" for r in results)


def _word(result: dict[str, Any]) -> str:
    """The reading word of one asset; a result with only a letter says so."""
    found = result.get("reading")
    if isinstance(found, dict):
        return reading_word(found)
    return old_grade_text(result.get("verdict"))


def _health(config: NightlyConfig, runner: Runner) -> list[dict[str, Any]]:
    """Read the saved report first: computing a new one changes the test identity every night."""
    steps = []
    for asset in config.assets:
        saved = ["data", "health", asset, "--stored", "--json"]
        step = new_step(f"N1.health.{asset}", "N1", f"data health {asset}", saved)
        payload = run_step(runner, step, saved, config.step_timeout)
        if step["state"] != PASS or payload is None or "verdict" not in payload:
            fresh = ["data", "health", asset, "--json"]
            step = new_step(f"N1.health.{asset}", "N1", f"data health {asset}", fresh)
            payload = run_step(runner, step, fresh, config.step_timeout, required=("verdict",))
        if payload is not None and _ok(step):
            step["verdict"] = str(payload["verdict"])
            if step["verdict"] == "warn":
                mark(step, MINOR, f"Data health for {asset} says warn. Run `{step['command']}`.")
            elif step["verdict"] != "pass":
                mark(step, BLOCKING, f"Data health for {asset} says {step['verdict']}.")
        steps.append(step)
    return steps


def _rule_test(
    config: NightlyConfig, runner: Runner
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tail = ["test", str(config.rule_spec), *(["--quick"] if config.quick else []), "--json"]
    step = new_step("N1.test", "N1", "rule test", tail)
    payload = run_step(runner, step, tail, config.step_timeout, required=("test_id", "results"))
    results: list[dict[str, Any]] = []
    if payload is not None and _ok(step):
        listed = payload["results"]
        results = [r for r in listed if isinstance(r, dict)] if isinstance(listed, list) else []
        step["ids"] = {"test_id": payload["test_id"]}
        step["evidence"] = evidence_of([r.get("labels") for r in results])
        step["verdict"] = _grades(results)
        if not results:
            mark(step, BLOCKING, f"`{step['command']}` returned no result rows.")
        for row in results:
            if row.get("error") or not row.get("run_id"):
                mark(step, BLOCKING, f"The test for {row.get('asset')} failed: {row.get('error')}.")
    return step, results


def _diagnose(config: NightlyConfig, runner: Runner, asset: str, run_id: str) -> dict[str, Any]:
    tail = ["diagnose", run_id, "--json"]
    step = new_step(f"N1.diagnose.{asset}", "N1", f"diagnose {asset}", tail)
    payload = run_step(
        runner, step, tail, config.step_timeout, required=("audit", "flags", "labels")
    )
    step["ids"] = {"run_id": run_id}
    audit = payload.get("audit") if payload else None
    unchecked = [
        str(line.get("check"))
        for line in audit or []
        if isinstance(line, dict) and line.get("status") == "NOT-CHECKED"
    ]
    if unchecked and _ok(step):
        mark(step, MINOR, f"Audit lines not checked: {', '.join(unchecked)}.")
    return step


def _words(row: dict[str, Any]) -> str:
    names = [str(label) for label in row.get("labels") or []]
    names += [str(f.get("flag") if isinstance(f, dict) else f) for f in row.get("flags") or []]
    return ", ".join(name.replace("-", " ") for name in names)


def _check(
    config: NightlyConfig, runner: Runner, asset: str, row: dict[str, Any]
) -> dict[str, Any]:
    """Cite the numbers with the real command, add the label words, then run the real check."""
    run_id = str(row["run_id"])
    tail = ["results", "check", f"<draft for run {run_id}>", "--json"]
    step = new_step(f"N1.check.{asset}", "N1", f"results check {asset}", tail)
    step["ids"] = {"run_id": run_id}
    lines: list[str] = []
    for metric in ("oos_sharpe", "total_trials"):
        cite = runner(alpha_argv(["results", "cite", run_id, metric]), config.step_timeout)
        if cite.exit_code != 0:
            step["exit_code"] = cite.exit_code
            mark(
                step,
                BLOCKING,
                f"`alpha results cite {run_id} {metric}` failed. "
                f"{stderr_tail(cite.stderr)}".rstrip(),
            )
            return step
        lines.append(cite.stdout.strip())
    lines.append(f"Labels: {_words(row)}")
    with tempfile.TemporaryDirectory(prefix="alpha-nightly-") as scratch:
        draft = Path(scratch) / "draft.md"
        draft.write_text("\n".join(lines) + "\n", encoding="utf-8")
        real = ["results", "check", str(draft), "--json"]
        payload = run_step(runner, step, real, config.step_timeout, required=("ok", "problems"))
    step["command"] = f"alpha results check <draft of `alpha results cite {run_id} <metric>` lines>"
    if payload is not None and step["state"] == BLOCKING:
        kinds = sorted({str(p.get("kind")) for p in payload.get("problems") or []})
        step["state"], step["defect"] = BLOCKING, f"results check disagreed: {', '.join(kinds)}."
    elif payload is not None and payload.get("ok") is not True:
        mark(step, BLOCKING, "results check did not say ok.")
    return step


def _tools(config: NightlyConfig, runner: Runner, run_id: str | None) -> list[dict[str, Any]]:
    steps = []
    for index, template in enumerate(config.post_tools, 1):
        step_id = f"N1.tool.{index}"
        if run_id is None:
            tail = shlex.split(template)
            steps.append(
                not_run(step_id, "N1", "post-test tool", tail, "not run: step N1.test failed")
            )
            continue
        tail = shlex.split(template.replace("{run_id}", run_id))
        step = new_step(step_id, "N1", "post-test tool", tail)
        run_step(runner, step, tail, config.step_timeout, expect_json="--json" in tail)
        steps.append(step)
    return steps


def rule_path(config: NightlyConfig, runner: Runner) -> list[dict[str, Any]]:
    next_tail = ["next", "--json"]
    nxt = new_step("N1.next", "N1", "alpha next", next_tail)
    run_step(
        runner, nxt, next_tail, config.step_timeout, required=("stores", "recent_trials", "paths")
    )
    steps = [nxt, *_health(config, runner)]
    test, rows = _rule_test(config, runner)
    steps.append(test)
    good = {str(r["asset"]): r for r in rows if r.get("run_id") and not r.get("error")}
    names = [str(r.get("asset")) for r in rows] or list(config.assets)
    first: str | None = None
    for asset in names:
        if asset in good:
            first = first or str(good[asset]["run_id"])
            diagnosed = _diagnose(config, runner, asset, str(good[asset]["run_id"]))
            steps += [diagnosed, _check(config, runner, asset, good[asset])]
            continue
        for kind in ("diagnose", "check"):
            steps.append(
                not_run(
                    f"N1.{kind}.{asset}",
                    "N1",
                    f"{kind} {asset}",
                    [kind],
                    "not run: step N1.test failed",
                )
            )
    return [*steps, *_tools(config, runner, first)]


def setup_path(config: NightlyConfig, runner: Runner) -> list[dict[str, Any]]:
    wait = "not run: step {} failed"
    tail = ["setup", "find", str(config.setup_spec), "--json"]
    find = new_step("N2.find", "N2", "setup find", tail)
    found = run_step(runner, find, tail, config.step_timeout, required=("find_id", "totals"))
    steps = [find]
    if not (found and _ok(find)):
        names = (("study", "setup study"), ("trade", "setup trade"), ("readback", "results show"))
        return steps + [
            not_run(f"N2.{key}", "N2", name, [name], wait.format("N2.find")) for key, name in names
        ]
    find_id = str(found["find_id"])
    find["ids"], find["evidence"] = {"find_id": find_id}, evidence_of([found.get("labels")])
    study = new_step("N2.study", "N2", "setup study", (t := ["setup", "study", find_id, "--json"]))
    studied = run_step(runner, study, t, config.step_timeout, required=("study_id", "outcome"))
    if studied and _ok(study):
        study["ids"], study["verdict"] = {"study_id": studied["study_id"]}, str(studied["outcome"])
        study["evidence"] = evidence_of([studied.get("labels")])
    trade = new_step("N2.trade", "N2", "setup trade", (t := ["setup", "trade", find_id, "--json"]))
    traded = run_step(runner, trade, t, config.step_timeout, required=("trade_id", "outcome"))
    steps += [study, trade]
    if not (traded and _ok(trade)):
        return [
            *steps,
            not_run(
                "N2.readback", "N2", "results show", ["results", "show"], wait.format("N2.trade")
            ),
        ]
    trade["ids"], trade["verdict"] = {"trade_id": traded["trade_id"]}, str(traded["outcome"])
    trade["evidence"] = evidence_of([traded.get("labels")])
    tail = ["results", "show", str(traded["trade_id"]), "--json"]
    back = new_step("N2.readback", "N2", "results show", tail)
    shown = run_step(runner, back, tail, config.step_timeout, required=("runs", "failed"))
    if shown and _ok(back) and (shown["failed"] or not shown["runs"]):
        mark(back, BLOCKING, f"`{back['command']}` found no stored result for the trade.")
    return [*steps, back]


def rdagent_path(config: NightlyConfig, runner: Runner) -> list[dict[str, Any]]:
    """Off until `rdagent_config` is set. Then the launcher runs unchanged: no cap of ours."""
    if config.rdagent_config is None:
        return [not_run("N3.stub", "N3", "rdagent run", ["rdagent", "run"], N3_STUB)]
    path = str(config.rdagent_config)
    run_tail = ["rdagent", "run", "--config", path]
    run = new_step("N3.run", "N3", "rdagent run", run_tail)
    run_step(runner, run, run_tail, config.rdagent_timeout, expect_json=False)
    tail = ["rdagent", "status", "--config", path, "--json"]
    if run["state"] == BLOCKING:
        return [
            run,
            not_run("N3.status", "N3", "rdagent status", tail, "not run: step N3.run failed"),
        ]
    status = new_step("N3.status", "N3", "rdagent status", tail)
    payload = run_step(runner, status, tail, config.step_timeout, required=("state",))
    if payload is not None and _ok(status):
        status["verdict"] = str(payload["state"])
        if status["verdict"] != "finished":
            mark(status, BLOCKING, f"The RD-Agent run did not finish. State: {status['verdict']}.")
    return [run, status]


def run_nightly(
    config: NightlyConfig,
    home: Path,
    runner: Runner,
    *,
    only: tuple[str, ...] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Run the chosen paths, write the record in a new dated folder and return it."""
    wanted = tuple(name for name in ALL if only is None or name in only)
    day = today or datetime.now(UTC).date()
    folder, number = new_folder(home, day)
    paths = {"N1": rule_path, "N2": setup_path, "N3": rdagent_path}
    steps = [step for name in wanted for step in paths[name](config, runner)]
    record = build_record(steps, wanted, day, number, config.source)
    write_record(folder, record)
    return record
