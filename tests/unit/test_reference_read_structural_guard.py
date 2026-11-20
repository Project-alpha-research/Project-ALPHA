"""The descriptive reference read is used only by descriptive toolbox entries."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = "read_reference_for_period"
MODULE = "toolbox.reference"
# Files that may name the helper, and files that may import its module.
CALLERS = {"apps/alpha-cli/src/alpha_cli/toolbox/families/context.py"}
IMPORTERS = CALLERS | {"apps/alpha-cli/src/alpha_cli/toolbox/inputs.py"}
HOME = "apps/alpha-cli/src/alpha_cli/toolbox/reference.py"


def _sources() -> list[Path]:
    roots = [*ROOT.glob("packages/*/src"), *ROOT.glob("apps/*/src"), ROOT / "workers"]
    return [p for root in roots for p in root.rglob("*.py") if ".venv" not in p.parts]


def test_only_descriptive_entries_use_the_reference_read() -> None:
    misuse: list[str] = []
    for path in _sources():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel != HOME and rel not in CALLERS and HELPER in text:
            misuse.append(f"{rel} names {HELPER}")
        if rel != HOME and rel not in IMPORTERS and MODULE in text:
            misuse.append(f"{rel} imports {MODULE}")
    assert not misuse, "\n".join(misuse)


def test_the_guard_sees_the_real_files() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _sources()}
    assert HOME in names and names >= CALLERS
    assert any(n.startswith("workers/") for n in names)
    assert any("alpha-strategies" in n for n in names)
