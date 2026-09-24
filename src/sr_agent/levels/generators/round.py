"""Family B — round-number ladders near spot (§3.6.3; BP §6.2; Osler 2003).

Original formulas (§3.6.3):

    P     = close_{as_of}
    e     = 10^⌊log₁₀ P⌋                      (P = 182.4 → e = 100)
    steps = { e/m : m ∈ {10, 20, 100} } ∪ { min(e/m)/2 }   (10, 5, 1, 0.5)
    rungs = { j·step : j ∈ ℤ,  |j·step − P| ≤ 3·ATR₂₀,  j·step > 0 }

Each rung is a CandidateLevel with lower/upper = rung ∓ 0.1·ATR₂₀,
`formed_at = null`, `available_at = −∞` (always known). A rung on several
ladders is emitted once with its coarsest step; `meta.rank` (0 = coarsest)
lets P2 weight $10 rungs above $1 rungs.
"""

from __future__ import annotations

import math
from datetime import date

from sr_agent.config import load_thresholds
from sr_agent.data.bars import Bars
from sr_agent.levels.atr import atr_at_as_of
from sr_agent.levels.generators.base import ALWAYS_AVAILABLE, CandidateLevel, LevelGenerator


def ladder_steps(price: float, multipliers: list[int]) -> list[float]:
    """Coarsest-first step sizes {e/m} plus the half-step of the finest ladder."""
    if price <= 0:
        raise ValueError("price must be positive")
    e = 10.0 ** math.floor(math.log10(price))  # e = 10^⌊log₁₀ P⌋
    steps = sorted({e / m for m in multipliers}, reverse=True)  # e/m, m ∈ multipliers
    steps.append(steps[-1] / 2)  # half-step of the finest ladder
    return steps


def rungs_within(price: float, radius: float, step: float) -> list[float]:
    """Rungs j·step with P − radius ≤ j·step ≤ P + radius and j·step > 0 (radius = 3·ATR)."""
    lo = math.ceil((price - radius) / step - 1e-9)  # smallest j with j·step ≥ P − radius
    hi = math.floor((price + radius) / step + 1e-9)  # largest j with j·step ≤ P + radius
    return [round(k * step, 6) for k in range(lo, hi + 1) if k * step > 0]


class RoundNumberGenerator(LevelGenerator):
    family = "B"

    def __init__(
        self,
        multipliers: list[int] | None = None,
        radius_atr: float | None = None,
        half_width_atr: float | None = None,
    ) -> None:
        cfg = load_thresholds()["p0"]["round"]
        self.multipliers = [int(m) for m in (multipliers or cfg["multipliers"])]
        self.radius_atr = float(radius_atr if radius_atr is not None else cfg["radius_atr"])
        self.half_width_atr = float(
            half_width_atr if half_width_atr is not None else cfg["half_width_atr"]
        )

    def generate(self, bars: Bars, as_of: date) -> list[CandidateLevel]:
        price = bars.spot  # P = close_{as_of}
        atr_now = atr_at_as_of(bars)
        radius = self.radius_atr * atr_now  # 3·ATR₂₀
        half = self.half_width_atr * atr_now  # 0.1·ATR₂₀
        seen: dict[float, CandidateLevel] = {}
        for rank, step in enumerate(ladder_steps(price, self.multipliers)):
            for rung in rungs_within(price, radius, step):
                if rung in seen:
                    continue  # already emitted from a coarser ladder
                seen[rung] = CandidateLevel(
                    level=rung,
                    lower=rung - half,
                    upper=rung + half,
                    source=f"round_{step:g}",
                    family=self.family,
                    timeframe="1D",
                    formed_at=None,
                    available_at=ALWAYS_AVAILABLE,
                    meta={"step": step, "rank": rank},
                )
        return sorted(seen.values(), key=lambda c: c.level)
