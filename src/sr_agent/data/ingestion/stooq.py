"""Stooq daily CSV (`https://stooq.com/q/d/l/?s=aapl.us&i=d`).

Since 2026-09 the endpoint sits behind a JavaScript proof-of-work challenge, so
`fetch()` normally fails with RawSourceError. The cache path still works: save
the CSV from a browser to `data/raw/stooq/AAPL.US/YYYY-MM-DD.csv` and `sr p0`
reads it. We do not solve the challenge programmatically.
"""

from __future__ import annotations

from io import StringIO

import polars as pl

from sr_agent.config import load_market
from sr_agent.data.ingestion.base import RawSource, RawSourceError, finish_frame, http_get

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_EXPECTED_HEADER = ("Date", "Open", "High", "Low", "Close", "Volume")


class StooqSource(RawSource):
    name = "stooq"

    def symbol(self, ticker: str, market: str) -> str:
        return f"{ticker.upper()}{load_market(market).stooq_suffix.upper()}"

    def fetch(self, symbol: str) -> str:
        text = http_get(STOOQ_URL.format(symbol=symbol.lower()))
        self.parse(text, symbol)  # validate before the caller caches it
        return text

    def parse(self, text: str, symbol: str) -> pl.DataFrame:
        stripped = text.strip()
        head = stripped.splitlines()[0] if stripped else ""
        if tuple(h.strip() for h in head.split(",")) != _EXPECTED_HEADER:
            hint = (
                " — Stooq's browser challenge; download the CSV manually into the cache"
                if head.lower().startswith("<!doctype")
                else ""
            )
            raise RawSourceError(f"{symbol}: not a Stooq CSV (first line {head[:60]!r}){hint}")
        df = pl.read_csv(StringIO(text), schema_overrides={"Date": pl.Date})
        return finish_frame(
            df.rename(
                {
                    "Date": "session",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
        )
