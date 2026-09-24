"""Raw sources, the immutable cache and point-in-time loading. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from sr_agent.data.bars import Bars
from sr_agent.data.ingestion import RawSourceError, default_source_name, load_bars, make_source
from sr_agent.data.ingestion.cache import cache_dir, fetch_to_cache, pick_cache_file
from sr_agent.data.ingestion.loader import attach_available_at
from sr_agent.data.ingestion.stooq import StooqSource
from sr_agent.data.ingestion.tiingo import TiingoSource
from sr_agent.data.ingestion.yfinance import YFinanceSource, history_to_csv
from tests.conftest import stooq_csv_text, synthetic_ohlcv

STOOQ = "Date,Open,High,Low,Close,Volume\n2026-09-10,1,2,0.5,1.5,100\n2026-09-11,1.5,2.5,1,2,200\n"
TIINGO = (
    "date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor\n"
    "2026-09-10T00:00:00.000Z,1.5,2,0.5,1,100,1.5,2,0.5,1,100,0,1\n"
    "2026-09-11T00:00:00.000Z,2,2.5,1,1.5,200,2,2.5,1,1.5,200,0,1\n"
)
YFINANCE = (
    "Date,Open,High,Low,Close,Adj Close,Volume\n"
    "2026-09-10,1,2,0.5,1.5,1.4,100\n"
    "2026-09-11,1.5,2.5,1,2,,200\n"  # partial bar of an open session: Adj Close empty
)
HTML = "<!DOCTYPE html><html><body>This site requires JavaScript</body></html>"


def yf_history(sessions: list[date], tz: str = "America/New_York") -> pd.DataFrame:
    """A frame shaped like `yfinance.Ticker.history(auto_adjust=False, actions=False)`."""
    n = len(sessions)
    return pd.DataFrame(
        {
            "Open": [1.0] * n,
            "High": [2.0] * n,
            "Low": [0.5] * n,
            "Close": [1.5] * n,
            "Adj Close": [1.4] * n,
            "Volume": [100] * n,
        },
        index=pd.DatetimeIndex([pd.Timestamp(d, tz=tz) for d in sessions], name="Date"),
    )


class FakeSource(StooqSource):
    """Stooq-format source with canned text instead of HTTP."""

    def __init__(self, text: str = STOOQ) -> None:
        self.text = text
        self.calls = 0

    def fetch(self, symbol: str) -> str:
        self.calls += 1
        self.parse(self.text, symbol)
        return self.text


def test_stooq_parse_and_symbol() -> None:
    src = StooqSource()
    assert src.symbol("aapl", "US") == "AAPL.US" and src.symbol("0700", "HK") == "0700.HK"
    df = src.parse(STOOQ, "X")
    assert df.columns == ["session", "open", "high", "low", "close", "volume"]
    assert df["session"].to_list() == [date(2026, 9, 10), date(2026, 9, 11)]
    assert df["close"].dtype == pl.Float64


def test_stooq_rejects_browser_challenge_page() -> None:
    with pytest.raises(RawSourceError, match="download the CSV manually"):
        StooqSource().parse(HTML, "AAPL.US")


def test_tiingo_parse_takes_unadjusted_columns_and_is_us_only() -> None:
    src = TiingoSource(token="t")
    df = src.parse(TIINGO, "AAPL")
    assert df["session"].to_list() == [date(2026, 9, 10), date(2026, 9, 11)]
    assert df["open"].to_list() == [1.0, 1.5] and df["volume"].to_list() == [100.0, 200.0]
    assert src.symbol("aapl", "US") == "AAPL"
    with pytest.raises(RawSourceError, match="US only"):
        src.symbol("0700", "HK")
    with pytest.raises(RawSourceError, match="not a Tiingo CSV"):
        src.parse(HTML, "AAPL")


def test_tiingo_without_token_fails_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(RawSourceError, match="TIINGO_API_KEY"):
        TiingoSource().fetch("AAPL")


def test_yfinance_symbol_parse_and_csv_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    src = YFinanceSource()
    assert src.symbol("aapl", "US") == "AAPL"
    assert src.symbol("700", "HK") == "0700.HK" and src.symbol("0700", "HK") == "0700.HK"
    df = src.parse(YFINANCE, "AAPL")
    assert df.columns == ["session", "open", "high", "low", "close", "volume"]
    assert df["session"].to_list() == [date(2026, 9, 10), date(2026, 9, 11)]
    assert df["volume"].to_list() == [100.0, 200.0]  # the partial bar is kept: cut is downstream
    with pytest.raises(RawSourceError, match="not a yfinance CSV"):
        src.parse(STOOQ, "AAPL")
    # fetch() serialises the pandas history to the CSV the parser reads; tz is dropped
    sessions = [date(2026, 9, 10), date(2026, 9, 11)]
    monkeypatch.setattr("sr_agent.data.ingestion.yfinance._history", lambda s: yf_history(sessions))
    text = src.fetch("AAPL")
    assert text.splitlines()[0] == "Date,Open,High,Low,Close,Adj Close,Volume"
    assert text == history_to_csv(yf_history(sessions))
    assert src.parse(text, "AAPL")["session"].to_list() == sessions
    hk = src.parse(history_to_csv(yf_history(sessions, tz="Asia/Hong_Kong")), "0700.HK")
    assert hk["session"].to_list() == sessions


def test_yfinance_empty_history_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sr_agent.data.ingestion.yfinance._history", lambda s: yf_history([]))
    with pytest.raises(RawSourceError, match="no history"):
        YFinanceSource().fetch("NOPE")


def test_default_source_is_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    assert default_source_name() == "yfinance"
    monkeypatch.setenv("TIINGO_API_KEY", "abc")
    assert default_source_name() == "yfinance"  # a token does not change the spine
    assert isinstance(make_source("yfinance"), YFinanceSource)
    assert isinstance(make_source("tiingo"), TiingoSource)
    assert isinstance(make_source("stooq"), StooqSource)
    with pytest.raises(ValueError, match="unknown source"):
        make_source("bloomberg")


def test_cache_is_immutable_and_dated(tmp_path: Path) -> None:
    src = FakeSource()
    p1 = fetch_to_cache(src, "T.US", tmp_path, today=date(2026, 9, 12))
    assert p1 == cache_dir(tmp_path, "stooq", "T.US") / "2026-09-12.csv"
    assert p1.read_text() == STOOQ and src.calls == 1
    src.text = "Date,Open,High,Low,Close,Volume\n2026-09-11,9,9,9,9,9\n"
    p2 = fetch_to_cache(src, "T.US", tmp_path, today=date(2026, 9, 12))
    assert p2 == p1 and p1.read_text() == STOOQ and src.calls == 1  # same day: untouched
    p3 = fetch_to_cache(src, "T.US", tmp_path, today=date(2026, 9, 13))
    assert p3.name == "2026-09-13.csv" and p1.read_text() == STOOQ  # new file, old intact
    assert not list(p1.parent.glob("*.part"))


def test_bad_response_never_reaches_disk(tmp_path: Path) -> None:
    with pytest.raises(RawSourceError):
        fetch_to_cache(FakeSource(HTML), "T.US", tmp_path, today=date(2026, 9, 12))
    assert not list(tmp_path.rglob("*"))  # not even the folder's files


def test_pick_cache_file_prefers_newest_at_or_before_as_of(tmp_path: Path) -> None:
    folder = tmp_path / "x"
    folder.mkdir()
    for d in ("2026-09-01", "2026-09-08", "2026-09-15"):
        (folder / f"{d}.csv").write_text("")
    (folder / "notes.csv").write_text("")
    assert pick_cache_file(folder, date(2026, 9, 10)).name == "2026-09-08.csv"
    assert pick_cache_file(folder, date(2026, 9, 20)).name == "2026-09-15.csv"
    assert pick_cache_file(folder, date(2026, 8, 1)).name == "2026-09-15.csv"  # fallback
    assert pick_cache_file(tmp_path / "missing", date(2026, 9, 1)) is None


def test_attach_available_at_uses_exact_close_and_warns_on_unknown_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    df = pl.DataFrame(
        {
            "session": [date(2026, 1, 9), date(2026, 9, 11), date(2026, 9, 13)],
            "open": [1.0] * 3,
            "high": [1.0] * 3,
            "low": [1.0] * 3,
            "close": [1.0] * 3,
            "volume": [1.0] * 3,
        }
    )
    with caplog.at_level("WARNING"):
        out = attach_available_at(df, "XNYS", 15, "20:00")
    assert out["available_at"].to_list() == [
        datetime(2026, 1, 9, 21, 15, tzinfo=UTC),  # EST close + lag
        datetime(2026, 9, 11, 20, 15, tzinfo=UTC),  # EDT close + lag
        datetime(2026, 9, 13, 20, 15, tzinfo=UTC),  # Sunday: fallback close + lag
    ]
    assert "not on XNYS calendar" in caplog.text


def test_load_bars_offline_miss_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="--offline"):
        load_bars("TEST", "US", date(2026, 9, 11), tmp_path, source=StooqSource(), offline=True)


def test_load_bars_fetches_once_then_reads_cache(tmp_path: Path) -> None:
    src = FakeSource(stooq_csv_text(synthetic_ohlcv(30, seed=0)))
    b1 = load_bars("TEST", "US", date(2026, 9, 11), tmp_path, source=src, today=date(2026, 9, 12))
    b2 = load_bars("TEST", "US", date(2026, 9, 11), tmp_path, source=src, offline=True)
    assert src.calls == 1 and b1.df.equals(b2.df)
    assert b1.ticker == "TEST" and b1.market == "US" and len(b1) == 30


def test_load_bars_is_point_in_time(cached_stooq: Path) -> None:
    full = load_bars(
        "TEST", "US", date(2026, 9, 11), cached_stooq, source=StooqSource(), offline=True
    )
    cut = load_bars(
        "TEST", "US", date(2026, 8, 14), cached_stooq, source=StooqSource(), offline=True
    )
    assert cut.last_session == date(2026, 8, 14)
    assert cut.df["session"].max() < full.df["session"].max()
    assert (cut.df["available_at"] <= datetime(2026, 8, 14, 23, 59, 59, tzinfo=UTC)).all()
    with pytest.raises(ValueError, match="no sessions on or before"):
        load_bars("TEST", "US", date(1980, 1, 1), cached_stooq, source=StooqSource(), offline=True)


def test_bars_hide_the_partial_bar_of_an_open_session() -> None:
    """available_at ≤ min(end of as_of, now): a session whose close is still in the
    future is not knowable even though the provider already serves its partial bar."""
    df = attach_available_at(synthetic_ohlcv(5, seed=0, end=date(2026, 9, 18)), "XNYS", 0, "20:00")
    sessions = df["session"].to_list()
    assert sessions[-1] == date(2026, 9, 18)
    during = datetime(2026, 9, 18, 15, 30, tzinfo=UTC)  # 11:30 New York, market open
    after = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)  # the close itself
    assert (
        Bars.from_frame(df, "T", "US", date(2026, 9, 18), now=during).last_session == sessions[-2]
    )
    assert Bars.from_frame(df, "T", "US", date(2026, 9, 18), now=after).last_session == sessions[-1]
    # an as_of in the past is unaffected by the clock
    assert Bars.from_frame(df, "T", "US", sessions[-2], now=after).last_session == sessions[-2]


def test_load_bars_passes_now_through(tmp_path: Path) -> None:
    text = stooq_csv_text(synthetic_ohlcv(30, seed=0, end=date(2026, 9, 18)))
    src = FakeSource(text)
    during = datetime(2026, 9, 18, 15, 30, tzinfo=UTC)
    b = load_bars(
        "TEST", "US", date(2026, 9, 18), tmp_path, source=src, today=date(2026, 9, 18), now=during
    )
    assert b.last_session == date(2026, 9, 17)
    assert src.calls == 1 and b.as_of == date(2026, 9, 18)


def test_bars_from_frame_enforces_availability_and_columns() -> None:
    df = attach_available_at(synthetic_ohlcv(5, seed=0), "XNYS", 0, "20:00")
    # as_of on the second-to-last session hides the last row even though it is in df.
    sessions = df["session"].to_list()
    b = Bars.from_frame(df, "T", "US", sessions[-2])
    assert b.last_session == sessions[-2]
    with pytest.raises(ValueError, match="missing columns"):
        Bars.from_frame(df.drop("available_at"), "T", "US", sessions[-1])
    with pytest.raises(ValueError, match="no sessions"):
        Bars.from_frame(df, "T", "US", date(1990, 1, 1))
