"""DuckDB smoke test: in-memory queries over an Arrow table, with external file access off.

ADR-0051 rule 12: DuckDB is a query tool over data ALPHA already holds, never the store.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:", config={"enable_external_access": False})


def test_duckdb_queries_polars_table_with_external_access_disabled() -> None:
    frame = pl.DataFrame({"family": ["a", "a", "b"], "sharpe": [1.0, 3.0, 2.0]})
    con = _connect()
    try:
        con.register("trials", frame.to_arrow())
        rows = con.execute(
            "SELECT family, count(*) AS n, avg(sharpe) AS mean_sharpe "
            "FROM trials GROUP BY family ORDER BY family"
        ).fetchall()
    finally:
        con.close()
    assert rows == [("a", 2, 2.0), ("b", 1, 2.0)]


def test_duckdb_refuses_file_reads_when_external_access_is_disabled() -> None:
    con = _connect()
    try:
        with pytest.raises(duckdb.Error):
            con.execute("SELECT * FROM read_csv('x.csv')").fetchall()
    finally:
        con.close()
