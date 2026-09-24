"""Live provider checks — opt in with `pytest -m integration`; each needs the network."""

from __future__ import annotations

import os
from datetime import date

import pytest

from sr_agent.data.ingestion.base import RawSourceError
from sr_agent.data.ingestion.stooq import StooqSource
from sr_agent.data.ingestion.tiingo import TiingoSource
from sr_agent.data.ingestion.yfinance import YFinanceSource

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("ticker", "market", "min_rows"), [("AAPL", "US", 5000), ("700", "HK", 3000)]
)
def test_yfinance_history(ticker: str, market: str, min_rows: int) -> None:
    src = YFinanceSource()
    symbol = src.symbol(ticker, market)
    df = src.parse(src.fetch(symbol), symbol)
    assert df.height > min_rows and df["session"].max() >= date(2026, 9, 1)
    # Yahoo ships a few inverted bars (0700.HK 2009-12-31, 2010-01-15: high < low).
    # Raw stays raw; P1's DQ score flags them. Fail only if it stops being a trace.
    inverted = (df["high"] < df["low"]).sum()
    assert inverted <= max(2, df.height // 1000), inverted


@pytest.mark.skipif(not os.environ.get("TIINGO_API_KEY"), reason="TIINGO_API_KEY not set")
def test_tiingo_aapl_history() -> None:
    src = TiingoSource()
    df = src.parse(src.fetch("AAPL"), "AAPL")
    assert df.height > 1000 and df["session"].max() >= date(2026, 9, 1)


def test_stooq_endpoint_status() -> None:
    """Documents the current state of Stooq's CSV endpoint (browser challenge as of 2026-09)."""
    src = StooqSource()
    try:
        df = src.parse(src.fetch("AAPL.US"), "AAPL.US")
    except RawSourceError as exc:
        pytest.xfail(f"stooq CSV not scriptable: {exc}")
    assert df.height > 1000
