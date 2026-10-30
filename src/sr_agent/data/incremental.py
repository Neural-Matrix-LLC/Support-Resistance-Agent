"""Incremental ingestion (§4.6.7): overlap-match append or full re-extract.

The nightly run re-extracts `overlap_sessions` sessions per symbol and diffs
against the cache tail. A match appends only new sessions; a mismatch (a
restatement) falls back to the symbol's full re-extract — which is safe
because extracts are immutable per day and the fold prefers later files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl


@dataclass(frozen=True)
class IncrementalResult:
    symbol: str
    appended: int
    restated: bool
    full_reextract: bool


def overlap_window(
    cache_last_session: date | None, overlap_sessions: int, today: date
) -> tuple[str, str]:
    """(start, end) of the overlap re-extract, in ISO dates."""
    if cache_last_session is None:
        return "2000-01-01", today.isoformat()
    start = cache_last_session - timedelta(days=overlap_sessions * 2 + 7)  # calendar slack
    return start.isoformat(), today.isoformat()


def diff_overlap(
    cached: pl.DataFrame,  # session-keyed tail of the cache (overlap window only)
    fresh: pl.DataFrame,  # same window from the new extract
    key_cols: tuple[str, ...] = ("Symbol", "Date"),
) -> bool:
    """True when the fresh rows agree with the cached tail (no restatement).

    Contract: every CACHED row in the overlap window must appear identically
    in `fresh` (the cached tail is a subset of fresh, values unchanged). Fresh
    rows beyond the cached tail are the new sessions, not a mismatch.
    """
    cols = [c for c in key_cols if c in cached.columns]
    if cached.is_empty():
        return True
    join_on = cols or cached.columns
    a = cached.select(sorted(set(cached.columns))).sort(join_on or cached.columns)
    b = fresh.select(sorted(set(fresh.columns))).sort(join_on or fresh.columns)
    if a.columns != b.columns:
        return False
    if a.height > b.height:
        return False  # cache has rows the source no longer reports → restatement
    joined = a.join(b, on=list(a.columns), how="anti")
    return joined.is_empty()


def plan_incremental(
    cached: pl.DataFrame, fresh: pl.DataFrame, overlap_sessions: int
) -> IncrementalResult:
    """Decide append vs full re-extract for one symbol (§4.6.7)."""
    sym = str(fresh["Symbol"][0]) if "Symbol" in fresh.columns and fresh.height else "?"
    _ = overlap_sessions  # config-driven; kept for signature stability
    if cached.is_empty():
        return IncrementalResult(
            symbol=sym, appended=fresh.height, restated=False, full_reextract=True
        )
    if not diff_overlap(cached, fresh):
        return IncrementalResult(symbol=sym, appended=0, restated=True, full_reextract=True)
    # Overlap matched: append only rows whose Date is not already cached.
    cached_dates = set(cached["Date"].to_list())
    new_rows = fresh.filter(~pl.col("Date").is_in(pl.Series(sorted(cached_dates))))
    return IncrementalResult(
        symbol=sym, appended=new_rows.height, restated=False, full_reextract=False
    )
