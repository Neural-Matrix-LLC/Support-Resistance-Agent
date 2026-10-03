"""Raw daily-bar sources (§2.5 Tier-0). A source knows how to name a symbol,
fetch its history as text, and parse that text into the normalised bar columns.
The text is what gets cached, verbatim — parsing is repeatable, downloads are not.
"""

from __future__ import annotations

import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping

import polars as pl

BAR_INPUT_COLUMNS: tuple[str, ...] = ("session", "open", "high", "low", "close", "volume")
_USER_AGENT = "SR-Agent/0.0 (research; contact via repository)"


class RawSourceError(RuntimeError):
    """The source answered with something that is not a daily-bar history."""


def http_get(url: str, headers: Mapping[str, str] | None = None, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class RawSource(ABC):
    """One provider of raw (unadjusted) daily OHLCV."""

    name: str

    @abstractmethod
    def symbol(self, ticker: str, market: str) -> str:
        """Provider-specific symbol; raises RawSourceError when the market is not covered."""

    @abstractmethod
    def fetch(self, symbol: str) -> str:
        """Download the full daily history as text (CSV). Network access happens only here."""

    @abstractmethod
    def parse(self, text: str, symbol: str) -> pl.DataFrame:
        """Text → frame with exactly BAR_INPUT_COLUMNS (session: Date, prices: Float64)."""


def finish_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Normalise a parsed frame: column subset/order, dtypes, ascending sessions, no dupes."""
    return (
        df.select(list(BAR_INPUT_COLUMNS))
        .with_columns(pl.col("open", "high", "low", "close", "volume").cast(pl.Float64))
        .unique(subset=["session"], keep="last")
        .sort("session")
    )
