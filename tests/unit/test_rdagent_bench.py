"""The replay bench: plan arithmetic and caps, resume, paired scoring, no loop state touched."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.rdagent_bench_model import (
    BenchError,
    FakeClient,
    GatewayClient,
    StoredPrompt,
    load_prices,
    load_prompts,
    make_plan,
    run_bench,
)
from alpha_cli.rdagent_bench_score import score_store
from alpha_cli.rdagent_cmds import rdagent_app

RUNNER = CliRunner()


def _spend(root: Path) -> Path:
    """The one month ledger of a test home."""
    return root / "home" / "rdagent-bench" / "spend.jsonl"


GOOD_PROPOSAL = json.dumps(
    {
        "name": "Volume Surge",
        "description": "declared_direction: +1; primary_clock: weekly; direction_reason: trend.",
    }
)
CLOSED_PROPOSAL = json.dumps(
    {
        "name": "Short-term Reversal",
        "description": "declared_direction: -1; primary_clock: weekly; direction_reason: x.",
    }
)


def _prompts(folder: Path, count: int = 3, stage: str = "proposal") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"p{i}.json").write_text(
            json.dumps(
                {
                    "id": f"p{i}",
                    "stage": stage,
                    "messages": [{"role": "user", "content": f"idea {i}"}],
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                }
            )
        )
    return folder


def _prices(path: Path) -> Path:
    path.write_text(
        "[a]\nin_per_mtok = 1.0\nout_per_mtok = 2.0\n[b]\nin_per_mtok = 3.0\nout_per_mtok = 6.0\n"
    )
    return path


def _fixture(path: Path, count: int = 3) -> Path:
    reply = {"provider": "fake-host", "prompt_tokens": 1000, "completion_tokens": 500}
    data: dict[str, dict[str, list[dict[str, object]]]] = {"a": {}, "b": {}}
    for i in range(count):
        data["a"][f"p{i}"] = [{"text": GOOD_PROPOSAL, **reply, "latency_ms": 100.0}] * 2
        data["b"][f"p{i}"] = [{"text": "not json", **reply, "latency_ms": 300.0}] * 2
    path.write_text(json.dumps(data))
    return path


def test_plan_cost_arithmetic(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr"), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a", "b"])
    plan = make_plan(prompts, ["a", "b"], 2, prices, month_spent=0.0)
    assert plan.calls == 12
    # a: 6 calls * (1000*1 + 500*2)/1e6 ; b: 6 calls * (1000*3 + 500*6)/1e6
    assert plan.usd == pytest.approx(6 * 0.002 + 6 * 0.006, rel=1e-9, abs=1e-12)


def test_plan_refuses_over_call_cap(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 11), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a", "b"])
    with pytest.raises(BenchError, match="60"):
        make_plan(prompts, ["a", "b"], 3, prices, month_spent=0.0)  # 66 calls


def test_plan_refuses_over_usd_and_month_caps(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 2)
    for file in folder.glob("*.json"):
        row = json.loads(file.read_text())
        row["prompt_tokens"] = 6_000_000
        file.write_text(json.dumps(row))
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    with pytest.raises(BenchError, match="10"):
        make_plan(load_prompts(folder, None), ["a"], 1, prices, month_spent=0.0)
    small = load_prompts(_prompts(tmp_path / "s"), None)
    with pytest.raises(BenchError, match="50"):
        make_plan(small, ["a"], 1, prices, month_spent=49.999)


def test_missing_price_or_tokens_refuse(tmp_path: Path) -> None:
    with pytest.raises(BenchError, match="price"):
        load_prices(_prices(tmp_path / "pr.toml"), ["a", "zzz"])
    folder = _prompts(tmp_path / "pr", 1)
    row = json.loads((folder / "p0.json").read_text())
    del row["completion_tokens"]
    (folder / "p0.json").write_text(json.dumps(row))
    prices = load_prices(_prices(tmp_path / "pr2.toml"), ["a"])
    with pytest.raises(BenchError, match="token"):
        make_plan(load_prompts(folder, None), ["a"], 1, prices, month_spent=0.0)


def test_stage_filter(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 2, "proposal")
    other = _prompts(tmp_path / "other", 1, "feedback")
    (folder / "f0.json").write_text((other / "p0.json").read_text().replace("p0", "f0"))
    assert len(load_prompts(folder, None)) == 3
    assert [p.id for p in load_prompts(folder, ["feedback"])] == ["f0"]


def test_run_stores_resumes_and_never_touches_loop_state(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr"), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a", "b"])
    client = FakeClient(json.loads(_fixture(tmp_path / "fx.json").read_text()))
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("row\n")
    memory = tmp_path / "memory"
    memory.mkdir()
    before = sorted(p.name for p in tmp_path.iterdir() if p.name not in {"store", "home"})
    store = tmp_path / "store"
    first = run_bench(
        prompts, ["a", "b"], 2, prices, client, store, spend=_spend(tmp_path), max_new_calls=5
    )
    assert first.new_calls == 5 and not first.finished
    second = run_bench(prompts, ["a", "b"], 2, prices, client, store, spend=_spend(tmp_path))
    assert second.new_calls == 7 and second.finished
    assert client.calls == 12
    third = run_bench(prompts, ["a", "b"], 2, prices, client, store, spend=_spend(tmp_path))
    assert third.new_calls == 0 and client.calls == 12
    after = sorted(p.name for p in tmp_path.iterdir() if p.name not in {"store", "home"})
    assert before == after and ledger.read_text() == "row\n" and not list(memory.iterdir())
    record = json.loads(next((store / "outputs" / "a").glob("p0.0.json")).read_text())
    assert record["provider"] == "fake-host" and record["usd"] == pytest.approx(0.002)


def test_store_inside_git_is_refused(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr"), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(BenchError, match="git"):
        run_bench(prompts, ["a"], 1, prices, FakeClient({}), repo / "store", spend=_spend(tmp_path))


def test_paired_scoring_on_fixtures(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr"), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a", "b"])
    client = FakeClient(json.loads(_fixture(tmp_path / "fx.json").read_text()))
    store = tmp_path / "store"
    run_bench(prompts, ["a", "b"], 2, prices, client, store, spend=_spend(tmp_path))
    result = score_store(prompts, ["a", "b"], store, closed=set(), dropped=set())
    a, b = result.models["a"], result.models["b"]
    assert a.prompts == 3 and a.outputs == 6
    assert a.buildable == pytest.approx(1.0) and b.buildable == pytest.approx(0.0)
    assert a.refusal == pytest.approx(0.0)
    assert a.cost_per_call == pytest.approx(0.002) and b.cost_per_call == pytest.approx(0.006)
    assert a.latency_ms == pytest.approx(100.0) and b.latency_ms == pytest.approx(300.0)
    assert a.prefix_reason and "not run" in a.prefix_reason
    pair = result.pairs[("a", "b")]
    assert pair.count == 3 and pair.buildable_diff == pytest.approx(1.0)
    assert "winner" not in result.text().lower()
    assert "3 prompts" in result.text()


def test_refusal_uses_closed_family_and_dropped_name(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 2), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    data = {
        "a": {
            "p0": [
                {
                    "text": CLOSED_PROPOSAL,
                    "provider": "h",
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "latency_ms": 1.0,
                }
            ],
            "p1": [
                {
                    "text": GOOD_PROPOSAL,
                    "provider": "h",
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "latency_ms": 1.0,
                }
            ],
        }
    }
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=_spend(tmp_path))
    closed = score_store(
        prompts, ["a"], store, closed={"past return (momentum or reversal)"}, dropped=set()
    )
    assert closed.models["a"].refusal == pytest.approx(0.5)
    dropped = score_store(prompts, ["a"], store, closed=set(), dropped={"volume surge"})
    assert dropped.models["a"].refusal == pytest.approx(0.5)


def test_missing_values_are_never_zero(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    data = {
        "a": {
            "p0": [
                {
                    "text": GOOD_PROPOSAL,
                    "provider": None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "latency_ms": None,
                }
            ]
        }
    }
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=_spend(tmp_path))
    record = json.loads(next((store / "outputs" / "a").glob("*.json")).read_text())
    assert record["usd"] is None and record["usd_reason"] and record["provider_reason"]
    reading = score_store(prompts, ["a"], store, closed=set(), dropped=set()).models["a"]
    assert reading.cost_per_call is None and reading.latency_ms is None
    assert reading.cost_reason and reading.latency_reason


def test_cli_plan_writes_nothing_and_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "home"))
    folder = _prompts(tmp_path / "pr", 11)
    prices = _prices(tmp_path / "pr.toml")
    before = sorted(tmp_path.rglob("*"))
    args = ["bench", "plan", "--prompts", str(folder), "--prices", str(prices), "--samples"]
    ok = RUNNER.invoke(rdagent_app, [*args, "1", "--models", "a,b"])
    assert ok.exit_code == 0 and "22 calls" in ok.output
    over = RUNNER.invoke(rdagent_app, [*args, "3", "--models", "a,b"])
    assert over.exit_code == 2 and "60" in over.output
    assert before == sorted(tmp_path.rglob("*"))


def _reply(prompt_tokens: object, completion_tokens: object) -> dict[str, object]:
    return {
        "text": GOOD_PROPOSAL,
        "provider": "h",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": 1.0,
    }


def test_month_cap_is_shared_by_every_store(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    spend = _spend(tmp_path)
    spend.parent.mkdir(parents=True)
    now = datetime.now(UTC).isoformat()
    spend.write_text(json.dumps({"ts": now, "usd": 49.9999}) + "\n")
    client = FakeClient({"a": {"p0": [_reply(1000, 500)]}})
    # A new, empty output folder does not reset what was spent this month.
    with pytest.raises(BenchError, match="50"):
        run_bench(prompts, ["a"], 1, prices, client, tmp_path / "new-store", spend=spend)
    assert client.calls == 0


def test_actual_spend_over_the_run_cap_stops_the_run(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 3), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["b"])
    # The model talks far more than the recorded counts: 2 million tokens out is 12 USD.
    client = FakeClient({"b": {f"p{i}": [_reply(1000, 2_000_000)] for i in range(3)}})
    with pytest.raises(BenchError, match="10"):
        run_bench(prompts, ["b"], 1, prices, client, tmp_path / "store", spend=_spend(tmp_path))
    assert client.calls == 1
    assert len(list((tmp_path / "store" / "outputs" / "b").glob("*.json"))) == 1


def test_a_call_without_token_counts_is_charged_its_estimate(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = FakeClient({"a": {"p0": [_reply(None, None)]}})
    spend = _spend(tmp_path)
    run_bench(prompts, ["a"], 1, prices, client, tmp_path / "store", spend=spend)
    rows = [json.loads(line) for line in spend.read_text().splitlines()]
    assert [r["usd"] for r in rows] == [pytest.approx(0.002, rel=1e-9, abs=1e-12)]
    assert rows[0]["estimated"] is True


@pytest.mark.parametrize(
    "url",
    ["http://localhost.example.com:8000", "http://127.0.0.1.example.com", "https://example.com"],
)
def test_gateway_address_off_this_machine_is_refused(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_BENCH_GATEWAY_TOKEN", "test-token")
    prompt = StoredPrompt("p0", "proposal", [], 1, 1)

    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("the bench opened a connection")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    with pytest.raises(BenchError, match="this machine"):
        GatewayClient({"a": url}).complete("a", prompt, 0)


def test_cli_run_refuses_a_store_outside_the_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "home"))
    args = ["bench", "run", "--prompts", str(_prompts(tmp_path / "pr", 1)), "--models", "a"]
    args += ["--prices", str(_prices(tmp_path / "pr.toml"))]
    fixture = ["--fixture", str(_fixture(tmp_path / "fx.json", 1))]
    outside = RUNNER.invoke(rdagent_app, [*args, *fixture, "--store", str(tmp_path / "out")])
    assert outside.exit_code == 2 and "data home" in outside.output
    assert not (tmp_path / "out").exists()
    inside = RUNNER.invoke(rdagent_app, [*args, *fixture, "--store", str(tmp_path / "home" / "b")])
    assert inside.exit_code == 0, inside.output
    assert _spend(tmp_path).is_file()
