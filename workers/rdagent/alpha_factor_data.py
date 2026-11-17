"""Build RD-Agent's daily frames and check generated code for prefix invariance."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

CUTS = (
    ("2020-12-31",)
    + tuple(
        f"{year}-{day}"
        for year in (2021, 2022, 2023)
        for day in ("03-31", "06-30", "09-30", "12-31")
        if f"{year}-{day}" <= "2023-09-30"
    )
    + ("2023-12-24",)
)
README = """# Daily price and volume data

The frozen universe of Binance USDT spot coins, daily bars.
Row d is the bar that opened at 00:00 UTC
on day d and is known at its close. Data ends 2023-12-31; 2024 onward is reserved.

Read with `pd.read_hdf('daily_pv.h5', key='data')`.

| File | Contents |
| --- | --- |
| daily_pv.h5 | DataFrame, key data; sorted (datetime, instrument) index |

| Field | Meaning |
| --- | --- |
| $open, $high, $low, $close | Spot OHLC prices in USDT |
| $volume | Base-asset volume |
| $factor | 1.0, no adjustments |

Missing days inside each instrument span are explicit null rows; ALPHA never forward-fills.
Every instrument also has null rows from the first data day until it lists, so every cut keeps
the same instrument columns; no rows follow an instrument's last bar. All fields are float64.
Factors are decided after the full day's close and judged
on the return from the next open to the following open, with costs.
"""


def prepare(panel: Path, out: Path) -> dict[str, Any]:
    frame = pd.read_parquet(panel)
    dates = pd.to_datetime(frame["date"], utc=True)
    if (
        dates.isna().any()
        or not dates.eq(dates.dt.normalize()).all()
        or dates.ge(pd.Timestamp("2024-01-01", tz="UTC")).any()
    ):
        raise ValueError("panel must contain midnight dates before the reserved window")
    frame["datetime"] = dates.dt.tz_localize(None)
    frame = frame.set_index(["datetime", "instrument"]).sort_index()
    if frame.index.has_duplicates:
        raise ValueError("duplicate factor data keys")
    frame = (
        frame[["open", "close", "high", "low", "volume"]]
        .rename(columns=lambda c: "$" + c)
        .astype("float64")
    )
    frame["$factor"] = 1.0
    # Every instrument starts at one common first day, no later than the first cut, so each cut
    # keeps the full instrument column set (null rows before listing). Each instrument still ends
    # at its own last bar: no row ever follows the last bar, as in the gapped-universe span rule.
    start = min(frame.index.get_level_values("datetime").min(), pd.Timestamp(CUTS[0]))
    pieces = []
    for instrument, group in frame.groupby(level="instrument", sort=True):
        index = pd.MultiIndex.from_product(
            [
                pd.date_range(start, group.index.get_level_values("datetime").max(), freq="D"),
                [instrument],
            ],
            names=["datetime", "instrument"],
        )
        pieces.append(group.reindex(index))
    frame = pd.concat(pieces).sort_index()
    out.mkdir(parents=True, exist_ok=False)
    parts = {
        "full": frame,
        "debug": frame.loc[
            (frame.index.get_level_values(0) >= "2021-01-01")
            & (frame.index.get_level_values(0) <= "2022-12-31")
        ],
    }
    parts.update({f"cuts/{cut}": frame.loc[frame.index.get_level_values(0) <= cut] for cut in CUTS})
    for name, data in parts.items():
        folder = out / name
        folder.mkdir(parents=True)
        data.to_hdf(folder / "daily_pv.h5", key="data", mode="w")
        if name in {"full", "debug"}:
            (folder / "README.md").write_text(README)
    receipt = {
        "schema": "AlphaRdagentFactorDataV1",
        "panel_sha256": hashlib.sha256(panel.read_bytes()).hexdigest(),
        "files": {
            str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*"))
            if p.is_file()
        },
    }
    (out / "prepare-receipt.json").write_text(json.dumps(receipt, sort_keys=True) + "\n")
    return receipt


def _normalized(frame: pd.DataFrame) -> pd.DataFrame:
    if (
        not isinstance(frame, pd.DataFrame)
        or not isinstance(frame.index, pd.MultiIndex)
        or frame.index.nlevels != 2
        or frame.index.has_duplicates
    ):
        raise ValueError("factor output requires a unique (datetime, instrument) index")
    result = frame.copy()
    dates = pd.to_datetime(result.index.get_level_values(0), utc=True).tz_localize(None)
    result.index = pd.MultiIndex.from_arrays(
        [dates, result.index.get_level_values(1)], names=["datetime", "instrument"]
    )
    return result.sort_index()


def compare_prefix(full: pd.DataFrame, truncated: pd.DataFrame, cut: str) -> dict[str, Any] | None:
    full, truncated = _normalized(full), _normalized(truncated)
    expected = full.loc[full.index.get_level_values(0) <= pd.Timestamp(cut)]
    actual = truncated.loc[truncated.index.get_level_values(0) <= pd.Timestamp(cut)]
    if not expected.index.equals(actual.index) or list(expected.columns) != list(actual.columns):
        changed = expected.index.symmetric_difference(actual.index).sort_values()
        keys = changed if len(changed) else expected.index.union(actual.index)
        first = keys[0] if len(keys) else (None, None)
        return {
            "cut": cut,
            "date": str(first[0]),
            "instrument": str(first[1]),
            "absolute_difference": None,
            "reason": "index or columns changed",
        }
    for index, (left, right) in enumerate(
        zip(expected.to_numpy().flat, actual.to_numpy().flat, strict=True)
    ):
        a, b = float(left), float(right)
        if math.isnan(a) and math.isnan(b):
            continue
        if (
            not math.isfinite(a)
            or not math.isfinite(b)
            or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
        ):
            row, col = divmod(index, len(expected.columns))
            return {
                "cut": cut,
                "date": str(expected.index[row][0]),
                "instrument": str(expected.index[row][1]),
                "column": str(expected.columns[col]),
                "reason": "value or NaN position changed",
                "absolute_difference": abs(a - b)
                if math.isfinite(a) and math.isfinite(b)
                else None,
            }
    return None


def _run_cut(code: bytes, source: Path, python_bin: str, timeout: float) -> pd.DataFrame:
    with tempfile.TemporaryDirectory(prefix="alpha-factor-cut-") as temporary:
        work = Path(temporary)
        (work / "factor.py").write_bytes(code)
        shutil.copyfile(source.resolve(strict=True), work / "daily_pv.h5")
        result = subprocess.run(
            [python_bin, "factor.py"],
            cwd=work,
            env={
                "HOME": temporary,
                "LANG": "C.UTF-8",
                "PATH": str(Path(python_bin).parent) + ":/usr/bin:/bin",
            },
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"truncated factor exit {result.returncode}")
        truncated = pd.read_hdf(work / "result.h5", key="data")
        if not isinstance(truncated, pd.DataFrame):
            raise ValueError("factor output must be a DataFrame")
        return truncated


def check_prefix_invariance(
    code: bytes, full_values: pd.DataFrame, cuts_dir: Path, python_bin: str, timeout: float
) -> dict[str, Any]:
    checked: list[dict[str, str]] = []
    for cut in CUTS:
        source = cuts_dir / cut / "daily_pv.h5"
        mismatch = None
        try:
            truncated = _run_cut(code, source, python_bin, timeout)
            mismatch = compare_prefix(full_values, truncated, cut)
            status = "PASS"
            repeat_mismatch = None
            if mismatch:
                repeated = _run_cut(code, source, python_bin, timeout)
                repeat_mismatch = compare_prefix(truncated, repeated, cut)
                status = "UNSTABLE" if repeat_mismatch else "LOOKAHEAD"
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
            checked.append({"cut": cut, "status": "ERROR"})
            return {
                "status": "ERROR",
                "cuts": checked,
                "first_mismatch": mismatch or {"cut": cut, "reason": str(error)},
                "error": str(error),
            }
        checked.append({"cut": cut, "status": status})
        if mismatch:
            return {
                "status": status,
                "cuts": checked,
                "first_mismatch": mismatch,
                "repeat_mismatch": repeat_mismatch,
            }
    return {"status": "PASS", "cuts": checked, "first_mismatch": None}


def current_universe() -> str:
    """Use this run's frozen receipt, never restored scenario text or launcher fallback."""
    run = os.environ.get("ALPHA_FACTOR_RUN_DIR")
    if not run:
        raise ValueError("current universe requires this run's frozen panel receipt")
    root = Path(run) / "panel"
    try:
        receipt = json.loads((root / "panel-receipt.json").read_bytes())
        count = len(receipt["instruments"])
        if not count:
            raise ValueError("current universe has no instruments")
        path = root / "universe.json"
        spec = json.loads(path.read_bytes()) if path.exists() else None
        if "universe_sha256" in receipt:
            canonical = (json.dumps(spec, sort_keys=True, separators=(",", ":")) + "\n").encode()
            if spec is None or hashlib.sha256(canonical).hexdigest() != receipt["universe_sha256"]:
                raise ValueError("universe file differs from the frozen receipt")
        if "universe_text" in receipt:
            return str(receipt["universe_text"])
        # Old default runs predate universe files and explicitly used survivors only.
        text = spec["survivorship"] if spec is not None else "survivors only"
        match = re.search(r"\b(\d+)\s+(?:later\s+)?delisted\b", text.lower())
        if match:
            if int(match[1]) > count:
                raise ValueError("universe delisted count exceeds this run's instrument count")
            return (
                f"{count} instruments, {match[1]} later delisted; "
                "selection is not survivorship-free"
            )
        if re.search(r"\b(?:includes?|including)\s+(?:later\s+)?delisted\b", text.lower()):
            return f"{count} instruments; includes-delisted; later-delisted count not recorded"
        if "surviv" in text.lower():
            return f"{count} instruments, 0 later delisted declared; survivors-only selection"
        raise ValueError("current universe survivorship status cannot be derived from frozen files")
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"cannot derive current universe: {error}") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build RD-Agent's daily frames for the ALPHA-judged factor loop."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--panel", type=Path, required=True)
    prepare_parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.panel, args.out)


if __name__ == "__main__":
    main()
