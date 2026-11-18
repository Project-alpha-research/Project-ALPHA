"""Exercise both sides of the file contract without a running worker."""

from __future__ import annotations

import ast
import json
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
                "deadline": "2026-11-18T05:30:00+00:00",
                "ideas": [
                    {
                        "name": name,
                        "plain_summary": summary,
                        "family": family,
                        "declared_direction": direction,
                        "primary_clock": "weekly",
                        "reason": reason,
                    }
                    for name, summary, family, direction, reason in [
                        (
                            "Funding",
                            "Cheaper funding may precede a rise.",
                            "funding",
                            -1,
                            "Buyers pay less to hold.",
                        ),
                        (
                            "Volume",
                            "Rising volume may precede a rise.",
                            "volume",
                            1,
                            "Demand may persist.",
                        ),
                    ]
                ],
            }
        )
    )


EXPECTED = """RD-Agent proposes 2 ideas for round 10.
It builds nothing until you answer or the wait ends.

1. Funding
   Cheaper funding may precede a rise.
   It expects coins with lower numbers to earn more over the next 7 days.
   Idea family: funding.
   The agent's reason: Buyers pay less to hold.

2. Volume
   Rising volume may precede a rise.
   It expects coins with higher numbers to earn more over the next 7 days.
   Idea family: volume.
   The agent's reason: Demand may persist.

It waits until 2026-11-18 05:30 UTC. If you do not answer, it builds every idea as proposed.

To answer, run:
  alpha ledger reply --run-dir {run} --as owner
Ideas you do not name are built as proposed. Add --drop NAME to skip one,
--revise "NAME=what to change" to ask for a change, or --idea "your idea" to add
your own (two at most). A stand-in answers with --as stand-in instead.
"""


def test_commands(tmp_path: Path) -> None:
    runner = CliRunner()
    example(tmp_path / "discussion/round-2")
    folder = tmp_path / "discussion/round-10"
    example(folder)
    args = ["--run-dir", str(tmp_path)]
    result = runner.invoke(ledger_app, ["proposal", *args])
    assert result.exit_code == 0, result.output
    assert result.output == EXPECTED.format(run=tmp_path)
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
            "Volume=Use turnover",
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
        "Drop: none.\n"
        "Ask the agent to change: Volume.\n"
        "Your own ideas: 1.\n"
        "Your note goes to the agent with the next round.\n"
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
    assert result.exit_code != 0 and "already has an answer" in result.output


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
        wanted = {"summary_fields", "validate_reply", "USER_TEXT_LIMIT"}
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
    assert len(worker) == 3 and worker == cli


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
    assert result["origin"] == "user" and result["author"] == "owner"
