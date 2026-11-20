"""The trial ledger and the Setup Lab speak in readings: words only, counts and ids unchanged."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.main import app
from alpha_cli.spine import reading, setup_controls, setup_study, setup_trade
from alpha_cli.spine.deflation import _distinct_tests, count_snapshot, same_asset_tests
from alpha_cli.spine.ledger import append_trial
from alpha_cli.spine.trial_reader import family_counts, spine_snapshot, trials_for_deflation
from alpha_cli.spine.trial_record import row_test_key
from alpha_validation.proportion import benjamini_hochberg
from tests.fixtures.cli_fixtures import seed_store
from tests.unit import _setup_reading_support as support
from tests.unit.test_reading_rule import PINNED_IDEA_ID, PINNED_RUN_ID, PINNED_TEST_ID
from tests.unit.test_trial_record import mapped, spine

RUNNER = CliRunner()
BANNED = re.compile(r"\b(supported|rejected|inconclusive|pass|fail|profit)\b", re.IGNORECASE)
OLD_PHRASE = re.compile(r"graded [A-F] under the old rules")
# A lone capital A to F. Only the article that starts a sentence ("A result of ...") is spared:
# at a line start or after ". ", and followed by one space and a lower-case word. "SPY  A  1.2",
# "SPY\tA" and "graded A under" are all caught.
LETTER = re.compile(r"(?<![\w'./-])[A-F](?![\w'./-])")
ARTICLE = re.compile(r"(?:^|(?<=[.!?:] ))A(?= [a-z])", re.MULTILINE)
WORDS = list(reading.WORDS)
OLD_SETUP = ("inconclusive", "not supported", "supported (exploratory, not confirmed)")


def clean(text: str) -> str:
    return OLD_PHRASE.sub("", text)


def assert_owner_text(text: str) -> None:
    assert not BANNED.search(text), BANNED.search(text)
    text = ARTICLE.sub("", clean(text))
    assert not LETTER.search(text), LETTER.search(text)


# ---------- ledger: mapping on read ----------


def test_a_new_rule_row_reads_as_its_evidence_word_and_keeps_the_machine_outcome() -> None:
    record = mapped(spine(verdict="B", evidence="some evidence", aim_relation="below the aim"))
    assert record.outcome == "some evidence"
    assert (record.evidence, record.aim_relation) == ("some evidence", "below the aim")
    assert record.machine_outcome == "supported" and record.raw_status == "B"


def test_a_fault_row_reads_as_fault() -> None:
    assert mapped(spine(verdict="F", evidence="fault", aim_relation=None)).outcome == "fault"


@pytest.mark.parametrize("letter", ["A", "B", "C", "D", "F"])
def test_an_old_row_with_only_a_letter_never_reads_supported_or_rejected(letter: str) -> None:
    record = mapped(spine(verdict=letter))
    assert record.outcome == f"graded {letter} under the old rules"
    assert record.machine_outcome in {"supported", "inconclusive", "rejected"}
    assert record.evidence is None and record.aim_relation is None


def test_an_error_row_stays_error_and_an_unknown_evidence_word_is_refused() -> None:
    assert mapped(spine(verdict=None, labels=["error"], evidence=None)).outcome == "error"
    with pytest.raises(ValueError, match="unknown evidence"):
        mapped(spine(evidence="proved"))


def setup_row(**over: Any) -> dict[str, Any]:
    row = spine(
        kind="setup_study",
        idea="Volume spike",
        assets=["SPY"],
        study_id="s1",
        outcome="not supported",
        verdict=None,
        labels=[],
    )
    return row | over


@pytest.mark.parametrize("word", OLD_SETUP)
def test_a_setup_row_accepts_the_three_old_words_and_reads_them_as_evidence(word: str) -> None:
    record = mapped(setup_row(outcome=word))
    assert record.machine_outcome == word
    assert record.outcome in WORDS and record.outcome != "clear of chance"
    assert record.reason and "old wording" in record.reason


@pytest.mark.parametrize("word", ["too little to read", "not clear of chance", "some evidence"])
def test_a_setup_row_accepts_the_new_words(word: str) -> None:
    record = mapped(setup_row(outcome="not supported", evidence=word))
    assert record.outcome == word and record.reason is None


def test_a_setup_row_refuses_an_unknown_word() -> None:
    with pytest.raises(ValueError, match="unknown study outcome"):
        mapped(setup_row(outcome="great"))


# ---------- ledger: counts are identical whatever the outcome word ----------


def ledger_rows(new_style: bool) -> list[dict[str, Any]]:
    letters = ["A", "B", "C", "D", "F", "B", "C", "C"]
    words = [*WORDS, "fault", None]
    rows: list[dict[str, Any]] = []
    for i, letter in enumerate(letters):
        row = spine(
            trial_index=i + 1,
            verdict=letter,
            rule="ma_cross" if i % 2 else "breakout",
            symbol="SPY" if i < 5 else "QQQ",
            spec_sha256=("a" if i % 3 else "b") * 64,
            first_ts="2020-01-01" if i != 4 else "2021-01-01",
            run_id=f"run{i}",
            labels=["repeat"] if i == 5 else (["error"] if i == 6 else []),
        )
        if new_style:
            row |= {"evidence": words[i % len(words)], "aim_relation": "below the aim"}
        rows.append(row)
    for j, word in enumerate(OLD_SETUP):
        rows.append(
            setup_row(
                trial_index=len(rows) + 1,
                study_id=f"s{j}",
                run_id=f"s{j}",
                outcome=word,
                **({"evidence": WORDS[j + 1]} if new_style else {}),
            )
        )
    return rows


def signature(home: Path) -> dict[str, Any]:
    snapshot = spine_snapshot(home)
    families = [f["family_id"] for f in family_counts(snapshot)]
    return {
        "reader": {f["family_id"]: f["reader_trials"] for f in family_counts(snapshot)},
        "deflation": {fam: trials_for_deflation(snapshot, fam) for fam in families},
        "distinct": {
            fam: [(r.trial_id, k) for r in _distinct_tests(snapshot, fam)[0] for k in [0]]
            + [_distinct_tests(snapshot, fam)[1]]
            for fam in families
        },
        "same_asset": {s: same_asset_tests(snapshot, s) for s in ("SPY", "QQQ")},
        "n_used": {
            rule: (c := count_snapshot(snapshot, rule)).prior_trials + c.this_run + c.repeats
            for rule in ("ma_cross", "breakout")
        },
        "keys": [row_test_key(r) for r in snapshot.raw_rows.values()],
        "counts_flag": [r.counts_for_deflation for r in snapshot.records],
    }


def write_ledger(home: Path, rows: list[dict[str, Any]]) -> None:
    path = home / "ledger/trials.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_every_count_is_identical_with_and_without_the_new_fields(tmp_path: Path) -> None:
    write_ledger(
        tmp_path / "old", [r | {"total_trials": r["trial_index"]} for r in ledger_rows(False)]
    )
    write_ledger(
        tmp_path / "new", [r | {"total_trials": r["trial_index"]} for r in ledger_rows(True)]
    )
    before, after = signature(tmp_path / "old"), signature(tmp_path / "new")
    assert before == after
    assert before["reader"]["spine:ma_cross"] >= 1 and before["same_asset"]["SPY"][0] >= 1


def test_no_counting_code_reads_the_outcome_word() -> None:
    root = Path(__file__).resolve().parents[2] / "apps/alpha-cli/src/alpha_cli/spine"
    assert "outcome" not in (root / "deflation.py").read_text()
    source = (root / "trial_record.py").read_text()
    for name in ("make_test_key", "row_test_key"):
        body = source.split(f"def {name}")[1].split("\ndef ")[0]
        assert "outcome" not in body and "evidence" not in body


def test_the_family_counts_name_owner_words(tmp_path: Path) -> None:
    write_ledger(tmp_path, [r | {"total_trials": r["trial_index"]} for r in ledger_rows(False)])
    counts = {f["family_id"]: f for f in family_counts(spine_snapshot(tmp_path))}
    assert all(not BANNED.search(" ".join(f["outcomes"])) for f in counts.values())


# ---------- owner text on synthetic homes ----------


def home_with(tmp_path: Path, new_style: bool) -> Path:
    home = tmp_path / ("new" if new_style else "old")
    seed_store(home, symbol="SPY", n=60)
    rows = [r | {"total_trials": r["trial_index"]} for r in ledger_rows(new_style)]
    write_ledger(home, rows)
    return home


@pytest.mark.parametrize("new_style", [False, True])
def test_ledger_next_and_results_print_no_verdict_words(tmp_path: Path, new_style: bool) -> None:
    home = home_with(tmp_path, new_style)
    env = {"ALPHA_DATA_DIR": str(home)}
    for args in (
        ["ledger", "summary"],
        ["ledger", "list"],
        ["ledger", "families"],
        ["ledger", "query", "by-outcome"],
        ["ledger", "show", "spine:2"],
        ["next"],
        ["results"],
    ):
        result = RUNNER.invoke(app, args, env=env)
        assert result.exit_code == 0, (args, result.output)
        text = result.output
        if args == ["next"]:  # the data-health counts above it are fact checks, not readings
            text = text.split("What you did recently")[1].split("Idea cards")[0]
        assert_owner_text(text)
    listing = RUNNER.invoke(app, ["ledger", "list"], env=env).output
    assert ("some evidence" in listing) if new_style else ("under the old rules" in listing)


def test_ledger_json_keeps_old_fields_and_adds_the_new_ones(tmp_path: Path) -> None:
    home = home_with(tmp_path, True)
    out = RUNNER.invoke(app, ["ledger", "list", "--json"], env={"ALPHA_DATA_DIR": str(home)})
    rows = {r["trial_id"]: r for r in json.loads(out.output)["records"]}
    first = rows["spine:1"]
    assert first["raw_status"] == "A" and first["machine_outcome"] == "supported"
    assert first["evidence"] == WORDS[0] and first["outcome"] == WORDS[0]
    assert "aim_relation" in first


def test_the_outcome_filter_still_accepts_the_machine_word(tmp_path: Path) -> None:
    home = home_with(tmp_path, False)
    out = RUNNER.invoke(
        app,
        ["ledger", "list", "--outcome", "rejected", "--json"],
        env={"ALPHA_DATA_DIR": str(home)},
    )
    assert [r["raw_status"] for r in json.loads(out.output)["records"]] == ["F", "D"]


# ---------- a real rule run writes the new fields and keeps every id ----------


@pytest.fixture(scope="module")
def run_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from alpha_data.store import ParquetStore

    path = tmp_path_factory.mktemp("ledger-reading")
    mp = pytest.MonkeyPatch()
    mp.setenv("ALPHA_DATA_DIR", str(path))
    mp.setattr(_runner, "execution_fingerprint", lambda: "e" * 64)
    seed_store(path, symbol="SPY", n=1000, seed=3, drift=0.0004, sigma=0.01)
    ParquetStore(path / "store").write_provenance(
        "SPY", source="synthetic", adapter_version="1", parser_version="1"
    )
    args = ["--rule", "ma_cross", "--param", "fast=10", "--param", "slow=30", "--asset", "SPY"]
    result = RUNNER.invoke(app, ["test", *args, "--quick", "--name", "probe"])
    assert result.exit_code == 0, result.output
    yield path
    mp.undo()


def test_a_new_run_row_carries_evidence_and_keeps_its_letter_and_ids(run_home: Path) -> None:
    rows = [json.loads(x) for x in (run_home / "ledger/trials.jsonl").read_text().splitlines()]
    row = rows[0]
    stored = json.loads((run_home / "runs" / PINNED_RUN_ID / "manifest.json").read_text())
    assert row["evidence"] == stored["reading"]["evidence"]["word"]
    relation = (stored["reading"]["aim"]["rows"] or [{}])[0].get("relation")
    assert row["aim_relation"] == relation
    assert row["verdict"] == "C" and row["run_id"] == PINNED_RUN_ID
    assert row["test_id"] == PINNED_TEST_ID and stored["idea_id"] == PINNED_IDEA_ID
    listing = RUNNER.invoke(app, ["ledger", "list"]).output
    assert row["evidence"] in listing
    assert_owner_text(listing)
    next_text = RUNNER.invoke(app, ["next"]).output
    assert_owner_text(next_text.split("What you did recently")[1].split("Idea cards")[0])
    assert_owner_text(RUNNER.invoke(app, ["results"]).output)


# ---------- Setup Lab ----------


def primary(n: int, p: float | None, excess: float | None) -> dict[str, Any]:
    return dict(
        occurrences=n,
        trades=n,
        mean=0.02,
        drift_mean=0.01,
        random_date_p=p,
        excess=excess,
        hit_rate=0.6,
        mean_bars_held=5,
    )


@pytest.mark.parametrize(
    ("n", "p", "excess", "labels", "word"),
    [
        (0, None, None, [], "too little to read"),
        (29, 0.001, 0.01, [], "too little to read"),
        (30, 0.05, 0.01, [], "some evidence"),
        (30, 0.05, 0.01, ["halves-disagree"], "not clear of chance"),
        (30, 0.1, 0.01, [], "not clear of chance"),
        (30, 0.01, -0.01, [], "not clear of chance"),
    ],
)
def test_study_evidence_words_and_the_unchanged_legacy_outcome(
    n: int, p: float | None, excess: float | None, labels: list[str], word: str
) -> None:
    value = primary(n, p, excess)
    if n == 0:
        value["mean"] = None
    assert setup_controls.study_evidence(value, labels) == word
    assert (
        setup_controls.reading(value, 5, labels)[1]
        == {
            "too little to read": "inconclusive",
            "not clear of chance": "not supported",
            "some evidence": "supported (exploratory, not confirmed)",
        }[word]
    )


def test_trade_evidence_needs_a_random_control() -> None:
    assert setup_controls.trade_evidence(primary(30, None, None), ["no-random-control"]) == (
        "not clear of chance"
    )
    assert setup_controls.trade_evidence(primary(30, 0.01, 0.01), []) == "some evidence"
    assert setup_controls.trade_evidence(primary(3, 0.01, 0.01), []) == "too little to read"


def test_no_setup_study_is_ever_clear_of_chance() -> None:
    for n, p in ((30, 0.0001), (500, 0.0005)):
        assert setup_controls.study_evidence(primary(n, p, 0.5), []) != "clear of chance"


# Ids and numbers measured on origin/main with the same seeded synthetic setups.
PINNED: dict[str, dict[str, Any]] = {
    "lift": dict(
        find="d03490186ae11b2f",
        study="e186fcb8683fb87d",
        trade="cb1db04a562f394f",
        study_sha="0edc2362a68def58",
        trade_sha="b8198d19f3ed7b26",
        lift=0.004,
        word="some evidence",
    ),
    "flat": dict(
        find="2017fcb5873c3430",
        study="0a14bd41f15883a7",
        trade="2bfe8ba67d56fb15",
        study_sha="21f93e3ab79fecaf",
        trade_sha="55c4f14ed8c99377",
        lift=0.0,
        word="not clear of chance",
    ),
}


def digest(summary: dict[str, Any]) -> str:
    import hashlib

    skip = {"folder", "trials_total", "family", "evidence", "old_wording"}
    body = {k: v for k, v in summary.items() if k not in skip}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


@pytest.mark.parametrize("name", ["lift", "flat"])
def test_setup_ids_and_stored_numbers_are_byte_identical_to_main(tmp_path: Path, name: str) -> None:
    pin = PINNED[name]
    support.seed_events(tmp_path, lift=float(pin["lift"]))
    found = support.make_find(tmp_path)
    study = setup_study.run_study(found["find_id"], home=tmp_path)
    trade = setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert (found["find_id"], study["study_id"], trade["trade_id"]) == (
        pin["find"],
        pin["study"],
        pin["trade"],
    )
    assert digest(study) == pin["study_sha"] and digest(trade) == pin["trade_sha"]
    assert study["evidence"] == pin["word"] and trade["evidence"] == pin["word"]
    stored = json.loads((Path(study["folder"]) / "summary.json").read_text())
    assert stored["outcome"] == study["outcome"] and stored["evidence"] == study["evidence"]
    assert setup_study.STUDY_RULE_VERSION == "setup-study-2"
    assert setup_trade.TRADE_RULE_VERSION == "setup-trade-1"


def run_text(home: Path, command: str, find_id: str) -> str:
    result = RUNNER.invoke(app, ["setup", command, find_id], env={"ALPHA_DATA_DIR": str(home)})
    assert result.exit_code == 0, result.output
    return result.output


@pytest.fixture
def lab(tmp_path: Path) -> tuple[Path, str]:
    support.seed_events(tmp_path, lift=0.004)
    return tmp_path, support.make_find(tmp_path)["find_id"]


def test_setup_text_has_an_evidence_word_a_family_count_and_no_verdict_words(
    lab: tuple[Path, str],
) -> None:
    home, find_id = lab
    for command, noun in (("study", "study"), ("trade", "trade")):
        text = run_text(home, command, find_id)
        assert_owner_text(text)
        assert "Evidence strength: some evidence." in text
        assert "not corrected for the number of setup variants tried" in text
        assert f"Setup {noun} 1 of 1 recorded for this idea." in text
        assert f"random-date figure adjusted for the 1 {noun} recorded" in text.lower()
        assert "Variants saved under another idea text are not counted." in text
    json_out = RUNNER.invoke(
        app, ["setup", "study", find_id, "--json"], env={"ALPHA_DATA_DIR": str(home)}
    )
    data = json.loads(json_out.stdout)
    assert data["outcome"].startswith("supported") and data["evidence"] == "some evidence"


def test_the_family_figure_is_the_validated_benjamini_hochberg_value(
    lab: tuple[Path, str],
) -> None:
    home, first = lab
    run_text(home, "study", first)
    second = support.make_find(home, horizon=3)["find_id"]
    text = run_text(home, "study", second)
    assert "Setup study 2 of 2 recorded for this idea." in text
    ps = [
        json.loads(line)["random_date_p"]
        for line in (home / "ledger/trials.jsonl").read_text().splitlines()
        if json.loads(line)["kind"] == "setup_study"
    ]
    assert len(ps) == 2
    q = float(benjamini_hochberg(ps).qvalues[1])
    assert (
        "random-date figure adjusted for the 2 studies recorded for this idea "
        f"(false-discovery method): {q:.2%}"
    ) in text.lower()
    assert f"unadjusted: {ps[1]:.2%}" in text


def test_without_every_stored_p_value_the_figure_says_not_adjusted(lab: tuple[Path, str]) -> None:
    home, find_id = lab
    append_trial(
        home,
        {
            "kind": "setup_study",
            "idea": "Volume spike",
            "assets": ["SPY"],
            "study_id": "x1",
            "run_id": "x1",
            "outcome": "inconclusive",
            "verdict": None,
            "labels": [],
            "random_date_p": None,
        },
    )
    text = run_text(home, "study", find_id)
    assert "not adjusted for the 2 studies recorded" in text
    assert "Setup study 2 of 2 recorded for this idea." in text
    assert_owner_text(text)


def test_an_old_stored_study_reads_through_the_evidence_words() -> None:
    word, old = reading.setup_evidence_of({"outcome": "not supported"})
    assert (word, old) == ("not clear of chance", True)
    assert reading.setup_evidence_of({"outcome": "x", "evidence": "some evidence"}) == (
        "some evidence",
        False,
    )


def test_the_nightly_verdict_word_is_the_evidence_word() -> None:
    from alpha_cli.nightly_run import setup_word

    assert setup_word({"outcome": "not supported", "evidence": "too little to read"}) == (
        "too little to read"
    )
    assert setup_word({"outcome": "not supported"}) == "not clear of chance"
