"""Wilder ATR against hand-computed values (§3.6.1)."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from sr_agent.levels.atr import atr, atr20, atr_at_as_of, true_range, wilder_atr
from tests.conftest import bars_from_ohlcv, synthetic_ohlcv, xnys_sessions

# 25 bars: (high, low, close). True ranges worked out by hand below.
FIXTURE = [
    (10.0, 9.0, 9.5),
    (10.5, 9.4, 10.2),
    (10.8, 10.0, 10.1),
    (10.4, 9.6, 9.8),
    (10.2, 9.5, 10.0),
    (11.0, 9.9, 10.9),
    (11.2, 10.6, 10.7),
    (10.9, 10.2, 10.4),
    (10.6, 10.0, 10.5),
    (10.8, 10.3, 10.6),
    (11.1, 10.5, 11.0),
    (11.5, 10.9, 11.4),
    (11.6, 11.0, 11.1),
    (11.3, 10.7, 10.8),
    (11.0, 10.4, 10.9),
    (11.2, 10.8, 11.1),
    (11.4, 11.0, 11.3),
    (11.9, 11.2, 11.8),
    (12.0, 11.5, 11.6),
    (11.8, 11.3, 11.4),
    (11.7, 11.2, 11.6),
    (12.1, 11.5, 12.0),
    (12.4, 11.9, 12.3),
    (12.2, 11.8, 12.0),
    (12.5, 12.0, 12.4),
]


def _fixture_bars():
    n = len(FIXTURE)
    hi = [h for h, _, _ in FIXTURE]
    lo = [lo for _, lo, _ in FIXTURE]
    cl = [c for _, _, c in FIXTURE]
    df = pl.DataFrame(
        {
            "session": xnys_sessions(date(2026, 9, 11), n),
            "open": cl,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": [1.0] * n,
        }
    )
    return bars_from_ohlcv(df)


def _reference_atr(n: int) -> list[float]:
    """Independent, loop-only implementation of the §3.6.1 formula."""
    trs = []
    for i, (h, lo, _c) in enumerate(FIXTURE):
        if i == 0:
            trs.append(h - lo)
        else:
            pc = FIXTURE[i - 1][2]
            trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    out: list[float] = [float("nan")] * (n - 1)
    out.append(sum(trs[:n]) / n)
    for i in range(n, len(trs)):
        out.append(((n - 1) * out[-1] + trs[i]) / n)
    return out


def test_true_range_by_hand() -> None:
    hi, lo, cl = (np.array(x) for x in zip(*FIXTURE, strict=True))
    tr = true_range(hi, lo, cl)
    assert tr[0] == pytest.approx(1.0)  # first bar: H − L only
    # bar 2: H−L = 1.1, |H−C_prev| = |10.5−9.5| = 1.0, |L−C_prev| = 0.1 → 1.1
    assert tr[1] == pytest.approx(1.1)
    # bar 6: H−L = 1.1, |11.0−10.0| = 1.0, |9.9−10.0| = 0.1 → 1.1
    assert tr[5] == pytest.approx(1.1)
    # bar 4: H−L = 0.8, |10.4−10.1| = 0.3, |9.6−10.1| = 0.5 → 0.8
    assert tr[3] == pytest.approx(0.8)


def test_wilder_seed_and_recursion_n3() -> None:
    hi, lo, cl = (np.array(x) for x in zip(*FIXTURE, strict=True))
    out = wilder_atr(hi, lo, cl, 3)
    assert np.isnan(out[:2]).all()
    # TR_3: H−L 0.8, |10.8−10.2| 0.6, |10.0−10.2| 0.2 → 0.8;  ATR_3 = mean(TR_1..TR_3)
    assert out[2] == pytest.approx((1.0 + 1.1 + 0.8) / 3)
    # ATR_4 = (2·ATR_3 + TR_4) / 3 with TR_4 = 0.8
    assert out[3] == pytest.approx((2 * out[2] + 0.8) / 3)


def test_atr20_matches_reference_on_25_bar_fixture() -> None:
    bars = _fixture_bars()
    got = atr20(bars).to_numpy()
    ref = np.array(_reference_atr(20))
    assert np.isnan(got[:19]).all()
    np.testing.assert_allclose(got[19:], ref[19:], rtol=1e-12)
    assert atr_at_as_of(bars) == pytest.approx(ref[-1])
    assert atr(bars, 20).name == "atr20"


def test_atr_undefined_with_too_few_bars() -> None:
    bars = bars_from_ohlcv(synthetic_ohlcv(10, seed=0))
    assert atr20(bars).is_nan().all()
    with pytest.raises(ValueError, match="ATR undefined"):
        atr_at_as_of(bars)


def test_atr_positive_on_random_walk() -> None:
    bars = bars_from_ohlcv(synthetic_ohlcv(300, seed=5))
    values = atr20(bars).to_numpy()[19:]
    assert (values > 0).all()
