"""RD-Agent extension classes: ALPHA measures factors and owns the search decision."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from rdagent.core.developer import Developer
from rdagent.core.exception import FactorEmptyError
from rdagent.core.proposal import Experiment2Feedback, HypothesisFeedback
from rdagent.oai.llm_utils import APIBackend
from rdagent.scenarios.qlib.experiment.factor_experiment import QlibFactorScenario
from rdagent.scenarios.qlib.experiment.quant_experiment import QlibQuantScenario
from rdagent.scenarios.qlib.proposal.factor_proposal import QlibFactorHypothesisGen
from rdagent.utils import convert2bool
from rdagent.utils.agent.tpl import T

from alpha_factor_coder import demote_in_file
from alpha_factor_data import check_prefix_invariance

LEGACY_KEYS = ["IC"] + [
    f"1day.excess_return_{cost}_cost.{metric}"
    for cost in ("without", "with")
    for metric in ("annualized_return", "max_drawdown")
]
# RD-Agent's own log viewer (rdagent/log/ui/app.py, QLIB_SELECTED_METRICS) indexes these too;
# ALPHA does not compute an information ratio, so it is present as NaN, never invented.
VIEWER_KEYS = ["1day.excess_return_with_cost.information_ratio"]


SWING_BRIEF = (
    "The trader is a retail swing trader holding days to weeks, never high frequency. "
    "ALPHA judges every factor at daily, weekly (7-day) and monthly (28-day) holding clocks; "
    "only a weekly or monthly pass can become a candidate. Wanted: slow signals whose "
    "cross-sectional ranks change rarely (low turnover). State an economic or behavioural "
    "mechanism in the hypothesis and a falsifier: what result would show it wrong. "
    "Every trade costs 10 bps fee plus 6 bps slippage on each side; turning over half the book "
    "every day costs about 29% a year. Fast daily reversal, gap and range ideas already passed "
    "the daily screen but lost money after costs because they traded 19%-79% of the portfolio "
    "per day; avoid re-proposing them. Slow volatility, illiquidity, max-return and "
    "return-volume ranks then passed the daily rank screen, yet the top third they would hold "
    "lost 28%-43% a year before costs: on 15 coins a few volatile coins' rallies dominate the "
    "mean, so rank order and the top third's return can disagree. ALPHA now rejects such a "
    "factor unless the top third it would hold beat the bottom third "
    "(top-third-does-not-beat-bottom-third). Exploratory, not admitted."
)
# Idea families by name pattern (regular expressions), first match wins (ADR-0055). Approximate
# by design: it groups near-variants so the proposer sees how often one idea has already failed.
FAMILY_KEYWORDS = (
    ("price near its high / range position", ("high_prox", "stoch", "rangepos", r"(^|_)hp\d")),
    ("short-term reversal and gaps", ("reversal_3d", "reversal_5d", "gap", "intraday_reversal")),
    ("long-term reversal", ("long_term_reversal",)),
    ("illiquidity", ("amihud", "illiquid")),
    ("return-volume relation", ("ret_vol_corr", "volume_return", "signed_volume", "flow_conf")),
    ("skewness and lottery returns", ("skew", "max_return", "up_day")),
    ("momentum and trend", ("momentum", "mom_", "trend", "sma_distance", "autocorr")),
    ("volatility and beta", ("volatil", "semivariance", "beta", "vol_")),
    ("range and compression", ("range",)),
    ("volume level and trend", ("volume", "dollar_volume")),
    ("VWAP distance", ("vwap", "clv", "close_location")),
)


def idea_family(name: str) -> str:
    lowered = name.lower()
    for family, keywords in FAMILY_KEYWORDS:
        if any(re.search(keyword, lowered) for keyword in keywords):
            return family
    return "other: " + lowered.split("_")[0]


def _rounded(value: Any) -> Any:
    # Seventeen digits tell the proposer nothing and crowd other trials out of its budget.
    return round(value, 3) if isinstance(value, float) else value


def replay_note(clock: str, replay: Any) -> str:
    """Why a replayed clock won or lost: before costs, after costs, the costs and the turnover."""
    if not replay:
        return ""
    if "counted_only" in replay:  # ADR-0055: a failed clock's replay only counts the trial
        return f"; {clock} replay counted only, not a result"
    gross = replay["gross"]["annualized_return"]
    net = replay["net"]["annualized_return"]
    return (
        f"; {clock} replay: {gross:+.0%}/yr before costs, {net:+.0%}/yr after "
        f"{replay['annual_cost']:.0%}/yr costs, turnover {replay['mean_turnover']:.0%}/day"
    )


def spread_line(clock: str, result: Any) -> str:
    """Top versus bottom third before costs (ADR-0055), with turnover and the cost it implies."""
    if not result or result.get("status") not in ("PASS", "FAIL"):
        return ""
    return (
        f"; {clock} spread {result['status']}: top third {result['top_third_mean_return']:+.2%} vs "
        f"bottom {result['bottom_third_mean_return']:+.2%} per hold "
        f"({result['annualized_spread']:+.0%}/yr before costs, t {result['t']:.1f}), "
        f"top third changes {result['top_share_changed_per_rebalance']:.0%} per rebalance, "
        f"about {result['estimated_annual_cost']:.0%}/yr costs"
    )


def _rank(row: dict[str, Any]) -> tuple[int, float]:
    order = ("CANDIDATE", "FAST_ONLY", "REPLAY_FAIL", "SPREAD_FAIL", "SCREEN_FAIL")
    status = row["status"]
    score = order.index(status) if status in order else len(order)
    if row["schema"] == "AlphaRdagentFactorTrialV3":
        ic = row["clocks"][row["lead_clock"]]["screen"].get("mean_ic")
    else:
        ic = row["screen"].get("mean_ic")
    return score, -abs(ic) if isinstance(ic, (int, float)) else 0.0


def family_summary(rows: list[dict[str, Any]], switch_after: int) -> str:
    """Every idea family: tries, best result, how each failed, and which to leave."""
    families: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        families.setdefault(idea_family(row["name"]), []).append(row)
    lines, closed = [], []
    for family, members in sorted(families.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        best = min(members, key=_rank)
        counts: dict[str, int] = {}
        for member in members:
            counts[member["status"]] = counts.get(member["status"], 0) + 1
        failed = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        lines.append(
            f"- {family}: {len(members)} tries; best {best['name']} ({best['status']}); {failed}"
        )
        if len(members) >= switch_after and not any(m["status"] == "CANDIDATE" for m in members):
            closed.append(family)
    text = "\nALPHA idea families (all runs; tries, best result, how they failed)\n" + "\n".join(
        lines
    )
    if closed:
        text += (
            f"\nThese families have {switch_after} or more failed tries and no candidate: "
            + "; ".join(closed)
            + ". Do not propose another near-variant of them (a new window, skip or scaling of "
            "the same idea); move to a different family with a different economic mechanism."
        )
    return text


def ledger_summary(row: dict[str, Any]) -> str:
    if row.get("schema") not in {
        "AlphaRdagentFactorTrialV1",
        "AlphaRdagentFactorTrialV2",
        "AlphaRdagentFactorTrialV3",
    }:
        raise ValueError("invalid ALPHA trial ledger schema")
    if row["schema"] == "AlphaRdagentFactorTrialV3":
        clocks = row["clocks"]
        statuses = ", ".join(f"{c} {clocks[c]['status']}" for c in ("daily", "weekly", "monthly"))
        lead = clocks[row["lead_clock"]]
        line = (
            f"{row['name']}: {row['status']} ({statuses}); lead {row['lead_clock']} "
            f"IC {_rounded(lead['screen'].get('mean_ic'))}; q {_rounded(lead['q'])}"
        )
        for clock in ("daily", "weekly", "monthly"):
            if clocks[clock]["status"] in ("SPREAD_FAIL", "REPLAY_FAIL", "PASS"):
                line += spread_line(clock, clocks[clock].get("spread"))
            line += replay_note(clock, clocks[clock].get("replay"))
    else:
        line = (
            f"{row['name']}: {row['status']}; "
            f"mean rank IC {_rounded(row['screen'].get('mean_ic'))}; "
            f"q {_rounded(row['q'])}; run {row['run_id']}"
        )
    if row.get("exposure", {}).get("previously_exposed") is True:
        line += "; protected window previously exposed"
    return line


def append_swing_context(context: dict[str, Any], ledger_name: str | None) -> None:
    context["hypothesis_and_feedback"] += "\n" + SWING_BRIEF
    if not ledger_name or not Path(ledger_name).exists():
        return
    raw = Path(ledger_name).read_bytes()
    # Another run may be appending; only complete lines participate in the summary.
    rows = [json.loads(line) for line in raw[: raw.rfind(b"\n") + 1].splitlines()]
    if not rows:
        return
    heading = (
        "\nALPHA trial ledger (all runs; exploratory, not admitted; "
        + os.environ.get("ALPHA_FACTOR_UNIVERSE_TEXT", "15 surviving coins only")
        + ")\n"
    )
    lines, seen = [], set()
    unknown: list[str] = []
    known = {"AlphaRdagentFactorTrialV1", "AlphaRdagentFactorTrialV2", "AlphaRdagentFactorTrialV3"}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("schema"), str):
            raise ValueError("invalid ALPHA trial ledger schema")
        if row["schema"] not in known | {"AlphaRuleTrialV1"}:
            unknown.append(row["schema"])
        elif row["schema"] in known:
            ledger_summary(row)  # Validate known rows even outside the 30-row summary.
    # Newest first, whole lines only, within 4000 characters; the count of the rest is stated so
    # the proposer knows the list is partial instead of reading a line cut in half.
    used, omitted = len(heading), 0
    for row in (r for r in reversed(rows) if r["schema"] in known):
        line = ledger_summary(row)
        if row["code_sha256"] in seen or row["status"] == "REPEAT":
            continue
        seen.add(row["code_sha256"])
        if omitted or len(lines) == 30 or used + len(line) + 1 > 4000 - 80:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    if omitted:
        lines.append(f"({omitted} older distinct factors not shown)")
    distinct: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["schema"] in known and row["status"] not in ("REPEAT", "IMPORTED"):
            distinct.setdefault(row["code_sha256"], row)
    switch_after = int(os.environ.get("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3"))
    context["hypothesis_and_feedback"] += family_summary(list(distinct.values()), switch_after)
    context["hypothesis_and_feedback"] += heading + "\n".join(lines)
    if unknown:
        context["hypothesis_and_feedback"] += (
            f"\n{len(unknown)} ledger rows of other kinds were skipped "
            f"({', '.join(sorted(set(unknown)))})"
        )


def record_coder_verdicts(
    run: Path, iteration: int, rejected: list[tuple[Any, dict[str, Any]]]
) -> None:
    if not rejected:
        return
    try:
        _record_coder_verdicts(run, iteration, rejected)
    except Exception as error:  # noqa: BLE001 - a verdict record never stops the runner
        print(f"coder verdicts not recorded: {type(error).__name__}", file=sys.stderr)


def _record_coder_verdicts(
    run: Path, iteration: int, rejected: list[tuple[Any, dict[str, Any]]]
) -> None:
    informations = [task.get_task_information() for task, _ in rejected]
    demoted, note = demote_in_file(
        os.environ, informations, [factor["code_sha256"] for _, factor in rejected]
    )
    with (run / "coder-verdicts.jsonl").open("a") as stream:
        for (_, factor), information in zip(rejected, informations, strict=True):
            stream.write(
                json.dumps(
                    {
                        "schema": "AlphaCoderVerdictV1",
                        "iteration": iteration,
                        "name": factor["name"],
                        "code_sha256": factor["code_sha256"],
                        "status": factor["status"],
                        "task_information_sha256": hashlib.sha256(information.encode()).hexdigest(),
                        "demoted": information in demoted,
                        "note": note,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def record_code(run: Path, digest: str, code: bytes) -> None:
    folder = run / "code"
    folder.mkdir(exist_ok=True)
    path = folder / f"{digest}.py"
    if path.exists():
        if path.read_bytes() != code:
            raise ValueError(f"conflicting factor code archive: {digest}")
        return
    # Write a temporary file, then link it into place: a crash never leaves a partial copy.
    temporary = folder / f".{digest}.{os.getpid()}.tmp"
    with temporary.open("wb") as stream:
        stream.write(code)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != code:
            raise ValueError(f"conflicting factor code archive: {digest}") from None
    finally:
        temporary.unlink()


def record_round(run: Path, exp: Any, feedback: Any, row: dict[str, Any]) -> None:
    hashes = {f["name"]: f["code_sha256"] for f in exp.alpha_evaluation.get("factors", [])}
    record = {
        "schema": "AlphaRdagentRoundV1",
        **row,
        "hypothesis": {
            key: getattr(exp.hypothesis, key, None)
            for key in (
                "hypothesis",
                "reason",
                "concise_reason",
                "concise_observation",
                "concise_justification",
                "concise_knowledge",
            )
        },
        "tasks": [
            {
                "name": task.factor_name,
                **{key: getattr(task, key, None) for key in ("description", "variables")},
                "formulation": getattr(task, "factor_formulation", None),
                "code_sha256": hashes.get(task.factor_name),
            }
            for task in exp.sub_tasks
        ],
        "feedback": {
            key: getattr(feedback, key)
            for key in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason")
        },
    }
    with (run / "rounds.jsonl").open("a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


class AlphaFactorScenario(QlibFactorScenario):
    def get_runtime_environment(self) -> str:
        # Upstream runs `python runtime_info.py` through a conda-derived PATH; without conda that
        # PATH has no `python`. Run RD-Agent's own probe with the factor runtime's interpreter.
        import rdagent.scenarios.shared.get_runtime_info as info

        script = Path(info.__file__).with_name("runtime_info.py")
        result = subprocess.run(
            [os.environ["ALPHA_FACTOR_CODE_PYTHON"], str(script)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
        if match is None:
            raise ValueError("RD-Agent runtime probe printed no JSON")
        return json.dumps(json.loads(match.group()), indent=2)

    @property
    def simulator(self) -> str:
        return (
            "A factor is judged by ALPHA's rank IC with inference and a cost-aware replay; there "
            "is no Qlib model. Decide at the close of UTC day d, fill at open d+1, hold daily "
            "(1 day), weekly (7 days) or monthly (28 days). Each clock uses non-overlapping "
            "screen windows phased at 2021-01-01. ALPHA canonical synchronized long-only replay "
            "(not Nautilus), top third equal "
            "weighted, against the equal-weight basket; 10 bps fee plus 6 bps slippage per side, "
            "365 days/year. Direction chosen in-sample. BH q < 0.10 screens the cross-run trial "
            "ledger, counting each factor x clock as a trial; a screened clock can pass only "
            "if the top third it would hold beat its bottom third before costs. "
            "Hold drifted weights between rebalances; residual trades are executed and charged. "
            "Positive net excess at a weekly or monthly clock makes an exploratory candidate; "
            "a daily-only pass is FAST_ONLY, never admission, evidence, approval or promotion."
        )

    @property
    def experiment_setting(self) -> str:
        return (
            "Binance USDT spot coins, daily bars: "
            + os.environ.get("ALPHA_FACTOR_UNIVERSE_TEXT", "15 surviving coins only")
            + ". History only: "
            "2017-08-17..2020-12-31; exploration decisions: 2021-01-01..2023-12-24; panel ends "
            "2023-12-31. 2024-01-01 onward is reserved and never available to this loop. "
            "Prefix-invariance checks at quarter ends and 2023-12-24 detect some look-ahead, "
            "not all. Daily, weekly (7-day) and monthly (28-day) holding/rebalance clocks are "
            "fixed in advance; only a weekly or monthly pass can become a candidate. "
            "exploratory, not admitted, not yet confirmed."
        )


class AlphaFactorRunner(Developer):
    def develop(self, exp: Any) -> Any:
        if exp.based_experiments and exp.based_experiments[-1].result is None:
            self.develop(exp.based_experiments[-1])
        if not exp.sub_tasks:
            exp.result = pd.Series(dict.fromkeys(LEGACY_KEYS + VIEWER_KEYS, float("nan")))
            exp.stdout = "baseline: no factors; ALPHA evaluates factors standalone"
            return exp
        run = Path(os.environ["ALPHA_FACTOR_RUN_DIR"])
        # Number attempts by the folders already made, so a failed evaluation (no record line)
        # or a resumed checkpoint never collides with an earlier attempt's folder.
        (run / "evaluations").mkdir(exist_ok=True)
        iteration = len(list((run / "evaluations").glob("iter-*")))
        folder = run / "evaluations" / f"iter-{iteration}"
        folder.mkdir(exist_ok=False)
        factors, frames = [], []
        rejected = []
        if not (len(exp.sub_tasks) == len(exp.sub_workspace_list) == len(exp.prop_dev_feedback)):
            raise ValueError("factor tasks, workspaces and feedback lengths differ")
        for task, workspace, feedback in zip(
            exp.sub_tasks, exp.sub_workspace_list, exp.prop_dev_feedback, strict=True
        ):
            if workspace is None or "factor.py" not in (workspace.file_dict or {}):
                # No code: identify the trial by the proposed task itself, so distinct failed
                # proposals stay distinct trials and the same proposal failing twice is a repeat.
                code = b""
                identity = b"no factor.py\0" + task.get_task_information().encode()
            else:
                code = workspace.file_dict["factor.py"].encode()
                identity = code
            factor = {
                "name": task.factor_name,
                "code_sha256": hashlib.sha256(identity).hexdigest(),
                "status": "FAILED",
                "lookahead": {"status": "NOT_RUN"},
            }
            if code:
                record_code(run, str(factor["code_sha256"]), code)
            if code and feedback:
                execution, values = workspace.execute("All")
                if values is not None:
                    check = check_prefix_invariance(
                        code,
                        values,
                        run / "factor_data/cuts",
                        os.environ["ALPHA_FACTOR_CODE_PYTHON"],
                        120.0,
                    )
                    factor["lookahead"] = check
                    factor["status"] = "OK" if check["status"] == "PASS" else "LOOKAHEAD"
                    if factor["status"] == "OK" and len(values.columns) != 1:
                        factor["status"] = "FAILED"
                        factor["failure_detail"] = "one output column required per factor task"
                    if factor["status"] == "OK":
                        frame = values.copy()
                        frame.columns = [task.factor_name]
                        frame.index.names = ["date", "instrument"]
                        frames.append(frame)
                    elif factor["status"] == "FAILED" or check["status"] == "LOOKAHEAD":
                        # Only ALPHA's verdict on the code itself: a check that merely errored
                        # (timeout, subprocess failure) says nothing about the code.
                        rejected.append((task, factor))
                else:
                    factor["failure_detail"] = execution
            factors.append(factor)
        record_coder_verdicts(run, iteration, rejected)
        if frames:
            values_frame = pd.concat(frames, axis=1).sort_index().reset_index()
            values_frame["date"] = pd.to_datetime(values_frame.date, utc=True).dt.date
        else:
            values_frame = pd.DataFrame(
                {"date": pd.Series(dtype="datetime64[ns]"), "instrument": pd.Series(dtype="str")}
            )
        values_frame.to_parquet(folder / "factors.parquet", index=False)
        request = {
            "schema": "AlphaRdagentFactorRequestV1",
            "iteration": iteration,
            "hypothesis_sha256": hashlib.sha256(str(exp.hypothesis).encode()).hexdigest(),
            "factors": factors,
            "values_file": "factors.parquet",
        }
        (folder / "request.json").write_text(json.dumps(request, sort_keys=True) + "\n")
        command = [
            os.environ["ALPHA_FACTOR_EVAL_PYTHON"],
            "-I",
            "-m",
            "alpha_cli.rdagent_factor_eval",
            "evaluate",
            "--run-dir",
            str(run),
            "--request",
            str(folder / "request.json"),
            "--out",
            str(folder / "result.json"),
            "--ledger",
            os.environ["ALPHA_FACTOR_TRIAL_LEDGER"],
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode:
            lines = result.stderr.strip().splitlines()
            raise FactorEmptyError(
                lines[-1] if lines else f"ALPHA evaluator exit {result.returncode}"
            )
        record = json.loads((folder / "result.json").read_bytes())
        exp.result = pd.Series(
            {**dict.fromkeys(VIEWER_KEYS, float("nan")), **record["legacy_result"]}
        )
        exp.stdout = record["feedback_text"]
        exp.alpha_evaluation = record
        if all(f["status"] == "FAILED" for f in factors):
            raise FactorEmptyError("ALPHA recorded every factor as FAILED")
        return exp


class AlphaFactorHypothesisGen(QlibFactorHypothesisGen):
    def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
        context, flag = super().prepare_context(trace)
        append_swing_context(context, os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER"))
        return context, flag


class AlphaFactorFeedback(Experiment2Feedback):
    def generate_feedback(self, exp: Any, trace: Any, exception: Exception | None = None) -> Any:
        scenario = (
            self.scen.get_scenario_all_desc(action="factor")
            if isinstance(self.scen, QlibQuantScenario)
            else self.scen.get_scenario_all_desc()
        )
        system = T("scenarios.qlib.prompts:factor_feedback_generation.system").r(scenario=scenario)
        user = T("scenarios.qlib.prompts:factor_feedback_generation.user").r(
            hypothesis_text=exp.hypothesis.hypothesis,
            task_details=[
                task.get_task_information_and_implementation_result() for task in exp.sub_tasks
            ],
            combined_result=exp.stdout,
        )
        reply = APIBackend().build_messages_and_create_chat_completion(
            user_prompt=user,
            system_prompt=system,
            json_mode=True,
            json_target_type=dict[str, str | bool | int],
        )
        response = json.loads(reply)
        feedback = HypothesisFeedback(
            observations=response.get("Observations", "No observations provided"),
            hypothesis_evaluation=response.get("Feedback for Hypothesis", "No feedback provided"),
            new_hypothesis=response.get("New Hypothesis", "No new hypothesis provided"),
            reason=response.get("Reasoning", "No reasoning provided"),
            decision=convert2bool(response.get("Replace Best Result", "no")),
        )
        record = exp.alpha_evaluation
        feedback.decision = record["decision"]
        row = {
            "iteration": record["iteration"],
            "model_decision": response.get("Replace Best Result", "no"),
            "alpha_decision": feedback.decision,
            "reply_sha256": hashlib.sha256(reply.encode()).hexdigest(),
        }
        with (Path(os.environ["ALPHA_FACTOR_RUN_DIR"]) / "feedback.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        try:
            record_round(Path(os.environ["ALPHA_FACTOR_RUN_DIR"]), exp, feedback, row)
        except Exception as error:  # noqa: BLE001 - evidence must never abort RD-Agent's step
            with (Path(os.environ["ALPHA_FACTOR_RUN_DIR"]) / "rounds-errors.jsonl").open(
                "a"
            ) as out:
                out.write(
                    json.dumps({"iteration": row.get("iteration"), "error": repr(error)[:500]})
                    + "\n"
                )
        return feedback
