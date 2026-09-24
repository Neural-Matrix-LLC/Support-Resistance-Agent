"""RoundNumberGenerator ladders (§3.6.3)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sr_agent.levels.generators.base import ALWAYS_AVAILABLE
from sr_agent.levels.generators.round import RoundNumberGenerator, ladder_steps, rungs_within
from tests.conftest import bars_from_ohlcv, xnys_sessions


def flat_bars(price: float, atr: float, n: int = 40):
    """Bars whose every session has range `atr` and closes at `price` (so ATR₂₀ = atr)."""
    df = pl.DataFrame(
        {
            "session": xnys_sessions(date(2026, 9, 11), n),
            "open": [price] * n,
            "high": [price + atr / 2] * n,
            "low": [price - atr / 2] * n,
            "close": [price] * n,
            "volume": [1.0] * n,
        }
    )
    return bars_from_ohlcv(df)


def test_ladder_steps_for_182() -> None:
    assert ladder_steps(182.4, [10, 20, 100]) == [10.0, 5.0, 1.0, 0.5]


def test_rungs_for_182_within_3_atr() -> None:
    bars = flat_bars(182.4, atr=4.0)  # ±12 → [170.4, 194.4]
    levels = RoundNumberGenerator().generate(bars, bars.as_of)
    values = [c.level for c in levels]
    assert values == sorted(values)
    assert {175.0, 180.0, 185.0, 190.0} <= set(values)
    assert 170.0 not in values and 195.0 not in values  # outside ±3·ATR
    assert set(values) == {v / 2 for v in range(341, 389)}  # every half-dollar in range
    by_level = {c.level: c for c in levels}
    assert by_level[180.0].source == "round_10" and by_level[180.0].meta["rank"] == 0
    assert by_level[185.0].source == "round_5" and by_level[185.0].meta["rank"] == 1
    assert by_level[183.0].source == "round_1" and by_level[183.0].meta["rank"] == 2
    assert by_level[182.5].source == "round_0.5" and by_level[182.5].meta["rank"] == 3
    assert all(
        c.family == "B" and c.formed_at is None and c.available_at == ALWAYS_AVAILABLE
        for c in levels
    )
    assert all(c.upper - c.lower == pytest.approx(0.1 * 4.0 * 2) for c in levels)


def test_each_rung_emitted_once() -> None:
    bars = flat_bars(50.0, atr=2.0)
    levels = RoundNumberGenerator().generate(bars, bars.as_of)
    values = [c.level for c in levels]
    assert len(values) == len(set(values))


@given(
    price=st.floats(min_value=0.5, max_value=5000.0),
    radius=st.floats(0.1, 50.0),
    step=st.sampled_from([0.5, 1.0, 5.0, 10.0, 0.05, 100.0]),
)
def test_rungs_within_are_multiples_inside_window(price: float, radius: float, step: float) -> None:
    for r in rungs_within(price, radius, step):
        assert r > 0
        assert abs(r / step - round(r / step)) < 1e-6
        assert price - radius - 1e-6 <= r <= price + radius + 1e-6
