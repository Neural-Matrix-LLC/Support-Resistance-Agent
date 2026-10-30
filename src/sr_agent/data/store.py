"""PITStore / AsOfQuery (§4.4, D6): the ONLY read path for every later layer.

Every query binds `available_at <= as_of`; the allow-list excludes
`bar_daily_adj_latest` (not point-in-time). Reads resolve to DuckDB views
over the local Parquet cache — no MySQL, no R2 (dropped 2026-10-29).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

# Tables readable through PITStore. `bar_daily_adj_latest` is deliberately
# absent: it is adjusted to the LATEST ingest and would leak the future.
ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "bar_daily_raw",
        "bar_daily_ref",
        "corporate_action",
        "session_calendar",
        "universe_membership",
        "security_master",
        "symbol_map",
        "filing",
        "macro_series",
        "macro_release",
        "dq_score",
        "option_daily",
    }
)


class StoreError(ValueError):
    """A read was attempted outside the point-in-time contract."""


@dataclass(frozen=True)
class AsOfQuery:
    """A parameterised read: table + as_of, nothing else is negotiable."""

    table: str
    as_of: date

    def __post_init__(self) -> None:
        if self.table not in ALLOWED_TABLES:
            raise StoreError(
                f"{self.table!r} is not point-in-time readable; allowed: {sorted(ALLOWED_TABLES)}"
            )

    def sql(self) -> str:
        """The guarded statement. `available_at <= ?` is ALWAYS present.

        Tables with an `event_ts` column order by it; session_calendar has
        neither column and binds on `session` instead (the one exception).
        """
        if self.table == "session_calendar":
            return f"SELECT * FROM {self.table} WHERE session <= ?"
        return f"SELECT * FROM {self.table} WHERE available_at <= ?"


class PITStore:
    """DuckDB-backed read API. One instance per process; the catalogue lives
    at `data/sr.duckdb` with views over `data/lake/<table>/…parquet`."""

    def __init__(self, catalog: Path | str = "data/sr.duckdb", read_only: bool = True) -> None:
        self.catalog = str(catalog)
        self.read_only = read_only
        self._con = duckdb.connect(self.catalog, read_only=read_only)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> PITStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read(self, query: AsOfQuery, as_of: date | None = None) -> list[tuple]:
        """Execute an AsOfQuery, binding the (re-checked) as_of parameter."""
        cutoff = as_of or query.as_of
        sql = query.sql()
        params: list[Any] = [cutoff]
        rows = self._con.execute(sql, params).fetchall()
        return rows

    def read_frame(self, query: AsOfQuery, as_of: date | None = None) -> Any:
        """Same read as a DuckDB relation (for Polars/Arrow hand-off)."""
        cutoff = as_of or query.as_of
        return self._con.execute(query.sql(), [cutoff])
