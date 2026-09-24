"""Shared fixtures: synthetic daily bars, built without any network access."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from sr_agent.data.bars import Bars
from sr_agent.data.calendars import get_calendar
from sr_agent.data.ingestion.loader import attach_available_at


def xnys_sessions(end: date, n: int) -> list[date]:
    """The last `n` XNYS sessions ending on or before `end`."""
    cal = get_calendar("XNYS")
    last = cal.date_to_session(pd.Timestamp(end), direction="previous")
    return [ts.date() for ts in cal.sessions_window(last, -n)]


def synthetic_ohlcv(
    n: int,
    seed: int = 0,
    start_price: float = 100.0,
    daily_vol: float = 0.015,
    gapless: bool = False,
    end: date = date(2026, 9, 11),
) -> pl.DataFrame:
    """Geometric random walk with intra-bar ranges. `gapless=True` forces
    H_s >= C_{s-1} >= L_s so a zone containing the spot is touched with certainty."""
    rng = np.random.default_rng(seed)
    sessions = xnys_sessions(end, n)
    close = start_price * np.exp(np.cumsum(rng.normal(0.0, daily_vol, n)))
    prev = np.concatenate([[start_price], close[:-1]])
    span = np.abs(rng.normal(0.0, daily_vol, n)) * prev + 1e-6
    hi = np.maximum(close, prev if gapless else close) + span * rng.uniform(0.2, 1.0, n)
    lo = np.minimum(close, prev if gapless else close) - span * rng.uniform(0.2, 1.0, n)
    opn = np.clip(prev * (1 + rng.normal(0, daily_vol / 4, n)), lo, hi)
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pl.DataFrame(
        {"session": sessions, "open": opn, "high": hi, "low": lo, "close": close, "volume": vol}
    )


def bars_from_ohlcv(
    df: pl.DataFrame, ticker: str = "TEST", market: str = "US", as_of: date | None = None
) -> Bars:
    stamped = attach_available_at(df, "XNYS", 0, "20:00")
    as_of = as_of or df["session"][-1]
    return Bars.from_frame(stamped, ticker=ticker, market=market, as_of=as_of)


def stooq_csv_text(df: pl.DataFrame) -> str:
    out = df.rename(
        {
            "session": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    return out.write_csv()


@pytest.fixture
def bars600() -> Bars:
    return bars_from_ohlcv(synthetic_ohlcv(600, seed=1))


@pytest.fixture
def gapless_bars() -> Bars:
    return bars_from_ohlcv(synthetic_ohlcv(600, seed=2, gapless=True))


@pytest.fixture
def cached_stooq(tmp_path: Path) -> Path:
    """A data_dir holding one Stooq-format cache file for TEST.US, fetched 2026-09-12."""
    df = synthetic_ohlcv(600, seed=3)
    folder = tmp_path / "raw" / "stooq" / "TEST.US"
    folder.mkdir(parents=True)
    (folder / "2026-09-12.csv").write_text(stooq_csv_text(df), encoding="utf-8")
    return tmp_path
