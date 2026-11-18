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
from alpha_factor_data import check_prefix_invariance, current_universe

LEGACY_KEYS = ["IC"] + [
    f"1day.excess_return_{cost}_cost.{metric}"
    for cost in ("without", "with")
    for metric in ("annualized_return", "max_drawdown")
]
# RD-Agent's own log viewer (rdagent/log/ui/app.py, QLIB_SELECTED_METRICS) indexes these too;
# ALPHA does not compute an information ratio, so it is present as NaN, never invented.
VIEWER_KEYS = ["1day.excess_return_with_cost.information_ratio"]


# The experiment step writes each factor's "description" and sees the scenario's simulator text,
# not the hypothesis context, so both carry this line; idea_families.declaration reads it.
DECLARATION_TEMPLATE = (
    'End every factor "description" with this line, filled in: declared_direction: <+1 or -1>; '
    "primary_clock: <weekly or monthly>; direction_reason: <one sentence of economic reasoning>. "
    "Write +1 "
    "when high factor values are bought or -1 when low values are bought, and weekly (7-day "
    "hold) or monthly (28-day hold); daily cannot be chosen. "
    "The sign and clock must follow from the idea; "
    "for example, a slow effect belongs on the monthly clock."
)
SWING_BRIEF = (
    "Single mechanisms are as welcome as learned mixes. A mix must list each input feature by name "
    "in its variables. Open families include every listed other: family and any mechanism not "
    "in the closed list. The trader is a retail swing trader holding days to weeks, "
    "never high frequency. "
    + DECLARATION_TEMPLATE
    + " Only that declared sign and clock can pass; all other results are diagnostic only: "
    "cannot pass. Wanted: slow signals whose "
    "cross-sectional ranks change rarely (low turnover). State an economic or behavioural "
    "mechanism in the hypothesis and a falsifier: what result would show it wrong. "
    "Every trade costs 10 bps fee plus 6 bps slippage on each side; turning over half the book "
    "every day costs about 29% a year. Fast daily reversal, gap and range ideas already passed "
    "the daily screen but lost money after costs because they traded 19%-79% of the portfolio "
    "per day; avoid re-proposing them. Slow volatility, illiquidity, max-return and "
    "return-volume ranks then passed the daily rank screen, yet the top third they would hold "
    "lost 28%-43% a year before costs: a few volatile coins' rallies can dominate the "
    "mean, so rank order and the top third's return can disagree. ALPHA now rejects such a "
    "factor unless the top third it would hold beat the bottom third "
    "(top-third-does-not-beat-bottom-third). Exploratory, not admitted."
)


def family_definitions() -> Any:
    import importlib

    try:
        return importlib.import_module("idea_families")
    except ModuleNotFoundError as error:
        if error.name != "idea_families":
            raise
        return importlib.import_module("workers.rdagent.idea_families")


GENERIC_ESTIMATOR_WORDS = family_definitions().GENERIC_ESTIMATOR_WORDS
FAMILY_KEYWORDS = family_definitions().FAMILY_KEYWORDS


def input_families(*names: str) -> set[str]:
    return set(family_definitions().input_families(*names))


def idea_family(
    name: str, description: str = "", formulation: str = "", variables: Any = None
) -> str:
    return str(family_definitions().idea_family(name, description, formulation, variables))


def _rounded(value: Any) -> str:
    return (
        "not available"
        if value is None
        else f"{value:.4g}"
        if isinstance(value, (float, int))
        else str(value)
    )


def percent(value: Any, *, signed: bool = False) -> str:
    if value is None:
        return "not available"
    return (f"{value * 100:+.4g}" if signed else f"{value * 100:.4g}") + "%"


def replay_note(clock: str, replay: Any) -> str:
    """Returns, costs and turnover at four significant digits, including small nonzero costs."""
    if not replay:
        return ""
    deflated = replay.get("deflated_sharpe") or {}
    note = (
        f"; {clock} deflated Sharpe {_rounded(deflated['dsr'])} against "
        f"{_rounded(deflated.get('threshold'))} over {deflated.get('n_trials')} trials"
        if deflated.get("dsr") is not None
        else f"; {clock} deflated Sharpe not recorded"
    )
    if "counted_only" in replay:
        return f"; {clock} replay counted only, not a result"
    if "error" in replay:
        return f"; {clock} replay error: {replay['error']}"
    return (
        f"; {clock} replay: {percent(replay['gross'].get('annualized_return'), signed=True)}/yr "
        "before costs, "
        f"{percent(replay['net'].get('annualized_return'), signed=True)}/yr after "
        f"{percent(replay.get('annual_cost'))}/yr costs, "
        f"turnover {percent(replay.get('mean_turnover'))}/day" + note
    )


def spread_line(clock: str, result: Any) -> str:
    if not result or result.get("status") not in ("PASS", "FAIL"):
        return ""
    return (
        f"; {clock} spread {result['status']}: top third "
        f"{percent(result.get('top_third_mean_return'), signed=True)} vs "
        f"bottom {percent(result.get('bottom_third_mean_return'), signed=True)} per hold "
        f"({percent(result.get('annualized_spread'), signed=True)}/yr before costs, "
        f"t {_rounded(result.get('t'))}), "
        f"top third changes {percent(result.get('top_share_changed_per_rebalance'))} "
        "per rebalance, "
        f"about {percent(result.get('estimated_annual_cost'))}/yr costs"
    )


def family_permissions(
    closed: set[str], proposed: set[str] | None = None, *, include_counts: bool = False
) -> str:
    opened = (
        {name for name, _ in FAMILY_KEYWORDS} | known_families() | (proposed or set())
    ) - closed
    source = family_definitions().universe_source(os.environ.get("ALPHA_FACTOR_RUN_DIR"))
    count_text = ""
    path = os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER") if include_counts else None
    if (rows := AlphaFactorHypothesisGen.ledger_rows(path)) is not None:
        limit = int(os.environ.get("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3"))
        count_text = "".join(
            "\n" + family_definitions().count_note(family, count, limit, family in closed)
            for family, count in sorted(family_definitions().family_failure_counts(rows).items())
            if family in family_definitions().offered_families({family}, source)
        )
    closed_text = "; ".join(sorted(family_definitions().offered_families(closed, source))) or "none"
    opened_text = "; ".join(sorted(family_definitions().offered_families(opened, source)))
    return (
        f"Closed families: {closed_text}. open families: {opened_text}. "
        "A mechanism that belongs to none of the closed families is allowed."
        + (
            " Session drift families are not offered because this 24/7 crypto venue's daily "
            "bars run from midnight to midnight, without an overnight trading break."
            if source == "binance-spot"
            else ""
        )
        + count_text
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


# The first proposal plus at most two re-asks within one round; then the round ends.
FAMILY_PROPOSALS_PER_ROUND = 3
# This round's closed-family refusals, shown to the proposer when it is asked again; FamilyGuard
# clears them when the round's coding step ends.
FAMILY_REFUSALS = list[str]()


def family_summary(rows: list[dict[str, Any]], switch_after: int) -> str:
    """Every idea family: tries, best result, how each failed, and which to leave."""
    families = AlphaFactorHypothesisGen.trial_families(rows)
    source = family_definitions().universe_source(os.environ.get("ALPHA_FACTOR_RUN_DIR"))
    offered = family_definitions().offered_families(set(families), source)
    lines, closed = [], []
    for family, members in sorted(families.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if family not in offered:
            continue
        best = min(members, key=_rank)
        best_name = best["name"]
        if family_definitions().mentions_family(
            best_name, family_definitions().hidden_families(source)
        ):
            best_name = "factor from an unavailable family"
        counts: dict[str, int] = {}
        for member in members:
            counts[member["status"]] = counts.get(member["status"], 0) + 1
        failed = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        is_closed = len(members) >= switch_after and "CANDIDATE" not in counts
        count = len(members) - counts.get("CANDIDATE", 0)
        lines.append(
            f"- {family}: {len(members)} {'try' if len(members) == 1 else 'tries'}; "
            f"best {best_name} ({best['status']}); {failed}; "
            + family_definitions().count_note(family, count, switch_after, is_closed)
        )
        if is_closed:
            closed.append(family)
    text = "\nALPHA idea families (all runs; tries, best result, how they failed)\n" + "\n".join(
        lines
    )
    if closed:
        text += (
            f"\nThese families have {switch_after} or more failed tries and no candidate: "
            + "; ".join(closed)
            + ". Do not propose another near-variant of them (a new window, skip or scaling of "
            "the same idea), including composites using ANY of these families; "
            "move to a different family with a different economic mechanism."
        )
    return text + "\n" + family_permissions(set(closed), set(families))


def ledger_summary(
    row: dict[str, Any],
    failures: dict[str, int] | None = None,
    limit: int | None = None,
    closed: set[str] | None = None,
) -> str:
    effective = family_definitions().recorded_status(row)
    derived = effective != row["status"]
    row = {**row, "status": effective}
    if row.get("schema") not in AlphaFactorHypothesisGen.TRIAL_SCHEMAS:
        raise ValueError("invalid ALPHA trial ledger schema")
    count_text = ""
    looks = row.get("screen_m", row.get("family_size"))
    if looks is not None:
        count_text += f"; looks so far across all ideas: {looks} (sets the screen cutoff)"
    if failures is not None and row["status"] != "IMPORTED":
        for family in AlphaFactorHypothesisGen.row_families(row):
            count_text += "; " + family_definitions().count_note(
                family, failures.get(family, 0), limit, family in (closed or set())
            )
    if row["schema"] == "AlphaRdagentFactorTrialV3":
        clocks = row["clocks"]
        statuses = ", ".join(f"{c} {clocks[c]['status']}" for c in ("daily", "weekly", "monthly"))
        lead = clocks[row["lead_clock"]]
        line = (
            f"{row['name']}: {row['status']} ({statuses}); lead {row['lead_clock']} "
            f"IC {_rounded(lead['screen'].get('mean_ic'))}; q {_rounded(lead['q'])}{count_text}"
        )
        for clock in ("daily", "weekly", "monthly"):
            if clocks[clock]["status"] in ("SPREAD_FAIL", "REPLAY_FAIL", "PASS"):
                line += spread_line(clock, clocks[clock].get("spread"))
            line += replay_note(clock, clocks[clock].get("replay"))
    else:
        line = (
            f"{row['name']}: {row['status']}; "
            f"mean rank IC {_rounded(row['screen'].get('mean_ic'))}; "
            f"q {_rounded(row['q'])}; run {row['run_id']}{count_text}"
        )
    if derived:
        line += "; DEFLATION_FAIL derived from recorded CANDIDATE"
    if row.get("exposure", {}).get("previously_exposed") is True:
        line += "; protected window previously exposed"
    if "writeoff_count" in row:
        line += f"; {row['writeoff_count']} write-off" + ("" if row["writeoff_count"] == 1 else "s")
    if row.get("failure_reason"):
        line += f"; {row['failure_reason']}: " + str(row.get("failure_detail", "")).split("\n")[0]
    if row.get("chance_pass_message"):
        line += "; " + row["chance_pass_message"]
    if row.get("diagnostics"):
        line += (
            "; diagnostic only: cannot pass. Choosing the sign or clock after "
            "seeing this is a new trial and will be counted."
        )
    return line


def append_swing_context(context: dict[str, Any], ledger_name: str | None) -> None:
    universe = current_universe()
    context["hypothesis_and_feedback"] += "\n" + SWING_BRIEF
    correction = f"\nCurrent universe: {universe}; earlier text saying otherwise is out of date"
    refusals = "".join(
        f"\nALPHA refused this round's earlier proposal: {message}" for message in FAMILY_REFUSALS
    )
    append_ledger_context(context, ledger_name, universe, len(correction) + len(refusals))
    source = family_definitions().universe_source(os.environ.get("ALPHA_FACTOR_RUN_DIR"))
    hidden = family_definitions().hidden_families(source)
    context["hypothesis_and_feedback"] += (
        family_definitions().filter_history(refusals, hidden, set()) + correction
    )


def append_ledger_context(
    context: dict[str, Any], ledger_name: str | None, universe: str, reserved_chars: int
) -> None:
    if not (rows := AlphaFactorHypothesisGen.ledger_rows(ledger_name)):
        return
    heading = "\nALPHA trial ledger (all runs; exploratory, not admitted; " + universe + ")\n"
    lines: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    known = AlphaFactorHypothesisGen.TRIAL_SCHEMAS
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("schema"), str):
            raise ValueError("invalid ALPHA trial ledger schema")
        if row["schema"] not in known | {"AlphaRuleTrialV1"}:
            unknown.append(row["schema"])
        elif row["schema"] in known:
            ledger_summary(row)  # Validate known rows even outside the 30-row summary.
    # Newest first, whole lines only, within 4000 characters; the count of the rest is stated so
    # the proposer knows the list is partial instead of reading a line cut in half.
    used, omitted = len(heading) + reserved_chars, 0
    failures = family_definitions().family_failure_counts(rows)
    switch_after = int(os.environ.get("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3"))
    groups = AlphaFactorHypothesisGen.trial_families(AlphaFactorHypothesisGen.distinct_trials(rows))
    closed = family_definitions().closed_groups(groups, switch_after)
    source = family_definitions().universe_source(os.environ.get("ALPHA_FACTOR_RUN_DIR"))
    hidden = family_definitions().hidden_families(source)
    for row in (r for r in reversed(rows) if r["schema"] in known):
        line = ledger_summary(row, failures, switch_after, closed)
        if family_definitions().mentions_family(line, hidden):
            continue
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
    context["hypothesis_and_feedback"] += family_summary(
        AlphaFactorHypothesisGen.distinct_trials(rows), switch_after
    )
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
    factors = {f["name"]: f for f in exp.alpha_evaluation.get("factors", [])}
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
        **({"discussion": exp.discussion} if hasattr(exp, "discussion") else {}),
        "tasks": [
            {
                "name": task.factor_name,
                **getattr(task, "summary_fields", {}),
                **getattr(task, "discussion_fields", {}),
                **{key: getattr(task, key, None) for key in ("description", "variables")},
                "formulation": getattr(task, "factor_formulation", None),
                "code_sha256": factors.get(task.factor_name, {}).get("code_sha256"),
                **{
                    k: v
                    for k, v in factors.get(task.factor_name, {}).items()
                    if k in {"critic_status", "critic_reason", "family"}
                },
            }
            for task in exp.sub_tasks
        ],
        "refused_before_coding": getattr(exp, "alpha_refused_before_coding", []),
        "feedback": {
            key: getattr(feedback, key)
            for key in ("observations", "hypothesis_evaluation", "new_hypothesis", "reason")
        },
    }
    with (run / "rounds.jsonl").open("a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def current_funding_setting() -> str:
    run = os.environ.get("ALPHA_FACTOR_RUN_DIR")
    path = Path(run) / "factor_data/full/daily_pv.h5" if run else None
    if path is None or not path.exists():
        return ""
    receipt = path.parents[1] / "prepare-receipt.json"
    if not (receipt.exists() and "funding_sha256" in json.loads(receipt.read_bytes())):
        # prepare writes fixed-format frames, whose column index is stored as axis0.
        store: Any
        with pd.HDFStore(path, mode="r") as store:
            columns = store.get_storer("data").read_index("axis0")
        if not {"$funding_sum", "$funding_last", "$funding_count"} <= set(columns):
            return ""
    return (
        " Futures funding inputs: $funding_sum, $funding_last, $funding_count. "
        "Missing funding stays NaN, never zero or forward-filled; only settlements known "
        "before the day's midnight UTC close are included. Funding factors rank only names "
        "with a funding row that day; outcomes remain spot returns."
    )


class AlphaFactorScenario(QlibFactorScenario):
    _funding_text: str | None = None

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
            "365 days/year. " + DECLARATION_TEMPLATE + " "
            "For each factor add a proposal_metadata object with plain_summary: one sentence "
            "of at most 30 words saying what the number measures and what it expects, "
            "without formula symbols, variable names or code."
            " The conservative screen "
            "counts each new factor once; "
            "historical per-clock looks remain counted. A screened primary clock can pass only "
            "if the top third it would hold beat its bottom third before costs. "
            "Hold drifted weights between rebalances; residual trades are executed and charged. "
            "New frozen panels require 20 consecutive daily bars and a non-null factor to rank. "
            "Missing rows are null. Held missing names wait at last close, exit at the first "
            "resuming close, or lose 30% after 30 calendar days without a bar. Outstanding "
            "waits at panel end also lose 30%; this haircut is an assumption, not a measurement. "
            "A candidate must pass the declared primary screen, spread, costed"
            " replay and deflation. "
            "It is a lead for one owner-approved reserved-data check, never evidence by itself."
            + (
                " Include input_columns in proposal_metadata, a list of the panel columns the "
                "factor plans to read."
                if os.environ.get("ALPHA_FACTOR_DISCUSS") == "1"
                else ""
            )
        )

    @property
    def experiment_setting(self) -> str:
        universe_text: str = current_universe()
        if self._funding_text is None:
            self._funding_text = current_funding_setting()
        return (
            "Binance USDT spot coins, daily bars: " + universe_text + ". History only: "
            "2017-08-17..2020-12-31; exploration decisions: 2021-01-01..2023-12-24; panel ends "
            "2023-12-31. 2024-01-01 onward is reserved and never available to this loop. "
            "Prefix-invariance checks at quarter ends and 2023-12-24 detect some look-ahead, "
            "not all. Daily, weekly (7-day) and monthly (28-day) holding/rebalance clocks are "
            "fixed in advance; only a weekly or monthly pass can become a candidate. "
            "exploratory, not admitted, not yet confirmed." + self._funding_text
        )


class AlphaFactorRunner(Developer):
    @staticmethod
    def critic_fields(feedback: Any) -> dict[str, str]:
        opinion = getattr(feedback, "code_feedback", None)
        status = getattr(feedback, "alpha_critic_status", None)
        if status in ("skipped", "unavailable"):
            return {"critic_status": status, "critic_reason": opinion}
        if not opinion:
            return {
                "critic_status": "unavailable",
                "critic_reason": "no code critic opinion recorded",
            }
        if opinion in (
            "Final decision is True and there are no code critics.",
            "This task has failed too many times, skip code evaluation.",
        ):
            return {"critic_status": "skipped", "critic_reason": opinion}
        if opinion.startswith("code critic unavailable (provider "):
            return {"critic_status": "unavailable", "critic_reason": opinion}
        return {"critic_status": "reviewed"}

    @staticmethod
    def text_reason(text: str) -> str | None:
        """cap_reached or exception when the text says so; otherwise None."""
        lowered = text.lower()
        if any(t in lowered for t in ("budget_exhausted", "budget exhausted", "call cap reached")):
            return "cap_reached"
        if "Traceback" in text or re.search(r"\b\w*(?:Error|Exception)\b", text):
            return "exception"
        return None

    @staticmethod
    def error_line(text: str) -> str:
        """The error's own first line: after a traceback, its final "SomeError: ..." line."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if "Traceback" in text:
            errors = [line for line in lines if re.match(r"[\w.]*(?:Error|Exception)\b", line)]
            if errors:
                return errors[-1]
        return lines[0] if lines else ""

    @staticmethod
    def execute_factor(workspace: Any, feedback: Any) -> tuple[Any, str | None, str]:
        """Separate execution, critic and output failures before they reach the ledger."""
        detail = str(getattr(feedback, "execution_feedback", "") or "")
        reason: str | None
        if not feedback:
            reason = AlphaFactorRunner.text_reason(detail) or "critic_rejected"
            line = AlphaFactorRunner.error_line(detail)
            return None, reason, line or "RD-Agent critic did not accept the code"
        try:
            execution, values = workspace.execute("All")
        except Exception as error:
            reason = AlphaFactorRunner.text_reason(f"{getattr(error, 'code', '')} {error}")
            return None, reason or "exception", f"{type(error).__name__}: {error}".split("\n")[0]
        if not isinstance(values, pd.DataFrame):
            text = str(execution)
            reason = AlphaFactorRunner.text_reason(text) or "bad_output"
            return (
                None,
                reason,
                AlphaFactorRunner.error_line(text) or "factor returned no data frame",
            )
        if (
            values.empty
            or len(values.columns) != 1
            or not isinstance(values.index, pd.MultiIndex)
            or values.index.nlevels != 2
        ):
            return (
                values,
                "bad_output",
                "one output column and a date/instrument index required per factor task",
            )
        try:
            dates = pd.to_datetime(values.index.get_level_values(0), utc=True, errors="raise")
            pd.to_numeric(values.iloc[:, 0], errors="raise")
            if dates.hasnans or any(
                not isinstance(name, str) or not name for name in values.index.get_level_values(1)
            ):
                raise ValueError("factor dates and instrument names must be present")
        except (ValueError, TypeError, OverflowError) as error:
            return values, "bad_output", f"{type(error).__name__}: {error}".split("\n")[0]
        return values, None, ""

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
                **getattr(task, "summary_fields", {}),
                **getattr(task, "discussion_fields", {}),
                # The family the tally counts this row under, stored once (no re-derivation).
                "family": family_definitions().idea_family(
                    task.factor_name,
                    getattr(task, "description", "") or "",
                    getattr(task, "factor_formulation", "") or "",
                    getattr(task, "variables", None),
                ),
                **self.critic_fields(feedback),
                **family_definitions().declaration(getattr(task, "description", "") or ""),
                "code_sha256": hashlib.sha256(identity).hexdigest(),
                "status": "FAILED",
                "lookahead": {"status": "NOT_RUN"},
                "description": getattr(task, "description", None),
                "formulation": getattr(task, "factor_formulation", None),
                # The feature names and meanings a composite is classified by (ADR-0055).
                "variables": getattr(task, "variables", None),
                # No code: the coder stopped (the call cap, an error) or produced no file.
                "failure_reason": self.text_reason(
                    str(getattr(feedback, "execution_feedback", "") or "")
                )
                or "bad_output",
                "failure_detail": "factor.py was not produced",
            }
            if code:
                record_code(run, str(factor["code_sha256"]), code)
            if code:
                values, failure, detail = self.execute_factor(workspace, feedback)
                factor.update(failure_reason=failure, failure_detail=detail)
                if values is not None and failure is None:
                    factor.pop("failure_reason")
                    factor.pop("failure_detail")
                    check = check_prefix_invariance(
                        code,
                        values,
                        run / "factor_data/cuts",
                        os.environ["ALPHA_FACTOR_CODE_PYTHON"],
                        120.0,
                    )
                    factor["lookahead"] = check
                    factor["status"] = {"PASS": "OK", "UNSTABLE": "UNSTABLE"}.get(
                        check["status"], "LOOKAHEAD"
                    )
                    if factor["status"] == "OK":
                        frame = values.copy()
                        frame.columns = [task.factor_name]
                        frame.index.names = ["date", "instrument"]
                        frames.append(frame)
                    elif check["status"] in {"LOOKAHEAD", "UNSTABLE"}:
                        # Only ALPHA's verdict on the code itself: a check that merely errored
                        # (timeout, subprocess failure) says nothing about the code.
                        rejected.append((task, factor))
                else:
                    if failure == "bad_output" and isinstance(values, pd.DataFrame):
                        rejected.append((task, factor))
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
        # The evaluator writes the trial ledger and records shortlist/lineage diagnostics.
        # Preserve those fields in alpha_evaluation; only its existing decision judges the run.
        exp.result = pd.Series(
            {**dict.fromkeys(VIEWER_KEYS, float("nan")), **record["legacy_result"]}
        )
        exp.stdout = record["feedback_text"]
        exp.alpha_evaluation = record
        if all(f["status"] == "FAILED" for f in factors):
            raise FactorEmptyError("ALPHA recorded every factor as FAILED")
        return exp


class AlphaFactorHypothesisGen(QlibFactorHypothesisGen):
    TRIAL_SCHEMAS = {
        "AlphaRdagentFactorTrialV1",
        "AlphaRdagentFactorTrialV2",
        "AlphaRdagentFactorTrialV3",
    }
    _ledger_snapshot: tuple[tuple[str, int, int], list[dict[str, Any]]] | None = None

    def gen(self, trace: Any, plan: Any = None) -> Any:
        # The guard's re-asks are part of the same round.
        if not FAMILY_REFUSALS:
            AlphaFactorHypothesisGen._ledger_snapshot = None
        return super().gen(trace, plan)

    @classmethod
    def ledger_rows(cls, name: str | None) -> list[dict[str, Any]] | None:
        if not name:
            return None
        path = Path(name)
        try:
            stat = path.stat()
        except FileNotFoundError:
            cls._ledger_snapshot = None
            return None
        key = (name, stat.st_size, stat.st_mtime_ns)
        if cls._ledger_snapshot is None or cls._ledger_snapshot[0] != key:
            raw = path.read_bytes()
            # Another run may be appending; consume only complete lines.
            rows = [json.loads(line) for line in raw[: raw.rfind(b"\n") + 1].splitlines()]
            cls._ledger_snapshot = key, rows
        return cls._ledger_snapshot[1]

    @classmethod
    def distinct_trials(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        distinct: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["schema"] in cls.TRIAL_SCHEMAS and row["status"] not in {"REPEAT", "IMPORTED"}:
                distinct.setdefault(row["code_sha256"], row)
        return list(distinct.values())

    @staticmethod
    def row_families(row: dict[str, Any]) -> list[str]:
        return list(family_definitions().row_families(row))

    @classmethod
    def trial_families(cls, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        families: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            row = {**row, "status": family_definitions().recorded_status(row)}
            if row["status"] not in {
                "SCREEN_FAIL",
                "SPREAD_FAIL",
                "REPLAY_FAIL",
                "FAST_ONLY",
                "CANDIDATE",
                "DEFLATION_FAIL",
            }:
                continue
            for family in cls.row_families(row):
                families.setdefault(family, []).append(row)
        return families

    bounded_history: Any = None

    @property
    def upstream_history(self) -> Any:
        return super().prepare_context

    def prepare_context(self, trace: Any) -> tuple[dict[str, Any], bool]:
        prepare = self.bounded_history or self.upstream_history
        context, flag = prepare(trace)
        append_swing_context(context, os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER"))
        if note := getattr(self, "discussion_note", None):
            context["hypothesis_and_feedback"] += FamilyGuard.discussion_tools().note_block(note)
            self.discussion_note = None
        return context, flag


class AlphaFactorFeedback(Experiment2Feedback):
    def generate_feedback(self, exp: Any, trace: Any, exception: Exception | None = None) -> Any:
        refusal = getattr(exp, "alpha_family_refusal", None)
        if refusal:
            return HypothesisFeedback(
                observations=refusal["message"],
                hypothesis_evaluation="refused_closed_family",
                new_hypothesis=(
                    "A mechanism that belongs to none of the closed families is allowed."
                ),
                reason="no_admissible_idea; no data read and no trial created",
                decision=False,
            )
        scenario = (
            self.scen.get_scenario_all_desc(action="factor")
            if isinstance(self.scen, QlibQuantScenario)
            else self.scen.get_scenario_all_desc()
        )
        scenario += (
            f"\nCurrent universe: {current_universe()}; "
            "earlier text saying otherwise is out of date"
        )
        scenario += "\n" + family_permissions(closed_families(), include_counts=True)
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
        identity = record.get("disclosures", {}).get("identity_breaks")
        if identity is not None:
            # Keep ALPHA's count in the next proposer's trace even if the model omits it.
            feedback.observations += "\n" + identity["message"]
        feedback.observations += "\n" + record.get("feedback_text", "")
        for refusal in getattr(exp, "alpha_refused_before_coding", []):
            feedback.observations += "\n" + refusal
        for factor in record.get("factors", []):
            if factor.get("writeoff_message"):
                feedback.observations += "\n" + factor["writeoff_message"]
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


def known_families() -> set[str]:
    rows = AlphaFactorHypothesisGen.ledger_rows(os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER"))
    families: set[str] = set()
    for row in rows or []:
        if row.get("schema", "").startswith("AlphaRdagentFactorTrial"):
            families.update(AlphaFactorHypothesisGen.row_families(row))
    return families


def closed_families() -> set[str]:
    """Families with enough evaluated failed tries and no candidate, from the trial ledger."""
    rows = AlphaFactorHypothesisGen.ledger_rows(os.environ.get("ALPHA_FACTOR_TRIAL_LEDGER"))
    families = AlphaFactorHypothesisGen.trial_families(
        AlphaFactorHypothesisGen.distinct_trials(rows or [])
    )
    limit = int(os.environ.get("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3"))
    return set(family_definitions().closed_groups(families, limit))


class FamilyGuard:
    """Check proposed tasks at the coder boundary; a refusal creates no trial and reads no data.

    A refused proposal is replaced by asking the proposer again, through the loop's own propose
    and experiment steps, at most twice per round; the refusal text is added to its context. A
    third refusal ends the round through upstream's FactorEmptyError skip path.
    """

    def __init__(self, coder: Any, loop: Any = None) -> None:
        self.coder = coder
        self.loop = loop

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "coder"), name)

    @staticmethod
    def refusals(tasks: list[Any], closed: set[str]) -> tuple[set[str], list[str]]:
        proposed: set[str] = set()
        missing = []
        for task in tasks:
            description = getattr(task, "description", "") or ""
            proposed.update(
                idea_family(
                    task.factor_name,
                    description,
                    getattr(task, "factor_formulation", "") or "",
                    getattr(task, "variables", None),
                ).split("; ")
            )
            try:
                family_definitions().declaration(description)
            except ValueError as error:
                missing.append(
                    f"missing declaration in {task.factor_name}: {str(error).rstrip('.')}"
                )
        return proposed, sorted(proposed & closed) + missing

    @staticmethod
    def discussion_tools() -> Any:
        import importlib

        package = family_definitions().__package__
        return importlib.import_module(f"{package}.discussion" if package else "discussion")

    def admit(self, exp: Any, closed: set[str], proposed: set[str]) -> None:
        if os.environ.get("ALPHA_FACTOR_DISCUSS") != "1":
            return
        discussion = self.discussion_tools()
        ideas = []
        for task in exp.sub_tasks:
            family = idea_family(
                task.factor_name, task.description, task.factor_formulation, task.variables
            )
            ideas.append(
                discussion.idea(task, family, family_definitions().declaration(task.description))
            )
        discussion.discuss(
            self,
            exp,
            ideas,
            family_permissions(closed, proposed),
            lambda tasks: self.refusals(tasks, closed_families()),
        )
        if not exp.sub_tasks:
            raise FactorEmptyError("Discussion ended with no ideas to build; no trial created.")

    def develop(self, exp: Any) -> Any:
        try:
            for attempt in range(1, FAMILY_PROPOSALS_PER_ROUND + 1):
                for task in exp.sub_tasks:
                    task.summary_fields = self.discussion_tools().summary_fields(
                        getattr(task, "plain_summary", None)
                    )
                closed = closed_families()
                proposed, refused = self.refusals(exp.sub_tasks, closed)
                if not refused:
                    if self.loop is not None and hasattr(self.loop, "loop_prev_out"):
                        previous = self.loop.loop_prev_out[self.round_index()]
                        previous["direct_exp_gen"] = {"propose": exp.hypothesis, "exp_gen": exp}
                    exp.alpha_refused_before_coding = list(FAMILY_REFUSALS)
                    self.admit(exp, closed, proposed)
                    return self.coder.develop(exp)
                final = attempt == FAMILY_PROPOSALS_PER_ROUND or self.loop is None
                self._refuse(exp, refused, proposed, closed, attempt, final)
                exp = self._propose_again()
        finally:
            FAMILY_REFUSALS.clear()
        raise AssertionError("unreachable: the last refusal ends the round")

    def _refuse(
        self,
        exp: Any,
        refused: list[str],
        proposed: set[str],
        closed: set[str],
        attempt: int,
        final: bool,
    ) -> None:
        open_families = sorted(
            ({name for name, _ in FAMILY_KEYWORDS} | known_families() | proposed) - closed
        )
        message = (
            ("Refused closed families: " if proposed & closed else "Refused: ")
            + "; ".join(refused)
            + ". "
            + family_permissions(closed, proposed)
            + (
                " List each input feature by name in the variables, then it can be judged."
                if "composite: unknown inputs" in refused
                else ""
            )
            + "".join(
                f" Unrecognised input {name}: {family_definitions().name_family(name)}."
                for task in exp.sub_tasks
                for name in family_definitions().input_names(getattr(task, "variables", None))
                if not family_definitions().name_matches(name)
            )
            + (
                " No admissible idea; round ended before coding, no trial created."
                if final
                else f" Proposal {attempt} refused before coding, no trial created; "
                "the proposer is asked again."
            )
        )
        row: dict[str, Any] = {
            "schema": "AlphaRdagentRoundV1",
            "status": "no_admissible_idea"
            if final
            else "refused_missing_declaration"
            if any(r.startswith("missing declaration") for r in refused)
            else "refused_closed_family",
            "reason": "refused_missing_declaration"
            if any(r.startswith("missing declaration") for r in refused)
            else "refused_closed_family",
            "attempt": attempt,
            "trial_created": False,
            "iteration": self.round_index(),
            "factor_names": [
                task.factor_name
                for task in exp.sub_tasks
                if set(
                    idea_family(
                        task.factor_name,
                        getattr(task, "description", "") or "",
                        getattr(task, "factor_formulation", "") or "",
                        getattr(task, "variables", None),
                    ).split("; ")
                )
                & closed
                or any(item.startswith("missing declaration") for item in refused)
            ],
            "refused_families": refused,
            "plain_summary": {t.factor_name: t.summary_fields for t in exp.sub_tasks},
            "all_closed_families": sorted(closed),
            "open_families": open_families,
            "hypothesis": str(exp.hypothesis),
            "message": message,
        }
        run = Path(os.environ["ALPHA_FACTOR_RUN_DIR"])
        with (run / "rounds.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        if final:
            exp.alpha_family_refusal = row
            exp.alpha_refused_before_coding = [
                *FAMILY_REFUSALS,
                "refused before coding: "
                + ", ".join(row["factor_names"])
                + " ("
                + "; ".join(refused)
                + ")",
            ]
            if self.loop is not None and hasattr(self.loop, "loop_prev_out"):
                self.loop.loop_prev_out[self.round_index()]["direct_exp_gen"] = {
                    "propose": exp.hypothesis,
                    "exp_gen": exp,
                }
            raise FactorEmptyError(message)
        FAMILY_REFUSALS.append(
            "refused before coding: "
            + ", ".join(row["factor_names"])
            + " ("
            + "; ".join(refused)
            + "). "
            + message
        )

    def _propose_again(self) -> Any:
        """The same two calls and plan fields as upstream RDLoop.direct_exp_gen, nothing more."""
        loop = self.loop
        tools = self.discussion_tools()
        with tools.proposal_step(self.round_index(), "proposal_reask", tools.utc_now):
            exp = loop._exp_gen(loop._propose())
        exp.base_features = loop.plan["features"]
        exp.base_feature_codes = loop.plan["feature_codes"]
        if exp.based_experiments:
            exp.based_experiments[-1].base_features = loop.plan["features"]
            exp.based_experiments[-1].base_feature_codes = loop.plan["feature_codes"]
        return exp

    def round_index(self) -> int:
        path = Path(os.environ["ALPHA_FACTOR_RUN_DIR"]) / "steps.jsonl"
        if path.exists():
            for line in reversed(path.read_text().splitlines()):
                row = json.loads(line)
                if row["step"] == "coding" and row["event"] == "start":
                    return int(row["loop"])
        return int(getattr(self.loop, "loop_idx", 0))
