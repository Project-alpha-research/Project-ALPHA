"""The OSAP catalogue importer and the checked/imported tiers of the library."""

import json
import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine import library, library_import
from alpha_cli.spine.errors import SpineError

RUNNER = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "tests/fixtures/context/osap/signal_doc_sample.csv"
IMPORTED = ROOT / "research/library/imported/osap"
CHECKED = ROOT / "research/library/published"


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["library", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def _import(home: Path, into: str = "home") -> tuple[int, str]:
    return _cli(
        home, "import-catalogue", "osap", "--from", str(CSV), "--release", "2026.10", "--into", into
    )


def test_import_writes_facts_only_records_for_predictors(tmp_path: Path) -> None:
    code, output = _import(tmp_path)
    assert code == 0, output
    folder = tmp_path / "library" / "imported" / "osap"
    assert sorted(p.stem for p in folder.glob("*.toml")) == [
        "osap-synthaccrual",
        "osap-synthmom",
        "osap-synthoption",
    ]
    raw = (folder / "osap-synthaccrual.toml").read_text(encoding="utf-8")
    assert "must never be copied" not in raw and "Synthetic SynthAccrual" not in raw
    data = tomllib.loads(raw)
    assert data["tier"] == "imported"
    assert data["idea"] == "Published signal: SynthAccrual (accruals)"
    assert data["mechanism_claimed"] == "not stated here; see the paper"
    assert data["decay_evidence"] == "none recorded"
    assert data["year_published"] == 1999 and data["source"]["authors"] == "Doe"
    assert data["imported"] == {
        "project": "Open Source Cross-Sectional Asset Pricing",
        "release": "2026.10",
        "source_id": "SynthAccrual",
        "acronym": "SynAcc",
        "category": "accruals",
        "data_category": "Accounting",
        "predicted_sign": -1,
        "sample_start": 1970,
        "sample_end": 1995,
    }
    assert data["can_test_today"].startswith("no")


def test_can_test_today_is_no_for_accounts_and_unknown_otherwise(tmp_path: Path) -> None:
    _import(tmp_path)
    found = {e.record.id: e.record for e in library.entries(tmp_path, imported=True)}
    assert found["osap-synthaccrual"].can_test_today.split(" ")[0] == "no"
    assert found["osap-synthmom"].can_test_today.split(" ")[0] == "unknown"
    assert found["osap-synthoption"].source.venue == "not stated in the source table"


def test_import_is_repeatable_and_counts_what_it_skipped(tmp_path: Path) -> None:
    _, first = _import(tmp_path)
    _, again = _import(tmp_path)
    assert "3 record(s)" in first and "2 not predictors" in first
    assert again == first
    folder = tmp_path / "library" / "imported" / "osap"
    assert len(list(folder.glob("*.toml"))) == 3


def test_a_changed_header_stops_the_import_and_writes_nothing(tmp_path: Path) -> None:
    broken = tmp_path / "broken.csv"
    broken.write_text(CSV.read_text().replace("Cat.Data", "Data.Cat", 1), encoding="utf-8")
    code, output = _cli(
        tmp_path, "import-catalogue", "osap", "--from", str(broken), "--release", "2026.10"
    )
    assert code == 1 and "Cat.Data" in output
    assert not (tmp_path / "library").exists()


def test_list_defaults_to_checked_and_prints_the_counts_of_each_tier(tmp_path: Path) -> None:
    _import(tmp_path)
    code, text = _cli(tmp_path, "list")
    assert code == 0
    assert "osap-" not in text
    committed = len(list(IMPORTED.glob("*.toml")))
    assert re.search(r"\b28 checked\b", text)
    assert re.search(rf"\b{committed + 3} imported\b", text)
    code, text = _cli(tmp_path, "list", "--tier", "imported")
    assert text.count("osap-synth") == 3 and "time-series-momentum" not in text
    code, raw = _cli(tmp_path, "list", "--tier", "all", "--json")
    facts = json.loads(raw)
    assert len(facts["records"]) == 28 + committed + 3
    assert facts["counts"] == {"checked": 28, "imported": committed + 3}
    assert {r["tier"] for r in facts["records"]} == {"checked", "imported"}
    assert _cli(tmp_path, "list", "--tier", "bogus")[0] == 1


def test_show_names_the_source_facts_and_a_card_is_allowed(tmp_path: Path) -> None:
    _import(tmp_path)
    code, text = _cli(tmp_path, "show", "osap-synthmom")
    assert code == 0
    assert "imported" in text and "SynthMom" in text and "2026.10" in text and "+1" in text
    code, text = _cli(tmp_path, "card", "osap-synthmom")
    assert code == 0 and "from imported library record osap-synthmom; not hand-checked" in text
    code, shown = _cli(tmp_path, "show", "osap-synthmom")
    assert code == 0 and "osap-synthmom" in shown


def test_the_two_tiers_live_in_separate_folders_and_are_checked_on_load(tmp_path: Path) -> None:
    for path in CHECKED.glob("*.toml"):
        assert tomllib.loads(path.read_text(encoding="utf-8"))["tier"] == "checked", path.name
    folder = tmp_path / "library" / "imported" / "osap"
    folder.mkdir(parents=True)
    (folder / "accruals.toml").write_text((CHECKED / "accruals.toml").read_text(), encoding="utf-8")
    _, skipped = library.read(tmp_path, imported=True)
    assert "tier" in str(skipped["accruals"])
    code, text = _cli(tmp_path, "list", "--tier", "imported")
    assert code == 0 and "Left out: The library record accruals.toml" in text


def test_an_unknown_key_in_an_imported_record_fails(tmp_path: Path) -> None:
    _import(tmp_path)
    path = tmp_path / "library" / "imported" / "osap" / "osap-synthmom.toml"
    path.write_text(path.read_text(encoding="utf-8") + 'description = "copied"\n', encoding="utf-8")
    with pytest.raises(SpineError):
        library_import.load_imported(path)


def test_the_committed_imported_records_are_facts_only() -> None:
    files = sorted(IMPORTED.glob("*.toml"))
    assert len(files) >= 200
    banned = re.compile(r"guarantee|will make money|risk-free|profitable strategy", re.I)
    for path in files:
        record = library_import.load_imported(path)
        assert record.id == path.stem and record.tier == "imported"
        facts = record.imported
        assert facts is not None and facts.release and facts.source_id
        assert record.idea == f"Published signal: {facts.source_id} ({facts.category})"
        assert record.mechanism_claimed == "not stated here; see the paper"
        assert record.decay_evidence == "none recorded"
        assert record.year_published is not None and 1960 <= record.year_published <= 2026
        assert not banned.search(path.read_text(encoding="utf-8"))
        assert set(tomllib.loads(path.read_text(encoding="utf-8"))) == {
            "id",
            "name",
            "tier",
            "year_published",
            "market",
            "idea",
            "mechanism_claimed",
            "data_needed",
            "direction",
            "holding_clock",
            "decay_evidence",
            "can_test_today",
            "notes",
            "source",
            "imported",
        }
    assert (ROOT / "research/library/imported/osap/README.md").exists()
