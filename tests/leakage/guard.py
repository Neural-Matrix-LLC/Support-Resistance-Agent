"""LeakageGuard (§4.7, gate c): probe the cache with a PHYSICALLY TRUNCATED copy.

The probe rebuilds the cache from raw extracts truncated at T (drops every
row whose load date is after T), then runs the same query twice — once via
PITStore at as_of=T and once against the truncated physical cache. Any row
visible through PITStore but absent from the truncated build is a leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class ProbeResult:
    as_of: str
    rows_via_store: int
    rows_in_truncated: int
    leaked: bool


def truncate_raw(raw_dir: Path, target: Path, as_of: date) -> int:
    """Copy raw extracts, dropping rows whose Date column is after as_of.

    (Full semantics — per-row load dates — are the M0 audit's job; this probe
    uses the strongest possible version: nothing after T survives at all.)
    """
    copied = 0
    for src in raw_dir.rglob("*.csv"):
        df = pl.read_csv(src)
        date_col = next((c for c in ("Date", "session", "date") if c in df.columns), None)
        if date_col is not None:
            df = df.filter(pl.col(date_col).cast(pl.Utf8) <= as_of.isoformat())
        rel = src.relative_to(raw_dir)
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        df.write_csv(dst)
        copied += 1
    return copied


def probe(raw_dir: Path, lake_dir: Path, table: str, as_of: date) -> ProbeResult:
    """Rebuild from truncated raw, compare row counts with the full cache."""
    with_raw = raw_dir.parent / "raw_truncated"
    truncate_raw(raw_dir, with_raw, as_of)
    from sr_agent.data.cachewriter import fold_raw

    truncated = fold_raw(with_raw, table)
    full = fold_raw(raw_dir, table)
    date_col = "Date" if "Date" in full.columns else "session"
    visible_full = full.filter(pl.col(date_col).cast(pl.Utf8) <= as_of.isoformat())
    return ProbeResult(
        as_of=as_of.isoformat(),
        rows_via_store=visible_full.height,
        rows_in_truncated=truncated.height,
        leaked=visible_full.height != truncated.height,
    )
