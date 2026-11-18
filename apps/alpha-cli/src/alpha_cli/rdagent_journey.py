"""Build read-only journeys from the judge's records. Publish only below journey/."""

from __future__ import annotations

import ast
import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from alpha_cli import rdagent_journey_words as words
from alpha_cli._rdagent_judge import RESERVED_START
from alpha_cli.figures import rdagent_journey_figures as charts
from alpha_cli.ledger_cmds import DEFAULT_RDAGENT_LEDGER
from alpha_core.atomic import write_text

Row = dict[str, Any]


def _read(path: Path) -> Row:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path}")
    return value


def _lines(path: Path) -> Iterator[Row]:
    if path.is_file():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Expected a recorded object in {path}")
                yield row


def _path(root: Path, relative: str | Path) -> Path:
    path = root / relative
    if not path.is_relative_to(root) or path.resolve() != path:
        raise ValueError(f"Path leaves the evidence or output folder: {path}")
    return path


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify(path: Path, expected: str | None) -> None:
    if expected and path.is_file() and _digest(path) != expected:
        raise ValueError(f"Recorded hash differs from {path}")


def _json(path: Path, value: object) -> None:
    write_text(path, json.dumps(value, allow_nan=False, indent=2, ensure_ascii=False) + "\n")


def _folder(iteration: int, row: Row) -> str:
    name, digest = row["name"], row["code_sha256"]
    if (
        type(iteration) is not int
        or iteration < 0
        or row.get("iteration", iteration) != iteration
        or not isinstance(name, str)
        or not name.strip()
        or Path(name).name != name
        or name in {".", ".."}
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise ValueError("Invalid judged idea identity")
    return f"{iteration}-{name}-{digest[:8]}"


def _evaluations(run: Path) -> Iterator[tuple[Path, Row]]:
    records: dict[int, tuple[Path, Row]] = {}
    log = _path(run, "evaluations.jsonl")
    for record in _lines(log):
        i = record["iteration"]
        if i in records:
            raise ValueError("Duplicate iteration in evaluations.jsonl")
        records[i] = log, record
    for p in _path(run, "evaluations").glob("iter-*/result.json"):
        record = _read(_path(run, p))
        i = record["iteration"]
        if p.parent.name != f"iter-{i}" or (i in records and records[i][1] != record):
            raise ValueError(f"Inconsistent evaluation identity or evidence at {p}")
        records[i] = p, record
    for i in sorted(records):
        yield records[i]


def _rounds(run: Path) -> dict[tuple[int, str, str], tuple[Row, Row]]:
    index = {}
    for record in _lines(_path(run, "rounds.jsonl")):
        for task in record.get("tasks", []):
            if record.get("iteration") is None or not task.get("code_sha256"):
                continue
            key = record["iteration"], task["name"], task["code_sha256"]
            if key in index:
                raise ValueError("Duplicate recorded round task")
            index[key] = task, record
    return index


def _ledger(run: Path) -> Path:
    launch = _path(run, "launch-command.json")
    if launch.is_file():
        argv = _read(launch)["argv"]
        for i, arg in enumerate(argv):
            if arg == "--trial-ledger" or arg.startswith("--trial-ledger="):
                path = Path(argv[i + 1] if arg == "--trial-ledger" else arg.split("=", 1)[1])
                if not path.is_absolute():
                    raise ValueError("Recorded trial ledger path must be absolute")
                return path
    return run.parent / DEFAULT_RDAGENT_LEDGER.relative_to("runs")


def _snippet(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        tree = ast.Module(body=[], type_ignores=[])
    assignments = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if (isinstance(target, ast.Name) and target.id in {name, "factor"}) or (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value in {name, "factor"}
                ):
                    assignments.append(node)
                    break
    if assignments:
        last = max(assignments, key=lambda n: n.lineno)
        start = last.lineno - 1
        # Include the immediately preceding calculation when it supplies an input.
        inputs = (
            {n.id for n in ast.walk(last.value) if isinstance(n, ast.Name)} if last.value else set()
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and node.end_lineno == start
                and any(isinstance(t, ast.Name) and t.id in inputs for t in node.targets)
            ):
                start = node.lineno - 1
                break
        end = last.end_lineno or last.lineno
        if end - start > 3:
            start = last.lineno - 1
        return "\n".join(lines[start : min(end, start + 3)])
    imports = {
        i
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for i in range(n.lineno, (n.end_lineno or n.lineno) + 1)
    }
    return "\n".join(
        [
            s
            for i, s in enumerate(lines, 1)
            if i not in imports and s.strip() and not s.lstrip().startswith(("import ", "from "))
        ][:12]
    )


def _bound_files(run: Path, folder: Path, row: Row, inputs: Row) -> dict[str, Path]:
    digest = row["code_sha256"]
    base = _path(run, folder / "series")
    paths = {
        kind: _path(run, base / f"{digest}.{kind}.parquet")
        for kind in ("screen", "buckets", "buckets_daily", "replay")
    }
    evidence = row.get("evidence", {})
    manifest = _path(run, base / "series.json")
    if evidence and _path(run, evidence["series_manifest"]) != manifest:
        raise ValueError("Series manifest belongs to another evaluation")
    if manifest.is_file():
        _verify(manifest, inputs.get("series_sha256"))
        _verify(manifest, evidence.get("sha256"))
        hashes = {
            f["name"]: f["sha256"]
            for item in _read(manifest)["factors"]
            if item["code_sha256"] == digest
            for f in item["files"]
        }
        paths = {k: p for k, p in paths.items() if p.name in hashes}
        for p in paths.values():
            _verify(p, hashes[p.name])
    elif evidence or inputs.get("series_sha256"):
        return {}
    return paths


def _figures(
    run: Path,
    dest: Path,
    row: Row,
    inputs: Row,
    folder: Path,
    ledger: Path,
    history: list[Row],
    dark: bool,
) -> dict[str, Row]:
    figures: dict[str, Row] = {
        name: {"file": None, "reason": reason, "source": []} for name, reason in words.SKIPS.items()
    }

    def save(name: str, data: Row | None, *paths: Path) -> None:
        if data is None:
            return
        _json(dest / f"{name}.json", data)
        (dest / f"{name}.png").write_bytes(charts.draw(name, data, dark))
        figures[name] = {
            "file": f"{name}.png",
            "data": f"{name}.json",
            "reason": None,
            "source": [str(p.relative_to(run)) if p.is_relative_to(run) else str(p) for p in paths],
        }

    values = _path(run, folder / "factors.parquet")
    panel = _path(run, "panel/panel.parquet")
    if values.is_file() and panel.is_file():
        _verify(values, inputs.get("factors_sha256") or row.get("factor_values", {}).get("sha256"))
        _verify(panel, inputs.get("panel_sha256"))
        save(
            "signal",
            charts.signal_data(values, panel, row["name"], row.get("plain_name")),
            values,
            panel,
        )
    clock = words.clock_of(row)
    if clock:
        paths = _bound_files(run, folder, row, inputs)
        if "buckets" in paths and "buckets_daily" in paths:
            total, days = paths["buckets"], paths["buckets_daily"]
            save("quick-test", charts.quick_data(total, days, clock), total, days)
        if "screen" in paths:
            screen = paths["screen"]
            save(
                "over-time",
                charts.timeline_data(screen, clock, words.direction_of(row)),
                screen,
            )
        replay = paths.get("replay")
        stats = words.trial_of(row).get("replay", {})
        if replay and replay.is_file() and stats.get("net") and "counted_only" not in stats:
            save("trading-test", charts.trading_data(replay, clock, stats), replay)
    if row.get("status") == "SCREEN_FAIL":
        figures["trading-test"]["reason"] = (
            "No trading test was run: the idea failed the quick test."
        )
    save("how-many-ideas", charts.looks_data(row, history), ledger)
    return figures


def _story(
    run: Path,
    dest: Path,
    row: Row,
    record: Row,
    source: Path,
    task: Row,
    rnd: Row,
    ledger: Path,
    history: list[Row],
    dark: bool,
) -> Row:
    i = record["iteration"]
    folder = _path(run, f"evaluations/iter-{i}")
    sources = [str(source.relative_to(run))]
    round_sources = sources + (["rounds.jsonl"] if rnd else [])
    window = row.get("windows") or record.get("disclosures", {}).get("windows", {})
    if window.get("panel_end", "") >= RESERVED_START or any(
        d >= RESERVED_START for d in window.get("exploration", [])
    ):
        raise ValueError("Recorded evaluation reaches the reserved period")
    code = _path(run, f"code/{row['code_sha256']}.py")
    filename = str(code.relative_to(run)) if code.is_file() else None
    _verify(code, row["code_sha256"])
    trial = words.trial_of(row)
    figures = _figures(run, dest, row, record.get("inputs", {}), folder, ledger, history, dark)
    steps = [
        words.idea_step(row, task, round_sources),
        words.code_step(
            _snippet(code, row["name"]) if filename else words.MISSING,
            filename,
            sources + ([filename] if filename else []),
        ),
        words.peek_step(row, sources),
        words.quick_step(row, trial, sources),
        words.trading_step(row, trial, sources),
        words.feedback_step(rnd.get("feedback", {}), round_sources),
        words.limits_step(row, trial, sources),
    ]
    for n, names in (
        (1, ["signal"]),
        (3, ["quick-test", "over-time"]),
        (4, ["trading-test"]),
        (6, ["how-many-ideas"]),
    ):
        step = steps[n]
        step["figure"] = next((figures[k]["file"] for k in names if figures[k]["file"]), None)
        step["figures"] = names
        step["figure_reason"] = (
            None if step["figure"] else "; ".join(figures[k]["reason"] for k in names)
        )
        step["source"] = list(
            dict.fromkeys([*step["source"], *(p for k in names for p in figures[k]["source"])])
        )
    return {
        "iteration": i,
        "name": row["name"],
        "code_sha256": row["code_sha256"],
        "steps": steps,
        "figures": figures,
    }


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    fd = os.open(root, os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def build(run: Path, out: Path | None, factor: str | None, dark: bool) -> Path:
    run = run.resolve(strict=True)
    root = _path((out or run).resolve(), "journey")
    rounds = _rounds(run)
    ledger = _ledger(run)
    history = list(_lines(ledger))
    entries = []
    selected = []
    folders = set()
    for source, record in _evaluations(run):
        for row in record["factors"]:
            i = record["iteration"]
            folder = _folder(i, row)
            if folder in folders:
                raise ValueError("Duplicate journey folder")
            folders.add(folder)
            entries.append(
                {
                    "iteration": i,
                    "name": row["name"],
                    "code_sha256": row["code_sha256"],
                    "folder": folder,
                }
            )
            if factor is None or row["name"] == factor:
                selected.append((folder, row, record, source))
    if factor is not None and not selected:
        raise ValueError(f"No judged factor named {factor!r}")
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root), TemporaryDirectory(dir=root) as temp:
        staging = Path(temp)
        previous = os.environ.get("MPLCONFIGDIR")
        os.environ["MPLCONFIGDIR"] = str(staging / "matplotlib")
        try:
            for folder, row, record, source in selected:
                key = record["iteration"], row["name"], row["code_sha256"]
                task, rnd = rounds.get(key, ({}, {}))
                stage = staging / folder
                stage.mkdir()
                story = _story(run, stage, row, record, source, task, rnd, ledger, history, dark)
                _json(stage / "journey.json", story)
        finally:
            if previous is None:
                del os.environ["MPLCONFIGDIR"]
            else:
                os.environ["MPLCONFIGDIR"] = previous
        for folder, *_ in selected:
            dest = _path(root, folder)
            dest.mkdir(exist_ok=True)
            stage = staging / folder
            available = _read(stage / "journey.json")["figures"]
            for p in sorted(stage.iterdir(), key=lambda p: p.name == "journey.json"):
                p.replace(dest / p.name)
            for name, item in available.items():
                if item["file"] is None:
                    for suffix in (".png", ".json"):
                        (dest / (name + suffix)).unlink(missing_ok=True)
        _json(root / "index.json", {"ideas": entries})
    return root / "index.json"
