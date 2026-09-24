"""Interface every candidate-level generator implements (§3.4).

`family` is the independence key BUILD-PLAN §6.4 uses for `n_independent_families`
(A = price structure, B = round numbers, C = volume, D = VWAP, E = technical,
F = statistical, G = options).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sr_agent.data.bars import Bars

#: `available_at` for facts that are always known (round numbers): "−∞".
ALWAYS_AVAILABLE = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class CandidateLevel:
    level: float
    lower: float
    upper: float
    source: str
    family: str
    timeframe: str
    formed_at: date | None
    available_at: datetime
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if not self.lower <= self.level <= self.upper:
            raise ValueError(
                f"{self.source}: level {self.level} outside [{self.lower}, {self.upper}]"
            )
        if self.available_at.tzinfo is None:
            raise ValueError(f"{self.source}: available_at must be tz-aware")


class LevelGenerator(ABC):
    family: str

    @abstractmethod
    def generate(self, bars: Bars, as_of: date) -> list[CandidateLevel]:
        """Candidates knowable at `as_of`: every result has available_at <= as_of close."""
