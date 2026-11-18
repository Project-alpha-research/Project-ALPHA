"""Exercise both sides of the file contract without a running worker."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import rdagent_discussion
from alpha_cli.ledger_cmds import ledger_app
from alpha_cli.rdagent_journey_words import idea_step
from workers.rdagent import discussion


def example(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "proposal.json").write_text(
        json.dumps(
            {
                "run_id": "example",
                "round": int(folder.name.split("-")[1]),
                "wait_minutes": 30,
                "caution": discussion.CAUTION,
                "remaining": {"calls": 6, "usd": 10},
                "deadline": "2026-11-18T05:30:00+00:00",
                "families": "Closed families: illiquidity. open families: drawdown.",
                "ideas": [
                    {
                        "name": name,
                        "plain_summary": summary,
                        "family": family,
                        "declared_direction": direction,
                        **(
                            {
                                "primary_clock": "weekly",
                                "instrument_count": 12,
                                "input_columns": ["$funding_rate"],
                            }
                            if name == "Funding"
                            else {}
                        ),
                        "reason": reason,
                    }
                    for name, summary, family, direction, reason in [
                        (
                            "Funding",
                            "Cheaper funding may precede a rise.",
                            "futures funding",
                            -1,
                            "**Buyers pay less to hold.** "
                            'proposal_metadata: {"plain_summary":"extra"}',
                        ),
                        (
                            "Volume",
                            None,
                            "other: first",
                            1,
                            None,
                        ),
                    ]
                ],
            }
        )
    )


EXPECTED = """RD-Agent proposes 2 ideas for round 10.
You have until 05:30 UTC (30 minutes). If you do not answer, the run builds every idea as proposed.

1. Funding
   Cheaper funding may precede a rise.
   It expects coins with lower numbers to earn more over the next 7 days.
   Holding period: about 7 days.
   Coins ranked each period: 12.
   How often positions change: every 7 days.
   Idea type: futures funding.
   The agent's reason: Buyers pay less to hold.
   Data it plans to read: funding rate.

2. Volume
   The agent gave no plain sentence.
   It expects coins with higher numbers to earn more.
   Holding period: not recorded.
   Coins ranked each period: not recorded.
   How often positions change: not recorded.
   Idea type: not classified.
   The agent's reason: not recorded.
   Data it plans to read: not recorded.

Model budget left in this run: 6 calls, $10.00.
Idea types closed after repeated failed tries: ease of trading.
{caution}

To answer, run:
  alpha ledger reply --run-dir {run} --as owner
Then add what you want to change. Name an idea by its number or its name:
  --drop 1                      do not build idea 1 (add =reason to say why)
  --revise "1=what to change"   ask the agent to change idea 1
  --idea "your idea"            add your own idea (two at most)
  --note "text"                 tell the agent something for the next round
Ideas you do not name are built as proposed.
A stand-in user answers with --as stand-in instead of --as owner.
"""


def test_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    example(tmp_path / "discussion/round-2")
    folder = tmp_path / "discussion/round-10"
    example(folder)
    args = ["--run-dir", str(tmp_path)]
    result = runner.invoke(ledger_app, ["proposal", *args])
    assert result.exit_code == 0, result.output
    assert result.output == EXPECTED.format(run=tmp_path, caution=discussion.CAUTION)
    result = runner.invoke(ledger_app, ["reply", *args, "--as", "owner", "--drop", "typo"])
    assert result.exit_code != 0 and all(n in result.output for n in ("typo", "Funding", "Volume"))
    assert not (folder / "reply.json").exists()
    result = runner.invoke(
        ledger_app,
        [
            "reply",
            *args,
            "--as",
            "stand-in",
            "--revise",
            "2=Use turnover",
            "--idea",
            "Try spreads",
            "--note",
            "Look at funding next",
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output == (
        "Your answer for round 10 is saved. RD-Agent reads it within seconds.\n"
        "Answered by: a stand-in user, not the owner.\n"
        "Build as proposed: Funding.\n"
        "Change: Volume. Your note: Use turnover.\n"
        "Your own idea: Try spreads.\n"
        "Note to the agent: Look at funding next.\n"
        "Saved in discussion/round-10/reply.json.\n"
    )
    reply = json.loads((folder / "reply.json").read_bytes())
    assert reply == {
        "author": "stand-in user, not the owner",
        "ideas": {
            "Funding": {"action": "accept"},
            "Volume": {"action": "revise", "note": "Use turnover"},
        },
        "user_ideas": ["Try spreads"],
        "note_to_agent": "Look at funding next",
    }
    result = runner.invoke(ledger_app, ["proposal", *args])
    assert result.exit_code == 0 and "No proposal is waiting." in result.output


@pytest.mark.parametrize("state", ["reply.json", "decision.json", "receipt.json"])
def test_late_or_second_reply_is_refused_and_kept(tmp_path: Path, state: str) -> None:
    folder = tmp_path / "discussion/round-3"
    example(folder)
    first = (tmp_path if state == "receipt.json" else folder) / state
    first.write_text("{}")
    before = first.read_bytes()
    result = CliRunner().invoke(
        ledger_app, ["reply", "--run-dir", str(tmp_path), "--as", "owner", "--drop", "Funding"]
    )
    assert result.exit_code != 0 and "refused-reply-1.json" in result.output
    assert first.read_bytes() == before
    kept = json.loads((folder / "refused-reply-1.json").read_bytes())
    assert kept["reply"]["ideas"]["Funding"] == {"action": "drop"} and kept["refused"]
    if state != "reply.json":
        assert not (folder / "reply.json").exists()


def test_validators_are_the_same_code() -> None:
    """The worker cannot import alpha_cli, so the two copies must stay identical."""

    def functions(path: Path) -> dict[str, str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        wanted = {
            "summary_fields",
            "validate_reply",
            "USER_TEXT_LIMIT",
            "validate_decision",
            "revision_statements",
        }
        found = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in wanted:
                found[node.name] = ast.dump(node)
            elif isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) in wanted:
                found[ast.unparse(node.targets[0])] = ast.dump(node)
        return found

    root = Path(__file__).resolve().parents[2]
    worker = functions(root / "workers/rdagent/discussion.py")
    cli = functions(root / "apps/alpha-cli/src/alpha_cli/rdagent_discussion.py")
    assert len(worker) == 5 and worker == cli


@pytest.mark.parametrize(
    "change,valid",
    [
        ({}, True),
        ({"author": "stand-in user, not the owner"}, True),
        ({"user_ideas": ["one", "two"]}, True),
        ({"author": "stand-in"}, False),
        ({"approve": True}, False),
        ({"ideas": {}}, False),
        ({"ideas": []}, False),
        ({"ideas": {"A": {"action": "revise"}}}, False),
        ({"ideas": {"A": {"action": "drop", "reason": "too fast"}}}, True),
        ({"ideas": {"A": {"action": "accept", "reason": "yes"}}}, False),
        ({"ideas": {"A": {"action": "revise", "note": "  "}}}, False),
        ({"ideas": {"B": {"action": "drop"}}}, False),
        ({"note_to_agent": 1}, False),
        ({"user_ideas": ["a", "b", "c"]}, False),
        ({"user_ideas": "abc"}, False),
        ({"user_ideas": ["x" * 500]}, True),
        ({"user_ideas": ["x" * 501]}, False),
        ({"note_to_agent": "x" * 501}, False),
        ({"ideas": {"A": {"action": "revise", "note": "x" * 501}}}, False),
        ({"ideas": {"A": {"action": "drop", "reason": "x" * 501}}}, False),
    ],
)
def test_validator_agreement(change: dict[str, Any], valid: bool) -> None:
    reply = {"author": "owner", "ideas": {"A": {"action": "accept"}}, **change}
    summaries = [None, "", "Quiet coins may rise.", "$close", "a_b", "word " * 31, 3]
    assert [discussion.summary_fields(x) for x in summaries] == [
        rdagent_discussion.summary_fields(x) for x in summaries
    ]
    for validate in (discussion.validate_reply, rdagent_discussion.validate_reply):
        if valid:
            validate(reply, ["A"])
        else:
            with pytest.raises(ValueError):
                validate(reply, ["A"])


def test_journey_starts_with_valid_summary() -> None:
    row = {"description": "Old wording.", "declared_direction": 1, "primary_clock": "weekly"}
    old = idea_step(row, {}, [])["text"]
    for raw in ("", "$close", "word " * 31):
        assert idea_step({**row, "plain_summary": raw}, {}, [])["text"] == old
    new = idea_step({**row, "plain_summary": "Quiet coins may rise"}, {}, [])["text"]
    assert new.startswith("Quiet coins may rise. ") and "Old wording" not in new


def test_new_ledger_rows_normalize_summary_and_keep_attribution() -> None:
    from alpha_cli._rdagent_ledger import new_factor_row

    factor = {"name": "Test", "primary_clock": "weekly"}
    inputs = dict.fromkeys(("panel_sha256", "factor_values_path", "factors_sha256"), "test")

    def row(**fields: Any) -> dict[str, Any]:
        return new_factor_row({**factor, **fields}, inputs, 1, "run", 0, ["A"], "test", "test")

    assert row()["plain_summary_status"] == "missing"
    assert row(plain_summary="$close")["plain_summary_status"] == "rejected"
    result = row(plain_summary="Cheaper coins may rise.", origin="user", author="owner")
    assert result["plain_summary"] == "Cheaper coins may rise."
    assert result["answered_by"] == "owner" and result["plain_summary_status"] == "ok"
    assert result["origin"] == "user" and result["author"] == "owner"
    canonical = row(origin="user", answered_by="owner")
    assert canonical["answered_by"] == canonical["author"] == "owner"


@pytest.mark.parametrize(
    "origin,who",
    [
        ("user", "You (the user)"),
        ("agent-revised-by-user", "RD-Agent (AI), changed at your request"),
        ("agent", "RD-Agent (AI)"),
    ],
)
def test_journey_credits_and_full_condition(origin: str, who: str) -> None:
    sentence = "If costs fall, buy the cheaper coins only when demand persists."
    row = {
        "origin": origin,
        "answered_by": "stand-in user, not the owner",
        "plain_summary": sentence,
        "plain_summary_status": "ok",
    }
    step = idea_step(row, {}, [])
    assert step["text"].startswith(sentence)
    assert step["who"] == who + " — answered by a stand-in user"


def test_numbered_drop_and_decision(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-10"
    example(folder)
    args = ["--run-dir", str(tmp_path)]
    runner = CliRunner()
    for flag in ("--drop", "--revise", "--accept"):
        bad = runner.invoke(ledger_app, ["reply", *args, "--as", "owner", flag, "3"])
        assert bad.exit_code and "1. Funding" in bad.output and "2. Volume" in bad.output
    result = runner.invoke(
        ledger_app, ["reply", *args, "--as", "owner", "--drop", "1=Too costly", "--accept", "2"]
    )
    assert result.exit_code == 0
    assert "Drop: Funding. Your reason: Too costly." in result.output
    assert "Build as proposed: Volume." in result.output
    decision = {
        "selected_tasks": [{"name": "Weekday"}],
        "dropped": [{"name": "Funding", "reason": "Too costly"}],
        "replacements": [
            {
                "name": "Weekday",
                "revised_from": "Volume",
                "honoured": ["Used weekdays."],
                "not_honoured": ["Skipped costs because data is missing."],
            }
        ],
    }
    (folder / "decision.json").write_text(json.dumps(decision))
    (folder.parent / "status.json").write_text(
        json.dumps(
            {
                "state": "building",
                "round": 10,
                "since": "2026-11-18T05:18:00+00:00",
                "estimate_minutes": 4,
            }
        )
    )
    result = runner.invoke(ledger_app, ["proposal", *args])
    assert result.exit_code == 0
    assert result.output.startswith(
        "No proposal is waiting. Round 10 is being built: 1 idea. "
        "The next proposal usually appears in about 4 minutes."
    )
    last = runner.invoke(ledger_app, ["proposal", *args, "--last-decision"])
    assert last.exit_code == 0 and result.output.endswith(last.output)
    for value in (
        "Volume",
        "Weekday",
        "Funding",
        "Too costly",
        "Used weekdays.",
        "Skipped costs because data is missing.",
    ):
        assert value in last.output


def test_full_families_only_in_details(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    args = ["proposal", "--run-dir", str(tmp_path)]
    result = CliRunner().invoke(ledger_app, [*args, "--details"])
    assert result.exit_code == 0 and "open families: drawdown" in result.output


def test_degenerate_verdict_names_tied_day_share() -> None:
    from alpha_cli.rdagent_journey_words import outcome

    row = {
        "status": "DEGENERATE",
        "primary_clock": "weekly",
        "clocks": {"weekly": {"screen": {"all_tied_day_share": 0.84}}},
    }
    assert "84% of days" in outcome(row)


def test_evaluator_feedback_uses_actual_ties() -> None:
    from alpha_cli._rdagent_clocks import clock_feedback

    row = {
        "name": "A",
        "schema": "AlphaRdagentFactorTrialV3",
        "status": "DEGENERATE",
        "primary_clock": "weekly",
        "clocks": {
            "weekly": {"screen": {"all_tied_day_share": 0.84}, "replay": {}, "status": "DEGENERATE"}
        },
    }
    assert "84% of days" in clock_feedback(row)


def test_revision_explanation_reader_refuses_malformed_lists(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    decision = {
        "selected_tasks": [],
        "dropped": [],
        "replacements": [
            {"name": "A", "revised_from": "Funding", "honoured": "wrong type", "not_honoured": []}
        ],
    }
    (folder / "decision.json").write_text(json.dumps(decision))
    result = CliRunner().invoke(
        ledger_app, ["proposal", "--run-dir", str(tmp_path), "--last-decision"]
    )
    assert result.exit_code == 1 and "honoured" in result.output


def test_reason_keeps_the_traders_sentence_inside_markup() -> None:
    reason = '**direction_reason:** "Sellers pay less." `proposal_metadata`: {"a":1}'
    assert rdagent_discussion.plain_reason(reason) == "Sellers pay less."


def test_family_limit_and_old_decision_while_waiting(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-1"
    example(folder)
    first = folder.parent / "round-0"
    example(first)
    (first / "decision.json").write_text(json.dumps({"selected_tasks": [{"name": "Previous"}]}))
    path = folder / "proposal.json"
    value = json.loads(path.read_bytes())
    value["families"] = (
        "Closed families: "
        + "; ".join(list(rdagent_discussion.FAMILY_NAMES)[:7])
        + ". open families: none."
    )
    value["caution"] = discussion.CAUTION
    value["on_timeout"] = "stop"
    path.write_text(json.dumps(value))
    text = rdagent_discussion.proposal_text(tmp_path)
    assert "and 2 more." in text and "open families:" not in text
    assert text.splitlines()[1].endswith("the run stops and builds nothing.")
    assert discussion.CAUTION in text
    assert "Previous" in rdagent_discussion.proposal_text(tmp_path, last_decision=True)


def test_recorded_lists_must_be_valid_but_may_be_missing() -> None:
    selected = [{"name": "A", "origin": "agent-revised-by-user", "answered_by": "owner"}]
    missing = {"selected_tasks": selected, "replacements": [{"name": "A", "revised_from": "F"}]}
    long = {**missing, "replacements": [{**missing["replacements"][0], "honoured": ["x"] * 6}]}
    for validate in (discussion.validate_decision, rdagent_discussion.validate_decision):
        validate(missing)
        with pytest.raises(ValueError, match="honoured"):
            validate(long)


LEAKS = re.compile(r"proposal_metadata|[{}\[\]]|\bother:|\b[a-z0-9]+(?:_[a-z0-9]+)+\b", re.I)


def test_printed_proposal_has_no_internal_keys(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-4"
    example(folder)
    path = folder / "proposal.json"
    value = json.loads(path.read_bytes())
    value["ideas"][1].update(
        family="other: first; futures funding",
        reason='`direction_reason`: Uses $funding_rate and open_interest. {"plain_summary": "x"}',
        input_columns=["$open_interest", "$close"],
    )
    value["refused"] = [
        {"name": "Old", "reason": "you dropped this idea in round 2", "dropped_in_round": 2}
    ]
    path.write_text(json.dumps(value))
    text = rdagent_discussion.proposal_text(tmp_path)
    lines = text.splitlines()
    # The wait and what happens on timeout come first.
    assert lines[0] == "RD-Agent proposes 2 ideas for round 4."
    assert lines[1].startswith("You have until 05:30 UTC (30 minutes). If you do not answer,")
    assert "   The agent's reason: Uses funding rate and open interest." in lines
    assert "   Data it plans to read: open interest, close." in lines
    assert "   Idea type: not classified, futures funding." in lines
    assert "Not offered again: Old. You dropped this idea in round 2." in text
    scanned = [line for line in lines if "--run-dir" not in line]
    assert [line for line in scanned if LEAKS.search(line)] == []


def test_names_and_numbers_mix_and_no_ideas_reads_plainly(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    text = rdagent_discussion.submit(
        tmp_path, "owner", ["Funding"], [], ["2=Use turnover"], [], None
    )
    assert "Build as proposed: Funding." in text and "Change: Volume." in text
    with pytest.raises(ValueError, match="named more than once"):
        rdagent_discussion.submit(tmp_path, "owner", ["Funding"], ["1"], [], [], None)
    empty = tmp_path / "empty"
    example(empty / "discussion/round-5")
    path = empty / "discussion/round-5/proposal.json"
    path.write_text(json.dumps({**json.loads(path.read_bytes()), "ideas": []}))
    first = rdagent_discussion.proposal_text(empty).splitlines()[0]
    assert first == "RD-Agent has no new ideas for round 5. You can add your own."


@pytest.mark.parametrize("policy", ["proceed", "stop"])
def test_timed_out_decision_says_what_the_run_did(tmp_path: Path, policy: str) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    selected = [{"name": "Funding"}] if policy == "proceed" else []
    record = {"reply": "none (timed out)", "policy": policy, "selected_tasks": selected}
    (folder / "decision.json").write_text(json.dumps(record))
    text = rdagent_discussion.proposal_text(tmp_path, last_decision=True)
    done = "built every idea as proposed" if policy == "proceed" else "stopped and built nothing"
    assert f"Nobody answered in time, so the run {done}." in text


def test_new_historical_factor_row_records_missing_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_rdagent_factor_eval import historical, import_command

    ledger, source = tmp_path / "trials.jsonl", tmp_path / "import.json"
    _, item = historical(tmp_path)
    source.write_text(json.dumps([item]))
    import_command(ledger, source, monkeypatch)
    row = json.loads(ledger.read_bytes())
    assert row["plain_summary"] is None and row["plain_summary_status"] == "missing"
