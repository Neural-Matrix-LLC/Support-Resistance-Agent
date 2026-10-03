"""Tiingo daily prices, free tier (§2.5; D4).

CSV columns: date, close, high, low, open, volume, adjClose, adjHigh, adjLow,
adjOpen, adjVolume, divCash, splitFactor. The raw cache keeps all of them; the
parser takes the *unadjusted* OHLCV (the lake treats every source as raw and
applies corporate actions itself from P1). US only.
"""

from __future__ import annotations

import os
from io import StringIO

import polars as pl

from sr_agent.data.ingestion.base import RawSource, RawSourceError, finish_frame, http_get

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{symbol}/prices?startDate={start}&format=csv"
TOKEN_ENV = "TIINGO_API_KEY"
_REQUIRED = {"date", "open", "high", "low", "close", "volume"}


def token_from_env() -> str | None:
    value = os.environ.get(TOKEN_ENV, "").strip()
    return value or None


class TiingoSource(RawSource):
    name = "tiingo"

    def __init__(self, token: str | None = None, start: str = "1990-01-01") -> None:
        self.token = token or token_from_env()
        self.start = start

    def symbol(self, ticker: str, market: str) -> str:
        if market != "US":
            raise RawSourceError(f"tiingo covers US only, not {market}")
        return ticker.upper()

    def fetch(self, symbol: str) -> str:
        if not self.token:
            raise RawSourceError(f"tiingo: set {TOKEN_ENV} (free at https://www.tiingo.com/)")
        text = http_get(
            TIINGO_URL.format(symbol=symbol.lower(), start=self.start),
            headers={"Authorization": f"Token {self.token}"},
        )
        self.parse(text, symbol)
        return text

    def parse(self, text: str, symbol: str) -> pl.DataFrame:
        stripped = text.strip()
        head = stripped.splitlines()[0] if stripped else ""
        cols = [h.strip() for h in head.split(",")]
        if not _REQUIRED.issubset(cols):
            raise RawSourceError(f"{symbol}: not a Tiingo CSV (first line {head[:80]!r})")
        df = pl.read_csv(StringIO(text))
        df = df.with_columns(pl.col("date").str.slice(0, 10).str.to_date().alias("session"))
        return finish_frame(df)
