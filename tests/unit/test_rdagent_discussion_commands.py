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
   Idea type: new (not one of the known types).
   The agent's reason: not recorded.
   Data it plans to read: not recorded.

Model budget left in this run: 6 chat calls, $10.00.
Idea types closed after repeated failed tries: ease of trading.
{caution}

To answer, run:
  alpha ledger reply --run-dir {run} --as owner
Then add what you want to change. Name an idea by its number or its name:
  --drop 1                      do not build idea 1 (add =reason to say why)
  --revise "1=what to change"   ask the agent to change idea 1
  --idea "your idea"            add your own idea (two at most)
  --note "text"                 guide the next proposal
A note guides the agent's next proposal. The agent does not answer questions.
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
        "A note guides the agent's next proposal. The agent does not answer questions.\n"
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
    from alpha_core import DataError

    assert row(origin="user", agent_choices=["Used one day."])["agent_choices"] == ["Used one day."]
    with pytest.raises(DataError, match="agent_choices"):
        row(origin="user", agent_choices=["x" * 201])
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
                "reply_to_proposal_seconds": [240],
                "rounds_total": 12,
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
    assert "How much the price moves for a given amount traded." in result.output


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
        + "; ".join(list(rdagent_discussion.FAMILY_WORDS)[:7])
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
    assert "   Idea type: new (not one of the known types), futures funding." in lines
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


def test_results_follow_built_round_even_after_skipped_round(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-2"
    example(folder)
    names = ["Old", "Leak", "Pass"]
    record = {
        "selected_tasks": [{"name": n} for n in names],
        "replacements": [
            {"name": "Pass", "user_idea": "Use carry.", "agent_choices": ["Used one day."]}
        ],
    }
    (folder / "decision.json").write_text(json.dumps(record))
    text = rdagent_discussion.proposal_text(tmp_path, last_decision=True)
    assert "Results are not ready." in text
    assert "Choices the agent made for you:\n   - Used one day." in text
    factors = [
        {"name": n, "discussion_round": 2, "status": v}
        for n, v in zip(names, ["SCREEN_FAIL", "LOOKAHEAD", "CANDIDATE"], strict=True)
    ]
    (tmp_path / "evaluations.jsonl").write_text(
        json.dumps({"iteration": 0, "factors": factors}) + "\n"
    )
    for pending in (False, True):
        if pending:
            example(tmp_path / "discussion/round-3")
        for last in (False, True):
            text = rdagent_discussion.proposal_text(tmp_path, last_decision=last)
            for line in (
                "Old: failed the quick test (the result could easily be luck).",
                "Leak: used information from the future, so the result is void.",
                "Pass: passed the quick test; it goes on to the stricter checks.",
            ):
                assert line in text


@pytest.mark.parametrize("state", ["building", "applying", "evaluating"])
def test_final_round_estimate_uses_median_reply_to_results(tmp_path: Path, state: str) -> None:
    folder = tmp_path / "discussion/round-2"
    example(folder)
    (folder / "decision.json").write_text(json.dumps({"selected_tasks": [{"name": "Funding"}]}))
    path = folder.parent / "status.json"
    for durations, estimate in (([], "several minutes"), ([720, 960], "about 14 minutes")):
        path.write_text(
            json.dumps(
                {
                    "state": state,
                    "round": 2,
                    "rounds_total": 3,
                    "build_seconds": [1020],
                    "reply_to_results_seconds": durations,
                    "reply_to_proposal_seconds": [60],
                }
            )
        )
        assert (
            f"This is the last round. Results usually appear in {estimate}."
            in rdagent_discussion.proposal_text(tmp_path)
        )


def test_usage_uses_run_counters_instead_of_step_labels(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    path = folder / "proposal.json"
    value = json.loads(path.read_bytes())
    value["remaining"].update(chat_used=31, chat_cap=60, embedding_used=253, embedding_cap=2000)
    value["refused_proposals"] = [{"names": ["Noisy"], "reasons": ["the idea type is closed"]}]
    value["reask_calls"] = 2
    path.write_text(json.dumps(value))
    text = rdagent_discussion.proposal_text(tmp_path)
    assert "31 of 60 chat calls" in text and "253 of 2000 embedding calls" in text
    assert (
        "ALPHA refused the agent's first proposal for this round (the idea type is closed). "
        "The agent asked again; this used 2 of the run's chat calls."
    ) in text


def test_family_meanings_match_worker_and_glossary() -> None:
    glossary = (Path(__file__).resolve().parents[2] / "docs/reference/glossary.md").read_text()
    for key, words in rdagent_discussion.FAMILY_WORDS.items():
        assert discussion.family_words(key) == words
        assert f"| {key} | {words[0]} | {words[1]} |" in glossary
    for key in ("other: lower_shadow", "unknown"):
        assert discussion.family_words(key) == rdagent_discussion.family_words(key)
    assert discussion.NAMED_TYPE in glossary and " | ".join(discussion.UNKNOWN_TYPE) in glossary
    # Run 8 stored these families; an open unmatched name reads as new, a closed one by its name.
    assert rdagent_discussion.plain_family("other: first") == "new (not one of the known types)"
    assert rdagent_discussion.plain_family("other: lower_shadow", closed=True) == (
        'ideas named "lower shadow"'
    )
    assert rdagent_discussion.plain_family("unknown", closed=True) == "ideas of no known type"
    assert rdagent_discussion.plain_family("drawdown") == "fall from a previous high"


def test_final_usage_counts_only_charged_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.unit.test_rdagent_factor_launch import args, launch

    job = launch.Launch(
        args(tmp_path, "--discuss"),
        {"ALPHA_RDAGENT_SOURCE": tmp_path, "ALPHA_FACTOR_PYTHON": tmp_path / "a/b/c/python"},
    )
    job.run.mkdir()
    counter = {"counted_calls": 31, "local_embedding_calls": 251, "provider_embedding_calls": 2}
    monkeypatch.setattr(job, "gateway_status", lambda: {"this_run": counter})
    job.finish(0, "completed")
    text = f"31 of {job.args.run_max_calls} chat calls, 253 of 2000 embedding calls."
    assert text in capsys.readouterr().out
    assert text in rdagent_discussion.proposal_text(job.run)


def test_old_identical_decisions_do_not_borrow_a_previous_verdict(tmp_path: Path) -> None:
    record = {
        "selected_tasks": [{"name": "Carry"}],
        "reply": "none (timed out)",
        "policy": "proceed",
    }
    for n in (0, 1):
        folder = tmp_path / f"discussion/round-{n}"
        example(folder)
        (folder / "decision.json").write_text(json.dumps(record))
    (tmp_path / "rounds.jsonl").write_text(
        json.dumps({"iteration": 0, "feedback": {}, "discussion": record}) + "\n"
    )
    (tmp_path / "evaluations.jsonl").write_text(
        json.dumps({"iteration": 0, "factors": [{"name": "Carry", "status": "LOOKAHEAD"}]}) + "\n"
    )
    text = rdagent_discussion.proposal_text(tmp_path, last_decision=True)
    assert "Results are not ready." in text and "result is void" not in text


def test_stricter_check_failure_is_reported(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    (folder / "decision.json").write_text(json.dumps({"selected_tasks": [{"name": "Carry"}]}))
    (tmp_path / "evaluations.jsonl").write_text(
        json.dumps(
            {
                "iteration": 0,
                "factors": [{"name": "Carry", "discussion_round": 0, "status": "REPLAY_FAIL"}],
            }
        )
        + "\n"
    )
    text = rdagent_discussion.proposal_text(tmp_path, last_decision=True)
    assert "failed the trading test with costs" in text.lower()


def test_active_evaluation_waits_for_publication(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-2"
    example(folder)
    (folder / "decision.json").write_text(json.dumps({"selected_tasks": [{"name": "Carry"}]}))
    (folder.parent / "status.json").write_text(
        json.dumps({"state": "evaluating", "round": 2, "rounds_total": 3})
    )
    path = tmp_path / "evaluations/iter-1/result.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"iteration":1')
    assert "Results are not ready." in rdagent_discussion.proposal_text(
        tmp_path, last_decision=True
    )


def test_every_ledger_verdict_has_one_plain_result_line() -> None:
    from alpha_cli._rdagent_judge import STATUSES
    from alpha_cli.rdagent_journey_words import discussion_outcome

    for status in sorted(STATUSES):
        line = discussion_outcome({"status": status, "screen": {}})
        assert line[0].islower() and line.endswith(".") and "profit" not in line
    assert discussion_outcome({"status": "CANDIDATE"}) == (
        "passed the quick test; it goes on to the stricter checks."
    )
    assert discussion_outcome({"status": "LOOKAHEAD"}).endswith("so the result is void.")
    assert discussion_outcome({"status": "NEW_VALUE"}) == "result not recorded."
    assert discussion_outcome({}) == "result not recorded."


def test_degenerate_result_names_only_the_screen_causes() -> None:
    from alpha_cli.rdagent_journey_words import discussion_outcome, outcome, quick_verdicts

    screen: dict[str, Any] = {"tie_share": 0.54, "coverage": 0.42, "all_tied_day_share": 0}
    row: dict[str, Any] = {"status": "DEGENERATE", "screen": screen}
    # Tie share does not decide the screen, so it is never given as the reason.
    expected = "Only 42% of coin-days had a value, so the coins could not be ranked."
    assert outcome(row) == expected
    assert discussion_outcome(row) == expected[0].lower() + expected[1:]
    assert quick_verdicts(row) == [expected]
    assert "tied" not in outcome(row)
    screen["all_tied_day_share"] = 0.2
    assert outcome(row) == (
        "Only 42% of coin-days had a value and all coins were tied on 20% of days, "
        "so the coins could not be ranked."
    )
    row["screen"] = {"all_tied_day_share": 0.0}
    assert "0%" not in outcome(row)
    row["screen"] = {"reason": "IC has no usable variation", "coverage": 1.0}
    assert "variation" in outcome(row) and "100%" not in outcome(row)


def test_reply_help_and_final_note(tmp_path: Path) -> None:
    runner = CliRunner()
    folder = tmp_path / "discussion/round-2"
    example(folder)
    (folder.parent / "status.json").write_text(
        json.dumps({"round": 2, "rounds_total": 3, "state": "waiting"})
    )
    help_text = runner.invoke(ledger_app, ["reply", "--help"]).output
    assert "The agent does not answer" in help_text
    result = runner.invoke(
        ledger_app,
        ["reply", "--run-dir", str(tmp_path), "--as", "owner", "--note", "Look at funding next"],
    )
    assert result.exit_code == 0, result.output
    assert result.output == (
        "Your answer for round 2 is saved. RD-Agent reads it within seconds.\n"
        "Answered by: the owner.\n"
        "Build as proposed: Funding, Volume.\n"
        "Note to the agent: Look at funding next.\n"
        "A note guides the agent's next proposal. The agent does not answer questions.\n"
        "This is the last round, so the note will not be used.\n"
        "Saved in discussion/round-2/reply.json.\n"
    )
    assert (
        json.loads((folder / "reply.json").read_bytes())["note_to_agent"] == "Look at funding next"
    )


def test_decision_prints_revision_choices_and_gate_warning(tmp_path: Path) -> None:
    folder = tmp_path / "discussion/round-0"
    example(folder)
    record = {
        "selected_tasks": [{"name": "Carry"}],
        "replacements": [
            {
                "name": "Carry",
                "revised_from": "Funding",
                "honoured": ["Kept cheaper coins.; ", "Used the monthly payment."],
                "not_honoured": ["Costs were unavailable;"],
                "agent_choices": ["Used Monday.", "Kept the old price condition. "],
                "uses_gate": True,
                "last_tries": [{"family": "futures funding", "failed": 2, "limit": 3}],
            }
        ],
    }
    (folder / "decision.json").write_text(json.dumps(record))
    assert rdagent_discussion.decision_text(folder) == (
        "Last decision, round 0:\n"
        "Built: Carry.\n"
        "Changed Funding into Carry, as you asked.\n"
        "   What the agent changed:\n"
        "   - Kept cheaper coins.\n"
        "   - Used the monthly payment.\n"
        "   What the agent did not do, and why:\n"
        "   - Costs were unavailable.\n"
        "   Choices the agent made for you:\n"
        "   - Used Monday.\n"
        "   - Kept the old price condition.\n"
        "   This idea still uses an on/off condition. "
        "It may have a value on too few days to rank coins.\n"
        "   This idea type has failed 2 of 3 tries. "
        "If this idea fails, the type is closed for later rounds.\n"
        "Results are not ready."
    )


def test_decision_validates_gate_as_a_boolean() -> None:
    for validate in (discussion.validate_decision, rdagent_discussion.validate_decision):
        record = {"selected_tasks": [], "replacements": [{"name": "Carry", "uses_gate": "true"}]}
        with pytest.raises(ValueError, match="uses_gate"):
            validate(record)


def test_proposal_estimate_never_borrows_results_duration() -> None:
    status = {"round": 1, "rounds_total": 3, "reply_to_results_seconds": [105]}
    assert "in a few minutes." in rdagent_discussion.time_estimate(status)
    assert "in about 7 minutes." in rdagent_discussion.time_estimate(
        {**status, "reply_to_proposal_seconds": [360, 420, 1050]}
    )


def test_coding_usage_splits_chat_and_embedding_rows(tmp_path: Path) -> None:
    example(tmp_path / "discussion/round-0")
    (tmp_path / "receipt.json").write_text(
        json.dumps(
            {
                "discussion_usage": {
                    "chat_used": 20,
                    "chat_cap": 60,
                    "embedding_used": 266,
                    "embedding_cap": 2000,
                }
            }
        )
    )
    calls = [
        {"step": step, "endpoint": endpoint}
        for step, endpoint, count in (
            ("coding", "/v1/chat/completions", 16),
            ("coding", "/v1/embeddings", 266),
            ("feedback", "/v1/chat/completions", 4),
        )
        for _ in range(count)
    ]
    (tmp_path / "calls-labelled.jsonl").write_text("".join(json.dumps(row) + "\n" for row in calls))
    text = rdagent_discussion.proposal_text(tmp_path)
    assert "20 of 60 chat calls, 266 of 2000 embedding calls." in text
    assert "During coding: 16 chat requests and 266 embedding requests." in text
