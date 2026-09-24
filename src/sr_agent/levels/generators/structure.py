"""Family A — multi-k swing highs/lows (§3.6.2; design-fixed §9).

Original formulas (§3.6.2), window w = 3, M = 20 sessions, k ∈ {0.5, 1, 1.5, 2}:

    candidate_high(t)  ⇔  H_t = max(H_{t−w..t+w})
    candidate_low(t)   ⇔  L_t = min(L_{t−w..t+w})
    accept_high(t, k)  ⇔  H_t − min(L_{t+1..t+m}) ≥ k·ATR_t   for some m ≤ M
    accept_low(t, k)   ⇔  max(H_{t+1..t+m}) − L_t ≥ k·ATR_t   for some m ≤ M

Each accepted (t, k) emits one CandidateLevel:

    level = H_t (or L_t),  lower = level − 0.1·ATR,  upper = level + 0.1·ATR
    formed_at = session t,  available_at = close of session t+m  (m = first
    confirming session — the level is not knowable before the retrace)
    kept only if |level − spot| ≤ 6·ATR

The 0.1·ATR half-width and the ±6·ATR cut use ATR₂₀ at `as_of`; the
acceptance test uses ATR_t at formation.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from sr_agent.config import load_thresholds
from sr_agent.data.bars import Bars
from sr_agent.levels.atr import atr20
from sr_agent.levels.generators.base import CandidateLevel, LevelGenerator


class SwingGenerator(LevelGenerator):
    family = "A"

    def __init__(
        self,
        k_atr: list[float] | None = None,
        window: int | None = None,
        confirm_max_sessions: int | None = None,
        half_width_atr: float | None = None,
        keep_within_atr: float | None = None,
    ) -> None:
        cfg: dict[str, Any] = load_thresholds()["p0"]["swing"]
        self.k_atr = [float(k) for k in (k_atr if k_atr is not None else cfg["k_atr"])]
        self.window = int(window if window is not None else cfg["window"])
        self.confirm_max_sessions = int(
            confirm_max_sessions
            if confirm_max_sessions is not None
            else cfg["confirm_max_sessions"]
        )
        self.half_width_atr = float(
            half_width_atr if half_width_atr is not None else cfg["half_width_atr"]
        )
        self.keep_within_atr = float(
            keep_within_atr if keep_within_atr is not None else cfg["keep_within_atr"]
        )

    def generate(self, bars: Bars, as_of: date) -> list[CandidateLevel]:
        df = bars.df
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        sessions = df["session"].to_list()
        avail = df["available_at"].to_list()
        atr_series = atr20(bars).to_numpy()
        n = high.shape[0]
        atr_now = atr_series[-1]
        if not np.isfinite(atr_now):
            return []
        spot = bars.spot
        half = self.half_width_atr * atr_now
        w, m_max = self.window, self.confirm_max_sessions
        out: list[CandidateLevel] = []

        for t in range(w, n - w):
            atr_t = atr_series[t]
            if not np.isfinite(atr_t):
                continue
            lo_win, hi_win = t - w, t + w + 1
            is_high = high[t] >= high[lo_win:hi_win].max()  # H_t = max(H_{t−w..t+w})
            is_low = low[t] <= low[lo_win:hi_win].min()  # L_t = min(L_{t−w..t+w})
            if not (is_high or is_low):
                continue
            end = min(n, t + 1 + m_max)  # retrace window L/H_{t+1..t+M}
            if is_high:
                out.extend(
                    self._accepted(
                        high[t],
                        "swing_high",
                        t,
                        atr_t,
                        # retrace[m−1] = H_t − min(L_{t+1..t+m})
                        high[t] - np.minimum.accumulate(low[t + 1 : end]),
                        sessions,
                        avail,
                        half,
                        spot,
                        atr_now,
                    )
                )
            if is_low:
                out.extend(
                    self._accepted(
                        low[t],
                        "swing_low",
                        t,
                        atr_t,
                        # retrace[m−1] = max(H_{t+1..t+m}) − L_t
                        np.maximum.accumulate(high[t + 1 : end]) - low[t],
                        sessions,
                        avail,
                        half,
                        spot,
                        atr_now,
                    )
                )
        return out

    def _accepted(
        self,
        level: float,
        kind: str,
        t: int,
        atr_t: float,
        retrace: np.ndarray,
        sessions: list[date],
        avail: list[Any],
        half: float,
        spot: float,
        atr_now: float,
    ) -> list[CandidateLevel]:
        if abs(level - spot) > self.keep_within_atr * atr_now:  # |level − spot| ≤ 6·ATR
            return []
        out: list[CandidateLevel] = []
        for k in self.k_atr:
            hits = np.nonzero(retrace >= k * atr_t)[0]  # accept ⇔ retrace_m ≥ k·ATR_t
            if hits.size == 0:
                continue  # never confirmed within m_max sessions (or not yet, as of as_of)
            m = int(hits[0]) + 1  # first confirming m; available_at = close of t+m
            out.append(
                CandidateLevel(
                    level=float(level),
                    lower=float(level - half),
                    upper=float(level + half),
                    source=f"{kind}_k{k:g}",
                    family=self.family,
                    timeframe="1D",
                    formed_at=sessions[t],
                    available_at=avail[t + m],
                    meta={"k": k, "confirm_sessions": m, "atr_at_formation": float(atr_t)},
                )
            )
        return out
