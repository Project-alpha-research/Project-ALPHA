"""`alpha report` and `alpha results cite` show readings, never a pass mark or a letter grade."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine.ledger import append_trial
from tests.unit.test_reading_rule import manifest as rule_manifest

RUNNER = CliRunner()
RUN = "ab" * 8
OLD_GRADE = re.compile(r"old grade(: [A-F])?")
# Standard trading terms stay allowed (profit factor, P&L, realized profit, take-profit).
# The scan looks for promise phrases, not the bare word "profit".
BANNED = re.compile(
    r"\b(supported|rejected|inconclusive|pass|passed|fail|failed|verdict|grade)\b"
    r"|will profit|profitable|profitability|make money|guaranteed",
    re.IGNORECASE,
)
LETTER = re.compile(r"(?<![\w'./-])[A-F](?![\w'./-])")


def assert_owner_text(text: str) -> None:
    text = OLD_GRADE.sub("", text)
    assert BANNED.search(text) is None, BANNED.search(text)
    assert LETTER.search(text) is None, LETTER.search(text)


def gauntlet(**over: Any) -> dict[str, Any]:
    """A synthetic gauntlet manifest: stored gates, nulls, an interval and the old letter grade."""
    base = rule_manifest(**over)
    base["command"] = "validate"
    base["verdict"] = {
        **base["verdict"],
        "edge": "B",
        "robustness": "B",
        "risk": "B",
        "sample": "B",
    }
    base["passed"] = True
    base["dsr"]["n_trials"] = 3
    base["spine"]["periods"]["scored"]["period"] = "scored"
    base["folds"] = [{"fold": 0}]
    for tier in base["nulls"]:
        tier.update(p_value=0.02, n_paths=1000, observed=0.75)
    base["outcomes"] = [
        {"name": "walk_forward_oos", "passed": True, "detail": {"sharpe": 0.75}},
        {"name": "randomized_price_null", "passed": True, "detail": {}},
        {"name": "bootstrap_ci", "passed": True, "detail": {}},
        {
            "name": "deflated_sharpe",
            "passed": True,
            "detail": {"psr": 0.995, "dsr": 0.99, "n_trials": 3.0},
        },
        {
            "name": "cpcv_oos",
            "passed": False,
            "detail": {"mean_sharpe": -0.1, "std_sharpe": 0.2, "frac_positive": 0.4},
        },
    ]
    base["cpcv"] = {"mean_sharpe": -0.1, "frac_positive": 0.4, "n_folds": 10, "passed": False}
    return base


def report(home: Path, manifest: dict[str, Any]) -> str:
    rdir = home / "runs" / RUN
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "manifest.json").write_text(json.dumps(manifest))
    result = RUNNER.invoke(app, ["report", RUN], env={"ALPHA_DATA_DIR": str(home)})
    assert result.exit_code == 0, result.output
    return result.output


def test_new_style_manifest_prints_the_stored_reading_word_and_the_old_grade(
    tmp_path: Path,
) -> None:
    stored = gauntlet()
    stored["reading"] = {
        "evidence": {"word": "some evidence", "because": []},
        "checks": [],
        "measures": [],
        "aim": {"source": "none", "basis": None, "rows": []},
        "counts": {},
        "sentence": "x",
    }
    text = report(tmp_path, stored)
    assert "reading: some evidence (old grade: B)" in text
    assert_owner_text(text)


def test_old_style_manifest_derives_the_word_on_read(tmp_path: Path) -> None:
    text = report(tmp_path, gauntlet())
    assert re.search(r"^reading: (clear of chance|some evidence) \(old grade: B\)$", text, re.M)
    assert_owner_text(text)


def test_a_fault_reads_as_fault(tmp_path: Path) -> None:
    broken = gauntlet()
    broken["oos_metrics"]["sharpe"] = None
    text = report(tmp_path, broken)
    assert "reading: fault (old grade: B)" in text
    assert "gate[walk_forward_oos]: fault" in text


def test_gates_show_numbers_and_plain_comparisons_not_a_pass_mark(tmp_path: Path) -> None:
    text = report(tmp_path, gauntlet())
    assert "null[returns_level]: percentile=0.9900 p=0.0200" in text
    assert "random data did as well in 2.0% of draws" in text
    assert "the level used by the old grade: 0.9500" in text
    assert "gate[walk_forward_oos]: sound, out-of-sample Sharpe 0.7500" in text
    assert "the interval is above zero" in text
    assert "deflated Sharpe 0.9900 after 3 tries" in text
    assert "mean Sharpe across folds -0.1000, 40% of folds above zero" in text
    assert_owner_text(text)


def test_an_old_manifest_with_only_a_grade_keeps_its_caveat_beside_it(tmp_path: Path) -> None:
    only = {
        "command": "validate",
        "verdict": {
            "overall": "C",
            "labels": ["too-few-trades"],
            "sentence": "Only 4 closed trades.",
        },
    }
    text = report(tmp_path, only)
    line = next(row for row in text.splitlines() if row.startswith("reading:"))
    assert "(old grade: C)" in line and "too-few-trades" in line and "Only 4 closed trades" in line


def test_monte_carlo_family_prints_percentiles_without_a_grade(tmp_path: Path) -> None:
    family = {
        "family": "iid_empirical",
        "status": "warning",
        "risk_grade": "D",
        "n_paths": 1000,
        "terminal_return_q05": -0.2,
        "terminal_return_q50": 0.05,
        "terminal_return_q95": 0.4,
        "maximum_drawdown_q50": 0.12,
        "maximum_drawdown_q95": 0.31,
        "loss_probability": {"point": 0.3, "lower": 0.27, "upper": 0.33},
    }
    text = report(
        tmp_path, {"command": "monte_carlo_classical", "status": "warning", "families": [family]}
    )
    assert "median_terminal=0.0500" in text and "drawdown_q95=0.3100" in text
    assert "terminal_5th=-0.2000" in text and "paths_below_zero=0.3000" in text
    assert_owner_text(text)


@pytest.mark.parametrize("metric", ["verdict", "evidence"])
def test_cite_prints_the_word_and_machines_keep_the_letter(tmp_path: Path, metric: str) -> None:
    rdir = tmp_path / "runs" / RUN
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps(gauntlet()))
    env = {"ALPHA_DATA_DIR": str(tmp_path)}
    append_trial(tmp_path, {"run_id": RUN, "test_id": "test", "labels": []})
    result = RUNNER.invoke(app, ["results", "cite", RUN, metric], env=env)
    text = result.output
    assert re.match(r"(clear of chance|some evidence)( \(old grade: B\))? \[", text), text
    assert ("(old grade: B)" in text) == (metric == "verdict")
    assert_owner_text(re.sub(r"\[\w+:\w+\]", "", text))  # the citation tag names the metric
    out = RUNNER.invoke(app, ["results", "cite", RUN, metric, "--json"], env=env).stdout
    fact = json.loads(out)
    assert fact["value"] in ({"B"} if metric == "verdict" else {"some evidence", "clear of chance"})


def test_the_card_text_scan_is_live() -> None:
    for bad in ("gate[x]: PASS", "grade: C", "verdict: FAIL", "reading: some evidence (C)"):
        with pytest.raises(AssertionError):
            assert_owner_text(bad)
    assert copy.deepcopy(OLD_GRADE.pattern)


def test_realized_profit_shows_as_gain_or_loss_while_the_stored_text_is_untouched(
    tmp_path: Path,
) -> None:
    from alpha_cli.spine.facts import plain_basis

    assert (
        plain_basis("full-sample closed-trade realized profit")
        == "full-sample closed-trade realized gain or loss"
    )
    assert plain_basis("no such words") == "no such words"
