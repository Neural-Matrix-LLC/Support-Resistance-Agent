"""M0 audit: measure what the upstream MySQL actually holds (§4.5.1).

Run against the live cluster through the DuckDB mysql extension:

    uv run sr mysql audit          # full audit → stdout + data/raw/mysql/audit-<date>.json
    uv run sr mysql audit --offline --from FILE   # re-print a saved audit

Never hardcode the answers — this command is the source of truth, and the
sizing/settings in §4.5 are replaced by its output in M0.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import polars as pl

from sr_agent.config.p1_settings import MysqlConfig, load_table_extracts

AuditQueryFn = Callable[[str], list[tuple]]

AUDIT_QUERIES: dict[str, str] = {
    # histdailyprice7: coverage, depth, vendors
    "bar_first_date": "SELECT MIN(Date) FROM {table}",
    "bar_last_date": "SELECT MAX(Date) FROM {table}",
    "bar_rows": "SELECT COUNT(*) FROM {table}",
    "bar_symbols": "SELECT COUNT(DISTINCT Symbol) FROM {table}",
    "bar_exchanges": """
        SELECT Exchange, COUNT(*) AS rows, COUNT(DISTINCT Symbol) AS symbols,
               MIN(Date) AS first_date, MAX(Date) AS last_date
        FROM {table} GROUP BY Exchange ORDER BY Exchange
    """,
    "bar_delisted": """
        SELECT COUNT(DISTINCT Symbol) AS delisted_symbols FROM {table} t
        WHERE NOT EXISTS (
            SELECT 1 FROM {table} u
            WHERE u.Symbol = t.Symbol
              AND u.Date >= (SELECT MAX(Date) FROM {table}) - INTERVAL 30 DAY
        )
    """,
    # load_audit: since when are finish timestamps exact?
    "audit_first": "SELECT MIN(finished_at) FROM load_audit",
    "audit_last": "SELECT MAX(finished_at) FROM load_audit",
    "audit_jobs": """
        SELECT job, COUNT(*) AS n, MIN(finished_at) AS first, MAX(finished_at) AS last
        FROM load_audit GROUP BY job ORDER BY job
    """,
}


@dataclass(frozen=True)
class AuditReport:
    as_of: str
    table: str
    results: dict[str, object]


def run_audit(cfg: MysqlConfig, exec_query: AuditQueryFn) -> dict[str, object]:
    """`exec_query(sql) -> list[tuple]` is injected so tests can fake the DB."""
    extracts = load_table_extracts()
    bar = extracts["histdailyprice7"]
    table = bar.shadow_table or bar.name
    out: dict[str, object] = {"as_of": date.today().isoformat(), "table": table}
    errors = 0
    for key, sql in AUDIT_QUERIES.items():
        try:
            out[key] = exec_query(sql.format(table=table))
        except Exception as exc:  # noqa: BLE001 — record, don't abort the audit
            out[key] = f"ERROR: {exc}"
            errors += 1
    out["ok"] = errors == 0
    out["n_errors"] = errors
    return out


def save_audit(report: AuditReport, raw_dir: Path) -> Path:
    folder = raw_dir / "mysql"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"audit-{report.as_of}.json"
    path.write_text(json.dumps(asdict(report), indent=2, default=str), encoding="utf-8")
    return path


def audit_frame(report: dict[str, object]) -> pl.DataFrame:
    """Long frame: one row per audit key (for `--dump` style consumption)."""
    rows = [
        {"key": k, "value": json.dumps(v, default=str)} for k, v in report.items() if k != "as_of"
    ]
    return pl.DataFrame(rows)
