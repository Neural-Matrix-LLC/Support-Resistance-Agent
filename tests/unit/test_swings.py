"""SwingGenerator on a zig-zag where the accepted swings are known by construction (§3.6.2)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from sr_agent.levels.atr import atr20
from sr_agent.levels.generators.structure import SwingGenerator
from tests.conftest import bars_from_ohlcv, xnys_sessions


def zigzag_bars(
    amplitude: float, leg: int = 6, legs: int = 12, base: float = 100.0, bar_range: float = 0.5
):
    """Triangle wave: peaks at base+amplitude, troughs at base, `leg` bars per leg.
    Every bar has range `bar_range`, so ATR ≈ bar_range (+ the close-to-close step)."""
    closes: list[float] = []
    for i in range(legs):
        up = i % 2 == 0
        for j in range(leg):
            frac = (j + 1) / leg
            closes.append(base + amplitude * (frac if up else 1 - frac))
    n = len(closes)
    hi = [c + bar_range / 2 for c in closes]
    lo = [c - bar_range / 2 for c in closes]
    df = pl.DataFrame(
        {
            "session": xnys_sessions(date(2026, 9, 11), n),
            "open": closes,
            "high": hi,
            "low": lo,
            "close": closes,
            "volume": [1.0] * n,
        }
    )
    return bars_from_ohlcv(df)


def test_peaks_and_troughs_are_found_with_known_k() -> None:
    bars = zigzag_bars(amplitude=10.0)
    atr_now = float(atr20(bars)[-1])
    gen = SwingGenerator(keep_within_atr=1e9)  # keep everything; the test is about detection
    levels = gen.generate(bars, bars.as_of)
    highs = {c.formed_at for c in levels if c.source.startswith("swing_high")}
    lows = {c.formed_at for c in levels if c.source.startswith("swing_low")}
    sessions = bars.df["session"].to_list()
    # Peaks sit at the end of every even leg, troughs at the end of every odd leg.
    leg = 6
    expected_peaks = {sessions[(2 * i + 1) * leg - 1] for i in range(6)}
    expected_troughs = {sessions[(2 * i + 2) * leg - 1] for i in range(5)}  # last trough = as_of
    # Swings before bar 20 have no ATR_t (Wilder warm-up) and the last trough sits at
    # as_of with no retrace after it, so none of those can be accepted.
    assert highs == {s for s in expected_peaks if sessions.index(s) >= 19}
    assert lows == {s for s in expected_troughs if sessions.index(s) >= 19} - {sessions[-1]}
    # Retrace of 10 points >> 2·ATR, so every accepted swing exists at all four k.
    per_swing = {}
    for c in levels:
        per_swing.setdefault((c.source.split("_k")[0], c.formed_at), set()).add(c.meta["k"])
    assert all(ks == {0.5, 1.0, 1.5, 2.0} for ks in per_swing.values())
    assert all(c.family == "A" and c.timeframe == "1D" for c in levels)
    assert all(c.upper - c.lower == pytest.approx(0.2 * atr_now) for c in levels)


def test_available_at_is_after_formation_and_grows_with_k() -> None:
    bars = zigzag_bars(amplitude=10.0)
    levels = SwingGenerator(keep_within_atr=1e9).generate(bars, bars.as_of)
    closes = dict(zip(bars.df["session"].to_list(), bars.df["available_at"].to_list(), strict=True))
    for c in levels:
        assert c.formed_at is not None
        assert c.available_at > closes[c.formed_at]  # the first leakage trap
        assert c.available_at <= bars.df["available_at"][-1]
    by_swing: dict[tuple[str, date], dict[float, int]] = {}
    for c in levels:
        by_swing.setdefault((c.source.split("_k")[0], c.formed_at), {})[c.meta["k"]] = c.meta[
            "confirm_sessions"
        ]
    for confirms in by_swing.values():
        ks = sorted(confirms)
        assert [confirms[k] for k in ks] == sorted(confirms[k] for k in ks)


def test_small_amplitude_rejects_large_k() -> None:
    # Bar range 0.5 → ATR = 0.5; peak-high to trough-low retrace = amplitude + 0.5 = 0.9,
    # which clears k ∈ {0.5, 1.0, 1.5} (≤ 0.75) but not k = 2.0 (needs 1.0).
    bars = zigzag_bars(amplitude=0.4)
    levels = SwingGenerator(keep_within_atr=1e9).generate(bars, bars.as_of)
    ks = {c.meta["k"] for c in levels}
    assert 0.5 in ks and 2.0 not in ks


def test_levels_far_from_spot_are_dropped() -> None:
    bars = zigzag_bars(amplitude=10.0, leg=12)  # gentler slope → smaller ATR
    atr_now = float(atr20(bars)[-1])
    assert 10.0 > 6 * atr_now  # peaks are more than 6 ATR above the trough at as_of
    levels = SwingGenerator().generate(bars, bars.as_of)
    assert levels and all(abs(c.level - bars.spot) <= 6 * atr_now for c in levels)
    assert not any(c.source.startswith("swing_high") for c in levels)
