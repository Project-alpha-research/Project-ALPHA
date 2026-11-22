"""The replay bench: plan arithmetic and caps, resume, paired scoring, no loop state touched."""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.rdagent_bench_clients import FakeClient, GatewayClient
from alpha_cli.rdagent_bench_model import (
    BenchError,
    Reply,
    StoredPrompt,
    load_prices,
    load_prompts,
    make_plan,
)
from alpha_cli.rdagent_bench_run import run_bench
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


def test_a_changed_prompt_under_the_same_id_is_not_served_from_the_store(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 1)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = FakeClient({"a": {"p0": [_reply(1000, 500)]}})
    store = tmp_path / "store"
    run_bench(load_prompts(folder, None), ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    row = json.loads((folder / "p0.json").read_text())
    row["messages"] = [{"role": "user", "content": "a different idea"}]
    (folder / "p0.json").write_text(json.dumps(row))
    with pytest.raises(BenchError, match="changed"):
        run_bench(
            load_prompts(folder, None), ["a"], 1, prices, client, store, spend=_spend(tmp_path)
        )
    assert client.calls == 1


def test_composite_variables_reach_the_family_check(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    text = json.dumps(
        {
            "name": "Composite Signal",
            "description": "declared_direction: +1; primary_clock: weekly; direction_reason: x.",
            "variables": {"momentum_12_1": "x", "volume_surge": "y"},
        }
    )
    reply = {**_reply(1, 1), "text": text}
    store = tmp_path / "store"
    run_bench(
        prompts, ["a"], 1, prices, FakeClient({"a": {"p0": [reply]}}), store, spend=_spend(tmp_path)
    )
    closed = {"past return (momentum or reversal)"}
    scored = score_store(prompts, ["a"], store, closed=closed, dropped=set())
    assert scored.models["a"].refusal == pytest.approx(1.0)


def test_worker_response_keyed_by_factor_name_is_scored(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    declared = "declared_direction: +1; primary_clock: weekly; direction_reason: x."
    text = json.dumps(
        {
            "Volume Surge": {"description": declared, "plain_summary": "s"},
            "Short-term Reversal": {"description": declared, "variables": {}},
        }
    )
    reply = {**_reply(1, 1), "text": text}
    store = tmp_path / "store"
    run_bench(
        prompts, ["a"], 1, prices, FakeClient({"a": {"p0": [reply]}}), store, spend=_spend(tmp_path)
    )
    closed = {"past return (momentum or reversal)"}
    scored = score_store(prompts, ["a"], store, closed=closed, dropped=set())
    assert scored.models["a"].buildable == pytest.approx(1.0)
    assert scored.models["a"].refusal == pytest.approx(0.5)


def test_resume_is_checked_against_the_calls_still_missing(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 2)
    for file in folder.glob("*.json"):
        row = json.loads(file.read_text())
        row["prompt_tokens"], row["completion_tokens"] = 4_000_000, 0
        file.write_text(json.dumps(row))
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    spend = _spend(tmp_path)
    spend.parent.mkdir(parents=True)
    spend.write_text(json.dumps({"ts": datetime.now(UTC).isoformat(), "usd": 42.0}) + "\n")
    client = FakeClient({"a": {f"p{i}": [_reply(4_000_000, 0)] for i in range(2)}})
    store = tmp_path / "store"
    first = run_bench(prompts, ["a"], 1, prices, client, store, spend=spend, max_new_calls=1)
    assert first.new_calls == 1
    second = run_bench(prompts, ["a"], 1, prices, client, store, spend=spend)
    # The last call ends exactly at the 50 USD cap, which is allowed.
    assert second.new_calls == 1 and second.finished


def test_a_resume_does_not_reset_the_run_budget(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 3), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["b"])
    client = FakeClient({"b": {f"p{i}": [_reply(1000, 2_000_000)] for i in range(3)}})
    store = tmp_path / "store"
    for _ in range(3):
        with pytest.raises(BenchError, match="10"):
            run_bench(prompts, ["b"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 1


def test_feedback_outputs_use_the_feedback_check_and_other_stages_are_not_checked(
    tmp_path: Path,
) -> None:
    folder = _prompts(tmp_path / "pr", 1, "feedback")
    other = _prompts(tmp_path / "pr2", 1, "mystery")
    (folder / "q0.json").write_text((other / "p0.json").read_text().replace("p0", "q0"))
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    feedback = json.dumps({"Observations": "o", "Reasoning": "r", "Replace Best Result": False})
    data = {
        "a": {
            "p0": [{**_reply(1, 1), "text": feedback}],
            "q0": [{**_reply(1, 1), "text": "anything"}],
        }
    }
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=_spend(tmp_path))
    reading = score_store(prompts, ["a"], store, closed=set(), dropped=set()).models["a"]
    # The feedback reply is buildable; the unknown stage is left out, not counted as a failure.
    assert reading.buildable == pytest.approx(1.0)
    assert reading.not_checked == 1


def test_the_default_report_reads_every_stored_sample(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    bad = {**_reply(1, 1), "text": "not json"}
    data = {"a": {"p0": [{**_reply(1, 1)}] * 10 + [bad] * 10}}
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 20, prices, FakeClient(data), store, spend=_spend(tmp_path))
    reading = score_store(prompts, ["a"], store, closed=set(), dropped=set()).models["a"]
    assert reading.outputs == 20 and reading.buildable == pytest.approx(0.5)


def test_the_gateways_reported_charge_is_what_is_booked(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    data = {"a": {"p0": [{**_reply(1000, 500), "cost": 1.0}]}}
    spend = _spend(tmp_path)
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=spend)
    rows = [json.loads(line) for line in spend.read_text().splitlines()]
    # A reservation of the estimate, then a settlement to the reported charge.
    assert sum(r["usd"] for r in rows) == pytest.approx(1.0)
    assert rows[-1]["estimated"] is False
    record = json.loads(next((store / "outputs" / "a").glob("*.json")).read_text())
    assert record["usd"] == pytest.approx(1.0) and record["usd_source"] == "reported by the gateway"


def test_duplicate_model_names_are_refused_before_any_call(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = FakeClient({"a": {"p0": [_reply(1000, 500)]}})
    with pytest.raises(BenchError, match="twice"):
        run_bench(
            prompts, ["a", "a"], 1, prices, client, tmp_path / "store", spend=_spend(tmp_path)
        )
    assert client.calls == 0


@pytest.mark.parametrize("cost", [-5.0, float("nan"), float("inf")])
def test_a_reported_cost_that_is_negative_or_not_finite_is_refused(
    tmp_path: Path, cost: float
) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 2), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    # A negative or NaN charge would lower the spend so far and open the caps.
    client = FakeClient({"a": {f"p{i}": [{**_reply(1, 1), "cost": cost}] for i in range(2)}})
    with pytest.raises(BenchError, match="cost"):
        run_bench(prompts, ["a"], 1, prices, client, tmp_path / "store", spend=_spend(tmp_path))
    assert not _spend(tmp_path).exists() or "NaN" not in _spend(tmp_path).read_text()


def test_model_names_that_look_alike_keep_separate_output_folders(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    names = ["a/b", "a__b"]
    prices_file = tmp_path / "pr.toml"
    prices_file.write_text(
        '["a/b"]\nin_per_mtok = 1.0\nout_per_mtok = 2.0\n'
        '["a__b"]\nin_per_mtok = 1.0\nout_per_mtok = 2.0\n'
    )
    prices = load_prices(prices_file, names)
    data = {name: {"p0": [_reply(1000, 500)]} for name in names}
    client = FakeClient(data)
    spend = _spend(tmp_path)
    run_bench(prompts, names, 1, prices, client, tmp_path / "store", spend=spend)
    assert client.calls == 2 and len(spend.read_text().splitlines()) == 2


def test_prompt_ids_with_dots_do_not_share_samples(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 1)
    row = json.loads((folder / "p0.json").read_text())
    (folder / "short.json").write_text(json.dumps({**row, "id": "p"}))
    (folder / "long.json").write_text(json.dumps({**row, "id": "p.extra"}))
    prompts = [p for p in load_prompts(folder, None) if p.id in ("p", "p.extra")]
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    good = {**_reply(1, 1)}
    bad = {**_reply(1, 1), "text": "not json"}
    data = {"a": {"p": [good], "p.extra": [bad, bad]}}
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=_spend(tmp_path))
    run_bench(
        [q for q in prompts if q.id == "p.extra"],
        ["a"],
        2,
        prices,
        FakeClient(data),
        store,
        spend=_spend(tmp_path),
    )
    scored = score_store(prompts, ["a"], store, closed=set(), dropped=set()).models["a"]
    assert scored.outputs == 3
    assert scored.by_prompt["p"] == pytest.approx(1.0)
    assert scored.by_prompt["p.extra"] == pytest.approx(0.0)


class _FailingClient:
    """A client whose calls fail after the provider may have taken the request."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply:
        self.calls += 1
        raise TimeoutError("the provider timed out")


def test_a_failed_call_is_charged_its_estimate(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    spend = _spend(tmp_path)
    with pytest.raises(TimeoutError):
        run_bench(prompts, ["a"], 1, prices, _FailingClient(), tmp_path / "store", spend=spend)
    rows = [json.loads(line) for line in spend.read_text().splitlines()]
    assert [r["usd"] for r in rows] == [pytest.approx(0.002, rel=1e-9, abs=1e-12)]
    assert rows[0]["estimated"] is True


def test_repeated_failed_calls_reach_the_run_cap(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 2)
    for file in folder.glob("*.json"):
        row = json.loads(file.read_text())
        row["prompt_tokens"], row["completion_tokens"] = 4_500_000, 0
        file.write_text(json.dumps(row))
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = _FailingClient()
    store = tmp_path / "store"
    for _ in range(2):
        with pytest.raises(TimeoutError):
            run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    # 9 USD is already charged for the two failed attempts: a third would pass the 10 USD cap.
    with pytest.raises(BenchError, match="10"):
        run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 2


def test_a_call_in_flight_is_reserved_in_the_shared_month_ledger(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 1)
    row = json.loads((folder / "p0.json").read_text())
    row["prompt_tokens"], row["completion_tokens"] = 1_000_000, 0  # one USD at the test price
    (folder / "p0.json").write_text(json.dumps(row))
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    spend = _spend(tmp_path)
    spend.parent.mkdir(parents=True)
    spend.write_text(json.dumps({"ts": datetime.now(UTC).isoformat(), "usd": 48.5}) + "\n")
    outcome: list[str] = []
    second = FakeClient({"a": {"p0": [_reply(1_000_000, 0)]}})

    class _Racing:
        """While this call is in flight, a second bench process asks for the same last dollar."""

        calls = 0

        def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply:
            try:
                run_bench(prompts, ["a"], 1, prices, second, tmp_path / "other", spend=spend)
                outcome.append("second run was allowed")
            except BenchError:
                outcome.append("second run was refused")
            return Reply("{}", "h", 1_000_000, 0, 1.0)

    run_bench(prompts, ["a"], 1, prices, _Racing(), tmp_path / "store", spend=spend)
    assert outcome == ["second run was refused"]


def test_failed_dispatches_count_against_the_call_cap(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = _FailingClient()
    store = tmp_path / "store"
    for _ in range(60):
        with pytest.raises(TimeoutError):
            run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    with pytest.raises(BenchError, match="60"):
        run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 60


def test_each_gateway_gets_its_own_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            body = {"choices": [{"message": {"content": "x"}}], "usage": {}}
            return json.dumps(body).encode()

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        seen[request.full_url] = request.get_header("Authorization")
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.delenv("ALPHA_BENCH_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_BENCH_TOKEN_A_B", "token-one")
    monkeypatch.setenv("ALPHA_BENCH_TOKEN_C", "token-two")
    client = GatewayClient({"a/b": "http://127.0.0.1:1", "c": "http://127.0.0.1:2"})
    prompt = StoredPrompt("p0", "proposal", [], 1, 1)
    client.complete("a/b", prompt, 0)
    client.complete("c", prompt, 0)
    assert seen["http://127.0.0.1:1/v1/chat/completions"] == "Bearer token-one"
    assert seen["http://127.0.0.1:2/v1/chat/completions"] == "Bearer token-two"
    with pytest.raises(BenchError, match="ALPHA_BENCH_TOKEN_D"):
        GatewayClient({"a": "http://127.0.0.1:1", "d": "http://127.0.0.1:3"}).complete(
            "d", prompt, 0
        )


def test_a_code_reply_in_a_json_envelope_is_checked_on_the_code_inside(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 4, "code")
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    texts = {
        "p0": json.dumps({"code": "def f():\n    return 1\n"}),
        "p1": json.dumps({"code": "def f(:\n pass"}),
        "p2": json.dumps({"code": ""}),
        "p3": "def g():\n    return 2\n",
    }
    data = {"a": {k: [{**_reply(1, 1), "text": v}] for k, v in texts.items()}}
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, FakeClient(data), store, spend=_spend(tmp_path))
    reading = score_store(prompts, ["a"], store, closed=set(), dropped=set()).models["a"]
    assert reading.by_prompt == {"p0": 1.0, "p1": 0.0, "p2": 0.0, "p3": 1.0}


def test_a_store_keeps_one_run_budget_when_the_models_change(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 1)
    row = json.loads((folder / "p0.json").read_text())
    row["prompt_tokens"], row["completion_tokens"] = 6_000_000, 0  # 6 USD at the test price
    (folder / "p0.json").write_text(json.dumps(row))
    prompts = load_prompts(folder, None)
    same = tmp_path / "same.toml"
    same.write_text(
        "[a]\nin_per_mtok = 1.0\nout_per_mtok = 2.0\n[b]\nin_per_mtok = 1.0\nout_per_mtok = 2.0\n"
    )
    prices = load_prices(same, ["a", "b"])
    one = {"a": {"p0": [_reply(6_000_000, 0)]}, "b": {"p0": [_reply(6_000_000, 0)]}}
    client = FakeClient(one)
    store = tmp_path / "store"
    run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    # Model b would cost 6 USD more in this store: 12 USD in all, over the 10 USD run cap.
    with pytest.raises(BenchError, match="10"):
        run_bench(prompts, ["b"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 1


def test_a_store_in_use_by_another_run_is_refused_before_any_call(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    store = tmp_path / "store"
    store.mkdir()
    client = FakeClient({"a": {"p0": [_reply(1000, 500)]}})
    with (store / ".run.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(BenchError, match="Another bench run"):
            run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 0


def test_each_call_reserves_against_the_month_it_is_made_in(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 2)
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    spend = _spend(tmp_path)
    spend.parent.mkdir(parents=True)
    # November's cap is untouched; December already holds 50 USD from another bench run.
    spend.write_text(json.dumps({"ts": "2026-12-01T00:00:01+00:00", "usd": 50.0}) + "\n")
    times = iter(
        [
            datetime(2026, 11, 30, 23, 59, tzinfo=UTC),  # plan and first call
            datetime(2026, 11, 30, 23, 59, tzinfo=UTC),
            datetime(2026, 12, 1, 0, 1, tzinfo=UTC),  # second call, next month
        ]
    )
    client = FakeClient({"a": {f"p{i}": [_reply(1000, 500)] for i in range(2)}})
    with pytest.raises(BenchError, match="50"):
        run_bench(
            prompts,
            ["a"],
            1,
            prices,
            client,
            tmp_path / "store",
            spend=spend,
            clock=lambda: next(times),
        )
    assert client.calls == 1


class _InterruptedClient:
    """A client stopped by Ctrl-C while the paid request is in flight."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, model: str, prompt: StoredPrompt, sample: int) -> Reply:
        self.calls += 1
        raise KeyboardInterrupt


def test_an_interrupted_dispatch_still_counts_against_the_call_cap(tmp_path: Path) -> None:
    prompts = load_prompts(_prompts(tmp_path / "pr", 1), None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    client = _InterruptedClient()
    store = tmp_path / "store"
    for _ in range(60):
        with pytest.raises(KeyboardInterrupt):
            run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    with pytest.raises(BenchError, match="60"):
        run_bench(prompts, ["a"], 1, prices, client, store, spend=_spend(tmp_path))
    assert client.calls == 60


def test_the_report_refuses_outputs_made_from_a_different_prompt(tmp_path: Path) -> None:
    folder = _prompts(tmp_path / "pr", 1)
    prompts = load_prompts(folder, None)
    prices = load_prices(_prices(tmp_path / "pr.toml"), ["a"])
    store = tmp_path / "store"
    run_bench(
        prompts,
        ["a"],
        1,
        prices,
        FakeClient({"a": {"p0": [_reply(1000, 500)]}}),
        store,
        spend=_spend(tmp_path),
    )
    row = json.loads((folder / "p0.json").read_text())
    row["messages"] = [{"role": "user", "content": "a different request"}]
    (folder / "p0.json").write_text(json.dumps(row))
    with pytest.raises(BenchError, match="changed"):
        score_store(load_prompts(folder, None), ["a"], store, closed=set(), dropped=set())
