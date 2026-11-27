"""The fast pull-request check always runs the repo-wide guards that read files they never import.

These tests read source, docs, workflows, CSS or generated files instead of importing the code
they guard, so the import mapping of `gate_select.select` cannot pick them up from a far change.
"""

from pathlib import Path

import gate_select

ROOT = Path(__file__).resolve().parents[2]

FAR_READING_GUARDS = (
    "tests/unit/test_calendar_home_guard.py",
    "tests/unit/test_context_attach_guard.py",
    "tests/unit/test_options_forward_guard.py",
    "tests/unit/test_reference_read_structural_guard.py",
    "tests/unit/test_research_boundary.py",
    "tests/unit/test_research_reads_are_cut.py",
    "tests/unit/test_reserved_confirmation_surfaces.py",
    "tests/unit/test_no_workaround_comments.py",
    "tests/unit/test_follow_separation.py",
    "tests/unit/test_cli_registry.py",
    "tests/unit/test_checks_reference.py",
    "tests/unit/test_ci_backend_bootstrap.py",
    "tests/unit/test_docs_links.py",
    "tests/unit/test_docs_work_pointers_at_tag.py",
    "tests/unit/test_repo_awareness_drift.py",
    "tests/unit/test_overlay_tables_drift.py",
    "tests/unit/test_theme_drift.py",
    "tests/unit/test_web_owner_actions_drift.py",
    "tests/unit/test_documentation_truth.py",
    "tests/unit/test_setup_script.py",
)

EARLIER_ENTRIES = (
    "tests/bias_guards",
    "tests/oracles",
    "tests/acceptance",
    "tests/unit/test_code_size.py",
    "tests/unit/test_reserved_date_one_home.py",
    "tests/unit/test_research_playbook.py",
    "tests/unit/test_filesystem_contract.py",
    "tests/unit/test_spine_spec.py",
    "tests/unit/test_capabilities.py",
    "tests/unit/test_status_page.py",
    "tests/unit/test_filesystem_completeness.py",
    "tests/unit/test_web_menu_groups.py",
)


def _covered(entry: str, paths: list[str]) -> bool:
    return any(entry == p or entry.startswith(f"{p}/") for p in paths)


def test_always_names_every_far_reading_guard() -> None:
    assert len(FAR_READING_GUARDS) == 20
    missing = [f for f in FAR_READING_GUARDS if f not in gate_select.ALWAYS]
    assert missing == [], f"ALWAYS does not name: {missing}"


def test_a_far_change_still_runs_every_far_reading_guard() -> None:
    # A docs-only change maps to no test by import; the guards must still run.
    selection = gate_select.select(ROOT, ["docs/notes-that-import-nothing.md"])
    paths = selection.pytest_paths()
    missing = [f for f in FAR_READING_GUARDS if not _covered(f, paths)]
    assert missing == [], f"the pull-request check would skip: {missing}"


def test_the_far_reading_guards_exist_in_the_repository() -> None:
    absent = [f for f in FAR_READING_GUARDS if not (ROOT / f).is_file()]
    assert absent == []


def test_always_keeps_its_earlier_entries() -> None:
    dropped = [e for e in EARLIER_ENTRIES if e not in gate_select.ALWAYS]
    assert dropped == []


def test_every_always_entry_exists_and_is_listed_once() -> None:
    assert len(set(gate_select.ALWAYS)) == len(gate_select.ALWAYS)
    absent = [e for e in gate_select.ALWAYS if not (ROOT / e).exists()]
    assert absent == []
