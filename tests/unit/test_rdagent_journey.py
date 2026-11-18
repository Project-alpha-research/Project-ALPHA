"""Exercise the registered command over two judged ideas, without executing their code."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli._rdagent_judge import STATUSES
from alpha_cli.main import app

FEEDBACK = "Orders were expensive. Fewer trades might help. Check the slow version next."


def make_run(base: Path) -> tuple[Path, list[dict[str, Any]]]:
    run = base / "runs" / "synthetic"
    (run / "code").mkdir(parents=True)
    rows = []
    rounds = []
    for i, status in enumerate(("SCREEN_FAIL", "REPLAY_FAIL")):
        code = f"import math\nx = close - {i}\nscore = x / close\nraise RuntimeError('never run')\n"
        digest = hashlib.sha256(code.encode()).hexdigest()
        (run / "code" / f"{digest}.py").write_text(code)
        screen = {
            "status": "OK",
            "mean_ic": -0.01234567,
            "effective_n": 18.7654,
            "p": 0.43 if i == 0 else 0.00031,
            "coverage": 0.97865,
        }
        trial = {
            "status": status,
            "screen": screen,
            "p": screen["p"],
            "spread": {"mean_spread": 0.00345, "status": "PASS"},
            "replay": {"net": {"annualized_return": -0.0345678}, "mean_turnover": 0.12345678}
            if i
            else {},
        }
        row = {
            "iteration": i,
            "name": "score",
            "code_sha256": digest,
            "status": status,
            "run_id": run.name,
            "trial_index": i + 1,
            "schema": "AlphaRdagentFactorTrialV3",
            "stage": "replay" if i else "screen",
            "panel_sha256": "c" * 64,
            "primary_clock": "weekly",
            "declared_direction": -1,
            "direction_reason": "Lower scores should recover.",
            "description": "Look for a recovery.\ndeclared_direction: -1\nprimary_clock: weekly",
            "screen_rule": "alpha-investing-simple-1",
            "screen_cutoff": 0.01234,
            "screen_m": 17,
            "clocks": {"weekly": trial, "daily": {"screen": {"mean_ic": 999}}},
            "lookahead": {"status": "PASS", "cuts": [{"cut": "2022-04-04", "status": "PASS"}]},
            "shortlist": False,
            "label": "exploratory, not admitted, not yet confirmed",
            "instruments": ["TEST-A", "TEST-B"],
            "survivorship": "survivors only",
            "windows": {
                "exploration": ["2022-02-01", "2023-12-20"],
                "panel_end": "2023-12-31",
                "reserved_start": "2024-01-01",
            },
        }
        folder = run / "evaluations" / f"iter-{i}"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"iteration": i, "factors": [row]}))
        rounds.append(
            {
                "iteration": i,
                "tasks": [{"name": "score", "code_sha256": digest}],
                "feedback": {"observations": FEEDBACK},
            }
        )
        rows.append(row)
    (run / "rounds.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rounds))
    return run, rows


def test_journeys_from_stored_evidence(tmp_path: Path) -> None:
    run, rows = make_run(tmp_path)
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    result = CliRunner().invoke(app, ["ledger", "journey", "--run-dir", str(run)])
    assert result.exit_code == 0, result.output or repr(result.exception)
    root = run / "journey"
    index = json.loads((root / "index.json").read_text())["ideas"]
    assert len(index) == 2
    for entry, row in zip(index, rows, strict=True):
        key = {k: row[k] for k in ("iteration", "name", "code_sha256")}
        assert entry == {**key, "folder": f"{row['iteration']}-score-{row['code_sha256'][:8]}"}
        story = json.loads((root / entry["folder"] / "journey.json").read_text())
        assert {k: story[k] for k in key} == key
        idea, code, peek, quick, trading, feedback, limits = story["steps"]
        for step in story["steps"]:
            assert {
                "title",
                "who",
                "text",
                "numbers",
                "figure",
                "what_this_means",
                "source",
            } <= step.keys()
            assert step["who"] in {"ALPHA rule", "RD-Agent (AI)"}
            assert len(step["numbers"]) <= 3
            assert step["source"] and step["what_this_means"]
        assert "declared_direction" not in idea["text"]
        assert "Look for a recovery." in idea["own_words"]
        assert "score = x / close" in code["code"] and "raise RuntimeError" not in code["code"]
        assert "1" in peek["text"]
        trial = row["clocks"]["weekly"]
        assert [n["value"] for n in quick["numbers"]] == [
            trial["screen"][k] for k in ("mean_ic", "p", "effective_n")
        ]
        assert "0.617%" in quick["text"]
        assert feedback["own_words"] == FEEDBACK
        assert "Orders were expensive. Fewer trades might help." in feedback["text"]
        assert "Check the slow" not in feedback["text"]
        assert limits["numbers"][0]["value"] == row["screen_m"]
        assert all(
            story["figures"][name]["reason"]
            for name in ("signal", "quick-test", "over-time", "trading-test", "how-many-ideas")
        )
        if row["stage"] == "screen":
            assert "no trading test" in trading["text"].lower() and not trading["numbers"]
        else:
            assert [n["value"] for n in trading["numbers"]] == [
                trial["spread"]["mean_spread"],
                trial["replay"]["net"]["annualized_return"],
                trial["replay"]["mean_turnover"],
            ]
    assert before == {
        p: p.read_bytes() for p in run.rglob("*") if p.is_file() and root not in p.parents
    }


def test_status_wording_covers_judge() -> None:
    from alpha_cli.rdagent_journey_words import outcome

    for status in STATUSES:
        assert outcome({"status": status}) and "recorded " + status.lower() != outcome(
            {"status": status}
        )
    with pytest.raises(ValueError, match="status"):
        outcome({"status": "NEW_UNEXPLAINED_STATE"})


def test_output_cannot_follow_a_journey_symlink(tmp_path: Path) -> None:
    run, _ = make_run(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (run / "journey").symlink_to(elsewhere, target_is_directory=True)
    result = CliRunner().invoke(app, ["ledger", "journey", "--run-dir", str(run)])
    assert result.exit_code != 0
    assert not list(elsewhere.iterdir())


def test_limits_and_prefix_wording() -> None:
    from alpha_cli import rdagent_journey_words as words
    from alpha_cli.rdagent_exposure import SEVERITY

    for state in {*SEVERITY, "no exposure log"}:
        row = {
            "status": "SCREEN_FAIL",
            "eligibility": "perp-funding",
            "exposure": {"worst_status": state},
        }
        facts = " ".join(words.limits_step(row, {}, [])["facts"])
        assert words.EXPOSURE[state] in facts and "funding" in facts
    for kind in ("NOT_RUN", "PASS", "LOOKAHEAD", "UNSTABLE", "ERROR"):
        message = words.peek_step({"lookahead": {"status": kind}}, [])["text"]
        assert words.PEEK[kind] in message and "not recorded" in message
    assert "includes coins that later stopped trading" in " ".join(
        words.limits_step({"status": "REPLAY_FAIL", "universe_includes_delisted": True}, {}, [])[
            "facts"
        ]
    )


def test_archive_filter_and_legacy_daily_replay(tmp_path: Path) -> None:
    run, rows = make_run(tmp_path)
    row = rows[-1]
    row["name"] = "archived"
    del row["primary_clock"]
    row["replay"] = row.pop("clocks")["weekly"]["replay"]
    row["schema"] = "AlphaRdagentFactorTrialV2"
    folder = run / "evaluations/iter-1"
    (folder / "result.json").unlink()
    (run / "evaluations.jsonl").write_text(json.dumps({"iteration": 1, "factors": [row]}) + "\n")
    result = CliRunner().invoke(
        app, ["ledger", "journey", "--run-dir", str(run), "--factor", "archived"]
    )
    assert result.exit_code == 0, repr(result.exception)
    index = json.loads((run / "journey/index.json").read_text())["ideas"]
    assert len(index) == 2 and not (run / "journey" / index[0]["folder"]).exists()
    story = json.loads((run / "journey" / index[1]["folder"] / "journey.json").read_text())
    assert all(n["value"] is None for n in story["steps"][3]["numbers"])
    trading = story["steps"][4]
    assert "daily" in trading["text"] and trading["numbers"][0]["value"] == -0.0345678
    assert story["steps"][5]["own_words"] == "not recorded"


def test_counted_only_replay_and_reserved_summary(tmp_path: Path) -> None:
    run, rows = make_run(tmp_path)
    row = rows[1]
    trial = row["clocks"]["weekly"]
    trial["replay"]["counted_only"] = "spread failure"
    row["status"] = "SPREAD_FAIL"
    path = run / "evaluations/iter-1/result.json"
    record = {"iteration": 1, "factors": [row]}
    path.write_text(json.dumps(record))
    args = ["ledger", "journey", "--run-dir", str(run)]
    assert CliRunner().invoke(app, args).exit_code == 0
    manifest = next((run / "journey").glob("1-*/journey.json"))
    old = manifest.read_bytes()
    assert [n["value"] for n in json.loads(old)["steps"][4]["numbers"]] == [
        trial["spread"]["mean_spread"]
    ]
    row["windows"]["panel_end"] = "2024-01-01"
    path.write_text(json.dumps(record))
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0 and "reserved" in str(result.exception)
    assert manifest.read_bytes() == old


def test_multiline_code_excerpt_keeps_assignment_and_fallback_limit(tmp_path: Path) -> None:
    from alpha_cli.rdagent_journey import _snippet

    code = tmp_path / "program.py"
    code.write_text("result['score'] = (\n    a\n    + b\n    + c\n)\n")
    snippet = _snippet(code, "score")
    assert snippet.startswith("result['score'] =") and len(snippet.splitlines()) <= 3
    lines = [f"x{i} = {i}" for i in range(15)]
    code.write_text("from pkg import (\n    value,\n)\n" + "\n".join(lines))
    assert _snippet(code, "score").splitlines() == lines[:12]


def test_older_records_fall_back_to_the_lead_clock_and_screen_direction() -> None:
    from alpha_cli import rdagent_journey_words as words

    row = {
        "lead_clock": "daily",
        "status": "SCREEN_FAIL",
        "clocks": {"daily": {"screen": {"direction": 1}}},
    }
    assert words.clock_of(row) == "daily" and words.direction_of(row) == 1
    assert words.clock_of({**row, "primary_clock": "weekly"}) == "weekly"
    text = words.idea_step(row, {}, [])["text"]
    assert "chosen after seeing these years" in text
    assert words.NO_TRADING_TEST in words.trading_step(row, {}, [])["text"]
