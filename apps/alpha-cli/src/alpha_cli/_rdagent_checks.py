"""Describe judged factor replays using the run's own evidence and toolbox ledger."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox import runner
from alpha_cli.toolbox.inputs import Target
from alpha_cli.toolbox.sets import SETS
from alpha_core.reserve import RESERVED_DAY
from alpha_validation import FloatArray

SET = "rdagent-post-judge"
ABOUT = (
    "They do not change the verdict. They use the idea's daily return above the average of "
    "all coins, after costs. This is not a profit."
)
Row = dict[str, Any]


def _changed(message: str) -> SpineError:
    return SpineError("FACTOR_SERIES_CHANGED", message, "Check the recorded replay evidence.")


@dataclass(frozen=True)
class FactorTarget(Target):
    row: Row
    iteration: int
    series_sha256: str | None

    @classmethod
    def from_row(cls, run: Path, record: Row, row: Row) -> FactorTarget:
        i, code, clock = record["iteration"], row["code_sha256"], row["lead_clock"]
        manifest = {
            "spine": {
                "test_id": None,
                "labels": ["rdagent-factor", "excess-over-equal-weight-basket", "after-verdict"],
            },
            "metadata": {"periods_per_year": 365},
        }
        return cls(
            f"rdagent-iter{i}-{code[:16]}-{clock}",
            run.resolve(),
            manifest,
            row,
            i,
            record["inputs"].get("series_sha256"),
        )

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset({"stored_equity"})

    @cached_property
    def _series(self) -> tuple[FloatArray, Row]:
        # Bind the bytes actually decoded, inside the runner's audited error boundary.
        evidence = self.row["evidence"]
        rel = f"evaluations/iter-{self.iteration}/series/series.json"
        path = self.directory / rel
        if evidence["series_manifest"] != rel or path.resolve() != path:
            raise _changed("Series manifest belongs to another evaluation")
        manifest = path.read_bytes()
        digest = hashlib.sha256(manifest).hexdigest()
        if digest != self.series_sha256 or digest != evidence["sha256"]:
            raise _changed("Recorded series manifest hash differs")
        code, clock = self.row["code_sha256"], self.row["lead_clock"]
        replay = path.with_name(f"{code}.replay.parquet")
        listed = [
            file["sha256"]
            for factor in json.loads(manifest)["factors"]
            if factor["code_sha256"] == code
            for file in factor["files"]
            if file["name"] == replay.name
        ]
        if len(listed) != 1 or replay.resolve() != replay:
            raise _changed("Replay file is not bound to this factor")
        payload = replay.read_bytes()
        replay_sha = hashlib.sha256(payload).hexdigest()
        if replay_sha != listed[0]:
            raise _changed("Recorded replay hash differs")
        frame = pl.read_parquet(payload, columns=["clock", "target_ts", "exit_ts", "excess_return"])
        frame = frame.filter(pl.col("clock") == clock).sort("target_ts")
        returns = frame["excess_return"].to_numpy()
        targets, exits = frame["target_ts"], frame["exit_ts"]
        if (
            len(returns) < 2
            or not np.isfinite(returns).all()
            or targets.null_count()
            or targets.n_unique() != len(returns)
            or exits.null_count()
            or (exits.dt.date() >= RESERVED_DAY).any()
        ):
            raise SpineError(
                "RESERVED_PERIOD",
                "Replay needs finite returns on distinct dates before the reserved period",
                "Check the recorded replay dates and returns.",
            )
        if not math.isclose(
            math.fsum(returns) / len(returns) * self.ppy,
            self.row["clocks"][clock]["replay"]["net"]["annualized_return"],
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise _changed("Excess returns do not reproduce the judged annualized return")
        self.manifest["metadata"]["last_ts"] = exits[-1].isoformat()
        return returns, {
            "series_sha256": digest,
            "replay_sha256": replay_sha,
            "clock": clock,
            "code_sha256": code,
        }

    def prepare(self, home: Path, needs: tuple[str, ...], settings: Row) -> tuple[None, Row]:
        if not self.kinds.issuperset(needs):
            raise ValueError(f"Target {self.run_id} cannot supply {needs}")
        return None, self._series[1]

    def scored_returns(self) -> FloatArray:
        return self._series[0]

    def ledger_fields(self) -> Row:
        return {
            "test_id": None,
            "name": self.row["name"],
            "symbol": "rdagent-factor-panel",
            "store": None,
        }


def post_judge_checks(run: Path, record: Row) -> tuple[Row, str]:
    factors, suffix = [], []
    try:
        for row in record["factors"]:
            if row["stage"] != "replay" or row["status"] == "REPEAT" or "evidence" not in row:
                continue
            replay = row["clocks"][row["lead_clock"]]["replay"]
            if "net" not in replay or "counted_only" in replay:
                continue
            results, readings = [], []
            for tool in SETS[SET]:
                source = FactorTarget.from_row(run, record, row)
                try:
                    doc = runner.run(
                        run / "checks", tool, source.run_id, set_name=SET, source=source
                    )
                except SpineError as exc:
                    results.append(
                        {"tool": tool, "error_code": exc.payload["code"], "message": str(exc)}
                    )
                    readings.append(f"Check {tool} could not run: {str(exc).removesuffix('.')}.")
                else:
                    results.append(
                        {"tool": tool, "file": f"checks/{doc['file']}", "reading": doc["reading"]}
                    )
                    readings.append(doc["reading"])
            factors.append(
                {"name": row["name"], "code_sha256": row["code_sha256"], "results": results}
            )
            suffix.append(
                f" After the verdict, ALPHA ran its fixed checks ({SET}) on {row['name']}."
                f" {ABOUT} They are information, not a target. " + " ".join(readings)
            )
    except Exception as exc:
        return {"set": SET, "note": f"{type(exc).__name__}: {exc}"}, ""
    return {"set": SET, "factors": factors}, "".join(suffix)
