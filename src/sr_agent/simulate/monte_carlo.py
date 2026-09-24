"""Bar-triple bootstrap Monte Carlo and P(touch) (§3.6.5).

Original formulas (§3.6.5), N = 500 sessions, n_paths = 10 000, H = 5:

    τ_s = ( H_s/C_{s−1},  L_s/C_{s−1},  C_s/C_{s−1} )          s over the last N sessions
    draw τ i.i.d. with replacement, seeded numpy.random.default_rng(seed)
    C_0 = spot
    H_j = C_{j−1}·τ.h,   L_j = C_{j−1}·τ.l,   C_j = C_{j−1}·τ.c,   j = 1..H
    P(touch) = (1/n_paths) · Σ_paths 1[ ∃ j ≤ H : L_j ≤ U  and  H_j ≥ L ]

Sampling whole bar shapes preserves the intra-bar high/low relationship
without a model. Ignores volatility clustering, gaps and events by design —
P3 replaces it behind the same `PathSimulator` interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from sr_agent.config import load_thresholds
from sr_agent.data.bars import Bars
from sr_agent.levels.zone import Zone

HIGH, LOW, CLOSE = 0, 1, 2


class PathSimulator(ABC):
    @abstractmethod
    def simulate(self, bars: Bars, n_paths: int, horizon: int, seed: int) -> np.ndarray:
        """Array [n_paths, horizon, 3] of (high, low, close) per simulated session."""

    @staticmethod
    def p_touch(paths: np.ndarray, zone: Zone) -> float:
        """P(touch) = (1/n_paths) · Σ_paths 1[ ∃ j ≤ H : L_j ≤ U and H_j ≥ L ]  (§2.4 touch)."""
        hit = (paths[:, :, LOW] <= zone.upper) & (paths[:, :, HIGH] >= zone.lower)
        return float(hit.any(axis=1).mean())  # any j on the path, then mean over paths

    @staticmethod
    def p_low_below(paths: np.ndarray, level: float) -> float:
        """P(Low < L) = (1/n_paths) · Σ_paths 1[ ∃ j ≤ H : L_j < L ]."""
        return float((paths[:, :, LOW] < level).any(axis=1).mean())

    @staticmethod
    def p_high_above(paths: np.ndarray, level: float) -> float:
        """P(High > U) = (1/n_paths) · Σ_paths 1[ ∃ j ≤ H : H_j > U ]."""
        return float((paths[:, :, HIGH] > level).any(axis=1).mean())


def bar_triples(bars: Bars, lookback: int) -> np.ndarray:
    """[m, 3] array τ_s = (H_s/C_{s−1}, L_s/C_{s−1}, C_s/C_{s−1}) over the last `lookback`
    sessions (needs lookback + 1 bars for the first C_{s−1})."""
    df = bars.df.tail(lookback + 1)
    if df.height < 2:
        raise ValueError(f"{bars.ticker}: need at least 2 bars for bootstrap triples")
    prev_close = df["close"].to_numpy()[:-1]  # C_{s−1}
    high = df["high"].to_numpy()[1:]  # H_s
    low = df["low"].to_numpy()[1:]  # L_s
    close = df["close"].to_numpy()[1:]  # C_s
    return np.column_stack([high / prev_close, low / prev_close, close / prev_close])


class BootstrapPathSimulator(PathSimulator):
    def __init__(self, lookback: int | None = None) -> None:
        cfg = load_thresholds()["p0"]["mc"]
        self.lookback = int(lookback if lookback is not None else cfg["lookback"])

    def simulate(self, bars: Bars, n_paths: int, horizon: int, seed: int) -> np.ndarray:
        triples = bar_triples(bars, self.lookback)
        rng = np.random.default_rng(seed)  # seeded: replay is byte-identical (BP §10.4.4)
        idx = rng.integers(0, triples.shape[0], size=(n_paths, horizon))  # i.i.d. with replacement
        tau = triples[idx]  # [n_paths, horizon, 3]: one τ per (path, session j)
        spot = bars.spot  # C_0 = spot
        close = spot * np.cumprod(tau[:, :, CLOSE], axis=1)  # C_j = C_{j−1}·τ.c
        prev_close = np.concatenate([np.full((n_paths, 1), spot), close[:, :-1]], axis=1)  # C_{j−1}
        out = np.empty((n_paths, horizon, 3))
        out[:, :, HIGH] = prev_close * tau[:, :, HIGH]  # H_j = C_{j−1}·τ.h
        out[:, :, LOW] = prev_close * tau[:, :, LOW]  # L_j = C_{j−1}·τ.l
        out[:, :, CLOSE] = close
        return out
