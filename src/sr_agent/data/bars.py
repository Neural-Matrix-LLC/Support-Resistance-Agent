"""`Bars`: the daily-bar frame every later layer consumes (L1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import polars as pl

BAR_COLUMNS: tuple[str, ...] = ("session", "open", "high", "low", "close", "volume", "available_at")

BAR_SCHEMA: dict[str, pl.DataType] = {
    "session": pl.Date(),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
    "available_at": pl.Datetime("us", "UTC"),
}


@dataclass(frozen=True)
class Bars:
    """Daily OHLCV for one security, already filtered to `available_at <= as_of`.

    `df` is sorted ascending by `session` and has exactly the columns in
    `BAR_COLUMNS`. Construct through `Bars.from_frame` so the invariants hold.
    """

    df: pl.DataFrame
    ticker: str
    market: str
    as_of: date

    @classmethod
    def from_frame(
        cls,
        df: pl.DataFrame,
        ticker: str,
        market: str,
        as_of: date,
        now: datetime | None = None,
    ) -> Bars:
        """The only constructor. Applies the availability rule (§2.4):

            visible(row)  ⇔  available_at ≤ min( end_of_day_UTC(as_of), now )

        `as_of` is a date, so its cut is 23:59:59.999999 UTC of that day; `now`
        (default: the wall clock) additionally hides a bar whose session close is
        still in the future — the partial bar a provider serves while the market
        is open (2026-09-18 finding, see HISTORY.md).
        """
        missing = [c for c in BAR_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"bars for {ticker}: missing columns {missing}")
        end_of_day = datetime.combine(as_of, datetime.max.time()).replace(tzinfo=UTC)
        cutoff = min(end_of_day, now or datetime.now(UTC))
        frame = (
            df.select(list(BAR_COLUMNS))
            .cast(BAR_SCHEMA)  # type: ignore[arg-type]
            .filter(pl.col("available_at") <= pl.lit(cutoff))
            .sort("session")
        )
        if frame.is_empty():
            raise ValueError(f"bars for {ticker}: no sessions available at {as_of}")
        return cls(df=frame, ticker=ticker, market=market, as_of=as_of)

    def __len__(self) -> int:
        return self.df.height

    def last(self) -> dict[str, object]:
        """The most recent visible bar as a plain dict."""
        return self.df.row(-1, named=True)

    @property
    def spot(self) -> float:
        return float(self.df["close"][-1])

    @property
    def last_session(self) -> date:
        value = self.df["session"][-1]
        assert isinstance(value, date)
        return value
