"""Checkpoint recovery, inherited rounds and restored proposal history."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit._rdagent_support import judge_namespace, universe_run
from tests.unit._rdagent_support import unfinished_session as unfinished_session
from workers.rdagent import research_memory as memory


def test_resume_ignores_partial_checkpoint_and_records_abandonment(tmp_path: Path) -> None:
    old = tmp_path / "old/work/log/__session__"
    for folder, name in (("0", "4_record"), ("1", "1_coding")):
        (old / folder).mkdir(parents=True)
        (old / folder / name).write_bytes(b"checkpoint")
    current = tmp_path / "new"
    current.mkdir()
    plan = memory.prepare(
        tmp_path / "memory",
        run_id="new",
        run_dir=current,
        source_sha256="pin",
        judge_sha256="judge",
    )
    loaded = SimpleNamespace(trace=SimpleNamespace(hist=["completed-round"], scen="scene"))
    cls = Mock(return_value=SimpleNamespace(trace=SimpleNamespace(hist=[], scen="scene")))
    cls.load.return_value = loaded
    env = {
        **plan.env,
        "ALPHA_RDAGENT_CONTINUE_SESSION": str(old),
        "ALPHA_RDAGENT_CONTINUE_LOOPS": "1",
        "LOG_TRACE_PATH": str(current / "log"),
    }
    loop, total = memory.open_factor_loop(cls, SimpleNamespace(), 2, env)
    assert cls.load.call_args.args[0] == old / "0/4_record"
    assert loop.trace.hist == ["completed-round"]
    assert total == 2  # fresh scheduler, shared completed history
    abandoned = json.loads((tmp_path / "old/rounds.jsonl").read_text())
    assert abandoned["status"] == "abandoned_at_cap" and abandoned["loop"] == 1
    assert not (tmp_path / "old/evaluations.jsonl").exists()


def test_completed_rounds_add_to_inherited_count(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    old = tmp_path / "old"
    old_session = old / "work/log/__session__/0"
    old_session.mkdir(parents=True)
    (old_session / "4_record").touch()
    plan = memory.prepare(
        root, run_id="old", run_dir=old, source_sha256="pin", judge_sha256="judge"
    )
    memory.record(plan, run_id="old", run_dir=old, started_at="start", ended_at="end", secrets=())
    new = tmp_path / "new"
    own = new / "work/log/__session__/0"
    own.mkdir(parents=True)
    (own / "4_record").touch()
    plan = memory.prepare(
        root, run_id="new", run_dir=new, source_sha256="pin", judge_sha256="judge"
    )
    result = memory.record(
        plan, run_id="new", run_dir=new, started_at="start", ended_at="end", secrets=()
    )
    assert result["loops_before"] == 1 and result["loops_after"] == 2
    # A half-finished round in this run's own session is recorded as abandoned, not counted.
    (new / "work/log/__session__/1").mkdir()
    (new / "work/log/__session__/1/0_direct_exp_gen").touch()
    newer = tmp_path / "newer"
    (newer / "work/log/__session__/0").mkdir(parents=True)
    (newer / "work/log/__session__/0/4_record").touch()
    plan = memory.prepare(
        root, run_id="newer", run_dir=newer, source_sha256="pin", judge_sha256="judge"
    )
    assert plan.loops_before == 2
    # The previous session could not be loaded: the run started a new lineage of its own.
    event = {
        "schema": "AlphaRdagentMemoryEventV1",
        "code": "session-unloadable",
        "message": "The previous session could not be loaded.",
        "ts": "now",
    }
    (newer / "memory-events.jsonl").write_text(json.dumps(event) + "\n")
    result = memory.record(
        plan, run_id="newer", run_dir=newer, started_at="start", ended_at="end", secrets=()
    )
    assert result["loops_after"] == 1
    for _ in range(2):  # recording an abandoned round twice writes it once
        memory.close_unfinished_rounds(new / "work/log/__session__")
    abandoned = [json.loads(line) for line in (new / "rounds.jsonl").read_text().splitlines()]
    assert [(row["schema"], row["loop"]) for row in abandoned] == [
        ("AlphaRdagentRoundAbandonedV1", 1)
    ]


def test_current_universe_replaces_fallback_and_corrects_restored_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    ns = judge_namespace()
    context = {"hypothesis_and_feedback": "restored scenario"}
    ns["append_swing_context"](context, None)
    text = context["hypothesis_and_feedback"]
    assert "15" not in text
    assert text.endswith("earlier text saying otherwise is out of date")
    assert "Current universe: 141 instruments, 66 later delisted" in text
    assert "141 instruments" in ns["AlphaFactorScenario"]().experiment_setting
    monkeypatch.setenv("ALPHA_FACTOR_UNIVERSE_TEXT", "15 surviving coins only")
    assert "15" not in ns["AlphaFactorScenario"]().experiment_setting


def test_round_history_uses_admitted_proposal_and_names_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._rdagent_support import (
        ProposingLoop,
        closed_volatility_ledger,
        proposal,
    )

    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    admitted = proposal("price_delay", "")

    class RecordingLoop(ProposingLoop):
        loop_prev_out: dict[int, dict[str, Any]]

    loop = RecordingLoop(ns, [admitted])
    loop.loop_prev_out = {0: {}}
    ns["FamilyGuard"](SimpleNamespace(develop=lambda exp: exp), loop).develop(
        proposal("vol_60d", "")
    )
    assert loop.loop_prev_out[0]["direct_exp_gen"]["exp_gen"] is admitted
    assert (
        "refused before coding: vol_60d (volatility and beta)"
        in admitted.alpha_refused_before_coding[0]
    )


def test_final_refusal_history_has_no_none_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit._rdagent_support import closed_volatility_ledger, proposal
    from workers.rdagent.loop_guard import RoundFeedback

    closed_volatility_ledger(tmp_path, monkeypatch)
    ns = judge_namespace()
    exp = proposal("vol_60d", "")
    with pytest.raises(ValueError):
        ns["FamilyGuard"](None).develop(exp)
    previous = {"direct_exp_gen": {"exp_gen": exp}, "exception": ValueError("refused")}

    def original(prev: Any) -> Any:
        return SimpleNamespace(observations=None, reason="refused", decision=False)

    result = RoundFeedback(original)(previous)
    assert result.observations == ""
    assert "refused before coding: vol_60d (volatility and beta)" in result.reason


def test_previous_run_judge_version_controls_warning(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    first = memory.prepare(
        root, run_id="first", run_dir=tmp_path, source_sha256="source", judge_sha256="current"
    )
    manifest = json.loads((root / "memory.json").read_text())
    session = tmp_path / "old-session"
    (session / "0").mkdir(parents=True)
    (session / "0/4_record").touch()
    manifest["latest_session"] = {
        "run_id": "old",
        "run_dir": str(tmp_path),
        "session_dir": str(session),
        "completed_loops": 1,
        "judge_sha256": "old",
        "recorded_at": "date",
    }
    manifest["runs"] = [
        {
            "run_id": "previous",
            "run_dir": str(tmp_path),
            "started_at": "date",
            "ended_at": "date",
            "continued_from_run_id": None,
            "loops_before": 0,
            "loops_after": 0,
            "knowledge_sha256_before": None,
            "knowledge_sha256_after": None,
            "judge_sha256": first.judge_sha256,
            "warnings": [],
        }
    ]
    (root / "memory.json").write_text(json.dumps(manifest))
    plan = memory.prepare(
        root, run_id="next", run_dir=tmp_path, source_sha256="source", judge_sha256="current"
    )
    assert "judge-version-changed" not in {w["code"] for w in plan.warnings}


def test_resume_error_is_not_abandoned_at_cap(tmp_path: Path, unfinished_session: Path) -> None:
    from workers.rdagent.research_memory import close_unfinished_rounds

    close_unfinished_rounds(unfinished_session)
    close_unfinished_rounds(unfinished_session)
    assert json.loads((tmp_path / "rounds.jsonl").read_text())["status"] == "abandoned_after_error"


def test_restored_proposal_text_keeps_four_same_panel_rounds(tmp_path: Path) -> None:
    history = []
    for i in range(21):
        exp = SimpleNamespace(
            alpha_panel_sha256="other" if i in (18, 20) else "current",
            sub_tasks=[
                SimpleNamespace(factor_name=f"price_delay_{i}", description="", variables={})
            ],
            alpha_evaluation={"factors": [{"name": f"price_delay_{i}", "status": "SCREEN_FAIL"}]},
        )
        history.append((exp, SimpleNamespace(observations=f"FULL ROUND {i}")))
    trace = SimpleNamespace(hist=history)
    closed = "Closed families: volatility and beta; past return (momentum or reversal)"

    def prepare(current: Any) -> tuple[dict[str, Any], bool]:
        return {
            "hypothesis_and_feedback": "\n".join(f.observations for _, f in current.hist)
            + "\n"
            + closed,
            "last_hypothesis_and_feedback": current.hist[-1][1].observations
            if current.hist
            else "",
            "RAG": len(current.hist),
        }, True

    wrapper = memory.ProposalHistory(prepare, 21, "current")
    context, flag = wrapper(trace)
    text = context["hypothesis_and_feedback"]
    assert flag and text.count("FULL ROUND") == 4
    assert text.count("Restored round:") == 17
    assert text.count("different coin panel") == 2
    assert all(f"FULL ROUND {i}" in text for i in (15, 16, 17, 19))
    assert "FULL ROUND 20" not in context["last_hypothesis_and_feedback"]
    assert context["RAG"] == 21
    assert text.count(closed) == 1
    assert len(trace.hist) == 21 and trace.hist is history
    assert wrapper.counts(trace) == {"history_rounds_full": 4, "history_rounds_summarised": 17}


def test_restore_installs_history_view_on_both_proposal_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = tmp_path / "old/work/log/__session__/0"
    session.mkdir(parents=True)
    (session / "4_record").touch()
    run = tmp_path / "new"
    (run / "panel").mkdir(parents=True)
    (run / "panel/panel-receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    trace = SimpleNamespace(hist=[(SimpleNamespace(alpha_panel_sha256="same"), None)] * 21)
    cls = Mock()
    cls.load.return_value = SimpleNamespace(trace=trace)
    loop = SimpleNamespace(
        hypothesis_gen=SimpleNamespace(prepare_context=Mock()),
        hypothesis2experiment=SimpleNamespace(prepare_context=Mock()),
    )
    monkeypatch.setattr(memory, "_new_factor_loop", lambda *args: loop)
    restored, rounds = memory.open_factor_loop(
        cls,
        None,
        2,
        {
            "ALPHA_RDAGENT_MEMORY_DIR": str(tmp_path),
            "FACTOR_CoSTEER_knowledge_base_path": str(tmp_path / "absent"),
            "ALPHA_RDAGENT_CONTINUE_SESSION": str(session.parent),
            "ALPHA_RDAGENT_MEMORY_EVENTS": str(run / "memory-events.jsonl"),
            "ALPHA_FACTOR_RUN_DIR": str(run),
            "LOG_TRACE_PATH": str(run / "log"),
        },
    )
    assert restored is loop and rounds == 2 and loop.trace is trace
    assert isinstance(loop.hypothesis_gen.prepare_context, memory.ProposalHistory)
    assert isinstance(loop.hypothesis2experiment.prepare_context, memory.ProposalHistory)
    assert json.loads((run / "history-context.json").read_text()) == {
        "history_rounds_full": 4,
        "history_rounds_summarised": 17,
    }


def test_history_summary_retains_provider_failure_status() -> None:
    exp = SimpleNamespace(sub_tasks=[SimpleNamespace(factor_name="price_delay")])
    trace = SimpleNamespace(
        hist=[
            (
                exp,
                SimpleNamespace(
                    reason="coding_failed_provider_timeout: coding; 4 attempts, 720 seconds waited"
                ),
            )
        ]
    )
    wrapper = memory.ProposalHistory(
        lambda trace: ({"hypothesis_and_feedback": ""}, True), 1, "panel"
    )
    context, _ = wrapper(trace)
    assert (
        "price_delay; other: price_delay; coding_failed_provider_timeout"
        in context["hypothesis_and_feedback"]
    )


def test_empty_restored_trace_after_proposal_failure_remains_usable() -> None:
    original = {
        "hypothesis_and_feedback": "no previous rounds",
        "last_hypothesis_and_feedback": "no previous rounds",
    }
    wrapper = memory.ProposalHistory(lambda trace: (dict(original), True), 0, "panel")
    context, flag = wrapper(SimpleNamespace(hist=[]))
    assert flag and context == original


def test_restored_panel_comes_from_the_recorded_evaluation_inputs() -> None:
    # Real evaluation records carry the panel hash under "inputs" and on each factor row.
    def evaluated(name: str, panel: str) -> tuple[Any, Any]:
        exp = SimpleNamespace(
            sub_tasks=[SimpleNamespace(factor_name=name, description="", variables={})],
            alpha_evaluation={
                "inputs": {"panel_sha256": panel},
                "factors": [{"name": name, "status": "SCREEN_FAIL", "panel_sha256": panel}],
            },
        )
        return exp, SimpleNamespace(observations=f"FULL {name}")

    unevaluated = (
        SimpleNamespace(sub_tasks=[SimpleNamespace(factor_name="lost")], alpha_evaluation=None),
        SimpleNamespace(reason="coding_failed_provider_timeout: coding", observations="FULL lost"),
    )
    trace = SimpleNamespace(
        hist=[evaluated("old", "other"), unevaluated, evaluated("same", "current")]
    )

    def prepare(current: Any) -> tuple[dict[str, Any], bool]:
        return {"hypothesis_and_feedback": "\n".join(f.observations for _, f in current.hist)}, True

    wrapper = memory.ProposalHistory(prepare, 3, "current")
    text = wrapper(trace)[0]["hypothesis_and_feedback"]
    assert "FULL same" in text and "FULL old" not in text
    assert "Restored round: old; other: old; SCREEN_FAIL; different coin panel" in text
    assert "lost; other: lost; coding_failed_provider_timeout; coin panel not recorded" in text
    assert wrapper.counts(trace) == {"history_rounds_full": 1, "history_rounds_summarised": 2}


def test_restored_history_uses_evaluation_then_run_receipt_then_freeze(tmp_path: Path) -> None:
    paths = [tmp_path / str(i) for i in range(4)]
    for path in paths:
        (path / "panel").mkdir(parents=True)
    (paths[0] / "receipt.json").write_text(json.dumps({"panel_sha256": "other"}))
    (paths[1] / "receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    (paths[2] / "panel/panel-receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    history = [
        (SimpleNamespace(alpha_run_dir=str(path)), SimpleNamespace(reason="failed"))
        for path in paths
    ]
    history[0][0].alpha_evaluation = {"inputs": {"panel_sha256": "same"}}
    trace = SimpleNamespace(hist=history)
    wrapper = memory.ProposalHistory(Mock(), 4, "same")
    assert wrapper.counts(trace) == {"history_rounds_full": 3, "history_rounds_summarised": 1}
    summary = wrapper._summary(*history[3])
    assert "panel unknown" in summary and "different coin panel" not in summary
    assert "\n" not in summary


def test_legacy_checkpoint_only_assigns_its_own_rounds_to_run(tmp_path: Path) -> None:
    session = tmp_path / "old/work/log/__session__"
    session.mkdir(parents=True)
    (tmp_path / "old/receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    inherited, failed = SimpleNamespace(), SimpleNamespace()
    previous = SimpleNamespace(
        trace=SimpleNamespace(hist=[(inherited, None), (failed, None)]),
        loop_prev_out={0: {"direct_exp_gen": {"exp_gen": failed}, "coding": None}},
    )
    memory.restored_run_provenance(previous, session)
    wrapper = memory.ProposalHistory(Mock(), 2, "same")
    assert wrapper._panel(failed) == "same"
    assert wrapper._panel(inherited) is None
    assert wrapper.counts(previous.trace)["history_rounds_full"] == 1


def test_inherited_legacy_round_uses_its_workspace_run_receipt(tmp_path: Path) -> None:
    old = tmp_path / "old"
    (old / "panel").mkdir(parents=True)
    (old / "panel/panel-receipt.json").write_text(json.dumps({"panel_sha256": "same"}))
    exp = SimpleNamespace(
        experiment_workspace=SimpleNamespace(
            workspace_path=old / "work/git_ignore_folder/RD-Agent_workspace/frozen-uuid",
        )
    )
    wrapper = memory.ProposalHistory(Mock(), 1, "same")
    assert wrapper.counts(SimpleNamespace(hist=[(exp, None)]))["history_rounds_full"] == 1
