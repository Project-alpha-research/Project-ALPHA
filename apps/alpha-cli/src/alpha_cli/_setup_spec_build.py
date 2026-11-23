"""Build a complete, commented Setup Lab spec from a few options.

The owner types a condition, an asset and a few numbers; this module writes the TOML file the
Setup Lab reads. It decides nothing about the market: every default is a plain starting value.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_core import DataError
from alpha_core.atomic import write_text

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
DEFAULT_WHEN = "crosses_above(close, sma(close, 20))"
HINT = "Run alpha setup new again with a corrected option."


@dataclass(frozen=True)
class SpecOptions:
    name: str
    assets: tuple[str, ...] = ("SPY",)
    when: str = DEFAULT_WHEN
    horizon: int = 10
    stop: str = "5 %"
    target: str = "10 %"


def build_spec(options: SpecOptions) -> dict[str, Any]:
    """The spec as a plain dict, in the shape `load_setup_spec` reads."""
    return {
        "setup": {
            "name": options.name,
            "idea": f"Days when: {options.when}",
            "assets": list(options.assets),
            "timeframe": "1D",
            "event": options.when,
        },
        "exit": {
            "direction": "long",
            "stop": options.stop,
            "target": options.target,
            "time_bars": options.horizon,
        },
        "study": {
            "horizons": sorted({1, 5, 10, 20, options.horizon}),
            "primary": options.horizon,
        },
    }


def _bad(option: str, detail: object) -> SpineError:
    return SpineError("BAD_OPTION", f"{option} is not valid: {detail}", HINT)


def check(options: SpecOptions) -> None:
    """Fail with one plain sentence that names the option. Each option is tried alone."""
    from alpha_cli.spine.setup_find import load_setup_spec

    if not NAME.fullmatch(options.name):
        raise _bad("The name", f"'{options.name}'. Use letters, digits, '.', '_' and '-' only.")
    if options.horizon < 1:
        raise _bad("--horizon", "give a whole number of bars, 1 or more")
    base = SpecOptions(name=options.name)
    for flag, field in (("--when", "when"), ("--stop", "stop"), ("--target", "target")):
        try:
            load_setup_spec(build_spec(replace(base, **{field: getattr(options, field)})))
        except (DataError, ValueError) as error:
            raise _bad(flag, f"{getattr(options, field)!r} ({error})") from error
    if not options.assets or not all(a.strip() for a in options.assets):
        raise _bad("--asset", "give a stored symbol such as SPY")


def spec_text(options: SpecOptions) -> str:
    """The commented TOML file. It loads to exactly `build_spec(options)`."""
    check(options)
    spec = build_spec(options)
    q = json.dumps
    setup, exits, study = spec["setup"], spec["exit"], spec["study"]
    return "\n".join(
        [
            "# Setup Lab spec written by `alpha setup new`. Change any value.",
            "# Rules read only bars known at the close of each day.",
            "# Sources: open, high, low, close, volume.",
            "# Functions: prev, sma, ema, atr, highest, lowest, pct_change, abs, crosses_above,",
            "# crosses_below, for_bars, within_bars.",
            "",
            "[setup]                  # what to look for",
            f"name = {q(setup['name'])}",
            f"idea = {q(setup['idea'])}",
            f"assets = {q(setup['assets'])}   # stored symbols",
            'timeframe = "1D"          # daily bars only',
            f"event = {q(setup['event'])}   # the day the setup happens (true or false)",
            "",
            "[exit]                   # how a traded setup ends; `alpha setup trade` reads it",
            'direction = "long"        # "long" or "short"',
            f"stop = {q(exits['stop'])}             # '5 %', '2 atr(14)' or a price rule",
            f"target = {q(exits['target'])}          # same forms as stop",
            f"time_bars = {exits['time_bars']}            # leave after this many bars",
            "",
            "[study]                  # `alpha setup study` measures these horizons",
            f"horizons = {q(study['horizons'])}   # bars after entry",
            f"primary = {study['primary']}            # quoted first; it must be one of horizons",
            "",
        ]
    )


def _file(home: Path, name: str) -> Path:
    return home / "specs" / f"{name}.toml"


def write_new(home: Path, options: SpecOptions) -> Path:
    """Write `<home>/specs/<name>.toml`. An existing file is never overwritten."""
    text = spec_text(options)
    path = _file(home, options.name)
    if path.exists():
        raise SpineError(
            "SPEC_EXISTS",
            f"The spec file already exists: {path}",
            "Choose another name, or edit that file.",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, text)
    return path


def direct_spec(home: Path, options: SpecOptions) -> Path:
    """The spec file for options given straight to `find`; the same options give the same file."""
    key = hashlib.sha256(json.dumps(build_spec(options), sort_keys=True).encode()).hexdigest()
    named = replace(options, name=f"quick-{key[:8]}")
    path = _file(home, named.name)
    text = spec_text(named)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, text)
    elif path.read_text(encoding="utf-8") != text:
        raise SpineError(
            "SPEC_CHANGED",
            f"The saved spec was edited and no longer matches your options: {path}",
            "Run it by path with alpha setup find, or delete that file.",
        )
    return path
