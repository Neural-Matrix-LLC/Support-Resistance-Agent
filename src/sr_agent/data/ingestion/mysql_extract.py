"""MySQL extractor (§4.5.3 rev): SELECT-only, chunked per symbol, immutable.

Writes `data/raw/mysql/{table}/{symbol}/{extract_date}.csv`. Never touches
MySQL from the read path of any later stage — D6.

The DuckDB mysql extension is the transport (as designed); the connection is
configured through sr_reader credentials from the environment. All statements
are SELECTs; anything else raises before it is sent.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sr_agent.config.p1_settings import MysqlConfig, TableExtract

log = logging.getLogger(__name__)

QueryFn = Callable[[str], list[tuple]]

_EXTRACT_HEADER = (
    "extract_date,source,object,"  # fold keys, prepended on landing
)


class ExtractError(RuntimeError):
    """The extractor refused to run (config, safety, or the answer was not readable)."""


class _MySqlCursor:
    """Minimal DB-API-ish cursor over DuckDB's mysql extension (test seam)."""

    def __init__(self, execute_fn: QueryFn) -> None:
        self._execute = execute_fn

    def rows(self, sql: str) -> list[tuple]:
        return self._execute(sql)


def assert_read_only(sql: str) -> str:
    """Reject anything that is not a SELECT (defence in depth for sr_reader)."""
    stripped = sql.strip().rstrip(";")
    first = stripped.split(None, 1)[0].upper() if stripped else ""
    if first != "SELECT":
        raise ExtractError(f"refusing non-SELECT statement: {first or '<empty>'!r}")
    return stripped + ";"


def extract_sql(table: TableExtract, symbol: str, start: str, end: str) -> str:
    """Deterministic per-symbol extract; ORDER BY makes re-runs byte-identical."""
    cols = ", ".join(table.columns)
    shadow = table.shadow_table
    name = shadow or table.name  # pre-cutover: read the shadow table
    return assert_read_only(
        f"SELECT {cols} FROM {name} "
        f"WHERE Symbol = '{symbol}' AND Date >= '{start}' AND Date <= '{end}' "
        f"ORDER BY {table.order_by}"
    )


def extract_load_audit(exec_query: QueryFn) -> list[dict[str, str]]:
    """Tail of load_audit — per-symbol finish timestamps (exact available_at)."""
    sql = assert_read_only(
        "SELECT Symbol, job, finished_at, n_rows FROM load_audit "
        "ORDER BY finished_at DESC LIMIT 5000"
    )
    rows = exec_query(sql)
    return [
        {"symbol": r[0], "job": r[1], "finished_at": str(r[2]), "n_rows": str(r[3])}
        for r in rows
    ]


@dataclass(frozen=True)
class ExtractReport:
    table: str
    symbols: int
    rows: int
    extract_date: str
    files: list[str]


def land_chunk(
    raw_dir: Path, table: TableExtract, symbol: str, rows: list[tuple], extract_date: date
) -> Path:
    """Write one immutable raw file: raw/mysql/{table}/{symbol}/{date}.csv."""
    folder = raw_dir / "mysql" / table.name / symbol
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{extract_date.isoformat()}.csv"
    if target.exists():  # immutability: same-day re-extract is a no-op
        return target
    tmp = target.with_suffix(".part")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(table.columns)
        w.writerows(rows)
    tmp.replace(target)
    return target


def extract_symbols(
    cfg: MysqlConfig,
    table: TableExtract,
    symbols: list[str],
    raw_dir: Path,
    exec_query: QueryFn,
    start: str = "2000-01-01",
    end: str | None = None,
    extract_date: date | None = None,
) -> ExtractReport:
    """Extract `symbols` one chunk per query, landing immutable CSVs.

    `exec_query(sql) -> list[tuple]` is the injected transport; a real run
    wires it to DuckDB's mysql_attach cursor. Determinism: the query ORDER BY
    plus the fixed fold order means identical inputs → identical bytes.
    """
    day = extract_date or date.today()
    end_s = end or day.isoformat()
    files: list[str] = []
    total = 0
    for sym in symbols:
        sql = extract_sql(table, sym, start, end_s)
        rows = exec_query(sql)
        if not rows:
            log.info("mysql extract %s %s: 0 rows", table.name, sym)
            continue
        target = land_chunk(raw_dir, table, sym, rows, day)
        files.append(str(target))
        total += len(rows)
    return ExtractReport(
        table=table.name, symbols=len(files), rows=total, extract_date=day.isoformat(), files=files
    )
