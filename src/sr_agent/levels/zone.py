"""`Zone`: an interval [L, U] with provenance — a level is never a line (BP §1.1)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sr_agent.levels.generators.base import CandidateLevel


@dataclass(frozen=True)
class Zone:
    zone_id: str
    side: str  # "support" | "resistance"
    lower: float
    upper: float
    center: float
    width_atr: float
    distance_atr: float  # (center − spot) / ATR₂₀, negative below spot
    provenance: tuple[CandidateLevel, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        if self.side not in ("support", "resistance"):
            raise ValueError(f"bad side {self.side!r}")
        if not self.lower <= self.center <= self.upper:
            raise ValueError(f"{self.zone_id}: center outside [L, U]")

    def n_sources(self) -> int:
        return len(self.provenance)

    def n_families(self) -> int:
        return len({c.family for c in self.provenance})

    def sources(self) -> list[str]:
        return sorted({c.source for c in self.provenance})

    def contains(self, price: float) -> bool:
        return self.lower <= price <= self.upper
