"""Small wording fixes of the third sweep (item 7)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.results_summary import summary_lines


def _cli(home: Path, *args: str) -> tuple[int, str]:
    out = CliRunner().invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    return out.exit_code, out.output


def test_idea_new_takes_the_bare_text_as_the_claim(tmp_path: Path) -> None:
    code, text = _cli(tmp_path, "idea", "new", "Gaps fill by noon", "--json")
    assert code == 0, text
    identity = json.loads(text)["id"]
    code, shown = _cli(tmp_path, "idea", "show", identity)
    assert code == 0 and "Gaps fill by noon" in shown
    _, plain = _cli(tmp_path, "idea", "new", "Gaps fill by noon")
    assert "--idea-card" in plain


def test_idea_new_refuses_the_claim_given_twice(tmp_path: Path) -> None:
    code, text = _cli(tmp_path, "idea", "new", "one", "--claim", "two")
    assert code != 0 and "given twice" in text


def test_results_show_glosses_the_inverted_sharpe_and_the_two_counts() -> None:
    run = {
        "run_id": "r1",
        "facts": [{"metric": "inverted_sharpe", "value": 0.3}],
        "audit": [{"status": "flagged"}, {"status": "flagged"}, {"status": "ok"}],
        "flags": [{"x": 1}, {"x": 2}, {"x": 3}],
    }
    text = "\n".join(summary_lines(run))
    assert "inverted sharpe: 0.3 (Sharpe ratio of the opposite rule" in text
    assert "counted apart" in text


def test_no_message_says_uv_run_alpha() -> None:
    root = Path(__file__).resolve().parents[2] / "apps" / "alpha-cli" / "src"
    offenders = [p.name for p in root.rglob("*.py") if "uv run alpha" in p.read_text("utf-8")]
    assert offenders == []


def test_follow_start_with_a_wrong_id_says_which_id_it_wants(tmp_path: Path) -> None:
    code, text = _cli(tmp_path, "follow", "start", "--test", "deadbeef")
    assert code != 0
    assert "RUN column" in text and "--test wants a run id" in text.replace("`", "")


def test_tool_run_takes_the_run_id_with_the_run_option(tmp_path: Path) -> None:
    both = _cli(tmp_path, "tool", "run", "some-tool", "abc", "--run", "abc")
    assert both[0] != 0 and "Name the run once" in both[1]
    neither = _cli(tmp_path, "tool", "run", "some-tool")
    assert neither[0] != 0 and "Name the run once" in neither[1]
    named = _cli(tmp_path, "tool", "run", "some-tool", "--run", "abc")
    assert "Name the run once" not in named[1]
