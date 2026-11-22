"""One in-memory DuckDB adapter; only fixed, named, parameter-bound questions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.trial_reader import LedgerSnapshot
from alpha_cli.spine.trial_record import TrialRecord

MEASURES = ("oos_sharpe", "dsr", "p", "q", "mean_ic", "annualised_excess")
ORDER = "created_at DESC NULLS LAST, source DESC, source_line DESC"


QUOTES = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")
ASSET_NOTE = (
    "Grouping normalises names: BTC/USDT, BTC-USDT and BTCUSDT count as BTC/USDT. "
    "Names with a ':' (perpetual contracts) are never merged with spot pairs. "
    "list and show keep each record's original name."
)


def asset_group(name: str) -> str:
    """Group key for an instrument name, used only for grouping; never stored on a record."""
    cleaned = name.strip().upper().replace("-", "/").replace("_", "/")
    if ":" in cleaned or not cleaned.replace("/", "").isalnum() or cleaned.count("/") > 1:
        return name
    if "/" in cleaned:
        return cleaned
    for quote in QUOTES:
        base = cleaned.removesuffix(quote)
        if base != cleaned and base and len(base) <= 6:
            return f"{base}/{quote}"
    return name


@dataclass(frozen=True)
class Question:
    sql: str
    parameters: tuple[str, ...] = ()


QUESTIONS = {
    "by-family": Question(
        "SELECT family_id, count(*) AS rows FROM trials "
        "GROUP BY family_id ORDER BY family_id LIMIT ?"
    ),
    "by-outcome": Question(
        "SELECT outcome, count(*) AS rows FROM trials GROUP BY outcome ORDER BY outcome LIMIT ?"
    ),
    "by-asset": Question(
        "SELECT asset, count(*) AS rows FROM trials, unnest(asset_groups) AS a(asset) "
        "GROUP BY asset ORDER BY asset LIMIT ?"
    ),
    "by-month": Question(
        "SELECT coalesce(substr(created_at, 1, 7), 'unknown') AS month, "
        "count(*) AS rows FROM trials GROUP BY month ORDER BY month LIMIT ?"
    ),
    "asset-history": Question(
        f"SELECT * FROM trials WHERE list_contains(asset_groups, ?) ORDER BY {ORDER} LIMIT ?",
        ("asset",),
    ),
    "family-trials": Question(
        f"SELECT * FROM trials WHERE family_id = ? ORDER BY {ORDER} LIMIT ?", ("family",)
    ),
    "top-measure": Question(
        """WITH selected AS (
        SELECT *, CASE ? WHEN 'oos_sharpe' THEN m_oos_sharpe WHEN 'dsr' THEN m_dsr
        WHEN 'p' THEN m_p WHEN 'q' THEN m_q WHEN 'mean_ic' THEN m_mean_ic
        WHEN 'annualised_excess' THEN m_annualised_excess END AS measure_value FROM trials)
        SELECT * FROM selected WHERE measure_value IS NOT NULL
        ORDER BY CASE WHEN ? IN ('p', 'q') THEN measure_value ELSE -measure_value END,
        trial_id LIMIT ?""",
        ("measure", "measure"),
    ),
    "repeats": Question(
        f"SELECT * FROM trials WHERE list_contains(labels, 'repeat') ORDER BY {ORDER} LIMIT ?"
    ),
}


TRIES = "tries"  # computed, not SQL: the count the deflated Sharpe uses, per asset


def _tries_per_asset(snapshot: LedgerSnapshot, limit: int) -> list[dict[str, Any]]:
    from collections import Counter

    from alpha_cli.spine.tries import distinct_asset_tests

    kept, _, _ = distinct_asset_tests(snapshot, None)
    counts = Counter(str(row["symbol"]) for _, row in kept)
    return [{"asset": name, "tries": n} for name, n in sorted(counts.items())][:limit]


def _frame(snapshot: LedgerSnapshot) -> Any:
    import polars as pl

    schema: dict[str, Any] = {}
    for field in fields(TrialRecord):
        if field.name in {"windows", "measures"}:
            continue
        schema[field.name] = (
            pl.List(pl.String)
            if field.name in {"assets", "labels"}
            else pl.Boolean
            if field.name == "counts_for_deflation"
            else pl.Int64
            if field.name in {"family_size_recorded", "source_line"}
            else pl.String
        )
    schema["asset_groups"] = pl.List(pl.String)
    schema.update({f"m_{name}": pl.Float64 for name in (*MEASURES, "benchmark_sharpe")})
    rows = []
    for record in snapshot.records:
        row = {
            name: getattr(record, name)
            for name in schema
            if not name.startswith("m_") and name != "asset_groups"
        }
        row["asset_groups"] = sorted({asset_group(a) for a in record.assets})
        row.update(
            {f"m_{name}": record.measures.get(name) for name in (*MEASURES, "benchmark_sharpe")}
        )
        rows.append(row)
    return pl.DataFrame(rows, schema=schema)


@contextmanager
def connection(snapshot: LedgerSnapshot) -> Iterator[Any]:
    import duckdb

    con = duckdb.connect(":memory:", config={"enable_external_access": False})
    try:
        con.register("trials", _frame(snapshot).to_arrow())
        yield con
    finally:
        con.close()


def query(
    snapshot: LedgerSnapshot,
    question: str,
    *,
    asset: str | None = None,
    family: str | None = None,
    measure: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    names = sorted([*QUESTIONS, TRIES])
    if question not in QUESTIONS and question != TRIES:
        raise SpineError(
            "UNKNOWN_QUESTION",
            f"Unknown question {question!r}.",
            f"Choose one of these questions: {', '.join(names)}.",
            names,
        )
    if question == TRIES:
        if any(value is not None for value in (asset, family, measure)) or not (
            type(limit) is int and 1 <= limit <= 200
        ):
            raise SpineError(
                "BAD_PARAMETER",
                "The question 'tries' takes no asset, family or measure.",
                "Run alpha ledger tries <asset> for one asset, or use a limit from 1 to 200.",
            )
        return _tries_per_asset(snapshot, limit)
    definition = QUESTIONS[question]
    provided = {
        k: v for k, v in dict(asset=asset, family=family, measure=measure).items() if v is not None
    }
    if (
        set(provided) != set(definition.parameters)
        or any(not value for value in provided.values())
        or type(limit) is not int
        or not 1 <= limit <= 200
        or (measure is not None and measure not in MEASURES)
    ):
        raise SpineError(
            "BAD_PARAMETER",
            "Missing or unlisted question parameter, measure or limit.",
            "Use the question's required parameter and a limit from 1 to 200.",
        )
    if asset is not None:
        provided["asset"] = asset_group(asset)
    values = [provided[name] for name in definition.parameters] + [limit]
    with connection(snapshot) as con:
        cursor = con.execute(definition.sql, values)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
