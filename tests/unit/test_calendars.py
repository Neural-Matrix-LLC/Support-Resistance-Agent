from datetime import UTC, date, datetime

from sr_agent.data.calendars import is_session, next_sessions, session_close_utc


def test_next_sessions_are_strictly_after_as_of_and_skip_weekends() -> None:
    # 2026-09-11 is a Friday and a session.
    assert next_sessions("XNYS", date(2026, 9, 11), 5) == [
        date(2026, 9, 14),
        date(2026, 9, 15),
        date(2026, 9, 16),
        date(2026, 9, 17),
        date(2026, 9, 18),
    ]
    # Saturday as_of → the same window.
    assert next_sessions("XNYS", date(2026, 9, 12), 5)[0] == date(2026, 9, 14)


def test_holidays_are_not_sessions() -> None:
    assert not is_session("XNYS", date(2026, 7, 3))  # Independence Day observed
    assert is_session("XNYS", date(2026, 7, 6))
    assert next_sessions("XNYS", date(2026, 7, 2), 1) == [date(2026, 7, 6)]


def test_session_close_follows_dst() -> None:
    assert session_close_utc("XNYS", date(2026, 9, 11)) == datetime(2026, 9, 11, 20, 0, tzinfo=UTC)
    assert session_close_utc("XNYS", date(2026, 1, 9)) == datetime(2026, 1, 9, 21, 0, tzinfo=UTC)
    assert session_close_utc("XHKG", date(2026, 9, 11)) == datetime(2026, 9, 11, 8, 0, tzinfo=UTC)


def test_is_session_covers_old_histories_and_never_raises() -> None:
    """yfinance serves AAPL from 1980-12-12; the calendar must know those sessions,
    and anything outside its range is simply 'not a session' (fallback stamp)."""
    assert is_session("XNYS", date(1980, 12, 12))  # AAPL's first bar, a Friday
    assert not is_session("XNYS", date(1980, 12, 14))  # Sunday
    assert is_session("XHKG", date(1990, 1, 2))
    assert not is_session("XNYS", date(1900, 1, 2))  # before the calendar: False, not an error
    assert not is_session("XNYS", date(2100, 1, 4))
