"""`alpha rdagent` needs no hand-written config: every path has a default."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import rdagent_defaults
from alpha_cli.rdagent_cmds import rdagent_app
from alpha_cli.rdagent_run_config import RdagentConfigError, load_config

RUNNER = CliRunner()


class Machine:
    """A synthetic checkout and data home. `installed` says whether the worker assets exist."""

    def __init__(self, root: Path, *, installed: bool) -> None:
        self.checkout = root / "checkout"
        self.home = root / "home"
        runtime = self.checkout / ".alpha" / "state" / "runtime"
        self.source = runtime / "rdagent-source"
        self.python = runtime / "rdagent-factor-py311" / "venv" / "bin" / "python"
        (self.checkout / "workers" / "rdagent").mkdir(parents=True)
        (self.checkout / "workers" / "rdagent" / "factor_loop_launch.py").write_text("")
        (self.checkout / ".venv" / "bin").mkdir(parents=True)
        (self.checkout / ".venv" / "bin" / "python").symlink_to(sys.executable)
        self.home.mkdir()
        if installed:
            self.source.mkdir(parents=True)
            self.python.parent.mkdir(parents=True)
            self.python.write_text("")


def machine(root: Path, monkeypatch: pytest.MonkeyPatch, *, installed: bool = True) -> Machine:
    made = Machine(root, installed=installed)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(made.home))
    monkeypatch.delenv("ALPHA_RDAGENT_SOURCE", raising=False)
    monkeypatch.delenv("ALPHA_FACTOR_PYTHON", raising=False)
    monkeypatch.setattr(rdagent_defaults, "find_checkout", lambda: made.checkout)
    return made


def test_every_path_has_a_default_from_the_home_and_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch)
    config = load_config(None, {})
    assert config.working_directory == m.checkout
    assert config.data_dir == m.home
    assert config.gateway_data_dir.parent.parent == m.home
    assert config.trial_ledger.parent.parent.parent == m.home
    assert config.rdagent_source == m.source
    assert config.factor_python == m.python


def test_the_environment_beats_the_default_for_the_two_worker_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, installed=False)
    other = tmp_path / "elsewhere"
    other.mkdir()
    py = other / "python"
    py.write_text("")
    config = load_config(None, {"ALPHA_RDAGENT_SOURCE": str(other), "ALPHA_FACTOR_PYTHON": str(py)})
    assert (config.rdagent_source, config.factor_python) == (other, py)


def test_a_file_with_one_key_keeps_the_defaults_for_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch)
    path = tmp_path / "rdagent.toml"
    path.write_text("loop_n = 3\n")
    config = load_config(path, {})
    assert config.loop_n == 3 and config.data_dir == m.home


def test_dry_run_needs_no_config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = machine(tmp_path, monkeypatch)
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Nothing was started." in result.output
    assert str(m.home / "runs" / "rdagent") in result.output
    assert not list(m.home.iterdir())  # a dry run writes nothing


def test_the_home_config_file_is_used_when_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch)
    (m.home / "rdagent.toml").write_text("loop_n = 7\n")
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert "loops: 7" in result.output


def test_a_dry_run_needs_no_factor_runtime_and_names_the_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch, installed=False)
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Nothing was started." in result.output
    assert str(m.home / "runs" / "rdagent") in result.output  # the full settings are shown
    named = [line for line in result.output.splitlines() if "factor runtime is missing" in line]
    assert len(named) == 1
    assert "rdagent_source" in named[0] and "factor_python" in named[0]
    assert "bash scripts/setup_rdagent.sh --with-factor-runtime" in named[0]
    assert not list(m.home.iterdir())  # a dry run writes nothing


def test_a_real_run_still_needs_the_factor_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, installed=False)
    result = RUNNER.invoke(rdagent_app, ["run"])
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)  # no traceback
    assert "rdagent_source" in result.output and "setup_rdagent.sh" in result.output


def test_a_dry_run_with_the_runtime_installed_prints_no_missing_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch)
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert "factor runtime is missing" not in result.output


def test_a_wrong_path_in_the_file_names_the_setting_and_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch)
    path = tmp_path / "rdagent.toml"
    path.write_text(f'data_dir = "{tmp_path / "nope"}"\n')
    with pytest.raises(RdagentConfigError) as caught:
        load_config(path, {})
    assert "data_dir" in str(caught.value) and "Fix:" in str(caught.value)


def test_an_explicit_config_that_is_missing_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch)
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run", "--config", str(tmp_path / "x.toml")])
    assert result.exit_code == 2 and "does not exist" in result.output


def test_no_checkout_is_one_plain_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    machine(tmp_path, monkeypatch)
    monkeypatch.setattr(rdagent_defaults, "find_checkout", lambda: None)
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert result.exit_code == 2
    assert "working_directory" in result.output and isinstance(result.exception, SystemExit)


def test_init_writes_a_config_that_loads_to_the_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch)
    result = RUNNER.invoke(rdagent_app, ["init"])
    assert result.exit_code == 0, result.output
    path = m.home / "rdagent.toml"
    assert str(path) in result.output
    assert load_config(path, {}) == load_config(None, {})
    again = RUNNER.invoke(rdagent_app, ["init"])
    assert again.exit_code == 2 and "already exists" in again.output


def test_init_says_what_it_could_not_find_and_what_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch, installed=False)
    result = RUNNER.invoke(rdagent_app, ["init"])
    assert result.exit_code == 0, result.output
    assert (m.home / "rdagent.toml").is_file()
    assert "Not found" in result.output
    assert "rdagent_source" in result.output and "factor_python" in result.output
    assert "bash scripts/setup_rdagent.sh --with-factor-runtime" in result.output


def test_a_data_home_inside_a_git_folder_is_refused_in_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = machine(tmp_path, monkeypatch)
    inside = tmp_path / "repo"
    (inside / ".git").mkdir(parents=True)
    home = inside / "data"
    home.mkdir()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = RUNNER.invoke(rdagent_app, ["run", "--dry-run"])
    assert result.exit_code == 2 and isinstance(result.exception, SystemExit)
    assert result.output.count("git") >= 1 and "data_dir" in result.output
    assert "ALPHA_DATA_DIR" in result.output
    assert len([x for x in result.output.splitlines() if "does not exist" in x or "git" in x]) == 1
    assert m.home.is_dir()


def test_init_gives_the_install_command_on_each_missing_worker_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, installed=False)
    result = RUNNER.invoke(rdagent_app, ["init"])

    lines = [ln for ln in result.output.splitlines() if ln.startswith("Not found:")]
    worker = [ln for ln in lines if "rdagent_source" in ln or "factor_python" in ln]
    assert len(worker) == 2
    assert all("bash scripts/setup_rdagent.sh --with-factor-runtime" in ln for ln in worker)
