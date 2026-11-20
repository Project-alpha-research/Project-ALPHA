"""Nightly steps that check "same input, same output": a recheck, or the first normal run.

A recheck is "computed again and compared with the stored result". The step asks for a recheck
first. With nothing stored to compare with (the first night), it runs the normal command once.
A recheck that differs is a blocking defect: the same test gave a different result. Whether the
engine ran is read from the `executed` field of the command output, never from a label.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_steps import (
    BLOCKING,
    PASS,
    Runner,
    alpha_argv,
    command_text,
    evidence_of,
    mark,
    new_step,
    parse_object,
    run_step,
    stderr_tail,
)
from alpha_cli.spine.reading import old_grade_text, reading_word
from alpha_cli.spine.recheck_compare import MISMATCH_EXIT

CODE_CHANGED = "The code changed since the stored result; a code change altered a stored result."


def _word(result: dict[str, Any]) -> str:
    found = result.get("reading")
    return reading_word(found) if isinstance(found, dict) else old_grade_text(result.get("verdict"))


def _defect(name: str, block: dict[str, Any]) -> str:
    """The text of a blocking defect for one recheck that differed."""
    first = block["differences"][0]
    more = block.get("differences_total", 1)
    text = (
        f"The same test gave a different result{name}: {first['field']} stored "
        f"{first['stored']}, recomputed {first['recomputed']}."
    )
    if more > 1:
        text += f" {more} differences in all."
    return text + (f" {CODE_CHANGED}" if block.get("code_changed") else "")


def _recheck_note(name: str, block: dict[str, Any]) -> dict[str, Any]:
    keys = ("compared_with", "seconds", "code_changed", "match")
    return {"asset": name, **{k: block.get(k) for k in keys}}


def try_recheck(
    runner: Runner,
    step: dict[str, Any],
    base: Sequence[str],
    timeout: float,
    named: Sequence[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[dict[str, Any] | None, list[tuple[str, dict[str, Any]]]]:
    """Run `<base> --recheck --json`; mark transport errors and differences on the step."""
    tail = [*base, "--recheck", "--json"]
    step["command"] = command_text(tail)
    outcome = runner(alpha_argv(tail), timeout)
    step["exit_code"], step["seconds"] = outcome.exit_code, round(outcome.seconds, 2)
    command = step["command"]
    if outcome.timed_out:
        mark(step, BLOCKING, f"`{command}` timed out after {timeout:g} seconds.")
        return None, []
    payload = parse_object(outcome.stdout)
    if outcome.exit_code not in (0, MISMATCH_EXIT):
        mark(
            step, BLOCKING, f"`{command}` exited {outcome.exit_code}. {stderr_tail(outcome.stderr)}"
        )
        return None, []
    if payload is None:
        mark(step, BLOCKING, f"`{command}` printed no valid JSON object.")
        return None, []
    blocks = _blocks(payload)
    if not blocks:
        mark(step, BLOCKING, f"`{command}` left out the recheck result.")
    for name, block in blocks:
        if block.get("match") is False:
            mark(step, BLOCKING, _defect(f" for {name}" if name else "", block))
    return payload, blocks


def _blocks(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload.get("recheck"), dict):
        return [("", payload["recheck"])]
    rows = payload.get("results")
    found = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    return [
        (str(r.get("asset")), r["recheck"]) for r in found if isinstance(r.get("recheck"), dict)
    ]


def _rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = payload.get("results") if payload else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def rule_test(config: NightlyConfig, runner: Runner) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Step N1.test: a recheck, or (nothing stored) the normal test once."""
    base = ["test", str(config.rule_spec), *(["--quick"] if config.quick else [])]
    step = new_step("N1.test", "N1", "rule test", [*base, "--recheck", "--json"])
    payload, blocks = try_recheck(runner, step, base, config.step_timeout)
    rows = _rows(payload)
    if payload is None or step["state"] == BLOCKING or not rows:
        return step, []
    done_blocks = [_recheck_note(n, b) for n, b in blocks if b.get("match") is not None]
    if done_blocks:
        step["recheck"] = done_blocks
    results: dict[str, dict[str, Any]] = {}
    flags: dict[str, object] = {}
    waiting = []
    for row in rows:
        asset, block = str(row.get("asset")), row["recheck"]
        if row.get("error"):
            mark(step, BLOCKING, f"The test for {asset} failed: {row['error']}.")
        elif block.get("match") is None:
            waiting.append(asset)
        else:
            results[asset], flags[asset] = row, block.get("computed") and block.get("match")
    if waiting and step["state"] != BLOCKING:
        normal = new_step("N1.test", "N1", "rule test", [*base, "--json"])
        ran = run_step(
            runner, normal, [*base, "--json"], config.step_timeout, required=("results",)
        )
        step.update(command=normal["command"], exit_code=normal["exit_code"])
        step["seconds"] = round(step["seconds"] + normal["seconds"], 2)
        step["note"] = "No stored result to compare with: the normal test ran once."
        if normal["state"] != PASS:
            mark(step, normal["state"], str(normal["defect"]))
        for row in _rows(ran):
            if str(row.get("asset")) in waiting:
                results[str(row["asset"])], flags[str(row["asset"])] = row, row.get("executed")
        if ran is not None:
            step["ids"] = {"test_id": ran.get("test_id")}
    done = [results[str(r.get("asset"))] for r in rows if str(r.get("asset")) in results]
    step["evidence"] = evidence_of([flags.get(str(r.get("asset"))) for r in rows])
    step["verdict"] = ", ".join(
        f"{r.get('asset')} {_word(r) if r.get('reading') else 'same result as stored'}"
        for r in done
    )
    for row in done:
        if row.get("error") or not row.get("run_id"):
            mark(step, BLOCKING, f"The test for {row.get('asset')} failed: {row.get('error')}.")
    return step, done


def setup_run(
    runner: Runner,
    step: dict[str, Any],
    base: Sequence[str],
    timeout: float,
    required: Sequence[str],
) -> dict[str, Any] | None:
    """A setup study or trade: a recheck, or (nothing stored) the normal command once."""
    payload, blocks = try_recheck(runner, step, base, timeout)
    if payload is None or step["state"] == BLOCKING:
        return None
    block = blocks[0][1] if blocks else {}
    if block.get("match") is None:
        step["note"] = "No stored result to compare with: the normal command ran once."
        spent = float(step["seconds"])
        tail = [*base, "--json"]
        step["command"] = command_text(tail)
        payload = run_step(runner, step, tail, timeout, required=required)
        step["seconds"] = round(float(step["seconds"]) + spent, 2)
        step["evidence"] = evidence_of([payload.get("executed")] if payload else [])
        return payload
    step["recheck"] = [_recheck_note("", block)]
    step["evidence"] = evidence_of([block.get("computed") and block.get("match")])
    step["verdict"] = "same result as stored"
    return payload
