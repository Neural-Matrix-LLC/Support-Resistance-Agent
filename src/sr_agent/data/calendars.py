"""Session arithmetic through exchange_calendars — never calendar days (D3)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

# Yahoo histories start in the 1960s for the oldest listings (AAPL: 1980-12-12);
# XHKG's lower bound is 1960-01-01, XNYS's is earlier. Building either from 1960
# takes ~0.4 s once per process (cached below).
_DEFAULT_START = "1960-01-01"


@lru_cache(maxsize=8)
def get_calendar(name: str, start: str = _DEFAULT_START) -> xcals.ExchangeCalendar:
    return xcals.get_calendar(name, start=start)


def is_session(calendar: str, day: date) -> bool:
    """True iff `day` is a session; False (never an exception) outside the calendar's range."""
    cal = get_calendar(calendar)
    ts = pd.Timestamp(day)
    if ts < cal.first_session or ts > cal.last_session:
        return False
    return bool(cal.is_session(ts))


def session_close_utc(calendar: str, day: date) -> datetime:
    """Exact close of `day` on `calendar` (DST- and half-day-aware), tz-aware UTC."""
    ts = get_calendar(calendar).session_close(pd.Timestamp(day))
    return ts.to_pydatetime().astimezone(UTC)


def next_sessions(calendar: str, as_of: date, n: int) -> list[date]:
    """The forecast window (§2.4): `sessions(as_of, n)` = the `n` exchange sessions
    strictly after `as_of`, half-days included, from `exchange_calendars` (D3)."""
    cal = get_calendar(calendar)
    first = cal.date_to_session(pd.Timestamp(as_of), direction="next")
    if first.date() == as_of:
        first = cal.next_session(first)
    window = cal.sessions_window(first, n)
    return [ts.date() for ts in window]
