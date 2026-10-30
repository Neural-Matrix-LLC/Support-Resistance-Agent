"""P1 CLI commands (§4.4 module table): `sr mysql …`, `sr cache …`, `sr status`.

Transport: DuckDB's `mysql` extension ATTACH (read-only). Every statement is
SELECT-only (asserted before sending); sr_reader credentials come from the
environment via mysql_extract.yaml. `--offline` variants run on saved extracts.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from sr_agent.config.p1_settings import MysqlConfig, load_mysql_config, load_table_extracts
from sr_agent.data.cachewriter import rebuild, refresh_catalog
from sr_agent.data.ingestion.mysql_audit import AuditReport, run_audit, save_audit
from sr_agent.data.ingestion.mysql_extract import (
    QueryFn,
    assert_read_only,
    extract_symbols,
)

log = logging.getLogger(__name__)


class MySqlUnavailable(RuntimeError):
    """The cluster is unreachable or the extension is missing."""


def live_query_fn(cfg: MysqlConfig) -> QueryFn:
    """Real transport: ATTACH mysql → execute → rows. Failures are loud."""
    import duckdb

    def query(sql: str) -> list[tuple]:
        checked = assert_read_only(sql)
        con = duckdb.connect()  # throwaway connection per statement; ATTACH is cheap
        try:
            con.execute("LOAD mysql")
            con.execute(
                f"ATTACH 'host={cfg.host} port={cfg.port} user={cfg.user} "
                f"password=*** db={cfg.database} connect_timeout={cfg.connect_timeout}' "
                "AS sr_mysql (TYPE mysql, read_only)"
            )
            # NOTE: duckdb ATTACH does not interpolate secrets into logs; the
            # password line above is built in-process and never logged.
            rows = con.execute(checked.replace("sr_mysql.", "")).fetchall()
        finally:
            con.close()
        return rows

    return query


def mysql_audit(data_dir: Path, offline_from: Path | None = None) -> dict[str, object]:
    """M0 audit: measure the upstream; save under data/raw/mysql/."""
    if offline_from is not None:
        return json.loads(Path(offline_from).read_text(encoding="utf-8"))["results"]
    cfg = load_mysql_config()
    results = run_audit(cfg, live_query_fn(cfg))
    report = AuditReport(
        as_of=date.today().isoformat(), table=str(results.get("table", "")), results=results
    )
    save_audit(report, data_dir)
    return results


def mysql_ingest(
    symbols: list[str],
    data_dir: Path,
    table: str = "histdailyprice7",
    start: str = "2000-01-01",
    end: str | None = None,
) -> dict[str, int]:
    """Extract the given symbols into immutable raw extracts (M2)."""
    cfg = load_mysql_config()
    extracts = load_table_extracts()
    if table not in extracts:
        raise KeyError(f"unknown table {table!r}; configured: {sorted(extracts)}")
    rep = extract_symbols(
        cfg, extracts[table], symbols, data_dir, live_query_fn(cfg), start=start, end=end
    )
    return {"symbols": rep.symbols, "rows": rep.rows}


def cache_rebuild(
    data_dir: Path, table: str, partition_by: list[str] | None = None
) -> dict[str, object]:
    """Fold raw → lake partitions → refresh the DuckDB catalogue view (M7)."""
    p1 = _p1_cfg()
    raw_dir = data_dir / p1["raw_dir"]
    lake_dir = data_dir / p1["cache_dir"]
    result = rebuild(raw_dir, lake_dir, table, partition_by or [])
    refresh_catalog(data_dir / p1["catalog"], lake_dir, table)
    return {"table": table, "rows": result.rows, "sha256": result.sha256}


def status(data_dir: Path) -> dict[str, object]:
    """`sr status`: last load_audit tail + cache manifest digests (M8)."""
    p1 = _p1_cfg()
    lake_dir = data_dir / p1["cache_dir"]
    out: dict[str, object] = {"ok": True}
    manifest_dir = lake_dir / "manifests"
    manifests = sorted(manifest_dir.glob("*.json")) if manifest_dir.exists() else []
    out["tables"] = {m.stem: json.loads(m.read_text())["sha256"][:12] for m in manifests}
    # freshness gate: raw extracts must exist for a recent extract_date
    raw_dir = data_dir / p1["raw_dir"] / "mysql"
    if raw_dir.exists():
        dates = sorted({p.stem for p in raw_dir.rglob("*.csv")})
        out["last_extract"] = dates[-1] if dates else None
        max_age = int(p1["max_load_age_sessions"])
        last = date.fromisoformat(dates[-1]) if dates else None
        if last is None or (date.today() - last).days > max_age + 2:  # +2: weekend grace
            out["ok"] = False
            out["reason"] = f"stale: last extract {out['last_extract']}"
    return out


def _p1_cfg() -> dict:
    from sr_agent.config.p1_settings import load_p1

    return load_p1()
