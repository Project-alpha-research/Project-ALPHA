"""A draft must not invent numbers, hide qualifications or omit its trial count."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.results_cmds import results_app
from alpha_cli.spine.check import check_text
from tests.unit.test_spine_compare import A, B, make_lookup

TRIALS = f"quick; 12 [{A}:total_trials] trials."


def test_correct_answer(tmp_path: Path) -> None:
    result = check_text(f"Sharpe 0.8 [{A[:8]}:oos_sharpe]. {TRIALS}", make_lookup(tmp_path))
    assert result == {
        "ok": True,
        "checked_numbers": 2,
        "problems": [],
        "warnings": [],
        "cited_runs": [A],
    }


@pytest.mark.parametrize(
    "text,kind",
    [
        ("The Sharpe was 1.8", "UNTAGGED_NUMBER"),
        (f"1.8 [{A}:benchmark_sharpe]", "VALUE_NOT_COMPUTED"),
        (f"1.8 [{A}:oos_sharpe]", "VALUE_MISMATCH"),
        (f"0.8 [{A}:oos_sharpe]", "LABEL_OMITTED"),
        (f"quick 0.8 [{A}:oos_sharpe]", "TRIAL_COUNT_OMITTED"),
        ("1.8 [eeeeeeee:oos_sharpe]", "UNKNOWN_RUN"),
        (f"1.8 [{A}:invented_metric]", "UNKNOWN_METRIC"),
    ],
)
def test_problem_kinds(tmp_path: Path, text: str, kind: str) -> None:
    result = check_text("Introduction\n" + text, make_lookup(tmp_path))
    assert not result["ok"]
    problem = next(item for item in result["problems"] if item["kind"] == kind)
    assert problem["line"] == 2
    assert problem["excerpt"] == text
    assert problem["message"] and problem["next"]
    assert {"stored", "known"} <= problem.keys()
    if kind == "VALUE_NOT_COMPUTED":
        assert "no benchmark bars" in problem["message"]
    if kind == "UNKNOWN_METRIC":
        assert "oos_sharpe" in problem["known"]
    if kind == "VALUE_MISMATCH":
        assert problem["stored"] == {"value": 0.8, "rounded": "0.8"}


@pytest.mark.parametrize(
    "number,ok", [("75.5%", True), ("75.6%", False), ("+0.755", True), ("0.755×", False)]
)
def test_precision_percent_and_ratio(tmp_path: Path, number: str, ok: bool) -> None:
    result = check_text(f"{number} [{A}:full_sample_total_return]. {TRIALS}", make_lookup(tmp_path))
    assert result["ok"] is ok


def test_ignored_numbers_and_tagged_small_integers(tmp_path: Path) -> None:
    lookup = make_lookup(tmp_path)
    text = """```python
99.99
```
~~~
88.88
~~~
`window=200` and ``x=`22.2` ``
2026-11-14, 14 Nov 2026, 09:30:22, 2026, 9a99cb94971d54dc, deadbeef, 0xfeed1234
12. item
## 13) heading
3 flags, 2 assets, 0 and 10.
"""
    assert check_text(text, lookup)["checked_numbers"] == 0
    assert check_text(text, lookup)["ok"]
    result = check_text(f"1 [{A}:trades]. {TRIALS}", lookup)
    assert any(p["kind"] == "VALUE_MISMATCH" for p in result["problems"])
    assert not check_text("3.0 flags and 2%", lookup)["ok"]


def test_ambiguous_prefix(tmp_path: Path) -> None:
    lookup = make_lookup(tmp_path)
    original = tmp_path / "runs" / A
    other = tmp_path / "runs" / (A[:8] + "00000000")
    other.mkdir()
    (other / "manifest.json").write_bytes((original / "manifest.json").read_bytes())
    # Discover again after adding another completed run.
    from alpha_cli.results_cmds import fact_lookup

    lookup = fact_lookup(tmp_path)
    result = check_text(f"0.8 [{A[:8]}:oos_sharpe]", lookup)
    assert result["problems"][0]["kind"] == "AMBIGUOUS_RUN"
    assert len(result["problems"][0]["known"]) == 2


def test_compare_tags(tmp_path: Path) -> None:
    result = check_text(
        f"0.4 [{A}~{B}:oos_sharpe:diff], 1.5x [{A[:8]}~{B[:8]}:oos_sharpe:ratio]. {TRIALS}",
        make_lookup(tmp_path),
    )
    assert result["ok"]
    assert result["cited_runs"] == [A, B]
    assert result["checked_numbers"] == 3


def test_untagged_budget(tmp_path: Path) -> None:
    lookup = make_lookup(tmp_path)
    result = check_text("There were 22 observations and 33 events.", lookup, allow_untagged=1)
    assert not result["ok"]
    assert len(result["warnings"]) == len(result["problems"]) == 1
    assert check_text("There were 22 observations.", lookup, allow_untagged=1)["ok"]


def test_all_labels_and_trial_citation_must_be_visible(tmp_path: Path) -> None:
    lookup = make_lookup(tmp_path)

    def labelled(run_id: str, metric: str) -> dict[str, Any]:
        return {
            **lookup(run_id, metric),
            "labels": ["quick", "source-defaulted", "short-history", "no-diagnostics"],
        }

    result = check_text(
        f"0.8 [{A}:oos_sharpe] `quick source defaulted short history no diagnostics`\n"
        f"`12 [{A}:total_trials]`",
        labelled,
    )
    assert sum(p["kind"] == "LABEL_OMITTED" for p in result["problems"]) == 4
    assert any(p["kind"] == "TRIAL_COUNT_OMITTED" for p in result["problems"])
    assert check_text(f"{TRIALS} source defaulted; short history; no diagnostics", labelled)["ok"]


def test_check_cli_and_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_lookup(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    path = tmp_path / "answer.md"
    runner = CliRunner()
    missing = runner.invoke(results_app, ["check", str(path), "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.stdout)["error"]["code"] == "UNREADABLE_FILE"
    path.write_text(f"Sharpe 0.8 [{A}:oos_sharpe]. {TRIALS}")
    passed = runner.invoke(results_app, ["check", str(path), "--json"])
    assert passed.exit_code == 0 and json.loads(passed.stdout)["ok"]
    path.write_text(path.read_text().replace("0.8", "1.8"))
    failed = runner.invoke(results_app, ["check", str(path), "--json"])
    assert failed.exit_code == 1
    assert json.loads(failed.stdout)["problems"][0]["kind"] == "VALUE_MISMATCH"
    human = runner.invoke(results_app, ["check", str(path)])
    assert "not the reasoning" in human.stdout.splitlines()[-1]
    assert "VALUE_MISMATCH" in human.stdout


@pytest.mark.parametrize(
    "number,metric",
    [
        ("1,234", "trades"),
        ("+0.755", "full_sample_total_return"),
        ("0.7550000000000000", "full_sample_total_return"),
    ],
)
def test_number_tokens_are_not_mistaken_for_hex(tmp_path: Path, number: str, metric: str) -> None:
    lookup = make_lookup(tmp_path)
    assert check_text(f"Value {number} [{A}:{metric}]. {TRIALS}", lookup)["checked_numbers"] == 2
    assert check_text(f"Value {number} [{A}:{metric}]. {TRIALS}", lookup)["ok"]
    assert not check_text(f"Value {number}", lookup)["ok"]


def test_tagged_year_and_integer_at_line_start_are_checked(tmp_path: Path) -> None:
    lookup = make_lookup(tmp_path)
    result = check_text(f"2026 [{A}:trades]. {TRIALS}", lookup)
    assert result["problems"][0]["kind"] == "VALUE_MISMATCH"
    result = check_text(f"1234. [{A}:trades]. {TRIALS}", lookup)
    # A period separates a list ordinal from a tag; this is not a quoted value.
    assert result["checked_numbers"] == 1


def test_mismatch_next_step_names_the_cite_command(tmp_path: Path) -> None:
    result = check_text(f"quick 1.8 [{A}:oos_sharpe]. {TRIALS}", make_lookup(tmp_path))
    mismatch = next(p for p in result["problems"] if p["kind"] == "VALUE_MISMATCH")
    assert f"alpha results cite {A} oos_sharpe" in mismatch["next"]
