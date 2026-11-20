"""Review checks on readings for the ledger and Setup Lab: RD-Agent's ledger text, the setup
words' one home, the family-adjusted line, and the owner-text scan."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine import reading, setup_controls, setup_reading
from alpha_cli.spine.ledger import append_trial
from tests.unit._rdagent_support import judge_namespace
from tests.unit.test_reading_ledger_setup import assert_owner_text

REPO = Path(__file__).resolve().parents[2]
# sha256 and length of the proposer's ledger text for the fixed ledger below, measured on
# origin/main before readings: RD-Agent's words change later, separately.
RD_TEXT = ("9b965ca32bb545ac8a15b3b8d748415d7205cadcc1ea7509b864ff2e0dc48747", 1458)


def test_the_rdagent_proposer_ledger_text_is_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"factor_{i}",
            "status": status,
            "screen": {},
            "q": 0.5 + i / 10,
            "run_id": "r",
            "code_sha256": str(i),
            "family_size": 12,
            "screen_m": 12,
        }
        for i, status in enumerate(["SCREEN_FAIL", "SPREAD_FAIL", "FAILED", "CANDIDATE", "REPEAT"])
    ]
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    monkeypatch.setenv("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3")
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    context: dict[str, Any] = {"hypothesis_and_feedback": ""}
    judge_namespace()["append_ledger_context"](context, str(ledger), "synthetic", 0)
    text = context["hypothesis_and_feedback"]
    assert (hashlib.sha256(text.encode()).hexdigest(), len(text)) == RD_TEXT


def test_the_proposer_never_reads_the_spine_reader_or_its_words() -> None:
    source = (REPO / "workers/rdagent/alpha_factor_judge.py").read_text()
    assert "alpha_cli.spine" not in source and "machine_outcome" not in source


def test_the_setup_words_have_one_home() -> None:
    assert (
        "SETUP_WORDS ="
        not in (REPO / "apps/alpha-cli/src/alpha_cli/spine/trial_record.py").read_text()
    )
    assert reading.CLEAR not in reading.SETUP_WORDS
    spine = REPO / "apps/alpha-cli/src/alpha_cli/spine"
    for path in [*spine.glob("setup_*.py"), spine / "trial_record.py"]:
        for word in reading.SETUP_WORDS:
            assert f'"{word}"' not in path.read_text(), (path, word)


def test_a_stored_top_word_on_a_setup_never_prints() -> None:
    word, old = reading.setup_evidence_of({"outcome": "not supported", "evidence": reading.CLEAR})
    assert (word, old) == (reading.NOT_CLEAR, True)


def primary(n: Any, p: Any, excess: Any) -> dict[str, Any]:
    return {"occurrences": n, "trades": n, "random_date_p": p, "excess": excess}


# n, p, excess, labels -> study word, trade word
TRUTH = [
    (29, 0.0, 1.0, [], reading.TOO_LITTLE, reading.TOO_LITTLE),
    (30, 0.05, 1e-9, [], reading.SOME, reading.SOME),
    (30, 0.0501, 1.0, [], reading.NOT_CLEAR, reading.NOT_CLEAR),
    (30, 0.01, 0.0, [], reading.NOT_CLEAR, reading.NOT_CLEAR),
    (30, 0.01, 1.0, ["halves-disagree"], reading.NOT_CLEAR, reading.NOT_CLEAR),
    (30, 0.01, 1.0, ["no-random-control"], reading.SOME, reading.NOT_CLEAR),
    (30, float("nan"), 1.0, [], reading.NOT_CLEAR, reading.NOT_CLEAR),
    (30, 0.01, float("nan"), [], reading.NOT_CLEAR, reading.NOT_CLEAR),
]


@pytest.mark.parametrize(("n", "p", "excess", "labels", "study", "trade"), TRUTH)
def test_the_setup_truth_table(
    n: int, p: float, excess: float, labels: list[str], study: str, trade: str
) -> None:
    assert setup_controls.study_evidence(primary(n, p, excess), labels) == study
    assert setup_controls.trade_evidence(primary(n, p, excess), labels) == trade


def test_a_missing_number_never_makes_the_word_stronger() -> None:
    assert setup_controls.trade_evidence(primary(30, None, 1.0), []) == reading.NOT_CLEAR
    assert setup_controls.trade_evidence(primary(30, 0.01, None), []) == reading.NOT_CLEAR
    for value in (primary(30, None, 1.0), primary(30, 0.01, None), primary(None, 0.01, 1.0)):
        with pytest.raises(TypeError):  # a study without its number is a fault, not a word
            setup_controls.study_evidence(value, [])


def study_row(run_id: str, p: float | None, idea: str = "Gap fill") -> dict[str, Any]:
    return {
        "kind": "setup_study",
        "idea": idea,
        "assets": ["SPY"],
        "study_id": run_id,
        "run_id": run_id,
        "outcome": "not supported",
        "verdict": None,
        "labels": [],
        "random_date_p": p,
    }


def test_repeats_count_once_and_other_idea_texts_are_not_counted(tmp_path: Path) -> None:
    for row in (study_row("a", 0.01), study_row("b", 0.04), study_row("a", 0.01)):
        append_trial(tmp_path, row)
    append_trial(tmp_path, study_row("c", 0.001, idea="Gap fill v2"))
    family = setup_reading.family_context(tmp_path, "setup_study", "gap  FILL", "b")
    assert (family["studies"], family["position"]) == (2, 2)
    assert family["adjusted_random_date_p"] == pytest.approx(0.04)
    text = "\n".join(
        setup_reading.owner_lines(
            {"family": family, "evidence": reading.NOT_CLEAR, "old_wording": False}
        )
    )
    assert "adjusted for the 2 studies recorded for this idea (false-discovery method)" in text
    assert "Variants saved under another idea text are not counted." in text
    assert_owner_text(text)


def test_a_run_outside_the_family_gets_no_other_runs_figure(tmp_path: Path) -> None:
    append_trial(tmp_path, study_row("a", 0.01))
    family = setup_reading.family_context(tmp_path, "setup_study", "Gap fill", "zz")
    assert family["position"] is None and family["random_date_p"] is None
    assert family["adjusted_random_date_p"] is None
    text = "\n".join(setup_reading.owner_lines({"family": family, "evidence": reading.TOO_LITTLE}))
    assert "not among the 1 study recorded" in text and "not adjusted" in text


@pytest.mark.parametrize(
    "text",
    ["SPY  A  1.2", "SPY\tB\t0.4", "grade: C", "verdict B some evidence", "(D)", "F"],
)
def test_the_owner_text_scan_catches_a_lone_grade(text: str) -> None:
    with pytest.raises(AssertionError):
        assert_owner_text(text)


@pytest.mark.parametrize(
    "text", ["A result of 3 trades.", "Note. A random draw.", "graded A under the old rules"]
)
def test_the_owner_text_scan_spares_the_article_and_the_old_grade_phrase(text: str) -> None:
    assert_owner_text(text)
