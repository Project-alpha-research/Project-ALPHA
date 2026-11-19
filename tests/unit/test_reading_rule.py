"""Rule tests give a reading in context, not a grade: builder, manifest and owner text."""

import copy
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.spine import reading
from tests.fixtures.cli_fixtures import seed_store

# Ids of the seeded synthetic run below, taken BEFORE the reading existed; it must change none.
# A run id hashes every alpha_cli source byte, so any edit moves it. The test holds that one input
# fixed, so only the reading could move an id.
PINNED_RUN_ID = "8f301ae2e5debf9a"
PINNED_TEST_ID = "fdd2adbd8f795cb9"
PINNED_IDEA_ID = "086e65226d0ce566"
PINNED_VERDICT = "C"
FORBIDDEN_WORDS = re.compile(r"\b(supported|rejected|pass|fail|profit)\b", re.IGNORECASE)
LETTER_GRADE = re.compile(r"(?<![\w'./-])[A-F](?![\w'./-])")


def manifest(**over: Any) -> dict[str, Any]:
    """A synthetic stored rule-test manifest where every evidence check holds."""
    base: dict[str, Any] = {
        "oos_metrics": {"sharpe": 0.75, "max_drawdown": -0.1, "risk_of_ruin": 0.0},
        "nulls": [
            {"tier": "returns_level", "passed": True, "percentile": 0.99, "threshold": 0.95},
            {"tier": "full_engine", "passed": True, "percentile": 0.98, "threshold": 0.95},
        ],
        "cis": [
            {"metric": "sharpe", "point": 0.75, "lower": 0.2, "upper": 1.3, "confidence": 0.95}
        ],
        "dsr": {
            "dsr": 0.99,
            "psr": 0.995,
            "passed": True,
            "threshold": 0.95,
            "n_trials": 1,
            "family_id": "spine:ma_cross",
        },
        "cpcv": {"mean_sharpe": 0.7, "passed": True},
        "verdict": {
            "overall": "B",
            "n_trials": 1,
            "detail": {"sample_n_oos": 1200.0},
            "labels": [],
        },
        "data_health": {"verdict": "pass"},
        "spine": {
            "labels": ["quick"],
            "periods": {
                "scored": {
                    "price_basis": "with dividends",
                    "benchmark": {"sharpe": 0.78},
                    "strategy": {"trades": 80},
                }
            },
        },
    }
    merged = copy.deepcopy(base)
    for key, value in over.items():
        merged[key] = value
    return merged


def test_the_four_words_have_fixed_definitions() -> None:
    assert list(reading.WORDS) == [
        "clear of chance",
        "some evidence",
        "not clear of chance",
        "too little to read",
    ]
    assert all(reading.WORDS.values())


CLEAN: dict[str, Any] = {"plausibility": []}


def test_below_buy_and_hold_reads_below_the_aim_with_no_positive_word() -> None:
    value = manifest()
    value["cis"][0].update(lower=0.1, upper=0.7)
    result = reading.build_reading(value, CLEAN)
    row = result["aim"]["rows"][0]
    assert result["schema"] == "AlphaReadingV1"
    assert result["aim"]["source"] == "default"
    assert (row["aim"], row["observed"], row["relation"]) == (
        pytest.approx(0.78, rel=1e-9, abs=1e-12),
        pytest.approx(0.75, rel=1e-9, abs=1e-12),
        "below the aim",
    )
    assert "below the aim" in result["sentence"]
    assert "Default aim: beat buy-and-hold" in result["sentence"]
    assert not FORBIDDEN_WORDS.search(result["sentence"])
    assert not LETTER_GRADE.search(result["sentence"])


@pytest.mark.parametrize(
    ("bench", "relation"),
    [
        (0.19, "above the aim"),
        (1.31, "below the aim"),
        (0.2, "within the uncertainty of the aim"),
        (1.3, "within the uncertainty of the aim"),
        # A point estimate below the aim is still within the strategy's interval: no "below".
        (0.9, "within the uncertainty of the aim"),
    ],
)
def test_relation_to_the_default_aim_uses_the_stored_interval(bench: float, relation: str) -> None:
    value = manifest()  # Sharpe 0.75, stored 95% interval 0.2 to 1.3
    value["spine"]["periods"]["scored"]["benchmark"]["sharpe"] = bench
    aim = reading.build_reading(value, CLEAN)["aim"]
    assert aim["rows"][0]["relation"] == relation
    assert "same scored days (with dividends, no costs)" in aim["basis"]
    assert "95% bootstrap Sharpe interval" in aim["basis"]


@pytest.mark.parametrize(
    "value",
    [
        manifest(cis=[]),
        manifest(spine={"labels": [], "periods": {"full_history": {"benchmark": {"sharpe": 0.1}}}}),
    ],
)
def test_no_same_days_benchmark_or_no_interval_gives_no_aim_relation(
    value: dict[str, Any],
) -> None:
    result = reading.build_reading(value, {**CLEAN, "closed_oos_trades": 80})
    assert result["aim"] == {"source": "none", "basis": None, "rows": []}
    assert "aim" not in result["sentence"]


def _trades(count: int) -> dict[str, Any]:
    return {"scored": {"benchmark": {"sharpe": 0.78}, "strategy": {"trades": count}}}


def _with(**changes: Any) -> dict[str, Any]:
    value = manifest()
    for path, new in changes.items():
        node = value
        *parents, leaf = path.split("__")
        for part in parents:
            node = node[part]
        node[leaf] = new
    return value


NULL_FAIL = [{"tier": "full_engine", "passed": False, "percentile": 0.6, "threshold": 0.95}]
LOW_CI = [{"metric": "sharpe", "lower": -0.1, "upper": 1.0, "point": 0.4}]


@pytest.mark.parametrize(
    ("value", "diagnostics", "word"),
    [
        (manifest(), CLEAN, "clear of chance"),
        # Held back from the top word, every other check holding.
        (_with(cpcv__passed=False), CLEAN, "some evidence"),
        (_with(cpcv={}), CLEAN, "some evidence"),
        (_with(dsr__family_id=None), CLEAN, "some evidence"),
        (manifest(), {}, "some evidence"),
        (manifest(), {"plausibility": [{"flag": "implausibly-good"}]}, "some evidence"),
        # The trial-corrected figure under the line, or missing: never a positive word.
        (_with(dsr__passed=False, dsr__dsr=0.6), CLEAN, "not clear of chance"),
        (_with(dsr__dsr=0.9499), CLEAN, "not clear of chance"),
        (_with(dsr__passed=True, dsr__dsr=0.6), CLEAN, "not clear of chance"),
        (_with(dsr__dsr=None), CLEAN, "not clear of chance"),
        (_with(dsr__dsr=float("nan")), CLEAN, "not clear of chance"),
        (_with(dsr={}), CLEAN, "not clear of chance"),
        (_with(cis=LOW_CI), CLEAN, "not clear of chance"),
        (_with(cis=[]), CLEAN, "not clear of chance"),
        (_with(nulls=NULL_FAIL), CLEAN, "not clear of chance"),
        (_with(nulls=[]), CLEAN, "not clear of chance"),
        (_with(nulls=[{"tier": "full_engine"}]), CLEAN, "not clear of chance"),
        (
            _with(oos_metrics={"sharpe": -0.2, "max_drawdown": -0.1, "risk_of_ruin": 0.1}),
            CLEAN,
            "not clear of chance",
        ),
        # Too little wins, and a count that was not stored is too little, never enough.
        (_with(spine={"labels": [], "periods": _trades(29)}), CLEAN, "too little to read"),
        (_with(spine={"labels": [], "periods": {}}), CLEAN, "too little to read"),
        (_with(verdict__detail={"sample_n_oos": 99.0}), CLEAN, "too little to read"),
        (_with(verdict__detail={}), CLEAN, "too little to read"),
        (
            _with(spine={"labels": [], "periods": _trades(29)}, cis=LOW_CI, nulls=NULL_FAIL),
            CLEAN,
            "too little to read",
        ),
    ],
)
def test_evidence_word_truth_table(
    value: dict[str, Any], diagnostics: dict[str, Any], word: str
) -> None:
    assert reading.build_reading(value, diagnostics)["evidence"]["word"] == word


def test_no_taste_band_or_letter_chooses_the_word() -> None:
    base = reading.build_reading(manifest(), CLEAN)
    for verdict_letter, drawdown, ruin in (("F", -0.9, 0.99), ("A", -0.01, 0.0)):
        value = _with(verdict__overall=verdict_letter)
        value["oos_metrics"].update(max_drawdown=drawdown, risk_of_ruin=ruin)
        assert reading.build_reading(value, CLEAN)["evidence"] == base["evidence"]
    for sharpe in (0.4, 0.6, 1.1, 1.6):  # either side of every old Sharpe band
        assert reading.build_reading(_with(oos_metrics__sharpe=sharpe), CLEAN)["evidence"][
            "word"
        ] == ("clear of chance")


def test_the_page_states_each_definition_as_the_code_has_it() -> None:
    page = (
        Path(__file__).resolve().parents[2] / "docs/reference/invariants/cli-rule-readings.md"
    ).read_text(encoding="utf-8")
    flat = " ".join(page.replace(">", " ").split())
    for word, definition in reading.WORDS.items():
        assert f"`{word}`: {definition}" in flat, word


def test_too_little_wins_over_every_other_word() -> None:
    value = _with(spine={"labels": ["too-few-trades"], "periods": _trades(80)})
    assert reading.build_reading(value, CLEAN)["evidence"]["word"] == "too little to read"


def test_implausibly_good_blocks_clear_of_chance() -> None:
    flagged = [{"flag": "implausibly-good", "detail": "check for a data error"}]
    result = reading.build_reading(manifest(), {"plausibility": flagged})
    assert result["evidence"]["word"] == "some evidence"
    assert any("too good" in line for line in result["evidence"]["because"])


@pytest.mark.parametrize("bad", [None, float("nan")])
def test_a_statistic_that_could_not_be_computed_is_a_fault_not_a_low_reading(
    bad: float | None,
) -> None:
    value = manifest()
    value["oos_metrics"]["sharpe"] = bad
    result = reading.build_reading(value)
    assert result["sentence"] == (
        "Fault: the out-of-sample Sharpe could not be computed. Fix this first. No reading."
    )
    assert result["evidence"]["word"] is None
    assert result["aim"]["rows"] == []
    assert [c["state"] for c in result["checks"]].count("fault") == 1


def test_look_ahead_and_bad_data_stay_hard_faults() -> None:
    audit = [{"check": "fills-after-decisions", "status": "FLAG", "detail": "2 of 9 fills"}]
    result = reading.build_reading(manifest(), {"audit": audit})
    assert result["sentence"].startswith("Fault: ")
    assert result["sentence"].endswith("Fix this first. No reading.")
    bad = reading.build_reading(manifest(data_health={"verdict": "fail"}))
    assert bad["sentence"].startswith("Fault: ") and bad["evidence"]["word"] is None


def test_counts_and_sentence_shape() -> None:
    diagnostics = {
        "closed_oos_trades": 80,
        "trials": {
            "total_trials": 3,
            "family": {"family_id": "spine:ma_cross", "n_trials_used": 7},
        },
        "variants_evaluated": 5,
    }
    result = reading.build_reading(manifest(), diagnostics)
    assert result["counts"] == {
        "trial_n": 3,
        "family_id": "spine:ma_cross",
        "family_trials": 7,
        "variants_tried": 5,
        "best_of": 6,
    }
    assert 1 <= result["sentence"].count(". ") + 1 <= 4
    assert "Trial 3" in result["sentence"] and "6 variants" in result["sentence"]


def test_old_manifest_without_reading_derives_one_and_old_letters_read_as_old() -> None:
    old = manifest()
    assert "reading" not in old
    assert reading.stored_reading(old, CLEAN)["evidence"]["word"] == "clear of chance"
    assert reading.stored_reading(old)["evidence"]["word"] == "some evidence"
    stored = {**old, "reading": {"sentence": "kept as stored"}}
    assert reading.stored_reading(stored) == {"sentence": "kept as stored"}
    assert reading.old_grade_text("B") == "graded B under the old rules"


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from alpha_data.store import ParquetStore

    path = tmp_path_factory.mktemp("reading")
    mp = pytest.MonkeyPatch()
    mp.setenv("ALPHA_DATA_DIR", str(path))
    mp.setattr(_runner, "execution_fingerprint", lambda: "e" * 64)
    seed_store(path, symbol="SPY", n=1000, seed=3, drift=0.0004, sigma=0.01)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="synthetic", adapter_version="1", parser_version="1"
    )
    yield path
    mp.undo()


ARGS = ["--rule", "ma_cross", "--param", "fast=10", "--param", "slow=30", "--asset", "SPY"]


@pytest.fixture(scope="module")
def first_run(home: Path) -> str:
    from alpha_cli.main import app

    result = CliRunner().invoke(app, ["test", *ARGS, "--quick", "--name", "probe"])
    assert result.exit_code == 0, result.output
    return result.output


def test_ids_counts_and_verdict_are_unchanged_by_the_reading(home: Path, first_run: str) -> None:
    run_dir = home / "runs" / PINNED_RUN_ID
    stored = json.loads((run_dir / "manifest.json").read_text())
    assert stored["run_id"] == PINNED_RUN_ID
    assert stored["idea_id"] == PINNED_IDEA_ID
    assert stored["spine"]["test_id"] == PINNED_TEST_ID
    assert stored["verdict"]["overall"] == PINNED_VERDICT
    assert stored["verdict"]["n_trials"] == 6
    assert stored["reading"]["schema"] == "AlphaReadingV1"
    rows = [json.loads(line) for line in (home / "ledger/trials.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["test_id"] == PINNED_TEST_ID and rows[0]["run_id"] == PINNED_RUN_ID
    assert rows[0]["verdict"] == PINNED_VERDICT
    assert "reading" not in rows[0]


def test_owner_text_has_no_grade_and_no_verdict_words(home: Path, first_run: str) -> None:
    from alpha_cli.main import app

    runner = CliRunner()
    texts = {
        "test": first_run,
        "list": runner.invoke(app, ["results"]).output,
        "show": runner.invoke(app, ["results", "show", PINNED_RUN_ID]).output,
        "diagnose": runner.invoke(app, ["diagnose", PINNED_RUN_ID]).output,
        "next": runner.invoke(app, ["next"]).output,
    }
    texts["next"] = texts["next"].split("What you did recently")[1].split("Idea cards")[0]
    for name, text in texts.items():
        # The stored details printed after the reading are older diagnostic text; the reading
        # and result lines above them are the new owner text.
        new_text = text.split("\n{")[0] if name in {"show", "diagnose"} else text
        assert not FORBIDDEN_WORDS.search(new_text), (name, FORBIDDEN_WORDS.search(new_text))
        assert not LETTER_GRADE.search(text), (name, LETTER_GRADE.search(text))
        assert '"PASS"' not in text, name
    assert "within the uncertainty of the aim" in texts["test"]
    assert "Evidence strength: " in texts["show"]
    assert "Evidence strength: " in texts["diagnose"]
    assert "(too little to read)" in texts["next"]


def test_json_keeps_the_verdict_and_adds_the_reading(home: Path, first_run: str) -> None:
    from alpha_cli.main import app

    out = json.loads(
        CliRunner().invoke(app, ["test", *ARGS, "--quick", "--name", "probe", "--json"]).stdout
    )
    item = out["results"][0]
    assert item["verdict"] == PINNED_VERDICT
    assert item["reading"]["schema"] == "AlphaReadingV1"
    assert out["test_id"] == PINNED_TEST_ID and item["run_id"] == PINNED_RUN_ID
    listed = json.loads(CliRunner().invoke(app, ["results", "--json"]).stdout)["items"][0]
    assert listed["verdict"] == PINNED_VERDICT and listed["reading"]["schema"] == "AlphaReadingV1"


def test_old_ledger_row_with_only_a_letter_reads_as_old_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.main import app
    from alpha_cli.spine.ledger import append_trial

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    append_trial(
        tmp_path,
        {
            "kind": "rule_test",
            "test_id": "t",
            "name": "old",
            "rule": "ma_cross",
            "verdict": "B",
            "labels": [],
            "symbol": "SPY",
        },
    )
    runner = CliRunner()
    for args in (["results"], ["next"]):
        text = runner.invoke(app, args).output
        assert "graded B under the old rules" in text, text
        assert not FORBIDDEN_WORDS.search(text)
