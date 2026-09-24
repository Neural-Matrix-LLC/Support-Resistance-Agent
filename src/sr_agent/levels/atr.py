"""Wilder average true range (SR_Technical_Document §3.6.1).

    TR_t  = max(H_t − L_t, |H_t − C_{t−1}|, |L_t − C_{t−1}|)
    ATR_n = mean(TR_1..TR_n);  ATR_t = ((n−1)·ATR_{t−1} + TR_t) / n

Every ATR-normalised quantity in every phase uses this exact series with
n = thresholds.atr_window (frozen at 20).
"""

from __future__ import annotations

import numpy as np
import polars as pl

from sr_agent.config import load_thresholds
from sr_agent.data.bars import Bars


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """§3.6.1:  TR_t = max( H_t − L_t,  |H_t − C_{t−1}|,  |L_t − C_{t−1}| ).

    The first bar has no C_{t−1}, so TR_0 = H_0 − L_0.
    """
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]  # C_{t−1}
    hl = high - low  # H_t − L_t
    hc = np.abs(high - prev_close)  # |H_t − C_{t−1}|
    lc = np.abs(low - prev_close)  # |L_t − C_{t−1}|
    tr = np.nanmax(np.vstack([hl, hc, lc]), axis=0)
    tr[0] = hl[0]  # no prior close on the first bar
    return tr


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """§3.6.1 Wilder smoothing:

        ATR_n = mean(TR_1..TR_n)                      (seed, at index n−1)
        ATR_t = ( (n−1)·ATR_{t−1} + TR_t ) / n        (t ≥ n)

    NaN for the first n−1 bars (not enough history).
    """
    tr = true_range(high, low, close)
    out = np.full(tr.shape, np.nan)
    if tr.shape[0] < n:
        return out
    out[n - 1] = tr[:n].mean()  # ATR_n = mean(TR_1..TR_n)
    for t in range(n, tr.shape[0]):
        out[t] = ((n - 1) * out[t - 1] + tr[t]) / n  # ATR_t = ((n−1)·ATR_{t−1} + TR_t)/n
    return out


def atr(bars: Bars, n: int) -> pl.Series:
    df = bars.df
    values = wilder_atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), n)
    return pl.Series(f"atr{n}", values, dtype=pl.Float64)


def atr20(bars: Bars) -> pl.Series:
    """ATR over the frozen window; `atr20(bars)[-1]` is ATR₂₀ at `as_of`."""
    n = int(load_thresholds()["atr_window"])
    return atr(bars, n)


def atr_at_as_of(bars: Bars) -> float:
    """§3.6.1: ATR₂₀ at `as_of` is the value on the last session ≤ `as_of`."""
    value = atr20(bars)[-1]
    if value is None or not np.isfinite(value):
        raise ValueError(
            f"{bars.ticker}: fewer than {load_thresholds()['atr_window']} bars, ATR undefined"
        )
    return float(value)
