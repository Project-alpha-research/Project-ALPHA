"""ml_contract.py hands the replay-signal code to ml_replay_signal.py: a pure move."""

from __future__ import annotations

import importlib
import inspect

from typer.testing import CliRunner

from alpha_cli import _ml_replay, ml_cmds, ml_contract

NEW_MODULE = "alpha_cli.ml_replay_signal"
MOVED = ("evaluate_result_bundle", "replay_signal_frame", "publish_replay_signal_frame")


def test_moved_names_are_defined_in_ml_replay_signal() -> None:
    module = importlib.import_module(NEW_MODULE)
    for name in MOVED:
        obj = getattr(module, name)
        assert callable(obj)
        assert obj.__module__ == NEW_MODULE, name


def test_ml_contract_no_longer_holds_moved_names() -> None:
    # No facade or re-export shim is left behind in the old module.
    for name in MOVED:
        assert not hasattr(ml_contract, name), name


def test_importers_look_up_moved_names_in_new_module() -> None:
    assert vars(ml_cmds)["evaluate_result_bundle"].__module__ == NEW_MODULE
    assert vars(ml_cmds)["publish_replay_signal_frame"].__module__ == NEW_MODULE
    assert vars(_ml_replay)["replay_signal_frame"].__module__ == NEW_MODULE


def test_ml_contract_keeps_shared_names() -> None:
    for name in (
        "MIN_SYMBOLS",
        "MIN_ALIGNED_SESSIONS",
        "canonical_json_bytes",
        "sha256_file",
        "validate_result_bundle",
        "validate_request_bundle",
        "prepare_exchange",
        "MLContractError",
    ):
        assert hasattr(ml_contract, name), name


def test_ml_contract_does_not_import_new_module() -> None:
    # The new module imports from ml_contract, never the other way.
    assert "ml_replay_signal" not in inspect.getsource(ml_contract)


def test_ml_help_still_lists_evaluate_and_prepare_replay() -> None:
    result = CliRunner().invoke(ml_cmds.ml_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "evaluate" in result.output
    assert "prepare-replay" in result.output
