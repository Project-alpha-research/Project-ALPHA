"""Rule test -> the three investigation tools -> their outputs listed and cited."""

import json
from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def _files(root: Path) -> dict[str, int]:
    return {str(path.relative_to(root)): path.stat().st_mtime_ns for path in root.rglob("*")}


def test_investigation_tools_on_a_rule_test(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    for symbol, seed, sigma in (("SPY", 0, 0.01), ("QQQ", 1, 0.02)):
        seed_store(data, symbol=symbol, n=500, seed=seed, sigma=sigma)
        # Strict pull provenance: bar reads reject a partial provenance file.
        ParquetStore(data / "store").write_provenance(
            symbol, source="alpaca", adapter_version="1", parser_version="1"
        )
    result = alpha(
        home,
        "test",
        "--rule",
        "ma_cross",
        "--param",
        "fast=5",
        "--param",
        "slow=20",
        "--asset",
        "SPY",
        "--quick",
        "--json",
    ).json()["results"][0]
    assert result["error"] is None, result
    run_id = result["run_id"]
    run_dir = data / "runs" / run_id
    before = _files(run_dir)

    own = alpha(home, "tool", "run", "market.attribution", run_id, "--json").json()
    assert own["tool"] == "market.attribution"
    assert {"quick", "dev-machine-data", "benchmark-is-same-asset"} <= set(own["labels"])
    assert 0.0 < own["result"]["beta"] < 1.0  # long or flat in the same asset
    assert own["result"]["join"]["run_bars_dropped"] == 0
    other = alpha(
        home, "tool", "run", "market.attribution", run_id, "--param", "benchmark=QQQ", "--json"
    ).json()
    assert "benchmark-is-same-asset" not in other["labels"]
    assert other["result"]["benchmark"] == "QQQ@home"
    assert other["file"] != own["file"]

    regimes = alpha(home, "tool", "run", "market.vol_regimes", run_id, "--json").json()
    assert "parameters-fit-in-sample" in regimes["labels"]
    assert regimes["result"]["hindsight"]["labels"] == ["hindsight"]
    assert "series" not in regimes["result"]
    assert "series" in json.loads((data / regimes["file"]).read_text())["result"]
    assert regimes["result"]["split"]["unlabelled_bars"] == 1
    assert [row["name"] for row in regimes["result"]["split"]["regimes"]] == ["calm", "turbulent"]

    points = alpha(home, "tool", "run", "market.changepoints", run_id, "--json").json()
    assert points["labels"][-1] == "hindsight"
    assert points["facts"][0]["metric"] == "market.changepoints.count"
    assert points["facts"][0]["value"] == len(points["result"]["breaks"])
    text = alpha(home, "tool", "run", "market.changepoints", run_id, "--param", "on=equity").stdout
    assert "market.changepoints.count" in text
    assert "Saved: diagnostics/" in text

    assert _files(run_dir) == before  # the immutable run directory is untouched
    shown = alpha(home, "results", "show", run_id, "--json").json()["runs"][0]
    tools = [item["tool"] for item in shown["tools"]]
    assert tools.count("market.attribution") == 2
    assert tools.count("market.changepoints") == 2
    assert tools.count("market.vol_regimes") == 1
    assert all((data / item["file"]).is_file() for item in shown["tools"])

    ambiguous = alpha(home, "results", "cite", run_id, "market_beta", "--json", expect=1).json()
    assert ambiguous["error"]["code"] == "AMBIGUOUS_TOOL_OUTPUT"
    own_id = Path(own["file"]).stem.rsplit("-", 1)[1]
    assert own_id in ambiguous["error"]["known"]
    assert "--tool-output" in ambiguous["error"]["next"]
    cited = alpha(
        home, "results", "cite", run_id, "market_beta", "--tool-output", own_id, "--json"
    ).json()
    assert cited["value"] == pytest.approx(own["result"]["beta"], rel=1e-12)
    assert cited["source"] == f"{own['file']}:result.beta"

    listing = alpha(home, "results", "--json").json()
    kinds = [item["kind"] for item in listing["items"]]
    assert kinds[-1] == "rule_test"
    assert kinds.count("tool:market.attribution") == 4
    assert own["trials_total"] == 3
    assert listing["total_trials"] == len(kinds) == 11

    missing = alpha(home, "tool", "run", "market.attribution", "0" * 16, "--json", expect=1).json()
    assert missing["error"]["code"] == "UNKNOWN_RUN"
    unknown = alpha(
        home,
        "tool",
        "run",
        "market.attribution",
        run_id,
        "--param",
        "benchmark=NOPE",
        "--json",
        expect=1,
    ).json()
    assert unknown["error"]["code"] == "UNKNOWN_ASSET"
    assert unknown["error"]["known"] == ["home"]
