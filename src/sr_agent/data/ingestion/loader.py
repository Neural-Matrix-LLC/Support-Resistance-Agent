"""`load_bars`: source cache → point-in-time `Bars` (§3.4)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from sr_agent.config import load_market
from sr_agent.data.bars import Bars
from sr_agent.data.calendars import is_session, session_close_utc
from sr_agent.data.ingestion.base import RawSource
from sr_agent.data.ingestion.cache import cache_dir, fetch_to_cache, pick_cache_file
from sr_agent.data.ingestion.stooq import StooqSource
from sr_agent.data.ingestion.tiingo import TiingoSource
from sr_agent.data.ingestion.yfinance import YFinanceSource

log = logging.getLogger(__name__)

SOURCES: dict[str, type[RawSource]] = {
    YFinanceSource.name: YFinanceSource,
    TiingoSource.name: TiingoSource,
    StooqSource.name: StooqSource,
}


def default_source_name() -> str:
    """The price spine (D4, 2026-09-18): yfinance — no token, US + HK. Tiingo and a
    browser-downloaded Stooq CSV remain selectable with `--source`."""
    return YFinanceSource.name


def make_source(name: str) -> RawSource:
    try:
        return SOURCES[name]()
    except KeyError:
        raise ValueError(f"unknown source {name!r}; known: {sorted(SOURCES)}") from None


def attach_available_at(
    df: pl.DataFrame, calendar: str, lag_minutes: int, fallback_close_utc: str
) -> pl.DataFrame:
    """Stamp every bar with the availability rule for daily bars (§2.4):

        available_at = session_close(calendar, session) + publication_lag

    `session_close` is the exact close from `exchange_calendars` (DST and
    half-days included); `publication_lag` is `markets.yaml:
    bar_publication_lag_minutes`. Sessions the exchange calendar does not
    recognise are kept (warn, don't fail — §3.5) and stamped with the
    configured standard-time `close_utc` instead.
    """
    hh, mm = (int(x) for x in fallback_close_utc.split(":"))
    lag = timedelta(minutes=lag_minutes)
    stamps: list[datetime] = []
    unknown: list[date] = []
    for d in df["session"].to_list():
        if is_session(calendar, d):
            stamps.append(session_close_utc(calendar, d) + lag)
        else:
            unknown.append(d)
            stamps.append(datetime(d.year, d.month, d.day, hh, mm, tzinfo=UTC) + lag)
    if unknown:
        log.warning(
            "%d session(s) not on %s calendar, e.g. %s", len(unknown), calendar, unknown[:3]
        )
    return df.with_columns(pl.Series("available_at", stamps, dtype=pl.Datetime("us", "UTC")))


def load_bars(
    ticker: str,
    market: str,
    as_of: date,
    data_dir: Path,
    source: RawSource | None = None,
    offline: bool = False,
    today: date | None = None,
    now: datetime | None = None,
) -> Bars:
    """Read the newest cached download (or fetch one) and return point-in-time `Bars`.

    `offline=True` forbids network access: a cache miss raises FileNotFoundError.
    `today` names the cache file; `now` is the wall clock for the availability
    cut (both default to the real clock; tests pin them).
    """
    mkt = load_market(market)
    src = source or make_source(default_source_name())
    symbol = src.symbol(ticker, market)
    folder = cache_dir(data_dir, src.name, symbol)
    path = pick_cache_file(folder, as_of)
    if path is None:
        if offline:
            raise FileNotFoundError(
                f"no cached {src.name} file for {symbol} under {folder} and --offline was given"
            )
        path = fetch_to_cache(src, symbol, data_dir, today)
    raw = src.parse(path.read_text(encoding="utf-8"), symbol)
    raw = raw.filter(pl.col("session") <= pl.lit(as_of))  # cheap pre-cut before stamping
    if raw.is_empty():
        raise ValueError(f"{symbol}: no sessions on or before {as_of} in {path}")
    stamped = attach_available_at(raw, mkt.calendar, mkt.bar_publication_lag_minutes, mkt.close_utc)
    return Bars.from_frame(stamped, ticker=ticker.upper(), market=market, as_of=as_of, now=now)
