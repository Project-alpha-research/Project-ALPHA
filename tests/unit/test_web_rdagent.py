"""Recorded RD-Agent projections, without sockets, real runs or model calls."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from alpha_web import _rdagent_runs as reader
from alpha_web.api import rdagent
from alpha_web.app import create_app


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data))
    monkeypatch.delenv("ALPHA_RDAGENT_RUNS_DIR", raising=False)
    root = tmp_path / "runs"
    for name, started, extra in [
        ("old", "2026-10-01T00:00:00+00:00", {}),
        (
            "new",
            "2026-11-01T00:00:00+00:00",
            {
                "counted_calls": 12,
                "local_embedding_calls": 3,
                "memory": {"rounds_completed": 2},
                "gateway_status": {
                    "this_run": {"usd": 0.2},
                    "caps": {"run_max_calls": 60, "run_max_usd": 10, "month_max_usd": 50},
                    "months": {"2026-11": {"usd": 1.3}},
                },
                "call_split": {
                    "chat_usage": {
                        "cache_hit_rate": 0.6,
                        "provider_calls": {"example": 12},
                        "summary": "One recorded provider.",
                    }
                },
                "call_cap_note": "Local embeddings are free.",
            },
        ),
        ("cap", "2026-11-02T00:00:00+00:00", {"exit_status": 1, "loop_reason": "budget_exhausted"}),
    ]:
        write_json(
            root / name / "receipt.json",
            {
                "schema": "AlphaRdagentFactorRunReceiptV1",
                "run_id": name,
                "started_at": started,
                "ended_at": started,
                "exit_status": 0,
                "loop_reason": "completed",
                **extra,
            },
        )
    write_json(root / "unrelated" / "receipt.json", {"schema": "SomeOtherReceipt"})
    write_json(
        root / "new" / "panel/panel-receipt.json",
        {
            "instruments": ["AAA", "BBB"],
            "universe_includes_delisted": True,
            "universe_text": "2 instruments, 1 later delisted",
            "instruments_ended_early": 1,
            "missing_instrument_days": 4,
            "identity_rescales": [{"instrument": "AAA", "ratio": 1000}],
        },
    )
    write_lines(
        root / "new/steps.jsonl",
        [
            {"loop": 0, "step": "coding", "event": "start", "ts": "2026-11-01T00:00:00Z"},
            {
                "loop": 0,
                "step": "coding",
                "event": "end",
                "ts": "2026-11-01T00:01:00Z",
                "status": "ok",
            },
        ],
    )
    write_lines(
        root / "new/rounds.jsonl",
        [
            {
                "status": "refused_closed_family",
                "closed_families": ["momentum"],
                "trial_created": False,
                "hypothesis": "PRIVATE MODEL OUTPUT",
                "message": "Refused closed families: momentum.",
            }
        ],
    )
    write_lines(
        root / "rdagent-trial-ledger/rdagent-factor-trials.jsonl",
        [
            {
                "schema": "AlphaRdagentFactorTrialV3",
                "run_id": "new",
                "name": "slow_rank",
                "description": "Slow relative returns.",
                "status": "CANDIDATE",
                "family_size": 9,
                "clocks": {
                    "weekly": {
                        "status": "PASS",
                        "q": 0.02,
                        "screen": {"mean_ic": 0.1},
                        "spread": {"status": "PASS", "mean_spread": 0.02},
                        "replay": {
                            "net_annual_excess": 0.03,
                            "haircuts_applied": 1,
                            "writeoff_instruments": ["BBB"],
                            "deflated_sharpe": {"dsr": 0.7, "n_trials": 5, "passed": False},
                        },
                    }
                },
                "environment": {"SECRET": "NEVER_RETURN"},
                "raw_prompt": "NEVER_RETURN",
            }
        ],
    )
    return root


def test_list_newest_first_and_recorded_fields(store: Path) -> None:
    result = rdagent.list_runs()
    assert [row.run_id for row in result.items] == ["cap", "new", "old"]
    assert result.items[0].outcome.value == "stopped by a cap"
    row = result.items[1]
    assert row.counted_calls.value == 12
    assert row.cost_usd.value == 0.2
    assert row.rounds_completed.value == 2
    assert row.universe_includes_delisted.value is True


def test_detail_preserves_figures_and_counts_only_recorded_rows(store: Path) -> None:
    result = rdagent.run_detail("new")
    assert result.funnel["passed_deflation"].value == 0
    assert result.funnel["passed_deflation"].basis
    factor = result.factors[0]
    assert factor.name.value == "slow_rank"
    assert factor.description.value == "Slow relative returns."
    assert "confirmation" in factor.sentence
    clock = factor.clocks["weekly"]
    assert clock.deflation["dsr"].value == 0.7
    assert clock.deflation["passed"].value is False
    assert clock.deflation["n_trials"].value == 5
    assert clock.replay["writeoff_instruments"].value == ["BBB"]
    assert result.refusals[0]["closed_families"].value == ["momentum"]
    assert len(result.timing) == 1
    assert result.timing[0]["ended_at"].value == "2026-11-01T00:01:00Z"
    assert result.timing[0]["minutes"].value == 1.0
    assert "recorded" in str(result.timing[0]["minutes"].basis)
    assert result.caps["month_usd"].used.value == 1.3
    assert result.cache["cache_hit_rate"].value == 0.6
    assert "PRIVATE MODEL OUTPUT" not in result.model_dump_json()
    assert "NEVER_RETURN" not in result.model_dump_json()


def test_legacy_nulls_missing_ledger_and_directory(store: Path) -> None:
    old = rdagent.run_detail("old")
    assert old.run.rounds_completed.value is None
    assert old.run.rounds_completed.reason == "not recorded by this run"
    (store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl").unlink()
    result = rdagent.run_detail("new")
    assert result.factors == []
    assert "ledger" in str(result.factor_reason).lower()
    assert reader.list_runs(store / "absent", store / "absent-ledger").items == []
    assert reader.list_runs(store / "absent", store / "absent-ledger").reason


@pytest.mark.parametrize("run_id", ["..", "../new", "/etc/passwd", "%2e%2e%2fnew", "unknown"])
def test_no_request_path_reaches_filesystem(store: Path, run_id: str) -> None:
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail(run_id)
    assert error.value.status_code == 404


def test_symlink_receipt_and_nested_files_refused(store: Path, tmp_path: Path) -> None:
    outside = tmp_path / "secret.json"
    write_json(outside, {"secret": "NEVER_RETURN"})
    (store / "linked").symlink_to(store / "new", target_is_directory=True)
    assert "linked" not in [row.folder for row in rdagent.list_runs().items]
    panel = store / "new/panel/panel-receipt.json"
    panel.unlink()
    panel.symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail("new")
    assert error.value.status_code == 422


def test_malformed_records_fail_loud(store: Path) -> None:
    (store / "new/steps.jsonl").write_text('{"bad":}\n')
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail("new")
    assert error.value.status_code == 422


def test_secret_redaction_and_override(store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_RDAGENT_RUNS_DIR", str(store))
    monkeypatch.setenv("EXAMPLE_API_KEY", "sensitive-test-value")
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    row["description"] = "description sensitive-test-value"
    write_lines(ledger, [row])
    assert "sensitive-test-value" not in rdagent.run_detail("new").model_dump_json()


def test_all_writer_statuses_have_sentences() -> None:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "apps/alpha-cli/src/alpha_cli/_rdagent_judge.py").read_text())
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "STATUSES" for t in node.targets)
    )
    assert isinstance(assignment.value, ast.Call)
    statuses = ast.literal_eval(assignment.value.args[0])
    assert statuses <= reader.STATUS_SENTENCES.keys()
    for status in statuses:
        assert reader.status_sentence(status, None)
    for reason in ("critic_rejected", "cap_reached", "exception", "bad_output"):
        assert reader.status_sentence("FAILED", reason) == reader.STATUS_SENTENCES[reason]
    assert reader.status_sentence("refused_closed_family", None)
    with pytest.raises(ValueError, match="status"):
        reader.status_sentence("NEW_UNMAPPED_STATUS", None)


def test_http_contract_without_sockets(store: Path) -> None:
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/rdagent/runs")
            assert response.status_code == 200
            response = await client.get("/api/rdagent/runs/new")
            assert response.status_code == 200
            assert response.json()["factors"][0]["status"] == "CANDIDATE"
            response = await client.get("/api/rdagent/runs/unknown")
            assert response.status_code == 404
            assert response.json()["code"] == "not_found"
            assert (await client.post("/api/rdagent/runs")).status_code == 405

    asyncio.run(exercise())


def test_current_panel_mapping_and_identity_policy(store: Path) -> None:
    path = store / "new/panel/panel-receipt.json"
    panel = json.loads(path.read_text())
    panel["instruments"] = {
        "AAA": {
            "first": "2021-01-01",
            "last": "2023-12-31",
            "missing_days": 0,
            "longest_gap": 0,
            "ends_early": False,
        }
    }
    panel["identity_jump_policy"] = {"min_gap_days": 7, "ratio": 100}
    panel["identity_rescales"] = [
        {"instrument": "AAA", "new_from": "2022-01-01", "reason": "redenominated", "ratio": 1000}
    ]
    write_json(path, panel)
    detail = rdagent.run_detail("new")
    assert detail.universe["instruments"].value == ["AAA"]
    assert detail.universe["identity_jump_policy.ratio"].value == 100
    assert detail.identity_rescales[0]["new_from"].value == "2022-01-01"


def test_actual_nested_replay_figures_and_counted_only(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    replay = row["clocks"]["weekly"]["replay"]
    replay.update(
        net={"annualized_return": 0.03, "sharpe": 0.4},
        gross={"annualized_return": 0.08},
        counted_only="spread check failed",
    )
    write_lines(ledger, [row])
    shown = rdagent.run_detail("new").factors[0].clocks["weekly"].replay
    assert shown["net.annualized_return"].value == 0.03
    assert shown["gross.annualized_return"].value == 0.08
    assert shown["counted_only"].value == "spread check failed"


def test_nested_newey_west_screen_figures_are_read_not_refused(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    row["clocks"]["weekly"].setdefault("screen", {})["newey_west"] = {
        "effective_n": 156.0,
        "lag": 5,
        "long_run_variance": 0.02,
    }
    write_lines(ledger, [row])
    shown = rdagent.run_detail("new").factors[0].clocks["weekly"].screen
    assert shown["newey_west.effective_n"].value == 156.0
    assert shown["newey_west.lag"].value == 5


def test_recorded_funnel_is_copied_without_deriving_counts(store: Path) -> None:
    path = store / "new/receipt.json"
    receipt = json.loads(path.read_text())
    receipt["funnel"] = {
        "proposed": 3,
        "code_ran": 2,
        "passed_rank_screen": 1,
        "refused_closed_family": 1,
        "stopped_by_provider": 0,
        "passed_spread_check": 1,
        "passed_deflation": 0,
    }
    write_json(path, receipt)
    detail = rdagent.run_detail("new")
    # A receipt written before the shortlist stage, over rows without the flag: not recorded.
    assert {key: value.value for key, value in detail.funnel.items()} == {
        **receipt["funnel"],
        "shortlisted": None,
    }
    assert detail.run.factors_proposed.value == 3


def test_status_sentences_cover_round_refusals_and_code_failure_reasons() -> None:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "workers/rdagent/alpha_factor_judge.py").read_text())
    runner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AlphaFactorRunner"
    )
    reasons: set[str] = set()
    for function in runner.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        if function.name == "text_reason":
            reasons.update(
                node.value.value
                for node in ast.walk(function)
                if isinstance(node, ast.Return)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
        if function.name == "execute_factor":
            for node in ast.walk(function):
                if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                    first = node.values[0]
                    if (isinstance(first, ast.Name) and first.id == "reason") or (
                        isinstance(first, ast.Call)
                        and isinstance(first.func, ast.Attribute)
                        and first.func.attr == "text_reason"
                    ):
                        reasons.update(
                            value.value
                            for value in node.values[1:]
                            if isinstance(value, ast.Constant) and isinstance(value.value, str)
                        )
    assert {"cap_reached", "exception", "critic_rejected", "bad_output"} <= reasons
    assert reasons <= reader.STATUS_SENTENCES.keys()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "status":
                    candidates = (
                        [value.body, value.orelse] if isinstance(value, ast.IfExp) else [value]
                    )
                    codes = {
                        n.value
                        for n in candidates
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    }
                    assert codes <= reader.STATUS_SENTENCES.keys()


def test_funnel_is_counted_from_recorded_rows_and_receipt_wins(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    base = json.loads(ledger.read_text())
    clock = {"status": "PASS", "spread": {"status": "PASS"}}
    rows = [
        {**base, "name": "a", "status": "CANDIDATE", "clocks": {"weekly": clock}},
        {
            **base,
            "name": "b",
            "status": "SCREEN_FAIL",
            "clocks": {"weekly": {"status": "SCREEN_FAIL"}},
        },
        {**base, "name": "c", "status": "FAILED", "clocks": {"weekly": {"status": "ERROR"}}},
        {**base, "name": "d", "status": "IMPORTED", "clocks": {"daily": {"status": "IMPORTED"}}},
        {
            **base,
            "name": "e",
            "status": "SPREAD_FAIL",
            "clocks": {"weekly": {"status": "SPREAD_FAIL"}},
        },
    ]
    rows[0]["clocks"]["weekly"]["replay"] = {"deflated_sharpe": {"passed": True}}
    write_lines(ledger, rows)
    funnel = {key: value.value for key, value in rdagent.run_detail("new").funnel.items()}
    assert funnel == {
        "proposed": 5,  # four own trials and one refused proposal
        "refused_closed_family": 1,
        "stopped_by_provider": 0,
        "code_ran": 3,
        "passed_rank_screen": 2,
        "passed_spread_check": 1,
        "shortlisted": None,  # these rows predate the shortlist flag: not recorded, never zero
        "passed_deflation": 1,
    }
    listed = {row.run_id: row for row in rdagent.list_runs().items}
    assert listed["new"].factors_proposed.value == 5
    assert listed["old"].factors_proposed.value is None
    assert rdagent.run_detail("old").funnel["proposed"].reason == "not recorded by this run"


def test_funnel_unknown_when_spread_check_not_recorded(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    base = json.loads(ledger.read_text())
    write_lines(
        ledger, [{**base, "status": "REPLAY_FAIL", "clocks": {"weekly": {"status": "REPLAY_FAIL"}}}]
    )
    funnel = rdagent.run_detail("new").funnel
    assert funnel["passed_spread_check"].value is None
    assert "spread check" in str(funnel["passed_spread_check"].reason)
    assert funnel["passed_rank_screen"].value == 1


def test_universe_size_counted_and_unfinished_step_has_no_minutes(store: Path) -> None:
    detail = rdagent.run_detail("new")
    assert detail.run.universe_size.value == 2
    assert detail.universe["instrument_count"].value == 2
    write_lines(
        store / "new/steps.jsonl",
        [
            {
                "loop": 0,
                "step": "coding",
                "step_index": 1,
                "event": "start",
                "ts": "2026-11-01T00:00:00Z",
            }
        ],
    )
    row = rdagent.run_detail("new").timing[0]
    assert row["minutes"].value is None
    assert row["minutes"].reason


def test_only_read_methods_exist_and_encoded_ids_are_refused(store: Path) -> None:
    for route in rdagent.router.routes:
        assert getattr(route, "methods", set()) <= {"GET", "HEAD"}

    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for run_id in (
                "..%2fnew",
                "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                "%2Fetc%2Fpasswd",
                "new%00",
            ):
                response = await client.get(f"/api/rdagent/runs/{run_id}")
                assert response.status_code in {404, 422}
                assert "NEVER_RETURN" not in response.text
            for method in ("PUT", "DELETE", "PATCH", "POST"):
                response = await client.request(method, "/api/rdagent/runs/new")
                assert response.status_code == 405

    asyncio.run(exercise())


def test_override_directory_carries_its_own_ledger(
    store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "elsewhere"
    (tmp_path / "moved").mkdir()
    store.rename(other)
    monkeypatch.setenv("ALPHA_RDAGENT_RUNS_DIR", str(other))
    assert rdagent.run_detail("new").factors[0].name.value == "slow_rank"


def test_older_ledger_rows_recorded_under_the_folder_name_are_found(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    write_lines(ledger, [{**row, "run_id": "old"}])
    assert rdagent.run_detail("old").factors[0].name.value == "slow_rank"


def test_long_bracketed_description_is_kept_whole_and_redacted(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXAMPLE_API_KEY", "sensitive-test-value")
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    text = "[Slow factor] " + "word " * 300 + "sensitive-test-value end"
    write_lines(ledger, [{**row, "description": text}])
    shown = str(rdagent.run_detail("new").factors[0].description.value)
    assert shown.startswith("[Slow factor] word")
    assert shown.endswith("[redacted] end")
    assert shown.count("word") == 300


def test_prose_slashes_survive_but_paths_are_redacted(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    text = "admitted/approval/promotion all false, read /home/someone/secret.txt now"
    write_lines(ledger, [{**row, "description": text}])
    shown = str(rdagent.run_detail("new").factors[0].description.value)
    assert "admitted/approval/promotion" in shown
    assert "someone" not in shown


def test_round_outcomes_of_the_loop_guard_and_resume_have_sentences() -> None:
    root = Path(__file__).resolve().parents[2]
    guard = ast.parse((root / "workers/rdagent/loop_guard.py").read_text())
    statuses = next(
        ast.literal_eval(node.value)
        for node in guard.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ROUND_STATUSES" for t in node.targets)
    )
    codes = set(statuses.values())
    memory = ast.parse((root / "workers/rdagent/research_memory.py").read_text())
    for node in ast.walk(memory):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "status":
                    branches = [value.body, value.orelse] if isinstance(value, ast.IfExp) else []
                    codes |= {
                        n.value
                        for n in branches
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    }
    assert {"coding_failed_provider_timeout", "abandoned_after_error"} <= codes
    for code in codes:
        assert reader.status_sentence(code, None)
    assert reader.status_sentence("DEFLATION_FAIL", None)


def test_story_links_tasks_by_evaluation_name_and_hash_not_loop_number(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    trial = {
        **json.loads(ledger.read_text()),
        "iteration": 4,
        "code_sha256": "a" * 64,
        "declared_direction": -1,
        "primary_clock": "weekly",
        "direction_reason": "Synthetic reason.",
        "shortlist": True,
        "diagnostics": {"daily": {"label": "diagnostic only: cannot pass"}},
        "twin": {"is_twin": True, "mean_abs_correlation": 0.99},
    }
    write_lines(ledger, [trial])
    write_lines(
        store / "new/evaluations.jsonl",
        [
            {
                "iteration": 4,
                "factors": [trial],
                "feedback_text": "Judge feedback.",
            }
        ],
    )
    write_lines(
        store / "new/rounds.jsonl",
        [
            {
                "iteration": 4,
                "tasks": [
                    {
                        "name": "slow_rank",
                        "code_sha256": "a" * 64,
                        "description": "The proposer's own words.",
                    }
                ],
                "feedback": {
                    "observations": "Try a different mechanism.",
                    "reason": "Stored reason.",
                },
            },
            {
                "iteration": 4,
                "status": "refused_missing_declaration",
                "attempt": 1,
                "factor_names": ["slow_rank", "second"],
                "trial_created": False,
                "message": "Direction was missing.",
            },
        ],
    )
    story = rdagent.run_detail("new").story
    assert story is not None
    assert len(story.ideas) == 3
    judged = next(idea for idea in story.ideas if idea.trial is not None)
    assert judged.description.value == "The proposer's own words."
    assert judged.feedback.value == "Try a different mechanism. Stored reason."
    assert judged.round_kind == "evaluation"
    assert judged.direction.value == -1
    assert story.journey["refused"].value == 2
    assert story.journey["judged"].value == 1
    assert story.journey["proposed"].value == 3
    refused = [idea for idea in story.ideas if idea.round_kind == "loop"]
    assert all(idea.trial is None and idea.feedback.value is None for idea in refused)
    assert "loop" in " ".join(story.missing_links).lower()


def test_story_never_joins_matching_names_with_different_hashes(store: Path) -> None:
    write_lines(
        store / "new/rounds.jsonl",
        [
            {
                "iteration": 0,
                "tasks": [{"name": "slow_rank", "code_sha256": "b" * 64}],
                "feedback": {"observations": "Must not attach to a different trial."},
            }
        ],
    )
    story = rdagent.run_detail("new").story
    assert story is not None
    trial = next(idea for idea in story.ideas if idea.trial is not None)
    assert trial.feedback.value is None
    assert trial.round.value is None
    assert story.journey["proposed"].value is None


def test_story_missing_counts_remain_unknown_and_partial_lines_are_disclosed(store: Path) -> None:
    story = rdagent.run_detail("old").story
    assert story is not None
    assert story.journey["proposed"].value is None
    assert story.journey["judged"].value is None
    (store / "new/evaluations.jsonl").write_text('{"iteration":')
    story = rdagent.run_detail("new").story
    assert story is not None
    assert any("still being written" in note for note in story.missing_links)


def test_story_keeps_tasks_without_hashes_and_never_counts_critic_events_twice(store: Path) -> None:
    write_lines(
        store / "new/rounds.jsonl",
        [
            {
                "iteration": 0,
                "tasks": [{"name": "old proposal", "description": "Stored words."}],
                "feedback": {"reason": "Stored round feedback."},
            },
            {
                "iteration": 1,
                "status": "critic_unavailable_provider_error",
                "factor_names": ["slow_rank"],
            },
        ],
    )
    story = rdagent.run_detail("new").story
    assert story is not None
    assert any(idea.description.value == "Stored words." for idea in story.ideas)
    assert story.journey["proposed"].value is None
    assert story.journey["judged"].value is None


def test_story_all_refused_has_zero_judged_and_preserves_refusal_text(store: Path) -> None:
    write_lines(
        store / "old/rounds.jsonl",
        [
            {
                "iteration": 0,
                "status": "refused_closed_family",
                "trial_created": False,
                "factor_names": ["first", "second"],
                "message": "Refused closed families: synthetic.",
            }
        ],
    )
    story = rdagent.run_detail("old").story
    assert story is not None
    assert story.journey["proposed"].value == 2
    assert story.journey["refused"].value == 2
    assert story.journey["judged"].value == 0
    assert story.ideas[0].refusal.value == "Refused closed families: synthetic."


@pytest.mark.parametrize(
    ("reason", "exit_status", "ending"),
    [
        ("completed", 0, "finished"),
        ("budget_exhausted", 1, "budget"),
        ("provider_timeout", 1, "provider"),
        (
            "Two consecutive rounds ended with an internal coding error; run stopped",
            1,
            "internal_error",
        ),
        ("an unknown error", 1, "error"),
    ],
)
def test_story_ending_is_the_run_ending_not_a_failed_round(
    store: Path,
    reason: str,
    exit_status: int,
    ending: str,
) -> None:
    path = store / "new/receipt.json"
    receipt = json.loads(path.read_text())
    write_json(path, {**receipt, "loop_reason": reason, "exit_status": exit_status})
    story = rdagent.run_detail("new").story
    assert story is not None
    assert story.ending == ending


def test_story_conflicting_links_fail_loud(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    trial = {**json.loads(ledger.read_text()), "iteration": 0, "code_sha256": "c" * 64}
    write_lines(ledger, [trial])
    write_lines(
        store / "new/evaluations.jsonl",
        [
            {"iteration": 0, "factors": [{**trial, "status": "SCREEN_FAIL"}]},
        ],
    )
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail("new")
    assert error.value.status_code == 422


def test_story_code_paths_cannot_escape_archive(store: Path, tmp_path: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    trial = {**json.loads(ledger.read_text()), "iteration": 0, "code_sha256": "d" * 64}
    write_lines(ledger, [trial])
    archive = store / "new/code"
    archive.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET CODE")
    (archive / ("d" * 64 + ".py")).symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail("new")
    assert error.value.status_code == 422


def test_story_preserves_legacy_evaluation_without_a_linkable_hash(store: Path) -> None:
    trial = {
        "schema": "AlphaRdagentFactorTrialV3",
        "name": "legacy idea",
        "run_id": "old",
        "status": "SCREEN_FAIL",
        "description": "Stored legacy description.",
    }
    write_lines(store / "old/evaluations.jsonl", [{"iteration": 3, "factors": [trial]}])
    story = rdagent.run_detail("old").story
    assert story is not None
    assert len(story.ideas) == 1
    assert story.ideas[0].description.value == "Stored legacy description."
    assert story.ideas[0].round.value == 3
    assert story.ideas[0].feedback.value is None


def test_story_rejects_evaluation_trials_from_a_different_run(store: Path) -> None:
    trial = {
        "schema": "AlphaRdagentFactorTrialV3",
        "name": "foreign idea",
        "run_id": "other",
        "status": "SCREEN_FAIL",
        "iteration": 3,
        "code_sha256": "a" * 64,
    }
    write_lines(store / "old/evaluations.jsonl", [{"iteration": 3, "factors": [trial]}])
    with pytest.raises(HTTPException) as error:
        rdagent.run_detail("old")
    assert error.value.status_code == 422


def test_story_provider_failure_before_any_proposal_records_zero_judged(store: Path) -> None:
    write_lines(
        store / "old/rounds.jsonl",
        [
            {
                "iteration": 0,
                "status": "proposal_failed_provider_timeout",
                "factor_names": [],
                "trial_created": False,
            }
        ],
    )
    story = rdagent.run_detail("old").story
    assert story is not None
    assert story.journey["judged"].value == 0
    assert story.events == ["proposal_failed_provider_timeout"]


def test_story_counts_recorded_ideas_when_a_later_round_died_before_recording_any(
    store: Path,
) -> None:
    write_lines(
        store / "old/rounds.jsonl",
        [
            {
                "iteration": 1,
                "status": "refused_closed_family",
                "trial_created": False,
                "factor_names": ["only_one"],
                "message": "Refused closed families: synthetic.",
            },
            {"loop": 1, "status": "abandoned_after_error", "trial_created": False},
        ],
    )
    story = rdagent.run_detail("old").story
    assert story is not None
    assert story.journey["proposed"].value == 1
    assert story.journey["refused"].value == 1
    assert story.journey["judged"].value == 0
    assert any("before any idea of it was recorded" in item for item in story.missing_links)


def test_story_failed_screen_is_not_shortlisted_even_in_old_rows(store: Path) -> None:
    ledger = store / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    row = json.loads(ledger.read_text())
    row["status"] = "SCREEN_FAIL"
    row.pop("shortlist", None)
    write_lines(ledger, [row])
    story = rdagent.run_detail("new").story
    assert story is not None
    assert all(idea.stages["shortlisted"] is False for idea in story.ideas)


def test_story_provider_stopped_coding_means_zero_coded_and_ran(store: Path) -> None:
    write_lines(
        store / "old/rounds.jsonl",
        [
            {
                "iteration": 0,
                "status": "coding_failed_provider_timeout",
                "factor_names": ["one", "two"],
                "trial_created": False,
            }
        ],
    )
    story = rdagent.run_detail("old").story
    assert story is not None
    assert [story.journey[key].value for key in ("proposed", "coded", "ran", "judged")] == [
        2,
        0,
        0,
        0,
    ]
