"""Candidate levels → zones. P0 ships the naive 1-D diameter-bounded merge
(§3.6.4); P2 replaces it with HDBSCAN behind the same `Clusterer` interface.

Original formulas (§3.6.4), ε = 0.5 (initial):

    x_i = level_i / ATR₂₀                     (sorted ascending)
    new cluster at i  ⇔  x_i − x_first > ε    (x_first = first member of the open cluster)
    center = mean(level_i),  L = min(lower_i),  U = max(upper_i)
    side = support if center < spot else resistance
    distance_atr = (center − spot) / ATR₂₀,   width_atr = (U − L) / ATR₂₀
    drop the cluster if L ≤ spot ≤ U; keep the nearest 4 per side by |distance_atr|
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sr_agent.config import load_thresholds
from sr_agent.levels.generators.base import CandidateLevel
from sr_agent.levels.zone import Zone


class Clusterer(ABC):
    @abstractmethod
    def cluster(
        self, levels: list[CandidateLevel], atr: float, spot: float, ticker: str = ""
    ) -> list[Zone]:
        """Zones sorted by |distance_atr|, nearest first, excluding any zone containing spot."""


class NaiveClusterer(Clusterer):
    """Sort levels in ATR units and walk once, starting a new cluster whenever the
    next level is more than `eps_atr` above the cluster's *first* member, so the
    cluster diameter is ≤ ε. (The design's first wording, a gap to the *previous*
    member, is single linkage: the round-number ladder, rungs 0.1–0.3 ATR apart,
    chained into one cluster spanning the spot, which was then dropped. Fixed in
    §3.6.4 on 2026-09-18.) Keeps the nearest `max_per_side` zones per side."""

    def __init__(self, eps_atr: float | None = None, max_per_side: int | None = None) -> None:
        cfg = load_thresholds()["p0"]["naive_cluster"]
        self.eps_atr = float(eps_atr if eps_atr is not None else cfg["eps_atr"])
        self.max_per_side = int(max_per_side if max_per_side is not None else cfg["max_per_side"])

    def cluster(
        self, levels: list[CandidateLevel], atr: float, spot: float, ticker: str = ""
    ) -> list[Zone]:
        if atr <= 0:
            raise ValueError("atr must be positive")
        if not levels:
            return []
        ordered = sorted(levels, key=lambda c: c.level)  # x_i = level_i / ATR₂₀, ascending
        groups: list[list[CandidateLevel]] = [[ordered[0]]]
        for cur in ordered[1:]:
            if (cur.level - groups[-1][0].level) / atr > self.eps_atr:  # x_i − x_first > ε
                groups.append([cur])
            else:
                groups[-1].append(cur)

        support: list[Zone] = []
        resistance: list[Zone] = []
        for members in groups:
            center = sum(c.level for c in members) / len(members)  # center = mean(level_i)
            lower = min(c.lower for c in members)  # L = min(lower_i)
            upper = max(c.upper for c in members)  # U = max(upper_i)
            if lower <= spot <= upper:
                continue  # L ≤ spot ≤ U: contains the spot, neither side
            side = "support" if center < spot else "resistance"
            zone = Zone(
                zone_id="",
                side=side,
                lower=lower,
                upper=upper,
                center=center,
                width_atr=(upper - lower) / atr,  # (U − L) / ATR₂₀
                distance_atr=(center - spot) / atr,  # (center − spot) / ATR₂₀
                provenance=tuple(members),
            )
            (support if side == "support" else resistance).append(zone)

        prefix = f"{ticker}-" if ticker else ""
        out: list[Zone] = []
        for side_zones, tag in ((support, "S"), (resistance, "R")):
            side_zones.sort(key=lambda z: abs(z.distance_atr))  # nearest first
            for i, z in enumerate(side_zones[: self.max_per_side], start=1):  # keep 4 per side
                out.append(
                    Zone(
                        zone_id=f"{prefix}{tag}-P0-{i:02d}",
                        side=z.side,
                        lower=z.lower,
                        upper=z.upper,
                        center=z.center,
                        width_atr=z.width_atr,
                        distance_atr=z.distance_atr,
                        provenance=z.provenance,
                    )
                )
        out.sort(key=lambda z: abs(z.distance_atr))
        return out
