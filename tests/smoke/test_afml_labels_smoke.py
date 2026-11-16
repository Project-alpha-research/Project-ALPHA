"""`alpha labels barrier` and `alpha labels weights` through the installed program and the worker.

Runs the installed ``alpha`` against the separately locked ``workers/afml`` environment. The root
test job does not install that worker (the ``afml-worker`` job does, and runs this file), so the
end-to-end part skips, with that reason, when ``workers/afml/.venv`` is missing. The refusal for a
missing worker is checked everywhere.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "workers" / "afml"


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    data = home / "data"
    data.mkdir(parents=True)
    seed_store(data, symbol="SPY", n=600)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return home


def test_missing_worker_is_refused_in_plain_english(tmp_path: Path) -> None:
    home = _home(tmp_path)
    bare = tmp_path / "afml-not-installed"
    bare.mkdir()
    shutil.copyfile(WORKER / "pyproject.toml", bare / "pyproject.toml")
    shutil.copyfile(WORKER / "uv.lock", bare / "uv.lock")
    refused = alpha(
        home, "labels", "barrier", "--asset", "SPY", "--worker-project", str(bare), "--json",
        expect=1,
    ).json()  # fmt: skip
    assert refused["error"]["code"] == "WORKER_NOT_INSTALLED"
    assert "not installed" in refused["error"]["message"]
    assert refused["error"]["next"].endswith("uv sync --locked --project workers/afml")
    assert not (home / "data" / "labels").exists()


def test_labels_and_weights_end_to_end(tmp_path: Path) -> None:
    if not (WORKER / ".venv" / "bin" / "python").is_file():
        pytest.skip("AFML worker not installed; run `uv sync --locked --project workers/afml`")
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH; the CLI launches the worker through `uv run`")
    home = _home(tmp_path)
    ran = alpha(home, "labels", "barrier", "--asset", "SPY", "--json", timeout=900).json()
    folder = Path(ran["result_dir"])
    assert {p.name for p in folder.iterdir()} >= {
        "bars.parquet", "events.parquet", "labels.png", "result.json", "summary.json",
    }  # fmt: skip
    assert ran["basis"] == "high_low" and not ran["repeat"]
    facts = {fact["metric"]: fact for fact in ran["facts"]}
    assert set(facts) >= {"events", "decided", "target", "stop", "vertical", "open", "ambiguous"}
    for fact in facts.values():
        assert set(fact) >= {"value", "basis", "reason", "source", "labels"}
        assert fact["reason"] is None and "high/low" in fact["basis"]
    outcomes = sum(facts[name]["value"] for name in ("target", "stop", "vertical", "open"))
    assert outcomes == facts["events"]["value"] > 0
    events = pl.read_parquet(folder / "events.parquet")
    assert events.height == facts["events"]["value"]
    again = alpha(home, "labels", "barrier", "--asset", "SPY", "--json", timeout=900).json()
    assert again["result_id"] == ran["result_id"] and again["repeat"]

    cut = str(events["ts"][events.height // 2].date())
    weighted = alpha(
        home, "labels", "weights", ran["result_id"], "--train-end", cut, "--json", timeout=900
    ).json()
    assert "weights-train-only" in weighted["labels"]
    wfacts = {fact["metric"]: fact for fact in weighted["facts"]}
    assert 0.0 < wfacts["mean_avg_uniqueness"]["value"] <= 1.0
    assert wfacts["max_library_gap"]["value"] <= 1e-10
    assert wfacts["labels"]["basis"].startswith("labels ending on or before")
    weights = pl.read_parquet(Path(weighted["result_dir"]) / "weights.parquet")
    assert weights.height == wfacts["labels"]["value"]

    close = alpha(
        home, "labels", "barrier", "--asset", "SPY", "--basis", "close", "--json", timeout=900
    ).json()
    assert "parity-basis" in close["labels"]
    assert "closes only" in close["facts"][0]["basis"]
