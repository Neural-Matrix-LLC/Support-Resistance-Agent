"""Yahoo Finance daily bars through `yfinance` (§2.5; D4 — replaces Stooq as the
P0 price spine, 2026-09-18).

`yfinance` is an unofficial client for Yahoo's public quote API: no token, US and
HK covered, full history. Two properties to remember downstream:

* Yahoo's OHLC is **split-adjusted back through time** even with
  `auto_adjust=False`; only dividends are left unadjusted (`Adj Close` carries
  those). The P1 corporate-action layer must treat this source accordingly.
* While the session is open the last row is the **partial** bar of the day
  (`Adj Close` is NaN on it). It is kept verbatim in the raw cache — the cache
  is a record of what was fetched — and excluded downstream by the availability
  rule `available_at ≤ now` in `Bars.from_frame`.

The history frame is serialised to a CSV with the header
`Date,Open,High,Low,Close,Adj Close,Volume` so the raw cache stays text, like
every other source.
"""

from __future__ import annotations

from io import StringIO
from typing import Any

import polars as pl

from sr_agent.config import load_market
from sr_agent.data.ingestion.base import RawSource, RawSourceError, finish_frame

CSV_HEADER = ("Date", "Open", "High", "Low", "Close", "Adj Close", "Volume")


def _history(symbol: str) -> Any:
    """`yfinance` call, isolated so tests can replace it. Returns a pandas frame
    indexed by tz-aware session dates with the columns in CSV_HEADER[1:]."""
    import yfinance as yf  # imported lazily: pandas + yfinance are only needed to fetch

    return yf.Ticker(symbol).history(period="max", auto_adjust=False, actions=False)


def history_to_csv(frame: Any) -> str:
    """pandas history frame → CSV text with CSV_HEADER (dates as YYYY-MM-DD)."""
    out = frame.loc[:, list(CSV_HEADER[1:])].copy()
    out.insert(0, "Date", out.index.strftime("%Y-%m-%d"))
    return str(out.to_csv(index=False, lineterminator="\n"))


class YFinanceSource(RawSource):
    name = "yfinance"

    def symbol(self, ticker: str, market: str) -> str:
        code = ticker.upper()
        if market == "HK" and code.isdigit():
            code = code.zfill(4)  # Yahoo wants 0700.HK, not 700.HK
        return f"{code}{load_market(market).yfinance_suffix.upper()}"

    def fetch(self, symbol: str) -> str:
        frame = _history(symbol)
        if frame is None or len(frame) == 0:
            raise RawSourceError(f"{symbol}: yfinance returned no history (unknown symbol?)")
        text = history_to_csv(frame)
        self.parse(text, symbol)  # validate before the caller caches it
        return text

    def parse(self, text: str, symbol: str) -> pl.DataFrame:
        stripped = text.strip()
        head = stripped.splitlines()[0] if stripped else ""
        if tuple(h.strip() for h in head.split(",")) != CSV_HEADER:
            raise RawSourceError(f"{symbol}: not a yfinance CSV (first line {head[:60]!r})")
        df = pl.read_csv(StringIO(text), schema_overrides={"Date": pl.Date})
        df = df.rename(
            {
                "Date": "session",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        # Rows without a price are placeholders Yahoo sometimes emits, never bars.
        df = df.filter(pl.col("close").is_not_null() & pl.col("high").is_not_null())
        return finish_frame(df)
